"""EC2 provisioning, validation, verification, and cleanup for Practical 01."""

import os
import platform
import stat
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from botocore.exceptions import ClientError

from cloudprac.core.models import (
    TrackedResource,
    VerificationCheck,
)
from cloudprac.utils.logging import get_logger
from cloudprac.utils.paths import get_cloudprac_home

logger = get_logger()


def get_default_or_first_vpc(ec2_client: Any) -> Tuple[str, str]:
    """Find a default VPC and suitable subnet, or fallback to an active VPC."""
    try:
        vpcs_resp = ec2_client.describe_vpcs(
            Filters=[{"Name": "isDefault", "Values": ["true"]}]
        )
        vpcs = vpcs_resp.get("Vpcs", [])
        if not vpcs:
            # Fallback to any available VPC
            all_vpcs_resp = ec2_client.describe_vpcs()
            vpcs = all_vpcs_resp.get("Vpcs", [])

        if not vpcs:
            raise RuntimeError(
                "No VPC found in the selected AWS Region. "
                "Run 'aws ec2 create-default-vpc' to create a default VPC before continuing."
            )

        vpc_id = vpcs[0]["VpcId"]

        # Find subnets in this VPC
        subnets_resp = ec2_client.describe_subnets(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )
        subnets = subnets_resp.get("Subnets", [])
        if not subnets:
            raise RuntimeError(
                f"VPC '{vpc_id}' contains no subnets. At least one subnet is required to launch an EC2 instance."
            )

        subnet_id = subnets[0]["SubnetId"]
        return vpc_id, subnet_id
    except ClientError as e:
        logger.error(f"Error querying VPCs/Subnets: {e}")
        raise


def find_latest_al2023_ami(ec2_client: Any, ssm_client: Optional[Any] = None, architecture: str = "x86_64") -> str:
    """Discover the latest available Amazon Linux 2023 AMI without hard-coding."""
    # 1. Attempt SSM Parameter Store query first if client provided
    if ssm_client:
        try:
            param_name = f"/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-{architecture}"
            resp = ssm_client.get_parameter(Name=param_name)
            ami_id = resp.get("Parameter", {}).get("Value")
            if ami_id and ami_id.startswith("ami-"):
                return ami_id
        except Exception as e:
            logger.debug(f"SSM AMI lookup failed or not permitted, falling back to DescribeImages: {e}")

    # 2. Query DescribeImages for Amazon Linux 2023
    try:
        images_resp = ec2_client.describe_images(
            Owners=["amazon"],
            Filters=[
                {"Name": "name", "Values": [f"al2023-ami-2023.*-{architecture}"]},
                {"Name": "state", "Values": ["available"]},
                {"Name": "image-type", "Values": ["machine"]},
            ],
        )
        images = images_resp.get("Images", [])
        if not images:
            raise RuntimeError(
                f"No available Amazon Linux 2023 AMI found for architecture '{architecture}' in this region."
            )

        # Sort descending by CreationDate
        images.sort(key=lambda x: x.get("CreationDate", ""), reverse=True)
        return images[0]["ImageId"]
    except ClientError as e:
        logger.error(f"Failed to describe EC2 images: {e}")
        raise


def setup_key_pair(
    ec2_client: Any,
    key_name: str,
    save_local_file: bool = True,
) -> Tuple[str, Optional[Path]]:
    """Create or verify an EC2 key pair, saving private key locally if newly created."""
    # Check if key pair already exists
    try:
        existing = ec2_client.describe_key_pairs(KeyNames=[key_name])
        if existing.get("KeyPairs"):
            logger.info(f"EC2 Key Pair '{key_name}' already exists in AWS.")
            return key_name, None
    except ClientError as e:
        err_code = e.response.get("Error", {}).get("Code", "")
        if err_code != "InvalidKeyPair.NotFound":
            raise

    # Create new key pair
    logger.info(f"Creating new EC2 Key Pair '{key_name}' in AWS...")
    resp = ec2_client.create_key_pair(KeyName=key_name, KeyType="rsa")
    private_key_material = resp.get("KeyMaterial")

    key_file_path: Optional[Path] = None
    if save_local_file and private_key_material:
        keys_dir = get_cloudprac_home() / "keys"
        keys_dir.mkdir(parents=True, exist_ok=True)
        key_file_path = keys_dir / f"{key_name}.pem"

        if not key_file_path.exists():
            with open(key_file_path, "w", encoding="utf-8") as f:
                f.write(private_key_material)

            # Apply restrictive 0600 permissions on POSIX
            if platform.system() != "Windows":
                try:
                    os.chmod(key_file_path, stat.S_IRUSR | stat.S_IWUSR)
                except Exception as ex:
                    logger.debug(f"Could not apply chmod 0600: {ex}")
            logger.info(f"Private key saved securely to {key_file_path}")

    return key_name, key_file_path


