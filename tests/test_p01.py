"""Unit and mock tests for Practical 01: EC2, S3, and DynamoDB workflow."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from botocore.exceptions import ClientError

from cloudprac.adapters.aws_client import AWSAdapter
from cloudprac.core.engine import ExecutionEngine
from cloudprac.core.models import PracticalStatus
from cloudprac.practicals.p01.config import P01Config
from cloudprac.practicals.p01.dynamodb import (
    cleanup_dynamodb_resources,
    create_dynamodb_table,
    insert_sample_records,
    retrieve_record,
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
from cloudprac.practicals.p01.practical import P01Practical
from cloudprac.practicals.p01.s3 import (
    calculate_sha256,
    cleanup_s3_resources,
    create_private_bucket,
    download_file_from_s3,
    list_bucket_objects,
    upload_file_to_s3,
    verify_s3_resources,
)
from cloudprac.practicals.p01.sample_data import get_default_dynamodb_items
from cloudprac.utils.config import CloudPracConfig
from cloudprac.utils.paths import get_cloudprac_home, get_run_dir


def test_p01_metadata_and_inspection():
    """Verify P01 metadata reflects CONFIGURED state and proper service scope."""
    p01 = P01Practical()
    meta = p01.metadata
    assert meta.id == "P01"
    assert meta.status == PracticalStatus.CONFIGURED
    assert "EC2" in meta.aws_services
    assert "S3" in meta.aws_services
    assert "DynamoDB" in meta.aws_services

    details = p01.inspect()
    assert details["id"] == "P01"
    assert len(details["objectives"]) >= 7
    assert len(details["cost_cautions"]) >= 1


def test_p01_plan_generation():
    """Verify P01 execution plan contains all required operational steps."""
    cfg = CloudPracConfig()
    p01 = P01Practical(P01Config(instance_type="t3.micro", ssh_cidr="192.0.2.1/32"))
    plan = p01.plan(cfg, "P01-TEST-RUN")

    assert plan.practical_id == "P01"
    assert len(plan.steps) == 7

    actions = [s.action for s in plan.steps]
    assert "CREATE_SECURITY_GROUP" in actions
    assert "CREATE_KEY_PAIR" in actions
    assert "RUN_EC2_INSTANCE" in actions
    assert "CREATE_S3_BUCKET" in actions
    assert "S3_FILE_OPERATIONS" in actions
    assert "CREATE_DYNAMODB_TABLE" in actions
    assert "DYNAMODB_RECORD_OPERATIONS" in actions


# ==================== EC2 MODULE TESTS ====================

def test_ec2_get_default_vpc_success():
    """Verify default VPC and subnet discovery."""
    mock_ec2 = MagicMock()
    mock_ec2.describe_vpcs.return_value = {"Vpcs": [{"VpcId": "vpc-12345"}]}
    mock_ec2.describe_subnets.return_value = {"Subnets": [{"SubnetId": "subnet-67890"}]}

    vpc_id, subnet_id = get_default_or_first_vpc(mock_ec2)
    assert vpc_id == "vpc-12345"
    assert subnet_id == "subnet-67890"


def test_ec2_get_vpc_none_found():
    """Verify error raised when no VPC exists."""
    mock_ec2 = MagicMock()
    mock_ec2.describe_vpcs.return_value = {"Vpcs": []}

    with pytest.raises(RuntimeError) as exc_info:
        get_default_or_first_vpc(mock_ec2)
    assert "No VPC found" in str(exc_info.value)


def test_ec2_find_latest_ami():
    """Verify AMI discovery sorts descending and returns latest image ID."""
    mock_ec2 = MagicMock()
    mock_ec2.describe_images.return_value = {
        "Images": [
            {"ImageId": "ami-old", "CreationDate": "2024-01-01T00:00:00.000Z"},
            {"ImageId": "ami-latest", "CreationDate": "2024-06-01T00:00:00.000Z"},
        ]
    }

    ami_id = find_latest_al2023_ami(mock_ec2)
    assert ami_id == "ami-latest"


def test_ec2_key_pair_creation(tmp_path: Path):
    """Verify new key pair creation saves private key material locally."""
    mock_ec2 = MagicMock()
    # Key does not exist
    mock_ec2.describe_key_pairs.side_effect = ClientError(
        {"Error": {"Code": "InvalidKeyPair.NotFound"}}, "DescribeKeyPairs"
    )
    mock_ec2.create_key_pair.return_value = {
        "KeyName": "test-key",
        "KeyMaterial": "-----BEGIN OPENSSH PRIVATE KEY-----\ntest\n-----END OPENSSH PRIVATE KEY-----",
    }

    key_name, path = setup_key_pair(mock_ec2, "test-key", save_local_file=True)
    assert key_name == "test-key"
    assert path is not None
    assert path.is_file()
    assert "BEGIN OPENSSH PRIVATE KEY" in path.read_text(encoding="utf-8")


def test_ec2_security_group_with_ssh():
    """Verify security group creation and ingress authorization."""
    mock_ec2 = MagicMock()
    mock_ec2.create_security_group.return_value = {"GroupId": "sg-9999"}

    sg_id = setup_security_group(mock_ec2, "vpc-123", "test-sg", ssh_cidr="203.0.113.10/32")
    assert sg_id == "sg-9999"
    mock_ec2.authorize_security_group_ingress.assert_called_once()


def test_ec2_launch_and_verify():
    """Verify instance launch and verification checks."""
    mock_ec2 = MagicMock()
    mock_ec2.run_instances.return_value = {"Instances": [{"InstanceId": "i-testvm123"}]}

    inst_id = launch_ec2_instance(
        ec2_client=mock_ec2,
        image_id="ami-test",
        instance_type="t2.micro",
        subnet_id="subnet-1",
        security_group_id="sg-1",
        key_name="key-1",
    )
    assert inst_id == "i-testvm123"

    # Verify checks
    mock_ec2.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-testvm123",
                        "State": {"Name": "running"},
                        "InstanceType": "t2.micro",
                        "KeyName": "key-1",
                        "SecurityGroups": [{"GroupId": "sg-1"}],
                        "PublicIpAddress": "54.200.10.20",
                    }
                ]
            }
        ]
    }

    checks = verify_ec2_instance(mock_ec2, "i-testvm123", "t2.micro", "key-1", "sg-1")
    assert all(c.passed for c in checks)


# ==================== S3 MODULE TESTS ====================

def test_s3_bucket_creation_us_east_1():
    """Verify us-east-1 does not include LocationConstraint."""
    mock_s3 = MagicMock()
    bucket_name = create_private_bucket(mock_s3, "test-bucket-us-east-1", "us-east-1")
    assert bucket_name == "test-bucket-us-east-1"
    mock_s3.create_bucket.assert_called_once_with(Bucket="test-bucket-us-east-1")
    mock_s3.put_public_access_block.assert_called_once()


def test_s3_bucket_creation_regional():
    """Verify regional bucket includes LocationConstraint."""
    mock_s3 = MagicMock()
    bucket_name = create_private_bucket(mock_s3, "test-bucket-eu-west-1", "eu-west-1")
    assert bucket_name == "test-bucket-eu-west-1"
    mock_s3.create_bucket.assert_called_once_with(
        Bucket="test-bucket-eu-west-1",
        CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
    )


def test_s3_upload_download_and_checksum(tmp_path: Path):
    """Verify S3 upload, download, and SHA-256 integrity calculation."""
    sample_file = tmp_path / "test_upload.txt"
    sample_file.write_text("Hello CloudPrac S3 Verification!", encoding="utf-8")
    expected_hash = calculate_sha256(sample_file)

    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {
        "ContentLength": len(sample_file.read_bytes()),
        "ETag": '"etag123"',
        "ContentType": "text/plain",
    }

    meta = upload_file_to_s3(mock_s3, "my-test-bucket", "data/test.txt", sample_file)
    assert meta["Key"] == "data/test.txt"
    assert meta["SHA256"] == expected_hash

    # Simulate download
    download_dest = tmp_path / "downloaded.txt"
    def fake_download(bucket, key, dest):
        Path(dest).write_text("Hello CloudPrac S3 Verification!", encoding="utf-8")
    mock_s3.download_file.side_effect = fake_download

    download_file_from_s3(mock_s3, "my-test-bucket", "data/test.txt", download_dest)
    assert download_dest.is_file()
    assert calculate_sha256(download_dest) == expected_hash


def test_s3_verify_checks(tmp_path: Path):
    """Verify S3 independent verification checks pass."""
    sample_file = tmp_path / "orig.txt"
    sample_file.write_text("Integrity Check Data", encoding="utf-8")

    mock_s3 = MagicMock()
    mock_s3.get_public_access_block.return_value = {
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        }
    }
    mock_s3.list_objects_v2.return_value = {
        "Contents": [{"Key": "data/sample.txt"}]
    }

    checks = verify_s3_resources(
        s3_client=mock_s3,
        bucket_name="my-bucket",
        sample_key="data/sample.txt",
        original_file_path=sample_file,
        downloaded_file_path=sample_file,
    )
    assert all(c.passed for c in checks)


# ==================== DYNAMODB MODULE TESTS ====================

def test_dynamodb_table_lifecycle():
    """Verify DynamoDB table creation, wait, insert, and retrieval."""
    mock_ddb = MagicMock()
    create_dynamodb_table(mock_ddb, "test-table", billing_mode="PAY_PER_REQUEST")
    mock_ddb.create_table.assert_called_once()

    # Wait active
    mock_ddb.describe_table.return_value = {"Table": {"TableStatus": "ACTIVE", "TableArn": "arn:aws:ddb:1"}}
    desc = wait_for_table_active(mock_ddb, "test-table")
    assert desc["TableStatus"] == "ACTIVE"

    # Insert items
    items = get_default_dynamodb_items()
    count = insert_sample_records(mock_ddb, "test-table", items)
    assert count == 3
    assert mock_ddb.put_item.call_count == 3

    # Retrieve item
    mock_ddb.get_item.return_value = {
        "Item": {
            "id": {"S": "item-001"},
            "name": {"S": "Notebook"},
            "category": {"S": "stationery"},
            "quantity": {"N": "10"},
        }
    }
    retrieved = retrieve_record(mock_ddb, "test-table", "item-001")
    assert retrieved is not None
    assert retrieved["id"] == "item-001"
    assert retrieved["name"] == "Notebook"
    assert retrieved["quantity"] == 10


def test_dynamodb_verify_checks():
    """Verify DynamoDB verification assertions."""
    mock_ddb = MagicMock()
    mock_ddb.describe_table.return_value = {
        "Table": {
            "TableStatus": "ACTIVE",
            "TableArn": "arn:aws:dynamodb:us-east-1:1234:table/test-table",
            "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        }
    }
    mock_ddb.get_item.return_value = {
        "Item": {
            "id": {"S": "item-001"},
            "name": {"S": "Notebook"},
        }
    }

    items = [{"id": "item-001", "name": "Notebook"}]
    checks = verify_dynamodb_resources(mock_ddb, "test-table", items)
    assert all(c.passed for c in checks)


# ==================== P01 FULL LIFECYCLE (MOCK MODE) ====================

def test_p01_full_lifecycle_mock_mode():
    """Verify end-to-end execution, reporting, verification, and cleanup for P01 in mock mode."""
    p01 = P01Practical()
    config = CloudPracConfig(student_name="Test Student", student_id="CS-999")
    adapter = AWSAdapter(mock_mode=True)
    engine = ExecutionEngine(config=config, adapter=adapter)

    res = engine.run_practical(
        practical=p01,
        auto_verify=True,
        auto_cleanup=True,
    )

    assert res.success is True
    assert res.practical_id == "P01"
    assert res.steps_executed == 7
    assert res.manifest is not None
    assert len(res.manifest.resources) == 5

    # Check that report.md and report.json exist
    run_dir = get_run_dir(res.run_id)
    assert (run_dir / "plan.json").is_file()
    assert (run_dir / "manifest.json").is_file()
    assert (run_dir / "verification.json").is_file()
    assert (run_dir / "cleanup.json").is_file()
    assert (run_dir / "report.md").is_file()
    assert (run_dir / "report.json").is_file()

    # Validate report contents
    md_report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "P01" in md_report
    assert "Test Student" in md_report
    assert "CS-999" in md_report
    assert "CREATE_SECURITY_GROUP" in md_report
    assert "RUN_EC2_INSTANCE" in md_report
    assert "CREATE_S3_BUCKET" in md_report
    assert "CREATE_DYNAMODB_TABLE" in md_report
    assert "Cleanup Executed" in md_report
