"""Practical 01 implementation: EC2, S3, and DynamoDB workflow."""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

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
from cloudprac.practicals.p01.config import P01Config
from cloudprac.practicals.p01.dynamodb import (
    cleanup_dynamodb_resources,
    create_dynamodb_table,
    insert_sample_records,
    verify_dynamodb_resources,
    wait_for_table_active,
)
from cloudprac.practicals.p01.ec2 import (
    cleanup_ec2_resources,
    find_latest_al2023_ami,
    get_default_or_first_vpc,
    launch_ec2_instance,
    setup_key_pair,
    setup_security_group,
    verify_ec2_instance,
    wait_for_instance_running,
)
from cloudprac.practicals.p01.s3 import (
    cleanup_s3_resources,
    create_private_bucket,
    download_file_from_s3,
    upload_file_to_s3,
    verify_s3_resources,
)
from cloudprac.practicals.p01.sample_data import (
    get_default_dynamodb_items,
    get_sample_file_content,
)
from cloudprac.utils.config import CloudPracConfig
from cloudprac.utils.logging import get_logger
from cloudprac.utils.paths import get_cloudprac_home, get_run_dir

logger = get_logger()


def sanitize_name(raw_name: str) -> str:
    """Sanitize strings for AWS resource naming."""
    return re.sub(r"[^a-zA-Z0-9-]", "-", raw_name).lower()


