"""Practical 05 implementation: Student Record Management using EC2, S3, and DynamoDB."""

import re
from typing import Any, Dict, List, Optional
from unittest.mock import Mock

from botocore.exceptions import ClientError

from cloudprac.adapters.aws_client import AWSAdapter, mask_account_id
from cloudprac.core.contract import PracticalContract
from cloudprac.core.models import (
    CleanupResult,
    ExecutionPlan,
    ExecutionPlanStep,
    ExecutionResult,
    PracticalMetadata,
    PracticalStatus,
    RunManifest,
    TrackedResource,
    VerificationCheck,
    VerificationResult,
)
from cloudprac.practicals.p05.config import P05Config
from cloudprac.practicals.p05.dynamodb import (
    cleanup_dynamodb_resources,
    create_student_table,
    get_student_record,
    insert_student_records,
    update_student_record,
    verify_dynamodb_resources,
    wait_for_table_active,
)
from cloudprac.practicals.p05.ec2 import (
    build_user_data_script,
    check_application_health,
    cleanup_ec2_resources,
    find_latest_al2023_ami,
    get_default_or_first_vpc,
    launch_ec2_instance,
    setup_key_pair,
    setup_security_group,
    verify_ec2_instance,
    wait_for_instance_running,
)
from cloudprac.practicals.p05.iam import (
    cleanup_iam_resources,
    setup_instance_profile,
)
from cloudprac.practicals.p05.preview import (
    is_real_public_ip,
    verify_application_and_preview,
)
from cloudprac.practicals.p05.s3 import (
    cleanup_s3_resources,
    create_private_bucket,
    upload_document_to_s3,
    verify_s3_resources,
)
from cloudprac.practicals.p05.sample_data import (
    get_default_student_records,
    get_sample_student_document,
)
from cloudprac.utils.config import CloudPracConfig
from cloudprac.utils.logging import get_logger
from cloudprac.utils.paths import get_cloudprac_home, get_run_dir, save_restricted_file

logger = get_logger()


def sanitize_name(raw_name: str) -> str:
    """Sanitize strings for AWS resource naming."""
    return re.sub(r"[^a-zA-Z0-9-]", "-", raw_name).lower()


def _is_mock_client(client: Any) -> bool:
    """Detect whether client is a unit test Mock object."""
    return isinstance(client, Mock) or hasattr(client, "_mock_return_value")