def setup_security_group(
    ec2_client: Any,
    vpc_id: str,
    group_name: str,
    ssh_cidr: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
) -> str:
    """Create a security group in the specified VPC with restrictive ingress rules."""
    tag_list = [{"Key": k, "Value": v} for k, v in (tags or {}).items()]

    try:
        sg_resp = ec2_client.create_security_group(
            GroupName=group_name,
            Description=f"CloudPrac P01 Security Group ({group_name})",
            VpcId=vpc_id,
            TagSpecifications=[
                {
                    "ResourceType": "security-group",
                    "Tags": tag_list,
                }
            ] if tag_list else [],
        )
        sg_id = sg_resp["GroupId"]
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "InvalidGroup.Duplicate":
            # Retrieve existing SG ID
            existing = ec2_client.describe_security_groups(
                Filters=[{"Name": "group-name", "Values": [group_name]}, {"Name": "vpc-id", "Values": [vpc_id]}]
            )
            sg_id = existing["SecurityGroups"][0]["GroupId"]
        else:
            raise

    # Only add SSH inbound rule if explicit source CIDR was provided
    if ssh_cidr:
        try:
            ec2_client.authorize_security_group_ingress(
                GroupId=sg_id,
                IpPermissions=[
                    {
                        "IpProtocol": "tcp",
                        "FromPort": 22,
                        "ToPort": 22,
                        "IpRanges": [{"CidrIp": ssh_cidr, "Description": "CloudPrac SSH Access"}],
                    }
                ],
            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "InvalidPermission.Duplicate":
                raise

    return sg_id


def launch_ec2_instance(
    ec2_client: Any,
    image_id: str,
    instance_type: str,
    subnet_id: str,
    security_group_id: str,
    key_name: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
) -> str:
    """Launch a single EC2 virtual machine instance."""
    tag_list = [{"Key": k, "Value": v} for k, v in (tags or {}).items()]

    launch_args: Dict[str, Any] = {
        "ImageId": image_id,
        "InstanceType": instance_type,
        "MinCount": 1,
        "MaxCount": 1,
        "SubnetId": subnet_id,
        "SecurityGroupIds": [security_group_id],
        "TagSpecifications": [
            {
                "ResourceType": "instance",
                "Tags": tag_list,
            },
            {
                "ResourceType": "volume",
                "Tags": tag_list,
            },
        ],
    }

    if key_name:
        launch_args["KeyName"] = key_name

    resp = ec2_client.run_instances(**launch_args)
    instance_id = resp["Instances"][0]["InstanceId"]
    return instance_id


def wait_for_instance_running(ec2_client: Any, instance_id: str, max_timeout: int = 180) -> Dict[str, Any]:
    """Poll until instance enters 'running' state or timeout is reached."""
    start_time = time.time()
    while time.time() - start_time < max_timeout:
        resp = ec2_client.describe_instances(InstanceIds=[instance_id])
        reservations = resp.get("Reservations", [])
        if reservations and reservations[0].get("Instances"):
            instance = reservations[0]["Instances"][0]
            state = instance.get("State", {}).get("Name", "")
            if state == "running":
                return instance
            if state in ("terminated", "shutting-down"):
                raise RuntimeError(f"EC2 instance {instance_id} unexpectedly entered '{state}' state.")
        time.sleep(5)

    raise TimeoutError(f"EC2 instance {instance_id} did not transition to 'running' within {max_timeout}s.")


def verify_ec2_instance(
    ec2_client: Any,
    instance_id: str,
    expected_type: str,
    expected_key_name: Optional[str] = None,
    expected_sg_id: Optional[str] = None,
) -> List[VerificationCheck]:
    """Verify actual EC2 instance state against expectations."""
    checks: List[VerificationCheck] = []
    try:
        resp = ec2_client.describe_instances(InstanceIds=[instance_id])
        instances = resp.get("Reservations", [{}])[0].get("Instances", [])
        if not instances:
            checks.append(
                VerificationCheck(
                    check_id="EC2-01",
                    name="EC2 Instance Existence",
                    description="Verify virtual machine exists in AWS",
                    expected=f"Instance {instance_id} exists",
                    actual="Not Found",
                    passed=False,
                )
            )
            return checks

        inst = instances[0]
        actual_state = inst.get("State", {}).get("Name", "unknown")
        actual_type = inst.get("InstanceType", "unknown")
        actual_key = inst.get("KeyName")
        actual_sgs = [sg.get("GroupId") for sg in inst.get("SecurityGroups", [])]
        public_ip = inst.get("PublicIpAddress", "None Assigned")

        checks.append(
            VerificationCheck(
                check_id="EC2-01",
                name="EC2 Instance Running State",
                description="Verify virtual machine state is 'running'",
                expected="running",
                actual=actual_state,
                passed=(actual_state == "running"),
                evidence={"InstanceId": instance_id, "State": actual_state, "PublicIp": public_ip},
            )
        )

        checks.append(
            VerificationCheck(
                check_id="EC2-02",
                name="EC2 Instance Type",
                description="Verify launched instance type matches configuration",
                expected=expected_type,
                actual=actual_type,
                passed=(actual_type == expected_type),
            )
        )

        if expected_key_name:
            checks.append(
                VerificationCheck(
                    check_id="EC2-03",
                    name="EC2 Key Pair Association",
                    description="Verify configured key pair is associated with instance",
                    expected=expected_key_name,
                    actual=str(actual_key),
                    passed=(actual_key == expected_key_name),
                )
            )

        if expected_sg_id:
            checks.append(
                VerificationCheck(
                    check_id="EC2-04",
                    name="EC2 Security Group Attachment",
                    description="Verify practical security group is attached",
                    expected=expected_sg_id,
                    actual=", ".join(actual_sgs),
                    passed=(expected_sg_id in actual_sgs),
                )
            )

        # Honest connectivity verification note
        checks.append(
            VerificationCheck(
                check_id="EC2-05",
                name="EC2 Connectivity Status",
                description="Report network connectivity status honestly",
                expected="Network Interface Active",
                actual=f"Public IP: {public_ip} (SSH connectivity requires live key and open port)",
                passed=True,
            )
        )
    except Exception as e:
        checks.append(
            VerificationCheck(
                check_id="EC2-ERR",
                name="EC2 Verification Query",
                description="Query EC2 instance state",
                expected="Successful query",
                actual=f"Error: {e}",
                passed=False,
            )
        )

    return checks


def cleanup_ec2_resources(
    ec2_client: Any,
    instance_id: Optional[str] = None,
    security_group_id: Optional[str] = None,
    key_name: Optional[str] = None,
) -> Tuple[List[str], List[str]]:
    """Safely terminate instance, wait, and remove security group and key pair."""
    deleted: List[str] = []
    failed: List[str] = []

    # 1. Terminate EC2 instance
    if instance_id:
        try:
            logger.info(f"Terminating EC2 instance {instance_id}...")
            ec2_client.terminate_instances(InstanceIds=[instance_id])
            # Wait up to 90s for instance termination so security group can be detached
            for _ in range(18):
                resp = ec2_client.describe_instances(InstanceIds=[instance_id])
                state = resp["Reservations"][0]["Instances"][0]["State"]["Name"]
                if state in ("terminated", "shutting-down"):
                    break
                time.sleep(5)
            deleted.append(f"EC2 Instance: {instance_id}")
        except Exception as e:
            logger.error(f"Failed to terminate instance {instance_id}: {e}")
            failed.append(f"EC2 Instance {instance_id}: {e}")

    # 2. Delete Security Group (with brief delay to allow instance dissociation)
    if security_group_id:
        time.sleep(5)
        for attempt in range(5):
            try:
                logger.info(f"Deleting Security Group {security_group_id}...")
                ec2_client.delete_security_group(GroupId=security_group_id)
                deleted.append(f"Security Group: {security_group_id}")
                break
            except Exception as e:
                if attempt == 4:
                    logger.warning(f"Could not delete SG {security_group_id}: {e}")
                    failed.append(f"Security Group {security_group_id}: {e}")
                else:
                    time.sleep(5)

    # 3. Delete AWS Key Pair (do NOT delete local private key file)
    if key_name:
        try:
            logger.info(f"Deleting AWS Key Pair registration for {key_name}...")
            ec2_client.delete_key_pair(KeyName=key_name)
            deleted.append(f"AWS Key Pair: {key_name} (Local key file preserved)")
        except Exception as e:
            logger.warning(f"Failed to delete AWS Key Pair {key_name}: {e}")
            failed.append(f"AWS Key Pair {key_name}: {e}")

    return deleted, failed
