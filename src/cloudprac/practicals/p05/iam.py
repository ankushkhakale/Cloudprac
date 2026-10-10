"""IAM Role and Instance Profile management for Practical 05 EC2 workload."""

import json
import time
from typing import Any, Dict, List, Optional
from botocore.exceptions import ClientError

from cloudprac.utils.logging import get_logger

logger = get_logger()

EC2_ASSUME_ROLE_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "ec2.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }
    ],
}


def build_least_privilege_policy(
    bucket_name: str,
    table_name: str,
    region: str,
    account_id: str,
) -> Dict[str, Any]:
    """Generate least-privilege IAM policy document granting S3 and DynamoDB access for student records."""
    bucket_arn = f"arn:aws:s3:::{bucket_name}"
    table_arn = f"arn:aws:dynamodb:{region}:{account_id}:table/{table_name}"

    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "S3StudentDocumentAccess",
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:ListBucket",
                ],
                "Resource": [
                    bucket_arn,
                    f"{bucket_arn}/*",
                ],
            },
            {
                "Sid": "DynamoDBStudentRecordAccess",
                "Effect": "Allow",
                "Action": [
                    "dynamodb:GetItem",
                    "dynamodb:PutItem",
                    "dynamodb:Scan",
                    "dynamodb:UpdateItem",
                    "dynamodb:DeleteItem",
                    "dynamodb:DescribeTable",
                ],
                "Resource": table_arn,
            },
        ],
    }


def setup_instance_profile(
    iam_client: Any,
    role_name: str,
    profile_name: str,
    bucket_name: str,
    table_name: str,
    region: str,
    account_id: str,
    policy_name: str = "CloudPracStudentRecordPolicy",
    tags: Optional[Dict[str, str]] = None,
) -> str:
    """Create IAM role and instance profile with least-privilege permissions for EC2."""
    tag_list = [{"Key": k, "Value": v} for k, v in (tags or {}).items()]

    # 1. Create or verify IAM Role
    try:
        logger.info(f"Creating IAM Role '{role_name}' with EC2 trust relationship...")
        create_role_kwargs: Dict[str, Any] = {
            "RoleName": role_name,
            "AssumeRolePolicyDocument": json.dumps(EC2_ASSUME_ROLE_POLICY),
            "Description": "CloudPrac P05 least-privilege role for student-record application on EC2",
        }
        if tag_list:
            create_role_kwargs["Tags"] = tag_list
        iam_client.create_role(**create_role_kwargs)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "EntityAlreadyExists":
            logger.info(f"IAM Role '{role_name}' already exists. Reusing.")
        else:
            logger.error(f"Failed to create IAM Role '{role_name}': {e}")
            raise

    # 2. Attach inline least-privilege policy
    policy_doc = build_least_privilege_policy(
        bucket_name=bucket_name,
        table_name=table_name,
        region=region,
        account_id=account_id,
    )
    logger.info(f"Applying least-privilege policy '{policy_name}' to role '{role_name}'...")
    iam_client.put_role_policy(
        RoleName=role_name,
        PolicyName=policy_name,
        PolicyDocument=json.dumps(policy_doc),
    )

    # 3. Create or verify Instance Profile
    try:
        logger.info(f"Creating IAM Instance Profile '{profile_name}'...")
        create_profile_kwargs: Dict[str, Any] = {"InstanceProfileName": profile_name}
        if tag_list:
            create_profile_kwargs["Tags"] = tag_list
        iam_client.create_instance_profile(**create_profile_kwargs)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "EntityAlreadyExists":
            logger.info(f"Instance profile '{profile_name}' already exists.")
        else:
            logger.error(f"Failed to create instance profile '{profile_name}': {e}")
            raise

    # 4. Add role to instance profile
    try:
        iam_client.add_role_to_instance_profile(
            InstanceProfileName=profile_name,
            RoleName=role_name,
        )
        logger.info(f"Added role '{role_name}' to instance profile '{profile_name}'.")
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "LimitExceeded":
            # Role might already be attached
            pass
        elif "Cannot perform the operation on an existing" in str(e):
            pass
        else:
            logger.debug(f"Role association response: {e}")

    # IAM propagation delay allowance
    time.sleep(2)
    return profile_name


def cleanup_iam_resources(
    iam_client: Any,
    role_name: str,
    profile_name: str,
    policy_name: str = "CloudPracStudentRecordPolicy",
) -> List[str]:
    """Tear down instance profile, remove roles, and delete IAM role cleanly."""
    deleted: List[str] = []

    # 1. Remove role from instance profile
    try:
        logger.info(f"Removing role '{role_name}' from instance profile '{profile_name}'...")
        iam_client.remove_role_from_instance_profile(
            InstanceProfileName=profile_name,
            RoleName=role_name,
        )
    except Exception as e:
        logger.debug(f"Could not remove role from profile (might already be removed): {e}")

    # 2. Delete instance profile
    try:
        logger.info(f"Deleting instance profile '{profile_name}'...")
        iam_client.delete_instance_profile(InstanceProfileName=profile_name)
        deleted.append(f"iam-instance-profile:{profile_name}")
    except Exception as e:
        logger.warning(f"Could not delete instance profile '{profile_name}': {e}")

    # 3. Delete inline policy from role
    try:
        logger.info(f"Deleting inline policy '{policy_name}' from role '{role_name}'...")
        iam_client.delete_role_policy(
            RoleName=role_name,
            PolicyName=policy_name,
        )
    except Exception as e:
        logger.debug(f"Could not delete role policy '{policy_name}': {e}")

    # 4. Delete IAM Role
    try:
        logger.info(f"Deleting IAM Role '{role_name}'...")
        iam_client.delete_role(RoleName=role_name)
        deleted.append(f"iam-role:{role_name}")
    except Exception as e:
        logger.warning(f"Could not delete IAM Role '{role_name}': {e}")

    return deleted
