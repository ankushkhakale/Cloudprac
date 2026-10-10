"""Unit and mock tests for Practical 05: Student Record Management using EC2, S3, and DynamoDB."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from botocore.exceptions import ClientError

from cloudprac.adapters.aws_client import AWSAdapter
from cloudprac.core.engine import ExecutionEngine
from cloudprac.core.models import PracticalStatus
from cloudprac.practicals.p05.config import P05Config
from cloudprac.practicals.p05.dynamodb import (
    cleanup_dynamodb_resources,
    create_student_table,
    delete_student_record,
    get_student_record,
    insert_student_record,
    insert_student_records,
    list_student_records,
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
    build_least_privilege_policy,
    cleanup_iam_resources,
    setup_instance_profile,
)
from cloudprac.practicals.p05.practical import P05Practical
from cloudprac.practicals.p05.s3 import (
    calculate_content_sha256,
    calculate_sha256,
    cleanup_s3_resources,
    create_private_bucket,
    download_document_from_s3,
    list_student_documents,
    upload_document_to_s3,
    verify_s3_resources,
)
from cloudprac.practicals.p05.sample_data import (
    get_default_student_records,
    get_sample_student_document,
)
from cloudprac.practicals.p05.web_app import create_app
from cloudprac.utils.config import CloudPracConfig
from cloudprac.utils.paths import get_cloudprac_home, get_run_dir


def test_p05_metadata_and_inspection():
    """Verify P05 metadata reflects CONFIGURED state and proper service scope."""
    p05 = P05Practical()
    meta = p05.metadata
    assert meta.id == "P05"
    assert meta.status == PracticalStatus.CONFIGURED
    assert "EC2" in meta.aws_services
    assert "S3" in meta.aws_services
    assert "DynamoDB" in meta.aws_services
    assert "IAM" in meta.aws_services
    assert "Student Record Management" in meta.title

    details = p05.inspect()
    assert details["id"] == "P05"
    assert len(details["objectives"]) >= 7
    assert "data_schema" in details
    assert details["data_schema"]["partition_key"] == "student_id (String)"
    assert len(details["cost_cautions"]) >= 1


def test_p05_plan_generation():
    """Verify execution plan produces deterministic resources and steps."""
    p05 = P05Practical()
    config = CloudPracConfig()
    plan = p05.plan(config, "run-test-1234")

    assert plan.practical_id == "P05"
    assert plan.run_id == "run-test-1234"
    assert len(plan.steps) == 7

    actions = [s.action for s in plan.steps]
    assert any("s3:CreateBucket" in a for a in actions)
    assert any("dynamodb:CreateTable" in a for a in actions)
    assert any("iam:CreateRole" in a for a in actions)
    assert any("ec2:RunInstances" in a for a in actions)


# =========================================================================
# EC2 & IAM Tests
# =========================================================================

def test_ec2_get_default_vpc_success():
    """Verify default VPC resolution."""
    mock_ec2 = MagicMock()
    mock_ec2.describe_vpcs.return_value = {"Vpcs": [{"VpcId": "vpc-12345"}]}
    mock_ec2.describe_subnets.return_value = {"Subnets": [{"SubnetId": "subnet-abcde"}]}

    vpc_id, subnet_id = get_default_or_first_vpc(mock_ec2)
    assert vpc_id == "vpc-12345"
    assert subnet_id == "subnet-abcde"


def test_ec2_get_vpc_none_found():
    """Verify RuntimeError is raised when no VPC exists."""
    mock_ec2 = MagicMock()
    mock_ec2.describe_vpcs.return_value = {"Vpcs": []}

    with pytest.raises(RuntimeError, match="No VPC found in the selected AWS Region"):
        get_default_or_first_vpc(mock_ec2)


def test_ec2_find_latest_ami():
    """Verify AMI resolution via DescribeImages."""
    mock_ec2 = MagicMock()
    mock_ec2.describe_images.return_value = {
        "Images": [
            {"ImageId": "ami-old", "CreationDate": "2023-01-01T00:00:00.000Z"},
            {"ImageId": "ami-new", "CreationDate": "2024-05-01T00:00:00.000Z"},
        ]
    }

    ami_id = find_latest_al2023_ami(mock_ec2)
    assert ami_id == "ami-new"


def test_ec2_key_pair_creation(tmp_path, monkeypatch):
    """Verify key pair creation and safe 0600 file saving."""
    monkeypatch.setattr("cloudprac.practicals.p05.ec2.get_cloudprac_home", lambda: tmp_path)
    mock_ec2 = MagicMock()
    mock_ec2.describe_key_pairs.side_effect = ClientError(
        {"Error": {"Code": "InvalidKeyPair.NotFound"}}, "DescribeKeyPairs"
    )
    mock_ec2.create_key_pair.return_value = {"KeyMaterial": "MOCK-RSA-PRIVATE-KEY"}

    key_name, path = setup_key_pair(mock_ec2, "test-p05-key", save_local_file=True)
    assert key_name == "test-p05-key"
    assert path is not None
    assert path.is_file()
    assert path.read_text() == "MOCK-RSA-PRIVATE-KEY"


def test_ec2_security_group_with_app_port():
    """Verify security group opens web application port 5000 and restricts SSH."""
    mock_ec2 = MagicMock()
    mock_ec2.create_security_group.return_value = {"GroupId": "sg-9999"}

    sg_id = setup_security_group(
        mock_ec2,
        group_name="cloudprac-p05-sg",
        vpc_id="vpc-12345",
        app_port=5000,
        app_cidr="10.0.0.0/16",
        ssh_cidr="192.168.1.1/32",
    )
    assert sg_id == "sg-9999"

    # Verify ingress author calls: port 5000 and port 22
    assert mock_ec2.authorize_security_group_ingress.call_count == 2
    calls = mock_ec2.authorize_security_group_ingress.call_args_list
    port_calls = [c[1]["IpPermissions"][0]["FromPort"] for c in calls]
    assert 5000 in port_calls
    assert 22 in port_calls


def test_ec2_launch_and_verify():
    """Verify EC2 launch with user-data and IAM instance profile."""
    mock_ec2 = MagicMock()
    mock_ec2.run_instances.return_value = {"Instances": [{"InstanceId": "i-0123456789"}]}
    mock_ec2.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-0123456789",
                        "State": {"Name": "running"},
                        "InstanceType": "t2.micro",
                        "IamInstanceProfile": {"Arn": "arn:aws:iam::123:instance-profile/cloudprac-p05-profile"},
                        "PublicIpAddress": "54.200.10.20",
                    }
                ]
            }
        ]
    }

    inst_id = launch_ec2_instance(
        mock_ec2,
        image_id="ami-test",
        instance_type="t2.micro",
        subnet_id="subnet-123",
        security_group_id="sg-123",
        instance_profile_name="cloudprac-p05-profile",
        user_data_script="#!/bin/bash\necho hello",
    )
    assert inst_id == "i-0123456789"

    # Verify instance state check
    running_inst = wait_for_instance_running(mock_ec2, inst_id)
    assert running_inst["State"]["Name"] == "running"

    # Verify checks
    checks = verify_ec2_instance(
        mock_ec2,
        inst_id,
        expected_instance_type="t2.micro",
        expected_profile_name="cloudprac-p05-profile",
        check_http=False,
    )
    assert len(checks) >= 3
    assert all(c.passed for c in checks)


def test_iam_policy_and_profile_setup():
    """Verify least-privilege IAM policy generation and instance profile creation."""
    policy = build_least_privilege_policy(
        bucket_name="cloudprac-p05-bucket",
        table_name="cloudprac-p05-students",
        region="us-east-1",
        account_id="123456789012",
    )
    assert policy["Version"] == "2012-10-17"
    statements = policy["Statement"]
    assert len(statements) == 2
    actions = [a for s in statements for a in s["Action"]]
    assert "s3:GetObject" in actions
    assert "dynamodb:PutItem" in actions

    mock_iam = MagicMock()
    mock_iam.create_role.return_value = {"Role": {"RoleName": "test-role"}}
    mock_iam.create_instance_profile.return_value = {"InstanceProfile": {"InstanceProfileName": "test-profile"}}

    profile_name = setup_instance_profile(
        iam_client=mock_iam,
        role_name="test-role",
        profile_name="test-profile",
        bucket_name="cloudprac-p05-bucket",
        table_name="cloudprac-p05-students",
        region="us-east-1",
        account_id="123456789012",
    )
    assert profile_name == "test-profile"
    assert mock_iam.create_role.called
    assert mock_iam.put_role_policy.called
    assert mock_iam.create_instance_profile.called
    assert mock_iam.add_role_to_instance_profile.called


# =========================================================================
# S3 Tests
# =========================================================================

def test_s3_bucket_creation_us_east_1():
    """Verify S3 creation in us-east-1 omits LocationConstraint and enables BPA."""
    mock_s3 = MagicMock()
    bname = create_private_bucket(mock_s3, "test-p05-bucket", region="us-east-1")
    assert bname == "test-p05-bucket"

    create_call_kwargs = mock_s3.create_bucket.call_args[1]
    assert "CreateBucketConfiguration" not in create_call_kwargs
    assert mock_s3.put_public_access_block.called


def test_s3_upload_download_and_checksum(tmp_path):
    """Verify document upload, download, and SHA-256 verification."""
    mock_s3 = MagicMock()
    content = "Student Verification Document Content\nLine 2\n"
    content_bytes = content.encode("utf-8")
    expected_sha = calculate_content_sha256(content_bytes)

    mock_s3.head_object.return_value = {
        "ContentLength": len(content_bytes),
        "ETag": '"test-etag"',
        "ContentType": "text/plain",
    }
    mock_s3.get_object.return_value = {"Body": MagicMock(read=lambda: content_bytes)}

    # Upload string content
    upload_meta = upload_document_to_s3(
        mock_s3,
        bucket_name="test-bucket",
        object_key="documents/STU-001-cert.txt",
        content=content,
    )
    assert upload_meta["SHA256"] == expected_sha
    assert upload_meta["Size"] == len(content_bytes)

    # Download to disk
    dest_path = tmp_path / "downloaded.txt"
    dl_path, dl_sha = download_document_from_s3(
        mock_s3,
        bucket_name="test-bucket",
        object_key="documents/STU-001-cert.txt",
        destination_path=dest_path,
    )
    assert dl_path.exists()
    assert dl_sha == expected_sha


def test_s3_verify_checks():
    """Verify S3 independent verification checks pass when bucket & BPA exist."""
    mock_s3 = MagicMock()
    mock_s3.head_bucket.return_value = {}
    mock_s3.get_public_access_block.return_value = {
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        }
    }
    mock_s3.head_object.return_value = {"ContentLength": 100, "ETag": '"abc"'}

    checks = verify_s3_resources(mock_s3, "test-bucket", ["documents/STU-001.txt"])
    assert len(checks) == 3
    assert all(c.passed for c in checks)


# =========================================================================
# DynamoDB Tests
# =========================================================================

def test_dynamodb_student_table_lifecycle():
    """Verify DynamoDB table creation with 'student_id' partition key and CRUD."""
    mock_dynamodb = MagicMock()
    mock_dynamodb.describe_table.return_value = {
        "Table": {
            "TableStatus": "ACTIVE",
            "KeySchema": [{"AttributeName": "student_id", "KeyType": "HASH"}],
            "BillingMode": "PAY_PER_REQUEST",
        }
    }

    tname = create_student_table(mock_dynamodb, "test-students-tbl")
    assert tname == "test-students-tbl"
    create_args = mock_dynamodb.create_table.call_args[1]
    assert create_args["KeySchema"][0]["AttributeName"] == "student_id"
    assert create_args["AttributeDefinitions"][0]["AttributeName"] == "student_id"

    # Wait active
    desc = wait_for_table_active(mock_dynamodb, tname)
    assert desc["TableStatus"] == "ACTIVE"

    # Insert sample records
    records = get_default_student_records()
    count = insert_student_records(mock_dynamodb, tname, records)
    assert count == 3
    assert mock_dynamodb.put_item.call_count == 3

    # Consistent GetItem
    mock_dynamodb.get_item.return_value = {
        "Item": {
            "student_id": {"S": "STU-001"},
            "name": {"S": "Aarav Sharma"},
            "course": {"S": "B.Tech Computer Science"},
        }
    }
    rec = get_student_record(mock_dynamodb, tname, "STU-001")
    assert rec is not None
    assert rec["student_id"] == "STU-001"
    assert rec["name"] == "Aarav Sharma"

    # Update item
    mock_dynamodb.update_item.return_value = {
        "Attributes": {
            "student_id": {"S": "STU-001"},
            "year": {"S": "4th Year"},
        }
    }
    updated = update_student_record(mock_dynamodb, tname, "STU-001", {"year": "4th Year"})
    assert updated["year"] == "4th Year"

    # Delete item
    deleted = delete_student_record(mock_dynamodb, tname, "STU-001")
    assert deleted is True
    assert mock_dynamodb.delete_item.called


# =========================================================================
# Web Application Offline Tests (Flask)
# =========================================================================

def test_web_app_endpoints_offline():
    """Verify student-record Flask application offline via test client."""
    mock_session = MagicMock()
    mock_dynamo = MagicMock()
    mock_s3 = MagicMock()
    mock_session.client.side_effect = lambda svc, **kwargs: mock_dynamo if svc == "dynamodb" else mock_s3

    app = create_app(
        table_name="test-table",
        bucket_name="test-bucket",
        boto_session=mock_session,
    )
    client = app.test_client()

    # 1. Health check endpoint
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["practical"] == "P05"

    # 2. Add student record (POST /api/students)
    resp = client.post(
        "/api/students",
        json={
            "student_id": "STU-105",
            "name": "Kavya Menon",
            "course": "B.Tech Data Science",
            "email": "kavya@college.edu",
            "year": "2nd Year",
        },
    )
    assert resp.status_code == 201
    assert mock_dynamo.put_item.called

    # 3. Input validation: missing required field
    bad_resp = client.post("/api/students", json={"name": "No ID"})
    assert bad_resp.status_code == 400

    # 4. Input validation: invalid student_id characters
    bad_id_resp = client.post(
        "/api/students",
        json={"student_id": "STU$*#", "name": "Test", "course": "CS"},
    )
    assert bad_id_resp.status_code == 400

    # 5. List students (GET /api/students)
    mock_dynamo.scan.return_value = {
        "Items": [
            {
                "student_id": {"S": "STU-105"},
                "name": {"S": "Kavya Menon"},
                "course": {"S": "B.Tech Data Science"},
            }
        ]
    }
    list_resp = client.get("/api/students")
    assert list_resp.status_code == 200
    list_data = list_resp.get_json()
    assert list_data["count"] == 1

    # 6. Get specific student (GET /api/students/STU-105)
    mock_dynamo.get_item.return_value = {
        "Item": {
            "student_id": {"S": "STU-105"},
            "name": {"S": "Kavya Menon"},
            "document_key": {"S": "documents/STU-105-doc.txt"},
        }
    }
    get_resp = client.get("/api/students/STU-105")
    assert get_resp.status_code == 200
    assert get_resp.get_json()["name"] == "Kavya Menon"

    # 7. Upload student document (POST /api/students/STU-105/document)
    from io import BytesIO
    upload_resp = client.post(
        "/api/students/STU-105/document",
        data={"document": (BytesIO(b"My certificate contents"), "cert.txt")},
        content_type="multipart/form-data",
    )
    assert upload_resp.status_code == 201
    assert mock_s3.put_object.called

    # 8. Download student document (GET /api/students/STU-105/document)
    mock_s3.get_object.return_value = {
        "Body": MagicMock(read=lambda: b"My certificate contents"),
        "ContentType": "text/plain",
    }
    doc_resp = client.get("/api/students/STU-105/document")
    assert doc_resp.status_code == 200
    assert doc_resp.data == b"My certificate contents"


# =========================================================================
# Full End-to-End Mock Lifecycle Test
# =========================================================================

def test_p05_full_lifecycle_mock_mode():
    """Verify P05 executes plan, run, verify, and cleanup through ExecutionEngine in mock mode."""
    adapter = AWSAdapter(region_name="us-east-1", mock_mode=True)
    config = CloudPracConfig()
    engine = ExecutionEngine(config=config, adapter=adapter)

    p05 = P05Practical()

    # Plan
    plan = engine.planner.plan(p05)
    assert plan.practical_id == "P05"
    assert len(plan.steps) == 7

    # Run
    result = engine.run_practical(p05, run_id=plan.run_id, auto_verify=False, auto_cleanup=False)
    assert result.success is True
    assert result.manifest is not None and len(result.manifest.resources) >= 4

    # Verify
    v_result = engine.verifier.verify(p05, run_id=plan.run_id)
    assert v_result.practical_id == "P05"

    # Cleanup
    c_result = engine.cleaner.cleanup(p05, run_id=plan.run_id)
    assert c_result.success is True