class P01Practical(PracticalContract):
    """Complete implementation of Practical 01: EC2, S3, and DynamoDB."""

    def __init__(self, p01_config: Optional[P01Config] = None) -> None:
        self.p01_config = p01_config or P01Config()
        self._metadata = PracticalMetadata(
            id="P01",
            title="EC2, S3 and DynamoDB Implementation",
            description=(
                "Create a storage bucket using Amazon S3 to manage files, create a NoSQL database "
                "using DynamoDB, insert and retrieve data, and launch and configure an Amazon EC2 "
                "virtual machine on AWS."
            ),
            category="Compute, Storage & Database",
            aws_services=["EC2", "S3", "DynamoDB"],
            status=PracticalStatus.CONFIGURED,
            estimated_cost="Free Tier eligible (hourly EC2/EBS/IPv4 charges apply if running past free tier)",
            prerequisites=[
                "Valid AWS IAM credentials with EC2, S3, and DynamoDB permissions",
                "Existing VPC and Subnet in target region (or permission to use default VPC)",
            ],
            syllabus_source="Cloud Computing Laboratory Practical 1",
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
                "1. Discover latest Amazon Linux 2023 AMI and launch EC2 virtual machine",
                "2. Create restricted security group and download private key pair",
                "3. Provision private Amazon S3 bucket with Block Public Access",
                "4. Upload sample file, list objects, download, and verify SHA-256 integrity",
                "5. Provision Amazon DynamoDB NoSQL table with On-Demand (PAY_PER_REQUEST) billing",
                "6. Insert structured sample items and verify consistent GetItem retrieval",
                "7. Independently verify resource states against requirements",
                "8. Provide guarded cleanup and rollback for all created resources",
            ],
            "cost_cautions": [
                "EC2 instances incur hourly compute and public IPv4 address charges while running.",
                "Always run 'cloudprac cleanup P01' after completing and submitting your lab.",
            ],
        }

    def plan(self, config: CloudPracConfig, run_id: str) -> ExecutionPlan:
        """Generate a dry-run execution plan detailing all proposed operations."""
        clean_run = sanitize_name(run_id)
        bucket_name = self.p01_config.bucket_name or f"cloudprac-p01-{clean_run}"
        table_name = self.p01_config.table_name or f"cloudprac-p01-items-{clean_run}"
        sg_name = f"cloudprac-p01-sg-{clean_run}"
        key_name = self.p01_config.key_name or f"cloudprac-p01-key-{clean_run}"
        instance_name = f"cloudprac-p01-vm-{clean_run}"

        steps = [
            ExecutionPlanStep(
                step_number=1,
                action="CREATE_SECURITY_GROUP",
                resource_type="AWS::EC2::SecurityGroup",
                resource_name=sg_name,
                description="Create practical security group in VPC with no open public ingress by default",
                estimated_cost="$0.00",
            ),
            ExecutionPlanStep(
                step_number=2,
                action="CREATE_KEY_PAIR",
                resource_type="AWS::EC2::KeyPair",
                resource_name=key_name,
                description="Create EC2 key pair and securely store private key locally at ~/.cloudprac/keys/",
                estimated_cost="$0.00",
            ),
            ExecutionPlanStep(
                step_number=3,
                action="RUN_EC2_INSTANCE",
                resource_type="AWS::EC2::Instance",
                resource_name=instance_name,
                description=f"Launch Amazon Linux 2023 ({self.p01_config.instance_type}) and wait until running",
                estimated_cost="~$0.0116/hr (Free Tier eligible)",
            ),
            ExecutionPlanStep(
                step_number=4,
                action="CREATE_S3_BUCKET",
                resource_type="AWS::S3::Bucket",
                resource_name=bucket_name,
                description="Create private S3 bucket and enable S3 Block Public Access",
                estimated_cost="$0.00 (within Free Tier)",
            ),
            ExecutionPlanStep(
                step_number=5,
                action="S3_FILE_OPERATIONS",
                resource_type="AWS::S3::Object",
                resource_name=f"{bucket_name}/data/sample_data.txt",
                description="Upload sample file, retrieve metadata, download, and verify SHA-256 checksum",
                estimated_cost="<$0.001 (PUT/GET requests)",
            ),
            ExecutionPlanStep(
                step_number=6,
                action="CREATE_DYNAMODB_TABLE",
                resource_type="AWS::DynamoDB::Table",
                resource_name=table_name,
                description="Create DynamoDB table with partition key 'id' and On-Demand (PAY_PER_REQUEST) billing",
                estimated_cost="$0.00 (Zero idle cost)",
            ),
            ExecutionPlanStep(
                step_number=7,
                action="DYNAMODB_RECORD_OPERATIONS",
                resource_type="AWS::DynamoDB::Item",
                resource_name=f"{table_name} [3 items]",
                description="Insert 3 sample records and verify consistent retrieval with GetItem",
                estimated_cost="<$0.001 (Read/Write units)",
            ),
        ]

        warnings = [
            "EC2 instances incur charges while running. Remember to run 'cloudprac cleanup P01' after submitting.",
            "Public IPv4 addresses on EC2 may incur an hourly charge depending on account configuration.",
            "Never share or commit generated private keys to source control.",
        ]

        return ExecutionPlan(
            practical_id=self.metadata.id,
            run_id=run_id,
            steps=steps,
            estimated_total_cost="~$0.012/hr while instance runs (Free Tier eligible)",
            warnings=warnings,
        )

    def execute(self, plan: ExecutionPlan, context: Any) -> ExecutionResult:
        """Execute the planned AWS operations in a controlled and tracked manner."""
        adapter: AWSAdapter = context if isinstance(context, AWSAdapter) else AWSAdapter()
        region = self.p01_config.region or adapter.region
        clean_run = sanitize_name(plan.run_id)

        # Handle mock/dry-run execution
        if adapter.mock_mode:
            logger.info("Executing in MOCK mode (no live AWS resources provisioned).")
            manifest = RunManifest(
                run_id=plan.run_id,
                practical_id="P01",
                aws_region=region,
                aws_account_id="123456789012",
                resources=[
                    TrackedResource(
                        resource_id="i-mock1234567890abcdef0",
                        resource_type="AWS::EC2::Instance",
                        resource_name=f"cloudprac-p01-vm-{clean_run}",
                        tags={"ManagedBy": "CloudPrac", "RunId": plan.run_id, "PracticalId": "P01"},
                    ),
                    TrackedResource(
                        resource_id="sg-mock1234567890abcdef0",
                        resource_type="AWS::EC2::SecurityGroup",
                        resource_name=f"cloudprac-p01-sg-{clean_run}",
                        tags={"ManagedBy": "CloudPrac", "RunId": plan.run_id},
                    ),
                    TrackedResource(
                        resource_id=f"cloudprac-p01-key-{clean_run}",
                        resource_type="AWS::EC2::KeyPair",
                        resource_name=f"cloudprac-p01-key-{clean_run}",
                    ),
                    TrackedResource(
                        resource_id=f"cloudprac-p01-{clean_run}",
                        resource_type="AWS::S3::Bucket",
                        resource_name=f"cloudprac-p01-{clean_run}",
                    ),
                    TrackedResource(
                        resource_id=f"cloudprac-p01-items-{clean_run}",
                        resource_type="AWS::DynamoDB::Table",
                        resource_name=f"cloudprac-p01-items-{clean_run}",
                    ),
                ],
            )
            return ExecutionResult(
                success=True,
                run_id=plan.run_id,
                practical_id="P01",
                message="Mock execution of Practical 01 completed successfully.",
                steps_executed=7,
                manifest=manifest,
            )

        identity = adapter.get_caller_identity()
        account_id = identity.get("Account", "000000000000")
        short_acc = account_id[-4:] if len(account_id) >= 4 else "0000"

        # Deterministic resource identifiers
        bucket_name = self.p01_config.bucket_name or f"cloudprac-p01-{short_acc}-{clean_run}"
        table_name = self.p01_config.table_name or f"cloudprac-p01-items-{clean_run}"
        sg_name = f"cloudprac-p01-sg-{clean_run}"
        key_name = self.p01_config.key_name or f"cloudprac-p01-key-{clean_run}"
        instance_name = f"cloudprac-p01-vm-{clean_run}"

        tag_dict = {
            "ManagedBy": "CloudPrac",
            "PracticalId": "P01",
            "RunId": plan.run_id,
        }

        tracked_resources: List[TrackedResource] = []
        errors: List[str] = []
        steps_done = 0

        ec2_client = adapter.get_client("ec2")
        s3_client = adapter.get_client("s3")
        dynamodb_client = adapter.get_client("dynamodb")

        run_dir = get_run_dir(plan.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 1. EC2 Networking: Discover VPC and Subnet
            vpc_id, subnet_id = get_default_or_first_vpc(ec2_client)

            # 2. EC2 Security Group
            sg_id = setup_security_group(
                ec2_client=ec2_client,
                vpc_id=vpc_id,
                group_name=sg_name,
                ssh_cidr=self.p01_config.ssh_cidr,
                tags=tag_dict,
            )
            tracked_resources.append(
                TrackedResource(
                    resource_id=sg_id,
                    resource_type="AWS::EC2::SecurityGroup",
                    resource_name=sg_name,
                    tags=tag_dict,
                )
            )
            steps_done += 1

            # 3. EC2 Key Pair
            kp_name, _ = setup_key_pair(
                ec2_client=ec2_client,
                key_name=key_name,
                save_local_file=self.p01_config.save_key_file,
            )
            tracked_resources.append(
                TrackedResource(
                    resource_id=kp_name,
                    resource_type="AWS::EC2::KeyPair",
                    resource_name=kp_name,
                )
            )
            steps_done += 1

            # 4. EC2 AMI & Launch
            ami_id = self.p01_config.ami_id or find_latest_al2023_ami(ec2_client)
            instance_tags = {**tag_dict, "Name": instance_name}
            instance_id = launch_ec2_instance(
                ec2_client=ec2_client,
                image_id=ami_id,
                instance_type=self.p01_config.instance_type,
                subnet_id=subnet_id,
                security_group_id=sg_id,
                key_name=kp_name,
                tags=instance_tags,
            )
            tracked_resources.append(
                TrackedResource(
                    resource_id=instance_id,
                    resource_type="AWS::EC2::Instance",
                    resource_name=instance_name,
                    tags=instance_tags,
                )
            )
            wait_for_instance_running(ec2_client, instance_id)
            steps_done += 1

            # 5. S3 Bucket Creation & BPA
            create_private_bucket(
                s3_client=s3_client,
                bucket_name=bucket_name,
                region=region,
                tags=tag_dict,
            )
            tracked_resources.append(
                TrackedResource(
                    resource_id=bucket_name,
                    resource_type="AWS::S3::Bucket",
                    resource_name=bucket_name,
                    tags=tag_dict,
                )
            )
            steps_done += 1

            # 6. S3 File Operations: Create local sample, Upload, Download, Checksum
            sample_content = get_sample_file_content(plan.run_id)
            sample_file_path = run_dir / "sample_data.txt"
            sample_file_path.write_text(sample_content, encoding="utf-8")

            upload_file_to_s3(
                s3_client=s3_client,
                bucket_name=bucket_name,
                object_key="data/sample_data.txt",
                local_path=sample_file_path,
            )
            download_dest = run_dir / "downloaded_sample_data.txt"
            download_file_from_s3(
                s3_client=s3_client,
                bucket_name=bucket_name,
                object_key="data/sample_data.txt",
                destination_path=download_dest,
            )
            steps_done += 1

            # 7. DynamoDB Table Creation & Wait Active
            create_dynamodb_table(
                dynamodb_client=dynamodb_client,
                table_name=table_name,
                billing_mode=self.p01_config.dynamodb_billing_mode,
                tags=tag_dict,
            )
            tracked_resources.append(
                TrackedResource(
                    resource_id=table_name,
                    resource_type="AWS::DynamoDB::Table",
                    resource_name=table_name,
                    tags=tag_dict,
                )
            )
            wait_for_table_active(dynamodb_client, table_name)
            steps_done += 1

            # 8. DynamoDB Record Insertion & Retrieval
            sample_items = get_default_dynamodb_items()
            insert_sample_records(dynamodb_client, table_name, sample_items)
            steps_done += 1

        except Exception as e:
            logger.error(f"Execution error during Practical 01: {e}")
            errors.append(str(e))

        manifest = RunManifest(
            run_id=plan.run_id,
            practical_id="P01",
            aws_region=region,
            aws_account_id=account_id,
            resources=tracked_resources,
        )

        return ExecutionResult(
            success=(len(errors) == 0),
            run_id=plan.run_id,
            practical_id="P01",
            message="Practical 01 executed successfully." if not errors else f"Execution failed: {errors[0]}",
            steps_executed=steps_done,
            manifest=manifest,
            errors=errors,
        )

    def verify(self, run_id: str, context: Any) -> VerificationResult:
        """Independently verify actual AWS state of EC2, S3, and DynamoDB resources."""
        adapter: AWSAdapter = context if isinstance(context, AWSAdapter) else AWSAdapter()
        checks: List[VerificationCheck] = []

        if adapter.mock_mode:
            # Simulated verification in mock mode
            checks.extend([
                VerificationCheck(
                    check_id="EC2-01",
                    name="EC2 Instance State",
                    description="Verify instance is running",
                    expected="running",
                    actual="running",
                    passed=True,
                ),
                VerificationCheck(
                    check_id="S3-01",
                    name="S3 Bucket Existence",
                    description="Verify bucket exists and is private",
                    expected="Active & BPA Enabled",
                    actual="Active & BPA Enabled",
                    passed=True,
                ),
                VerificationCheck(
                    check_id="S3-04",
                    name="S3 Data Integrity",
                    description="Verify uploaded vs downloaded SHA-256 hash match",
                    expected="Checksum Match",
                    actual="Checksum Match",
                    passed=True,
                ),
                VerificationCheck(
                    check_id="DDB-01",
                    name="DynamoDB Table State",
                    description="Verify table is ACTIVE",
                    expected="ACTIVE",
                    actual="ACTIVE",
                    passed=True,
                ),
                VerificationCheck(
                    check_id="DDB-03",
                    name="DynamoDB Record Retrieval",
                    description="Verify sample records retrieved via GetItem",
                    expected="3 verified records",
                    actual="3 verified records",
                    passed=True,
                ),
            ])
            return VerificationResult(
                success=True,
                run_id=run_id,
                practical_id="P01",
                checks=checks,
                summary="All mock verification checks passed.",
            )

        run_dir = get_run_dir(run_id)
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.is_file():
            return VerificationResult(
                success=False,
                run_id=run_id,
                practical_id="P01",
                checks=[
                    VerificationCheck(
                        check_id="MANIFEST-01",
                        name="Run Manifest Existence",
                        description="Verify run manifest exists to locate provisioned resources",
                        expected="Manifest file present",
                        actual="Manifest not found",
                        passed=False,
                    )
                ],
                summary="Verification could not locate run manifest.",
            )

        manifest = RunManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        res_by_type = {r.resource_type: r for r in manifest.resources}

        # 1. Verify EC2
        ec2_res = res_by_type.get("AWS::EC2::Instance")
        sg_res = res_by_type.get("AWS::EC2::SecurityGroup")
        kp_res = res_by_type.get("AWS::EC2::KeyPair")
        if ec2_res:
            ec2_client = adapter.get_client("ec2")
            checks.extend(
                verify_ec2_instance(
                    ec2_client=ec2_client,
                    instance_id=ec2_res.resource_id,
                    expected_type=self.p01_config.instance_type,
                    expected_key_name=kp_res.resource_id if kp_res else None,
                    expected_sg_id=sg_res.resource_id if sg_res else None,
                )
            )

        # 2. Verify S3
        s3_res = res_by_type.get("AWS::S3::Bucket")
        if s3_res:
            s3_client = adapter.get_client("s3")
            sample_orig = run_dir / "sample_data.txt"
            sample_down = run_dir / "downloaded_sample_data.txt"
            checks.extend(
                verify_s3_resources(
                    s3_client=s3_client,
                    bucket_name=s3_res.resource_id,
                    sample_key="data/sample_data.txt",
                    original_file_path=sample_orig,
                    downloaded_file_path=sample_down,
                )
            )

        # 3. Verify DynamoDB
        ddb_res = res_by_type.get("AWS::DynamoDB::Table")
        if ddb_res:
            dynamodb_client = adapter.get_client("dynamodb")
            sample_items = get_default_dynamodb_items()
            checks.extend(
                verify_dynamodb_resources(
                    dynamodb_client=dynamodb_client,
                    table_name=ddb_res.resource_id,
                    expected_items=sample_items,
                )
            )

        all_passed = all(c.passed for c in checks)
        return VerificationResult(
            success=all_passed,
            run_id=run_id,
            practical_id="P01",
            checks=checks,
            summary="All verification checks passed." if all_passed else "Some verification checks failed.",
        )

    def cleanup(self, manifest: RunManifest, context: Any) -> CleanupResult:
        """Safely destroy only the AWS resources provisioned by this practical run."""
        adapter: AWSAdapter = context if isinstance(context, AWSAdapter) else AWSAdapter()
        deleted: List[str] = []
        failed: List[str] = []
        errors: List[str] = []

        if adapter.mock_mode:
            logger.info("Performing simulated cleanup in MOCK mode.")
            return CleanupResult(
                success=True,
                run_id=manifest.run_id,
                practical_id="P01",
                resources_deleted=[r.resource_id for r in manifest.resources],
                resources_failed=[],
            )

        res_by_type = {r.resource_type: r for r in manifest.resources}

        # 1. EC2 Cleanup (Instance -> SG -> KeyPair)
        ec2_res = res_by_type.get("AWS::EC2::Instance")
        sg_res = res_by_type.get("AWS::EC2::SecurityGroup")
        kp_res = res_by_type.get("AWS::EC2::KeyPair")
        ec2_client = adapter.get_client("ec2")
        ec2_del, ec2_fail = cleanup_ec2_resources(
            ec2_client=ec2_client,
            instance_id=ec2_res.resource_id if ec2_res else None,
            security_group_id=sg_res.resource_id if sg_res else None,
            key_name=kp_res.resource_id if kp_res else None,
        )
        deleted.extend(ec2_del)
        failed.extend(ec2_fail)

        # 2. S3 Cleanup (Empty bucket -> Delete bucket)
        s3_res = res_by_type.get("AWS::S3::Bucket")
        if s3_res:
            s3_client = adapter.get_client("s3")
            s3_del, s3_fail = cleanup_s3_resources(s3_client, s3_res.resource_id)
            deleted.extend(s3_del)
            failed.extend(s3_fail)

        # 3. DynamoDB Cleanup (Delete table)
        ddb_res = res_by_type.get("AWS::DynamoDB::Table")
        if ddb_res:
            dynamodb_client = adapter.get_client("dynamodb")
            ddb_del, ddb_fail = cleanup_dynamodb_resources(dynamodb_client, ddb_res.resource_id)
            deleted.extend(ddb_del)
            failed.extend(ddb_fail)

        return CleanupResult(
            success=(len(failed) == 0),
            run_id=manifest.run_id,
            practical_id="P01",
            resources_deleted=deleted,
            resources_failed=failed,
            errors=errors,
        )