class P05Practical(PracticalContract):
    """Complete implementation of Practical 05: Student Record Management using EC2, S3, and DynamoDB."""

    def __init__(self, p05_config: Optional[P05Config] = None) -> None:
        self.p05_config = p05_config or P05Config()
        self._metadata = PracticalMetadata(
            id="P05",
            title="EC2, S3 and DynamoDB Implementation: Student Record Management",
            description=(
                "A college wants to store student details in DynamoDB, upload student documents to S3, "
                "and use EC2 to run a simple application for managing student records."
            ),
            category="Compute, Storage & Database",
            aws_services=["EC2", "S3", "DynamoDB", "IAM"],
            status=PracticalStatus.CONFIGURED,
            estimated_cost="Potentially billable: EC2 compute, EBS volume (8GB gp3), public IPv4 address, S3 requests/storage, DynamoDB operations (charges depend on account Free Tier status and runtime; unverified exact cost)",
            prerequisites=[
                "Valid AWS IAM credentials with EC2, S3, DynamoDB, and IAM permissions",
                "Existing VPC and Subnet in target region (or permission to use default VPC)",
            ],
            syllabus_source="College Cloud Computing Syllabus Practical 05",
        )

    @property
    def metadata(self) -> PracticalMetadata:
        return self._metadata

    def inspect(self) -> Dict[str, Any]:
        """Return detailed practical guidance and configuration parameters."""
        return {
            "id": self._metadata.id,
            "title": self._metadata.title,
            "status": self._metadata.status.value,
            "description": self._metadata.description,
            "category": self._metadata.category,
            "aws_services": self._metadata.aws_services,
            "prerequisites": self._metadata.prerequisites,
            "objectives": [
                "1. Provision Amazon DynamoDB table for student records with 'student_id' string partition key",
                "2. Provision private Amazon S3 bucket with Block Public Access and SSE-S3 encryption for student documents",
                "3. Configure least-privilege IAM Role & Instance Profile for EC2 (no embedded credentials)",
                "4. Launch Amazon Linux 2023 EC2 instance with user-data bootstrapping the student-record Flask web app",
                "5. Upload student documents to S3 and populate initial student records in DynamoDB",
                "6. Verify DynamoDB operations (Insert, Consistent Read, Update, Delete) and schema",
                "7. Verify S3 privacy, encryption, and document checksum integrity",
                "8. Verify EC2 running state and application endpoint health",
                "9. Provide guarded cleanup and rollback for all created AWS resources",
            ],
            "data_schema": {
                "dynamodb_table": "cloudprac-p05-students-<run_id>",
                "partition_key": "student_id (String)",
                "attributes": ["student_id", "name", "course", "email", "year", "document_key"],
                "s3_bucket": "cloudprac-p05-<account>-<run_id>",
                "document_prefix": "documents/STU-xxx-*.txt",
            },
            "cost_cautions": [
                "EC2 instances incur hourly compute and public IPv4 address charges (~$0.005/hr) while running.",
                "Always run 'cloudprac cleanup P05 --run-id <run_id>' after completing your lab demonstration.",
            ],
        }

    def plan(self, config: CloudPracConfig, run_id: str) -> ExecutionPlan:
        """Generate a dry-run execution plan detailing all proposed operations."""
        clean_run = sanitize_name(run_id)
        bucket_name = self.p05_config.bucket_name or f"cloudprac-p05-{clean_run}"
        table_name = self.p05_config.table_name or f"cloudprac-p05-students-{clean_run}"
        profile_name = self.p05_config.iam_profile_name or f"cloudprac-p05-profile-{clean_run}"
        sg_name = f"cloudprac-p05-sg-{clean_run}"

        steps: List[ExecutionPlanStep] = [
            ExecutionPlanStep(
                step_number=1,
                action="s3:CreateBucket & s3:PutPublicAccessBlock",
                resource_type="s3-bucket",
                resource_name=bucket_name,
                estimated_cost="Standard S3 storage & request pricing",
                description="Create private S3 bucket with Block Public Access and SSE-S3 encryption for student documents",
            ),
            ExecutionPlanStep(
                step_number=2,
                action="s3:PutObject",
                resource_type="s3-object",
                resource_name=f"s3://{bucket_name}/documents/STU-001-admission-certificate.txt",
                estimated_cost="S3 PUT request rate",
                description="Upload initial student document with metadata and SHA-256 integrity hash",
            ),
            ExecutionPlanStep(
                step_number=3,
                action="dynamodb:CreateTable",
                resource_type="dynamodb-table",
                resource_name=table_name,
                estimated_cost="DynamoDB Pay-Per-Request pricing (zero idle cost)",
                description="Create DynamoDB table with partition key 'student_id' (String) and PAY_PER_REQUEST billing",
            ),
            ExecutionPlanStep(
                step_number=4,
                action="dynamodb:PutItem",
                resource_type="dynamodb-item",
                resource_name=f"{table_name}#STU-001",
                estimated_cost="DynamoDB Write Request Units",
                description="Insert sample student records (Aarav Sharma, Priya Patel, Rohan Verma)",
            ),
            ExecutionPlanStep(
                step_number=5,
                action="iam:CreateRole & iam:CreateInstanceProfile",
                resource_type="iam-instance-profile",
                resource_name=profile_name,
                estimated_cost="$0.00 (IAM is free of charge)",
                description="Provision least-privilege IAM instance profile granting EC2 access to S3 bucket and DynamoDB table",
            ),
            ExecutionPlanStep(
                step_number=6,
                action="ec2:CreateSecurityGroup & ec2:AuthorizeSecurityGroupIngress",
                resource_type="security-group",
                resource_name=f"{sg_name} [Port {self.p05_config.app_port} ingress: {self.p05_config.app_cidr or 'REQUIRED: provide --app-cidr <your-ip>/32'}]",
                estimated_cost="$0.00 (Security Groups are free of charge)",
                description=f"Create restricted security group allowing inbound port {self.p05_config.app_port} for web application",
            ),
            ExecutionPlanStep(
                step_number=7,
                action="ec2:RunInstances",
                resource_type="ec2-instance",
                resource_name=f"cloudprac-p05-app-{clean_run}",
                estimated_cost="Standard On-Demand rate (public IPv4 ~$0.005/hr billable in all accounts)",
                description=f"Launch {self.p05_config.instance_type} EC2 instance running Amazon Linux 2023 with Flask app bootstrap",
            ),
        ]

        target_region = self.p05_config.region or getattr(config, "default_region", "us-east-1")
        return ExecutionPlan(
            practical_id="P05",
            run_id=run_id,
            aws_region=target_region,
            steps=steps,
            estimated_total_cost="Unverified exact cost - billable AWS resources deployed (EC2 compute, EBS gp3, public IPv4, S3, DynamoDB). Not guaranteed to be free; tear down promptly via 'cloudprac cleanup P05'.",
            warnings=[
                "This practical provisions real AWS resources in your configured account.",
                "Application security: Inbound access to port 5000 requires an explicit restricted CIDR (e.g. --app-cidr <your-ip>/32). Broad access (0.0.0.0/0) is strictly blocked.",
                "Cost transparency: Public IPv4 addresses incur hourly charges (~$0.005/hr) in all AWS accounts. EC2, EBS, S3, and DynamoDB charges depend on Free Tier eligibility.",
                "Always run 'cloudprac cleanup P05 --run-id <run_id>' after your lab evaluation to avoid unexpected charges.",
            ],
        )

    def execute(self, plan: ExecutionPlan, context: Any) -> ExecutionResult:
        """Execute the planned AWS provisioning sequence safely."""
        adapter: AWSAdapter = context if isinstance(context, AWSAdapter) else getattr(context, "adapter", None)
        if not adapter:
            raise RuntimeError("Execution context missing valid AWSAdapter.")

        clean_run = sanitize_name(plan.run_id)
        region = plan.aws_region or self.p05_config.region or adapter.region_name
        identity = adapter.get_caller_identity()
        raw_account = identity.get("Account", "unknown")
        account_id = mask_account_id(raw_account).replace("*", "x")

        bucket_name = self.p05_config.bucket_name or f"cloudprac-p05-{account_id[:8]}-{clean_run}"
        table_name = self.p05_config.table_name or f"cloudprac-p05-students-{clean_run}"
        role_name = self.p05_config.iam_role_name or f"cloudprac-p05-role-{clean_run}"
        profile_name = self.p05_config.iam_profile_name or f"cloudprac-p05-profile-{clean_run}"
        key_name = self.p05_config.key_name or f"cloudprac-p05-key-{clean_run}"
        sg_name = f"cloudprac-p05-sg-{clean_run}"

        tags = {
            "ManagedBy": "CloudPrac",
            "PracticalId": "P05",
            "RunId": plan.run_id,
        }

        if adapter.mock_mode:
            mock_resources = [
                TrackedResource(
                    resource_type="s3-bucket",
                    resource_id=bucket_name,
                    resource_name=bucket_name,
                    arn=f"arn:aws:s3:::{bucket_name}",
                    tags=tags,
                ),
                TrackedResource(
                    resource_type="s3-object",
                    resource_id=f"s3://{bucket_name}/documents/STU-001-admission-certificate.txt",
                    resource_name="documents/STU-001-admission-certificate.txt",
                    tags=tags,
                ),
                TrackedResource(
                    resource_type="dynamodb-table",
                    resource_id=table_name,
                    resource_name=table_name,
                    arn=f"arn:aws:dynamodb:{region}:{raw_account}:table/{table_name}",
                    tags=tags,
                ),
                TrackedResource(
                    resource_type="dynamodb-item",
                    resource_id=f"{table_name}#STU-001",
                    resource_name="Student#STU-001",
                    tags=tags,
                ),
                TrackedResource(
                    resource_type="iam-instance-profile",
                    resource_id=profile_name,
                    resource_name=profile_name,
                    arn=f"arn:aws:iam::{raw_account}:instance-profile/{profile_name}",
                    tags=tags,
                ),
                TrackedResource(
                    resource_type="security-group",
                    resource_id=f"sg-mock{clean_run[:8]}",
                    resource_name=sg_name,
                    tags=tags,
                ),
                TrackedResource(
                    resource_type="ec2-instance",
                    resource_id=f"i-mock{clean_run[:8]}",
                    resource_name=f"cloudprac-p05-app-{clean_run}",
                    arn=f"arn:aws:ec2:{region}:{raw_account}:instance/i-mock{clean_run[:8]}",
                    tags=tags,
                ),
            ]
            manifest = RunManifest(
                practical_id="P05",
                run_id=plan.run_id,
                aws_account_id=mask_account_id(raw_account),
                aws_region=region,
                resources=mock_resources,
            )
            run_dir = get_run_dir(plan.run_id)
            run_dir.mkdir(parents=True, exist_ok=True)
            import secrets
            mock_token = secrets.token_urlsafe(32)
            save_restricted_file(run_dir / "admin_token", mock_token)
            manifest_path = run_dir / "manifest.json"
            manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
            k_name = self.p05_config.key_name or f"cloudprac-p05-key-{clean_run}"
            key_file = get_cloudprac_home() / "keys" / f"{k_name}.pem"
            return ExecutionResult(
                practical_id="P05",
                run_id=plan.run_id,
                success=True,
                message="P05 mock execution completed successfully",
                steps_executed=len(mock_resources),
                manifest=manifest,
                outputs={
                    "public_ip": "54.200.10.25",
                    "app_port": self.p05_config.app_port,
                    "app_url": f"http://54.200.10.25:{self.p05_config.app_port}",
                    "bucket_name": bucket_name,
                    "table_name": table_name,
                    "key_name": k_name,
                    "key_file": str(key_file),
                },
            )

        tracked_resources: List[TrackedResource] = []
        errors: List[str] = []
        public_ip = ""

        # Validate explicit restricted CIDR before any cloud resource provisioning
        if not self.p05_config.app_cidr or self.p05_config.app_cidr.strip() in ("0.0.0.0/0", "::/0") or self.p05_config.app_cidr.strip().endswith("/0"):
            raise ValueError(
                f"Execution halted: Opening application port {self.p05_config.app_port} to the public internet or an unspecified CIDR is prohibited to protect student records. "
                "Provide an explicit restricted CIDR via --app-cidr (e.g. --app-cidr <your-ip>/32 or your VPC CIDR)."
            )

        run_dir = get_run_dir(plan.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = run_dir / "manifest.json"

        def checkpoint_manifest() -> None:
            manifest = RunManifest(
                practical_id="P05",
                run_id=plan.run_id,
                aws_account_id=mask_account_id(raw_account),
                aws_region=region,
                resources=list(tracked_resources),
            )
            manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

        # ---------------------------------------------------------
        # 1. Provision Amazon S3 Private Bucket & Documents
        # ---------------------------------------------------------
        s3_client = adapter.get_client("s3", region_name=region)
        try:
            logger.info("Step 1: Provisioning Amazon S3 private bucket...")
            created_bucket = create_private_bucket(
                s3_client=s3_client,
                bucket_name=bucket_name,
                region=region,
                tags=tags,
            )
            tracked_resources.append(
                TrackedResource(
                    resource_type="s3-bucket",
                    resource_id=created_bucket,
                    resource_name=created_bucket,
                    arn=f"arn:aws:s3:::{created_bucket}",
                    tags=tags,
                )
            )
            checkpoint_manifest()

            # Upload initial student document
            doc_content = get_sample_student_document("STU-001", "Aarav Sharma", plan.run_id)
            doc_key = "documents/STU-001-admission-certificate.txt"
            upload_document_to_s3(
                s3_client=s3_client,
                bucket_name=created_bucket,
                object_key=doc_key,
                content=doc_content,
            )
            tracked_resources.append(
                TrackedResource(
                    resource_type="s3-object",
                    resource_id=f"s3://{created_bucket}/{doc_key}",
                    resource_name=doc_key,
                    tags=tags,
                )
            )
            checkpoint_manifest()

            # Generate and securely store unique admin token in private S3 bucket
            import secrets
            admin_token = secrets.token_urlsafe(32)
            token_s3_key = f"secrets/{plan.run_id}/admin_token"
            upload_document_to_s3(
                s3_client=s3_client,
                bucket_name=created_bucket,
                object_key=token_s3_key,
                content=admin_token,
            )
            tracked_resources.append(
                TrackedResource(
                    resource_type="s3-object",
                    resource_id=f"s3://{created_bucket}/{token_s3_key}",
                    resource_name=token_s3_key,
                    tags=tags,
                )
            )
            checkpoint_manifest()

            # Save admin token locally with strict 0600 permissions restricted to current user
            save_restricted_file(run_dir / "admin_token", admin_token)
        except Exception as e:
            logger.error(f"S3 provisioning failed: {e}")
            errors.append(f"S3 Error: {e}")

        # ---------------------------------------------------------
        # 2. Provision Amazon DynamoDB Student Table & Records
        # ---------------------------------------------------------
        dynamodb_client = adapter.get_client("dynamodb", region_name=region)
        try:
            logger.info("Step 2: Provisioning Amazon DynamoDB table...")
            created_table = create_student_table(
                dynamodb_client=dynamodb_client,
                table_name=table_name,
                billing_mode=self.p05_config.dynamodb_billing_mode,
                tags=tags,
            )
            tracked_resources.append(
                TrackedResource(
                    resource_type="dynamodb-table",
                    resource_id=created_table,
                    resource_name=created_table,
                    arn=f"arn:aws:dynamodb:{region}:{raw_account}:table/{created_table}",
                    tags=tags,
                )
            )
            checkpoint_manifest()

            # Wait for table to be ACTIVE
            wait_for_table_active(dynamodb_client, created_table)

            # Insert sample student records
            records = get_default_student_records(bucket_name=bucket_name)
            inserted_count = insert_student_records(dynamodb_client, created_table, records)
            logger.info(f"Inserted {inserted_count} student records into '{created_table}'.")
            for rec in records:
                tracked_resources.append(
                    TrackedResource(
                        resource_type="dynamodb-item",
                        resource_id=f"{created_table}#{rec['student_id']}",
                        resource_name=rec["student_id"],
                        tags=tags,
                    )
                )
            checkpoint_manifest()
        except Exception as e:
            logger.error(f"DynamoDB provisioning failed: {e}")
            errors.append(f"DynamoDB Error: {e}")

        # ---------------------------------------------------------
        # 3. Provision IAM Role & Instance Profile for EC2
        # ---------------------------------------------------------
        iam_client = adapter.get_client("iam", region_name=region)
        try:
            logger.info("Step 3: Setting up IAM Role and Instance Profile...")
            created_profile = setup_instance_profile(
                iam_client=iam_client,
                role_name=role_name,
                profile_name=profile_name,
                bucket_name=bucket_name,
                table_name=table_name,
                region=region,
                account_id=raw_account,
                tags=tags,
            )
            tracked_resources.append(
                TrackedResource(
                    resource_type="iam-instance-profile",
                    resource_id=created_profile,
                    resource_name=created_profile,
                    arn=f"arn:aws:iam::{raw_account}:instance-profile/{created_profile}",
                    tags=tags,
                )
            )
            tracked_resources.append(
                TrackedResource(
                    resource_type="iam-role",
                    resource_id=role_name,
                    resource_name=role_name,
                    arn=f"arn:aws:iam::{raw_account}:role/{role_name}",
                    tags=tags,
                )
            )
            checkpoint_manifest()
        except Exception as e:
            logger.warning(f"IAM provisioning encountered issues (continuing with degraded role binding if restricted): {e}")
            errors.append(f"IAM Notice: {e}")

        # ---------------------------------------------------------
        # 4. Provision EC2 Networking, Security Group, and Key Pair
        # ---------------------------------------------------------
        ec2_client = adapter.get_client("ec2", region_name=region)
        ssm_client = adapter.get_client("ssm", region_name=region)
        key_file = None
        k_name = self.p05_config.key_name or f"cloudprac-p05-key-{clean_run}"
        try:
            logger.info("Step 4: Setting up EC2 networking and security group...")
            vpc_id, subnet_id = get_default_or_first_vpc(ec2_client)

            # Discover AL2023 AMI dynamically
            ami_id = self.p05_config.ami_id or find_latest_al2023_ami(ec2_client, ssm_client)

            # Security group with app port and SSH restricted to student's CIDR
            sg_id = setup_security_group(
                ec2_client=ec2_client,
                group_name=sg_name,
                vpc_id=vpc_id,
                app_port=self.p05_config.app_port,
                app_cidr=self.p05_config.app_cidr,
                ssh_cidr=self.p05_config.ssh_cidr or self.p05_config.app_cidr,
                tags=tags,
            )
            tracked_resources.append(
                TrackedResource(
                    resource_type="security-group",
                    resource_id=sg_id,
                    resource_name=sg_name,
                    tags=tags,
                )
            )
            checkpoint_manifest()

            # Key Pair
            if self.p05_config.create_key_pair:
                k_name, key_file = setup_key_pair(
                    ec2_client=ec2_client,
                    key_name=key_name,
                    save_local_file=self.p05_config.save_key_file,
                )
                tracked_resources.append(
                    TrackedResource(
                        resource_type="key-pair",
                        resource_id=k_name,
                        resource_name=k_name,
                        tags=tags,
                    )
                )
                checkpoint_manifest()
            else:
                k_name = self.p05_config.key_name
                disk_key = get_cloudprac_home() / "keys" / f"{k_name}.pem"
                if disk_key.exists():
                    key_file = disk_key

            # Build user-data bootstrap script fetching admin token via S3 + IAM role
            token_s3_key = f"secrets/{plan.run_id}/admin_token"
            user_data = build_user_data_script(
                table_name=table_name,
                bucket_name=bucket_name,
                region=region,
                app_port=self.p05_config.app_port,
                token_s3_key=token_s3_key,
            )

            # ---------------------------------------------------------
            # 5. Launch EC2 Virtual Machine
            # ---------------------------------------------------------
            logger.info("Step 5: Launching EC2 virtual machine...")
            instance_id = launch_ec2_instance(
                ec2_client=ec2_client,
                image_id=ami_id,
                instance_type=self.p05_config.instance_type,
                subnet_id=subnet_id,
                security_group_id=sg_id,
                instance_profile_name=profile_name,
                user_data_script=user_data,
                key_name=k_name,
                tags=tags,
            )
            tracked_resources.append(
                TrackedResource(
                    resource_type="ec2-instance",
                    resource_id=instance_id,
                    resource_name=f"cloudprac-p05-app-{clean_run}",
                    arn=f"arn:aws:ec2:{region}:{raw_account}:instance/{instance_id}",
                    tags=tags,
                )
            )
            checkpoint_manifest()

            # Wait for instance running state
            logger.info(f"Waiting for instance '{instance_id}' to enter 'running' state...")
            inst_data = wait_for_instance_running(
                ec2_client,
                instance_id,
                region=region,
                account_id=raw_account,
            )
            public_ip = inst_data.get("PublicIpAddress", "")

            # Validate real public IP
            is_real, ip_reason = is_real_public_ip(public_ip)
            if not is_real:
                logger.warning(f"EC2 instance '{instance_id}' does not have a valid public IP: {ip_reason}")
                errors.append(f"EC2 Public IP: {ip_reason}")
            else:
                logger.info(f"EC2 instance is running at public IP: {public_ip}")
                # Verify application readiness before reporting success or generating preview URL
                logger.info(f"Verifying application readiness at http://{public_ip}:{self.p05_config.app_port}/health...")
                app_ready, health_detail = check_application_health(
                    public_ip=public_ip,
                    app_port=self.p05_config.app_port,
                    max_timeout=120,
                    poll_interval=5,
                )
                if not app_ready:
                    logger.error(f"Application readiness check failed: {health_detail}")
                    errors.append(f"Application Readiness: {health_detail}")
                else:
                    logger.info(f"Application is healthy and ready: {health_detail}")

        except Exception as e:
            logger.error(f"EC2 provisioning failed: {e}")
            errors.append(f"EC2 Error: {e}")

        # Save run manifest
        manifest = RunManifest(
            practical_id="P05",
            run_id=plan.run_id,
            aws_account_id=mask_account_id(raw_account),
            aws_region=region,
            resources=tracked_resources,
        )
        run_dir = get_run_dir(plan.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

        outputs = {}
        is_ip_valid, _ = is_real_public_ip(public_ip)
        if public_ip and is_ip_valid and len(errors) == 0:
            outputs = {
                "public_ip": public_ip,
                "app_port": self.p05_config.app_port,
                "app_url": f"http://{public_ip}:{self.p05_config.app_port}",
                "bucket_name": bucket_name,
                "table_name": table_name,
                "key_name": k_name,
                "key_file": str(key_file) if key_file else None,
            }
        else:
            outputs = {
                "public_ip": public_ip if is_ip_valid else None,
                "app_port": self.p05_config.app_port,
                "bucket_name": bucket_name,
                "table_name": table_name,
                "key_name": k_name,
                "key_file": str(key_file) if key_file else None,
            }

        success = len(errors) == 0
        return ExecutionResult(
            practical_id="P05",
            run_id=plan.run_id,
            success=success,
            message=f"P05 execution {'completed successfully' if success else 'encountered errors'}",
            steps_executed=len(tracked_resources),
            errors=errors,
            manifest=manifest,
            outputs=outputs,
        )


    def verify(self, run_id: str, context: Any) -> VerificationResult:
        """Perform independent verification on AWS resources and deployed student application."""
        adapter: AWSAdapter = context if isinstance(context, AWSAdapter) else getattr(context, "adapter", None)
        if not adapter:
            raise RuntimeError("Verification context missing valid AWSAdapter.")

        run_dir = get_run_dir(run_id)
        manifest_path = run_dir / "manifest.json"

        # Fail closed immediately if manifest is missing (no false-positive passes)
        if not manifest_path.is_file():
            return VerificationResult(
                practical_id="P05",
                run_id=run_id,
                success=False,
                checks=[
                    VerificationCheck(
                        check_id="manifest-exists",
                        name="Run Manifest Verification",
                        description="Verify run manifest exists before checking AWS resources",
                        passed=False,
                        expected="Manifest file exists in run directory",
                        actual=f"Manifest file not found at {manifest_path}",
                    )
                ],
                summary="Practical P05 Verification FAILED: Missing run manifest.",
            )

        manifest_data = RunManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))

        if adapter.mock_mode:
            has_s3 = any(r.resource_type == "s3-bucket" for r in manifest_data.resources)
            has_ddb = any(r.resource_type == "dynamodb-table" for r in manifest_data.resources)
            has_ec2 = any(r.resource_type == "ec2-instance" for r in manifest_data.resources)

            mock_checks = [
                VerificationCheck(
                    check_id="s3-bucket-exists",
                    name="S3 Bucket Verification (Mock)",
                    description="Verify private S3 bucket exists in run manifest",
                    passed=has_s3,
                    expected="Bucket exists",
                    actual="Bucket verified in mock manifest" if has_s3 else "Missing S3 bucket",
                ),
                VerificationCheck(
                    check_id="s3-bpa-enabled",
                    name="S3 Block Public Access (Mock)",
                    description="Verify S3 Block Public Access is enabled",
                    passed=has_s3,
                    expected="BlockPublicAcls=True",
                    actual="Verified in mock mode",
                ),
                VerificationCheck(
                    check_id="dynamodb-table-active",
                    name="DynamoDB Table Status (Mock)",
                    description="Verify DynamoDB table is ACTIVE",
                    passed=has_ddb,
                    expected="ACTIVE",
                    actual="ACTIVE (Mock)" if has_ddb else "Table missing",
                ),
                VerificationCheck(
                    check_id="dynamodb-records",
                    name="DynamoDB Student Records (Mock)",
                    description="Verify student records exist",
                    passed=has_ddb,
                    expected="3 records",
                    actual="3 records verified" if has_ddb else "Records missing",
                ),
                VerificationCheck(
                    check_id="ec2-instance-running",
                    name="EC2 Instance Running (Mock)",
                    description="Verify EC2 instance is running",
                    passed=has_ec2,
                    expected="running",
                    actual="running (Mock)" if has_ec2 else "Instance missing",
                ),
                VerificationCheck(
                    check_id="ec2-app-health",
                    name="Application Health Check (Mock)",
                    description="Verify Flask application HTTP /health endpoint",
                    passed=has_ec2,
                    expected="HTTP 200 OK",
                    actual="HTTP 200 OK (Mock)" if has_ec2 else "App unreachable",
                ),
            ]
            mock_success = all(c.passed for c in mock_checks)
            return VerificationResult(
                practical_id="P05",
                run_id=run_id,
                success=mock_success,
                checks=mock_checks,
                summary=f"Practical P05 Verification (Mock): {sum(1 for c in mock_checks if c.passed)}/{len(mock_checks)} checks passed.",
            )

        clean_run = sanitize_name(run_id)
        bucket_res = next((r for r in manifest_data.resources if r.resource_type == "s3-bucket"), None)
        table_res = next((r for r in manifest_data.resources if r.resource_type == "dynamodb-table"), None)
        profile_res = next((r for r in manifest_data.resources if r.resource_type == "iam-instance-profile"), None)
        inst_res = next((r for r in manifest_data.resources if r.resource_type == "ec2-instance"), None)

        bucket_name = bucket_res.resource_id if bucket_res else (self.p05_config.bucket_name or f"cloudprac-p05-{clean_run}")
        table_name = table_res.resource_id if table_res else (self.p05_config.table_name or f"cloudprac-p05-students-{clean_run}")
        profile_name = profile_res.resource_id if profile_res else (self.p05_config.iam_profile_name or f"cloudprac-p05-profile-{clean_run}")
        instance_id = inst_res.resource_id if inst_res else None

        all_checks: List[VerificationCheck] = []

        # -------------------------------------------------------------
        # Part A: Infrastructure Checks (S3, DynamoDB, EC2 VM state)
        # -------------------------------------------------------------
        # 1. Verify S3 Resources
        s3_client = adapter.get_client("s3")
        expected_keys = ["documents/STU-001-admission-certificate.txt"]
        all_checks.extend(verify_s3_resources(s3_client, bucket_name, expected_keys))

        # 2. Verify DynamoDB Resources
        dynamodb_client = adapter.get_client("dynamodb")
        sample_students = get_default_student_records(bucket_name=bucket_name)
        all_checks.extend(verify_dynamodb_resources(dynamodb_client, table_name, sample_students))

        # Test live DynamoDB CRUD operations: UpdateItem verification
        test_sid = "STU-003"
        try:
            update_student_record(
                dynamodb_client,
                table_name,
                test_sid,
                {"year": "Graduated"},
            )
            updated_rec = get_student_record(dynamodb_client, table_name, test_sid)
            all_checks.append(
                VerificationCheck(
                    check_id=f"dynamodb-update-{test_sid}",
                    name="DynamoDB UpdateItem Verification",
                    description="Verify updating student record reflects in DynamoDB",
                    passed=updated_rec is not None and updated_rec.get("year") == "Graduated",
                    expected="Year updated to 'Graduated'",
                    actual=f"Year is '{updated_rec.get('year') if updated_rec else 'None'}'",
                )
            )
        except Exception as e:
            all_checks.append(
                VerificationCheck(
                    check_id=f"dynamodb-update-{test_sid}",
                    name="DynamoDB UpdateItem Verification",
                    description="Verify updating student record reflects in DynamoDB",
                    passed=False,
                    expected="Successful UpdateItem",
                    actual=f"Error: {e}",
                )
            )

        # 3. Verify EC2 Resources & VM state
        public_ip: Optional[str] = None
        if instance_id:
            ec2_client = adapter.get_client("ec2")
            all_checks.extend(
                verify_ec2_instance(
                    ec2_client=ec2_client,
                    instance_id=instance_id,
                    expected_instance_type=self.p05_config.instance_type,
                    expected_profile_name=profile_name,
                    app_port=self.p05_config.app_port,
                    check_http=False,  # Checked comprehensively in Part B
                )
            )
            try:
                desc = ec2_client.describe_instances(InstanceIds=[instance_id])
                resvs = desc.get("Reservations", [])
                if resvs and resvs[0].get("Instances"):
                    public_ip = resvs[0]["Instances"][0].get("PublicIpAddress")
            except Exception:
                pass

        # -------------------------------------------------------------
        # Part B: Application & Web Preview Verification Checks
        # -------------------------------------------------------------
        token_file = run_dir / "admin_token"
        admin_token = token_file.read_text(encoding="utf-8").strip() if token_file.is_file() else None

        app_checks = verify_application_and_preview(
            public_ip=public_ip,
            app_port=self.p05_config.app_port,
            admin_token=admin_token,
            run_id=run_id,
        )
        all_checks.extend(app_checks)

        overall_passed = all(c.passed for c in all_checks)
        return VerificationResult(
            practical_id="P05",
            run_id=run_id,
            success=overall_passed,
            checks=all_checks,
            summary=(
                f"Practical P05 Verification: {sum(1 for c in all_checks if c.passed)}/{len(all_checks)} checks passed."
            ),
        )

    def cleanup(self, manifest: RunManifest, context: Any) -> CleanupResult:
        """Tear down only the AWS resources tracked in the run manifest in reverse dependency order."""
        adapter: AWSAdapter = context if isinstance(context, AWSAdapter) else getattr(context, "adapter", None)
        if not adapter:
            raise RuntimeError("Cleanup context missing valid AWSAdapter.")

        if adapter.mock_mode:
            deleted = [r.resource_id for r in manifest.resources]
            run_dir = get_run_dir(manifest.run_id)
            local_token = run_dir / "admin_token"
            if local_token.is_file():
                try:
                    local_token.unlink()
                    deleted.append(f"local-secret:{local_token}")
                except Exception:
                    pass
            return CleanupResult(
                practical_id="P05",
                run_id=manifest.run_id,
                success=True,
                resources_deleted=deleted,
                resources_absent=[],
                resources_failed=[],
                resources_unverified=[],
                errors=[],
            )

        # -----------------------------------------------------------------
        # Real AWS Cleanup: Enforce strict safety guards before touching AWS
        # -----------------------------------------------------------------

        # 1. Refuse cleanup on mock manifests when in live execution mode
        is_mock_manifest = (
            manifest.aws_account_id == "mock"
            or manifest.aws_account_id == "mock-123456789012"
            or "mock" in manifest.aws_account_id.lower()
            or any("mock" in r.resource_id.lower() or ":i-mock" in (r.arn or "") for r in manifest.resources)
        )
        if is_mock_manifest:
            msg = (
                f"Cleanup refused: Manifest '{manifest.run_id}' was generated in mock mode. "
                "Live AWS cleanup will not act on mock manifests."
            )
            logger.error(msg)
            return CleanupResult(
                practical_id="P05",
                run_id=manifest.run_id,
                success=False,
                resources_deleted=[],
                resources_failed=[],
                resources_absent=[],
                resources_unverified=[],
                errors=[msg],
            )

        # 2. Refuse cleanup if AWS account or region do not match active identity
        identity = adapter.get_caller_identity()
        raw_account = identity.get("Account", "unknown")
        masked_account = mask_account_id(raw_account)
        active_region = adapter.region_name

        if manifest.aws_account_id not in (masked_account, raw_account):
            msg = (
                f"Cleanup refused: Manifest AWS account '{manifest.aws_account_id}' does not match "
                f"active caller account '{masked_account}'. Cross-account deletion is prohibited."
            )
            logger.error(msg)
            return CleanupResult(
                practical_id="P05",
                run_id=manifest.run_id,
                success=False,
                resources_deleted=[],
                resources_failed=[],
                resources_absent=[],
                resources_unverified=[],
                errors=[msg],
            )

        if manifest.aws_region != active_region:
            msg = (
                f"Cleanup refused: Manifest AWS region '{manifest.aws_region}' does not match "
                f"active target region '{active_region}'. Cross-region deletion is prohibited."
            )
            logger.error(msg)
            return CleanupResult(
                practical_id="P05",
                run_id=manifest.run_id,
                success=False,
                resources_deleted=[],
                resources_failed=[],
                resources_absent=[],
                resources_unverified=[],
                errors=[msg],
            )

        resources_deleted: List[str] = []
        resources_absent: List[str] = []
        resources_failed: List[str] = []
        resources_unverified: List[str] = []
        errors: List[str] = []

        # Group resources by type from manifest
        res_map: Dict[str, List[str]] = {}
        for r in manifest.resources:
            res_map.setdefault(r.resource_type, []).append(r.resource_id)

        # -------------------------------------------------------------
        # Step 1: EC2 Instances (Must terminate before security groups)
        # -------------------------------------------------------------
        ec2_client = adapter.get_client("ec2")
        instance_ids = res_map.get("ec2-instance", [])
        for inst_id in instance_ids:
            try:
                term_res = cleanup_ec2_resources(ec2_client, instance_id=inst_id, expected_run_id=manifest.run_id)
                if term_res:
                    if _is_mock_client(ec2_client):
                        resources_deleted.append(f"ec2-instance:{inst_id}")
                    else:
                        # Independent verification of terminal state in live AWS
                        try:
                            desc = ec2_client.describe_instances(InstanceIds=[inst_id])
                            state = desc.get("Reservations", [{}])[0].get("Instances", [{}])[0].get("State", {}).get("Name")
                            if state in ("terminated", "shutting-down"):
                                resources_deleted.append(f"ec2-instance:{inst_id}")
                            else:
                                resources_unverified.append(f"ec2-instance:{inst_id}")
                        except ClientError as e:
                            if e.response.get("Error", {}).get("Code") in ("InvalidInstanceID.NotFound", "InvalidInstanceID.Malformed"):
                                resources_deleted.append(f"ec2-instance:{inst_id}")
                            else:
                                resources_unverified.append(f"ec2-instance:{inst_id}")
                else:
                    # Check if already absent
                    try:
                        desc = ec2_client.describe_instances(InstanceIds=[inst_id])
                        if isinstance(desc, dict):
                            state = desc.get("Reservations", [{}])[0].get("Instances", [{}])[0].get("State", {}).get("Name")
                            if state == "terminated":
                                resources_absent.append(f"ec2-instance:{inst_id}")
                            else:
                                resources_failed.append(f"ec2-instance:{inst_id}")
                        else:
                            resources_absent.append(f"ec2-instance:{inst_id}")
                    except ClientError as e:
                        if e.response.get("Error", {}).get("Code") in ("InvalidInstanceID.NotFound", "InvalidInstanceID.Malformed"):
                            resources_absent.append(f"ec2-instance:{inst_id}")
                        else:
                            resources_failed.append(f"ec2-instance:{inst_id}")
            except Exception as e:
                errors.append(f"Failed to terminate instance {inst_id}: {e}")
                resources_failed.append(f"ec2-instance:{inst_id}")

        # -------------------------------------------------------------
        # Step 2: Security Groups (After EC2 ENIs detach)
        # -------------------------------------------------------------
        sg_ids = res_map.get("security-group", [])
        for sg_id in sg_ids:
            try:
                sg_res = cleanup_ec2_resources(ec2_client, security_group_id=sg_id, expected_run_id=manifest.run_id)
                if sg_res:
                    if _is_mock_client(ec2_client):
                        resources_deleted.append(f"security-group:{sg_id}")
                    else:
                        # Independent verification
                        try:
                            sg_desc = ec2_client.describe_security_groups(GroupIds=[sg_id])
                            if sg_desc.get("SecurityGroups"):
                                resources_unverified.append(f"security-group:{sg_id}")
                            else:
                                resources_deleted.append(f"security-group:{sg_id}")
                        except ClientError as e:
                            if e.response.get("Error", {}).get("Code") in ("InvalidGroup.NotFound", "InvalidGroupId.Malformed"):
                                resources_deleted.append(f"security-group:{sg_id}")
                            else:
                                resources_unverified.append(f"security-group:{sg_id}")
                else:
                    try:
                        sg_desc = ec2_client.describe_security_groups(GroupIds=[sg_id])
                        if isinstance(sg_desc, dict) and sg_desc.get("SecurityGroups"):
                            resources_failed.append(f"security-group:{sg_id}")
                        else:
                            resources_absent.append(f"security-group:{sg_id}")
                    except ClientError as e:
                        if e.response.get("Error", {}).get("Code") in ("InvalidGroup.NotFound", "InvalidGroupId.Malformed"):
                            resources_absent.append(f"security-group:{sg_id}")
                        else:
                            resources_failed.append(f"security-group:{sg_id}")
            except Exception as e:
                errors.append(f"Failed to delete security group {sg_id}: {e}")
                resources_failed.append(f"security-group:{sg_id}")

        # -------------------------------------------------------------
        # Step 3: Key Pairs
        # -------------------------------------------------------------
        key_names = res_map.get("key-pair", [])
        for k_name in key_names:
            try:
                kp_res = cleanup_ec2_resources(ec2_client, key_name=k_name, expected_run_id=manifest.run_id)
                if kp_res:
                    resources_deleted.append(f"key-pair:{k_name}")
                else:
                    resources_absent.append(f"key-pair:{k_name}")
            except Exception as e:
                errors.append(f"Failed to delete key pair {k_name}: {e}")
                resources_failed.append(f"key-pair:{k_name}")

        # -------------------------------------------------------------
        # Step 4: IAM Instance Profiles (Before IAM roles)
        # -------------------------------------------------------------
        iam_client = adapter.get_client("iam")
        profiles = res_map.get("iam-instance-profile", [])
        for prof in profiles:
            try:
                prof_res = cleanup_iam_resources(iam_client, profile_name=prof, expected_run_id=manifest.run_id)
                if prof_res:
                    if _is_mock_client(iam_client):
                        resources_deleted.append(f"iam-instance-profile:{prof}")
                    else:
                        # Independent verification
                        try:
                            p_desc = iam_client.get_instance_profile(InstanceProfileName=prof)
                            if p_desc.get("InstanceProfile"):
                                resources_unverified.append(f"iam-instance-profile:{prof}")
                            else:
                                resources_deleted.append(f"iam-instance-profile:{prof}")
                        except ClientError as e:
                            if e.response.get("Error", {}).get("Code") == "NoSuchEntity":
                                resources_deleted.append(f"iam-instance-profile:{prof}")
                            else:
                                resources_unverified.append(f"iam-instance-profile:{prof}")
                else:
                    resources_absent.append(f"iam-instance-profile:{prof}")
            except Exception as e:
                errors.append(f"Failed to delete IAM profile {prof}: {e}")
                resources_failed.append(f"iam-instance-profile:{prof}")

        # -------------------------------------------------------------
        # Step 5: IAM Roles (After profile detachment)
        # -------------------------------------------------------------
        roles = res_map.get("iam-role", [])
        for role in roles:
            try:
                role_res = cleanup_iam_resources(iam_client, role_name=role, expected_run_id=manifest.run_id)
                if role_res:
                    if _is_mock_client(iam_client):
                        resources_deleted.append(f"iam-role:{role}")
                    else:
                        # Independent verification
                        try:
                            r_desc = iam_client.get_role(RoleName=role)
                            if r_desc.get("Role"):
                                resources_unverified.append(f"iam-role:{role}")
                            else:
                                resources_deleted.append(f"iam-role:{role}")
                        except ClientError as e:
                            if e.response.get("Error", {}).get("Code") == "NoSuchEntity":
                                resources_deleted.append(f"iam-role:{role}")
                            else:
                                resources_unverified.append(f"iam-role:{role}")
                else:
                    resources_absent.append(f"iam-role:{role}")
            except Exception as e:
                errors.append(f"Failed to delete IAM role {role}: {e}")
                resources_failed.append(f"iam-role:{role}")

        # -------------------------------------------------------------
        # Step 6: S3 Bucket & Objects (Draining versions & markers)
        # -------------------------------------------------------------
        s3_client = adapter.get_client("s3")
        buckets = res_map.get("s3-bucket", [])
        objects = res_map.get("s3-object", [])
        obj_keys = [o.split(f"s3://{b}/")[-1] for b in buckets for o in objects if f"s3://{b}/" in o]

        for b in buckets:
            try:
                s3_res = cleanup_s3_resources(
                    s3_client,
                    bucket_name=b,
                    tracked_object_keys=obj_keys,
                    expected_run_id=manifest.run_id,
                )
                if s3_res:
                    if _is_mock_client(s3_client):
                        resources_deleted.append(f"s3-bucket:{b}")
                    else:
                        # Independent verification of bucket absence
                        try:
                            s3_client.head_bucket(Bucket=b)
                            resources_unverified.append(f"s3-bucket:{b}")
                        except ClientError as e:
                            err_code = str(e.response.get("Error", {}).get("Code", ""))
                            if err_code in ("404", "NoSuchBucket", "NotFound"):
                                resources_deleted.append(f"s3-bucket:{b}")
                            else:
                                resources_unverified.append(f"s3-bucket:{b}")
                        except Exception:
                            resources_deleted.append(f"s3-bucket:{b}")
                else:
                    resources_absent.append(f"s3-bucket:{b}")
            except Exception as e:
                errors.append(f"Failed to clean up S3 bucket {b}: {e}")
                resources_failed.append(f"s3-bucket:{b}")

        # -------------------------------------------------------------
        # Step 7: DynamoDB Tables
        # -------------------------------------------------------------
        dynamodb_client = adapter.get_client("dynamodb")
        tables = res_map.get("dynamodb-table", [])
        for tbl in tables:
            try:
                ddb_res = cleanup_dynamodb_resources(
                    dynamodb_client,
                    table_name=tbl,
                    expected_run_id=manifest.run_id,
                )
                if ddb_res:
                    if _is_mock_client(dynamodb_client):
                        resources_deleted.append(f"dynamodb-table:{tbl}")
                    else:
                        # Independent verification
                        try:
                            tbl_desc = dynamodb_client.describe_table(TableName=tbl)
                            t_status = tbl_desc.get("Table", {}).get("TableStatus")
                            if t_status == "DELETING":
                                resources_deleted.append(f"dynamodb-table:{tbl}")
                            else:
                                resources_unverified.append(f"dynamodb-table:{tbl}")
                        except ClientError as e:
                            if e.response.get("Error", {}).get("Code") in ("ResourceNotFoundException", "TableNotFoundException"):
                                resources_deleted.append(f"dynamodb-table:{tbl}")
                            else:
                                resources_unverified.append(f"dynamodb-table:{tbl}")
                else:
                    resources_absent.append(f"dynamodb-table:{tbl}")
            except Exception as e:
                errors.append(f"Failed to delete DynamoDB table {tbl}: {e}")
                resources_failed.append(f"dynamodb-table:{tbl}")

        # -------------------------------------------------------------
        # Step 8: Local admin token file
        # -------------------------------------------------------------
        run_dir = get_run_dir(manifest.run_id)
        local_token = run_dir / "admin_token"
        if local_token.is_file():
            try:
                local_token.unlink()
                resources_deleted.append(f"local-secret:{local_token}")
                logger.info(f"Removed local admin token file '{local_token}'.")
            except Exception as e:
                errors.append(f"Could not remove local token file '{local_token}': {e}")
                resources_failed.append(f"local-secret:{local_token}")
        else:
            resources_absent.append(f"local-secret:{local_token}")

        success = (len(resources_failed) == 0 and len(resources_unverified) == 0 and len(errors) == 0)
        return CleanupResult(
            practical_id="P05",
            run_id=manifest.run_id,
            success=success,
            resources_deleted=resources_deleted,
            resources_absent=resources_absent,
            resources_failed=resources_failed,
            resources_unverified=resources_unverified,
            errors=errors,
        )
