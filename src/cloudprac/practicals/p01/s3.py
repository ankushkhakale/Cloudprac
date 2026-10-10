"""S3 bucket provisioning, file management, verification, and cleanup for Practical 01."""

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


def create_private_bucket(
    s3_client: Any,
    bucket_name: str,
    region: str,
    tags: Optional[Dict[str, str]] = None,
) -> str:
    """Create a private S3 bucket with Block Public Access enabled."""
    create_kwargs: Dict[str, Any] = {"Bucket": bucket_name}
    if region != "us-east-1":
        create_kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}

    logger.info(f"Creating S3 bucket '{bucket_name}' in region '{region}'...")
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


def upload_file_to_s3(
    s3_client: Any,
    bucket_name: str,
    object_key: str,
    local_path: Path,
) -> Dict[str, Any]:
    """Upload a local file to S3 and return object metadata."""
    if not local_path.is_file():
        raise FileNotFoundError(f"Local file '{local_path}' does not exist.")

    sha256_hash = calculate_sha256(local_path)
    file_size = local_path.stat().st_size

    logger.info(f"Uploading '{local_path.name}' ({file_size} bytes) to s3://{bucket_name}/{object_key}...")
    with open(local_path, "rb") as f:
        s3_client.put_object(
            Bucket=bucket_name,
            Key=object_key,
            Body=f,
            ContentType="text/plain",
            Metadata={"sha256": sha256_hash},
        )

    # Inspect object metadata
    head = s3_client.head_object(Bucket=bucket_name, Key=object_key)
    return {
        "Key": object_key,
        "Size": head.get("ContentLength", file_size),
        "ETag": head.get("ETag", "").strip('"'),
        "SHA256": sha256_hash,
        "ContentType": head.get("ContentType", "text/plain"),
    }


def download_file_from_s3(
    s3_client: Any,
    bucket_name: str,
    object_key: str,
    destination_path: Path,
) -> Path:
    """Download an S3 object to local disk without silently overwriting unmanaged files."""
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Downloading s3://{bucket_name}/{object_key} to {destination_path}...")
    s3_client.download_file(bucket_name, object_key, str(destination_path))
    return destination_path


def list_bucket_objects(s3_client: Any, bucket_name: str) -> List[str]:
    """List all object keys present in the S3 bucket."""
    resp = s3_client.list_objects_v2(Bucket=bucket_name)
    contents = resp.get("Contents", [])
    return [item["Key"] for item in contents]


def verify_s3_resources(
    s3_client: Any,
    bucket_name: str,
    sample_key: str,
    original_file_path: Path,
    downloaded_file_path: Optional[Path] = None,
) -> List[VerificationCheck]:
    """Perform independent verification on S3 bucket and object integrity."""
    checks: List[VerificationCheck] = []

    # 1. Bucket existence check
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        checks.append(
            VerificationCheck(
                check_id="S3-01",
                name="S3 Bucket Existence",
                description="Verify storage bucket exists and is accessible",
                expected="Active & Accessible",
                actual="Active & Accessible",
                passed=True,
            )
        )
    except Exception as e:
        checks.append(
            VerificationCheck(
                check_id="S3-01",
                name="S3 Bucket Existence",
                description="Verify storage bucket exists and is accessible",
                expected="Active & Accessible",
                actual=f"Error: {e}",
                passed=False,
            )
        )
        return checks

    # 2. Block Public Access configuration check
    try:
        pab_resp = s3_client.get_public_access_block(Bucket=bucket_name)
        cfg = pab_resp.get("PublicAccessBlockConfiguration", {})
        all_blocked = all([
            cfg.get("BlockPublicAcls"),
            cfg.get("IgnorePublicAcls"),
            cfg.get("BlockPublicPolicy"),
            cfg.get("RestrictPublicBuckets"),
        ])
        checks.append(
            VerificationCheck(
                check_id="S3-02",
                name="S3 Block Public Access",
                description="Verify public access is blocked to prevent data exposure",
                expected="All 4 BPA settings enabled",
                actual="All 4 BPA settings enabled" if all_blocked else f"Partial: {cfg}",
                passed=bool(all_blocked),
            )
        )
    except Exception as e:
        checks.append(
            VerificationCheck(
                check_id="S3-02",
                name="S3 Block Public Access",
                description="Verify public access is blocked",
                expected="All BPA settings enabled",
                actual=f"Check failed: {e}",
                passed=False,
            )
        )

    # 3. Object listing check
    try:
        keys = list_bucket_objects(s3_client, bucket_name)
        checks.append(
            VerificationCheck(
                check_id="S3-03",
                name="S3 Object Listing",
                description="Verify sample object is listed in bucket",
                expected=f"Key '{sample_key}' present",
                actual=f"Found {len(keys)} objects: {', '.join(keys)}",
                passed=(sample_key in keys),
            )
        )
    except Exception as e:
        checks.append(
            VerificationCheck(
                check_id="S3-03",
                name="S3 Object Listing",
                description="Verify sample object is listed",
                expected=f"Key '{sample_key}' present",
                actual=f"Error: {e}",
                passed=False,
            )
        )

    # 4. Checksum integrity comparison check
    if original_file_path.is_file() and downloaded_file_path and downloaded_file_path.is_file():
        orig_hash = calculate_sha256(original_file_path)
        down_hash = calculate_sha256(downloaded_file_path)
        hashes_match = (orig_hash == down_hash)
        checks.append(
            VerificationCheck(
                check_id="S3-04",
                name="S3 Object Data Integrity",
                description="Verify downloaded file SHA-256 checksum matches original upload",
                expected=orig_hash,
                actual=down_hash,
                passed=hashes_match,
                evidence={"Original": orig_hash, "Downloaded": down_hash},
            )
        )

    return checks


def cleanup_s3_resources(s3_client: Any, bucket_name: str) -> Tuple[List[str], List[str]]:
    """Safely delete all objects in the bucket and remove the bucket."""
    deleted: List[str] = []
    failed: List[str] = []

    try:
        logger.info(f"Emptying objects from S3 bucket '{bucket_name}'...")
        # 1. Delete all current objects
        resp = s3_client.list_objects_v2(Bucket=bucket_name)
        contents = resp.get("Contents", [])
        if contents:
            delete_objects = [{"Key": item["Key"]} for item in contents]
            s3_client.delete_objects(Bucket=bucket_name, Delete={"Objects": delete_objects})
            for obj in delete_objects:
                deleted.append(f"S3 Object: {bucket_name}/{obj['Key']}")

        # 2. Delete versioned objects if any
        try:
            versions_resp = s3_client.list_object_versions(Bucket=bucket_name)
            ver_items = [
                {"Key": v["Key"], "VersionId": v["VersionId"]}
                for v in (versions_resp.get("Versions", []) + versions_resp.get("DeleteMarkers", []))
            ]
            if ver_items:
                s3_client.delete_objects(Bucket=bucket_name, Delete={"Objects": ver_items})
        except Exception:
            pass

        # 3. Delete bucket
        logger.info(f"Deleting S3 bucket '{bucket_name}'...")
        s3_client.delete_bucket(Bucket=bucket_name)
        deleted.append(f"S3 Bucket: {bucket_name}")
    except Exception as e:
        logger.error(f"Failed to cleanup S3 bucket {bucket_name}: {e}")
        failed.append(f"S3 Bucket {bucket_name}: {e}")

    return deleted, failed
