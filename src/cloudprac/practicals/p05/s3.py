"""Amazon S3 bucket provisioning, document management, verification, and cleanup for Practical 05."""

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from botocore.exceptions import ClientError

from cloudprac.core.models import VerificationCheck
from cloudprac.utils.logging import get_logger

logger = get_logger()


def calculate_sha256(file_path: Path) -> str:
    """Calculate the SHA-256 hash of a local file."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            sha.update(chunk)
    return sha.hexdigest()


def calculate_content_sha256(content: bytes) -> str:
    """Calculate SHA-256 of byte content."""
    return hashlib.sha256(content).hexdigest()


def create_private_bucket(
    s3_client: Any,
    bucket_name: str,
    region: str,
    tags: Optional[Dict[str, str]] = None,
) -> str:
    """Create a private S3 bucket with Block Public Access and SSE-S3 encryption enabled."""
    create_kwargs: Dict[str, Any] = {"Bucket": bucket_name}
    if region != "us-east-1":
        create_kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}

    logger.info(f"Creating private S3 bucket '{bucket_name}' in region '{region}'...")
    s3_client.create_bucket(**create_kwargs)

    # Enable S3 Block Public Access
    logger.info(f"Enabling S3 Block Public Access on '{bucket_name}'...")
    s3_client.put_public_access_block(
        Bucket=bucket_name,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )

    # Set default server-side encryption (SSE-S3 AES256)
    try:
        s3_client.put_bucket_encryption(
            Bucket=bucket_name,
            ServerSideEncryptionConfiguration={
                "Rules": [
                    {
                        "ApplyServerSideEncryptionByDefault": {
                            "SSEAlgorithm": "AES256"
                        }
                    }
                ]
            },
        )
    except Exception as e:
        logger.debug(f"Could not explicitly set bucket encryption (default applied): {e}")

    # Apply resource tags
    if tags:
        tag_set = [{"Key": k, "Value": v} for k, v in tags.items()]
        try:
            s3_client.put_bucket_tagging(
                Bucket=bucket_name,
                Tagging={"TagSet": tag_set},
            )
        except Exception as e:
            logger.debug(f"Could not apply bucket tags (non-fatal): {e}")

    return bucket_name


def upload_document_to_s3(
    s3_client: Any,
    bucket_name: str,
    object_key: str,
    local_path: Optional[Path] = None,
    content: Optional[str] = None,
    content_type: str = "text/plain",
) -> Dict[str, Any]:
    """Upload a document file or raw string content to S3 and return object metadata."""
    if local_path is not None:
        if not local_path.is_file():
            raise FileNotFoundError(f"Local file '{local_path}' does not exist.")
        file_bytes = local_path.read_bytes()
    elif content is not None:
        file_bytes = content.encode("utf-8")
    else:
        raise ValueError("Either local_path or content must be provided for S3 upload.")

    sha256_hash = calculate_content_sha256(file_bytes)
    file_size = len(file_bytes)

    logger.info(f"Uploading '{object_key}' ({file_size} bytes) to s3://{bucket_name}/{object_key}...")
    s3_client.put_object(
        Bucket=bucket_name,
        Key=object_key,
        Body=file_bytes,
        ContentType=content_type,
        Metadata={"sha256": sha256_hash},
    )

    # Inspect object metadata
    head = s3_client.head_object(Bucket=bucket_name, Key=object_key)
    return {
        "Key": object_key,
        "Size": head.get("ContentLength", file_size),
        "ETag": head.get("ETag", "").strip('"'),
        "SHA256": sha256_hash,
        "ContentType": head.get("ContentType", content_type),
    }


def download_document_from_s3(
    s3_client: Any,
    bucket_name: str,
    object_key: str,
    destination_path: Path,
    overwrite: bool = False,
) -> Tuple[Path, str]:
    """Download a student document from S3 and return the destination path and calculated SHA-256."""
    if destination_path.exists() and not overwrite:
        raise FileExistsError(
            f"Destination file '{destination_path}' already exists. Refusing silent overwrite."
        )

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Downloading s3://{bucket_name}/{object_key} to '{destination_path}'...")

    resp = s3_client.get_object(Bucket=bucket_name, Key=object_key)
    body = resp["Body"].read()

    with open(destination_path, "wb") as f:
        f.write(body)

    downloaded_sha = calculate_sha256(destination_path)
    return destination_path, downloaded_sha


def list_student_documents(s3_client: Any, bucket_name: str, prefix: str = "") -> List[Dict[str, Any]]:
    """List documents stored in the S3 bucket."""
    resp = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
    contents = resp.get("Contents", [])
    return [
        {
            "Key": item["Key"],
            "Size": item["Size"],
            "LastModified": item["LastModified"].isoformat() if hasattr(item["LastModified"], "isoformat") else str(item["LastModified"]),
        }
        for item in contents
    ]


def verify_s3_resources(
    s3_client: Any,
    bucket_name: str,
    expected_keys: List[str],
) -> List[VerificationCheck]:
    """Perform independent verification on S3 bucket configuration, privacy, and uploaded objects."""
    checks: List[VerificationCheck] = []

    # 1. Verify Bucket Existence & Location
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        checks.append(
            VerificationCheck(
                check_id=f"s3-bucket-exists-{bucket_name}",
                name="S3 Bucket Existence",
                description=f"Verify S3 bucket {bucket_name} exists and is accessible",
                passed=True,
                expected=f"Bucket '{bucket_name}' exists and is accessible",
                actual="Bucket exists and responds to head_bucket",
            )
        )
    except Exception as e:
        checks.append(
            VerificationCheck(
                check_id=f"s3-bucket-exists-{bucket_name}",
                name="S3 Bucket Existence",
                description=f"Verify S3 bucket {bucket_name} exists and is accessible",
                passed=False,
                expected=f"Bucket '{bucket_name}' exists and is accessible",
                actual=f"Failed to access bucket: {e}",
            )
        )
        return checks

    # 2. Verify Block Public Access is strictly enabled
    try:
        pab_resp = s3_client.get_public_access_block(Bucket=bucket_name)
        pab_conf = pab_resp.get("PublicAccessBlockConfiguration", {})
        all_blocked = all([
            pab_conf.get("BlockPublicAcls", False),
            pab_conf.get("IgnorePublicAcls", False),
            pab_conf.get("BlockPublicPolicy", False),
            pab_conf.get("RestrictPublicBuckets", False),
        ])
        checks.append(
            VerificationCheck(
                check_id=f"s3-bpa-{bucket_name}",
                name="S3 Block Public Access Enforcement",
                description="Verify Block Public Access is strictly enabled on the bucket",
                passed=all_blocked,
                expected="All 4 Block Public Access settings enabled (True)",
                actual=f"BlockPublicAcls={pab_conf.get('BlockPublicAcls')}, IgnorePublicAcls={pab_conf.get('IgnorePublicAcls')}, BlockPublicPolicy={pab_conf.get('BlockPublicPolicy')}, RestrictPublicBuckets={pab_conf.get('RestrictPublicBuckets')}",
            )
        )
    except Exception as e:
        checks.append(
            VerificationCheck(
                check_id=f"s3-bpa-{bucket_name}",
                name="S3 Block Public Access Enforcement",
                description="Verify Block Public Access is strictly enabled on the bucket",
                passed=False,
                expected="Block Public Access enabled",
                actual=f"Could not retrieve Block Public Access: {e}",
            )
        )

    # 3. Verify each expected document exists and has valid metadata
    for key in expected_keys:
        try:
            head = s3_client.head_object(Bucket=bucket_name, Key=key)
            size = head.get("ContentLength", 0)
            checks.append(
                VerificationCheck(
                    check_id=f"s3-doc-{key}",
                    name=f"S3 Student Document: {key}",
                    description=f"Verify document {key} exists with size > 0",
                    passed=size > 0,
                    expected=f"Object '{key}' exists with size > 0 bytes",
                    actual=f"Object exists (size: {size} bytes, ETag: {head.get('ETag', '').strip('\"')})",
                )
            )
        except Exception as e:
            checks.append(
                VerificationCheck(
                    check_id=f"s3-doc-{key}",
                    name=f"S3 Student Document: {key}",
                    description=f"Verify document {key} exists with size > 0",
                    passed=False,
                    expected=f"Object '{key}' exists",
                    actual=f"Object not found or error: {e}",
                )
            )

    return checks



def cleanup_s3_resources(
    s3_client: Any,
    bucket_name: str,
    tracked_object_keys: Optional[List[str]] = None,
) -> List[str]:
    """Delete tracked objects and remove the bucket cleanly."""
    deleted: List[str] = []

    # 1. Delete tracked objects or all objects if created by run
    try:
        if tracked_object_keys:
            objects_to_delete = [{"Key": k} for k in tracked_object_keys]
            s3_client.delete_objects(
                Bucket=bucket_name,
                Delete={"Objects": objects_to_delete, "Quiet": True},
            )
            deleted.extend([f"s3://{bucket_name}/{k}" for k in tracked_object_keys])
        else:
            # Drain bucket before deleting
            resp = s3_client.list_objects_v2(Bucket=bucket_name)
            contents = resp.get("Contents", [])
            if contents:
                objects_to_delete = [{"Key": item["Key"]} for item in contents]
                s3_client.delete_objects(
                    Bucket=bucket_name,
                    Delete={"Objects": objects_to_delete, "Quiet": True},
                )
                deleted.extend([f"s3://{bucket_name}/{item['Key']}" for item in contents])
    except ClientError as e:
        logger.warning(f"Error removing objects from bucket '{bucket_name}': {e}")

    # 2. Delete the bucket
    try:
        logger.info(f"Deleting S3 bucket '{bucket_name}'...")
        s3_client.delete_bucket(Bucket=bucket_name)
        deleted.append(f"s3-bucket:{bucket_name}")
    except ClientError as e:
        logger.error(f"Failed to delete S3 bucket '{bucket_name}': {e}")
        raise

    return deleted
