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
    secret_prefix: str = "secrets",
) -> Dict[str, Any]:
    """Generate least-privilege IAM policy document granting scoped S3 and DynamoDB access.

    Least-Privilege Scoping:
    - S3 Document Access: Allows s3:GetObject and s3:PutObject strictly on documents/* prefix.
    - S3 Secret Token Access: Allows s3:GetObject strictly on secrets/* prefix (read-only; EC2 cannot modify or delete token).
    - S3 Bucket Listing: Allows s3:ListBucket on the bucket itself.
    - DynamoDB Record Access: Allows CRUD strictly on the specific student table ARN.
    """
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
                ],
                "Resource": f"{bucket_arn}/documents/*",
            },
            {
                "Sid": "S3SecretTokenReadOnly",
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject",
                ],
                "Resource": f"{bucket_arn}/{secret_prefix}/*",
            },
            {
                "Sid": "S3BucketListing",
                "Effect": "Allow",
                "Action": [
                    "s3:ListBucket",
                ],
                "Resource": bucket_arn,
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
    role_name: Optional[str] = None,
    profile_name: Optional[str] = None,
    policy_name: str = "CloudPracStudentRecordPolicy",
    expected_run_id: Optional[str] = None,
) -> List[str]:
    """Tear down instance profile, remove attached roles, and delete IAM role cleanly.

    Enforces ownership validation against expected_run_id and handles already-deleted resources idempotently.
    """
    deleted: List[str] = []

    # 1. Clean up instance profile if specified
    if profile_name:
        should_delete_profile = True
        try:
            prof_resp = iam_client.get_instance_profile(InstanceProfileName=profile_name)
            inst_profile = prof_resp.get("InstanceProfile", {})
            if expected_run_id:
                tags = {t["Key"]: t["Value"] for t in inst_profile.get("Tags", [])}
                is_owned = tags.get("ManagedBy") == "CloudPrac" and tags.get("RunId") == expected_run_id
                if not is_owned:
                    logger.error(
                        f"Ownership check failed for IAM instance profile '{profile_name}': "
                        f"Tags {tags} do not verify ownership (expected ManagedBy=CloudPrac, RunId={expected_run_id}). "
                        "Skipping deletion to prevent accidental destruction."
                    )
                    should_delete_profile = False

            if should_delete_profile:
                for r in inst_profile.get("Roles", []):
                    r_name = r.get("RoleName")
                    try:
                        iam_client.remove_role_from_instance_profile(
                            InstanceProfileName=profile_name,
                            RoleName=r_name,
                        )
                    except Exception as e:
                        logger.debug(f"Could not remove role '{r_name}' from profile: {e}")

                logger.info(f"Deleting instance profile '{profile_name}'...")
                iam_client.delete_instance_profile(InstanceProfileName=profile_name)
                deleted.append(f"iam-instance-profile:{profile_name}")
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "NoSuchEntity":
                logger.info(f"IAM instance profile '{profile_name}' not found. Already cleaned up.")
            else:
                logger.error(f"Could not verify or delete instance profile '{profile_name}': {e}. Skipping deletion.")
        except Exception as e:
            logger.error(f"Unexpected error inspecting instance profile '{profile_name}': {e}. Skipping deletion.")

    # 2. Clean up IAM role if specified
    if role_name:
        should_delete_role = True
        try:
            if expected_run_id:
                try:
                    tags_resp = iam_client.list_role_tags(RoleName=role_name)
                    tags = {t["Key"]: t["Value"] for t in tags_resp.get("Tags", [])}
                    is_owned = tags.get("ManagedBy") == "CloudPrac" and tags.get("RunId") == expected_run_id
                    if not is_owned:
                        logger.error(
                            f"Ownership check failed for IAM role '{role_name}': "
                            f"Tags {tags} do not verify ownership (expected ManagedBy=CloudPrac, RunId={expected_run_id}). "
                            "Skipping deletion to prevent accidental destruction."
                        )
                        should_delete_role = False
                except ClientError as e:
                    if e.response.get("Error", {}).get("Code") == "NoSuchEntity":
                        logger.info(f"IAM role '{role_name}' not found. Already cleaned up.")
                        should_delete_role = False
                    else:
                        logger.error(f"Ownership check failed for IAM role '{role_name}': {e}. Skipping deletion.")
                        should_delete_role = False
                except Exception as e:
                    logger.error(f"Unexpected error inspecting tags on IAM role '{role_name}': {e}. Skipping deletion.")
                    should_delete_role = False

            if should_delete_role:
                try:
                    pol_resp = iam_client.list_role_policies(RoleName=role_name)
                    for p in pol_resp.get("PolicyNames", []):
                        try:
                            iam_client.delete_role_policy(RoleName=role_name, PolicyName=p)
                        except Exception as e:
                            logger.debug(f"Could not delete policy '{p}': {e}")
                except Exception as e:
                    logger.debug(f"Could not list policies for role '{role_name}': {e}")

                logger.info(f"Deleting IAM Role '{role_name}'...")
                iam_client.delete_role(RoleName=role_name)
                deleted.append(f"iam-role:{role_name}")
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "NoSuchEntity":
                logger.info(f"IAM role '{role_name}' not found. Already cleaned up.")
            else:
                logger.error(f"Could not delete IAM Role '{role_name}': {e}")
        except Exception as e:
            logger.error(f"Unexpected error inspecting/deleting IAM Role '{role_name}': {e}")

    return deleted
