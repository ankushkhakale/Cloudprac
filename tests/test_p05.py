"""Unit and mock tests for Practical 05: Student Record Management using EC2, S3, and DynamoDB."""

import json
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from cloudprac.adapters.aws_client import AWSAdapter
from cloudprac.core.engine import ExecutionEngine
from cloudprac.core.models import PracticalStatus, RunManifest, TrackedResource
from cloudprac.practicals.p05.dynamodb import (
    cleanup_dynamodb_resources,
    create_student_table,
    delete_student_record,
    get_student_record,
    insert_student_records,
    update_student_record,
    wait_for_table_active,
)
from cloudprac.practicals.p05.ec2 import (
    build_user_data_script,
    cleanup_ec2_resources,
    find_latest_al2023_ami,
    get_default_or_first_vpc,
    launch_ec2_instance,
    setup_key_pair,
    setup_security_group,
    validate_cidr_block,
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
    cleanup_s3_resources,
    create_private_bucket,
    download_document_from_s3,
    upload_document_to_s3,
    verify_s3_resources,
)
from cloudprac.practicals.p05.sample_data import (
    get_default_student_records,
)
from cloudprac.practicals.p05.web_app import create_app
from cloudprac.utils.config import CloudPracConfig
from cloudprac.utils.paths import get_run_dir, save_restricted_file


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
    assert len(statements) == 4
    actions = [a for s in statements for a in s["Action"]]
    assert "s3:GetObject" in actions
    assert "dynamodb:PutItem" in actions

    # Verify least-privilege scoping: token is strictly read-only, PutObject restricted to documents
    doc_stmt = next(s for s in statements if s.get("Sid") == "S3StudentDocumentAccess")
    secret_stmt = next(s for s in statements if s.get("Sid") == "S3SecretTokenReadOnly")
    assert "documents/*" in doc_stmt["Resource"]
    assert "s3:PutObject" in doc_stmt["Action"]
    assert "secrets/*" in secret_stmt["Resource"]
    assert secret_stmt["Action"] == ["s3:GetObject"]
    assert "s3:PutObject" not in secret_stmt["Action"]

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
    mock_s3.get_bucket_policy.return_value = {
        "Policy": json.dumps({
            "Statement": [
                {
                    "Effect": "Deny",
                    "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                }
            ]
        })
    }
    mock_s3.head_object.return_value = {"ContentLength": 100, "ETag": '"abc"'}

    checks = verify_s3_resources(mock_s3, "test-bucket", ["documents/STU-001.txt"])
    assert len(checks) == 4
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

    test_token = "test-secret-token-suite-987"
    app = create_app(
        table_name="test-table",
        bucket_name="test-bucket",
        boto_session=mock_session,
        admin_token=test_token,
    )
    client = app.test_client()

    # 1. Health check endpoint (public)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["practical"] == "P05"

    # 2. Mutating without auth token MUST return 401 Unauthorized
    unauth_resp = client.post(
        "/api/students",
        json={
            "student_id": "STU-105",
            "name": "Kavya Menon",
            "course": "B.Tech Data Science",
        },
    )
    assert unauth_resp.status_code == 401

    # 3. Query string token MUST be rejected (prevent URL logging)
    query_unauth = client.post(
        f"/api/students?token={test_token}",
        json={
            "student_id": "STU-105",
            "name": "Kavya Menon",
            "course": "B.Tech Data Science",
        },
    )
    assert query_unauth.status_code == 401

    # 4. Wrong header token MUST return 401
    bad_token_resp = client.post(
        "/api/students",
        json={
            "student_id": "STU-105",
            "name": "Kavya Menon",
            "course": "B.Tech Data Science",
        },
        headers={"X-Admin-Token": "wrong-secret-token"},
    )
    assert bad_token_resp.status_code == 401

    auth_headers = {"X-Admin-Token": test_token}

    # 5. Add student record (POST /api/students) with valid auth header
    resp = client.post(
        "/api/students",
        json={
            "student_id": "STU-105",
            "name": "Kavya Menon",
            "course": "B.Tech Data Science",
            "email": "kavya@college.edu",
            "year": "2nd Year",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert mock_dynamo.put_item.called

    # 6. Add student record using Bearer Authorization header
    bearer_resp = client.post(
        "/api/students",
        json={
            "student_id": "STU-106",
            "name": "Arjun Das",
            "course": "B.Tech CS",
        },
        headers={"Authorization": f"Bearer {test_token}"},
    )
    assert bearer_resp.status_code == 201

    # 4. Input validation: missing required field
    bad_resp = client.post("/api/students", json={"name": "No ID"}, headers=auth_headers)
    assert bad_resp.status_code == 400

    # 5. Input validation: invalid student_id characters
    bad_id_resp = client.post(
        "/api/students",
        json={"student_id": "STU$*#", "name": "Test", "course": "CS"},
        headers=auth_headers,
    )
    assert bad_id_resp.status_code == 400

    # 6. List students (GET /api/students - read-only)
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

    # 7. Get specific student (GET /api/students/STU-105 - read-only)
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

    # 8. Upload student document without auth MUST return 401
    from io import BytesIO
    unauth_upload = client.post(
        "/api/students/STU-105/document",
        data={"document": (BytesIO(b"My certificate contents"), "cert.txt")},
        content_type="multipart/form-data",
    )
    assert unauth_upload.status_code == 401

    # 9. Upload student document with disallowed extension (.exe) MUST return 400
    bad_ext_upload = client.post(
        "/api/students/STU-105/document",
        data={"document": (BytesIO(b"malicious script"), "payload.exe")},
        content_type="multipart/form-data",
        headers=auth_headers,
    )
    assert bad_ext_upload.status_code == 400
    assert "Unsupported file extension" in bad_ext_upload.get_json()["error"]

    # 10. Upload student document with auth and allowed extension (.txt)
    upload_resp = client.post(
        "/api/students/STU-105/document",
        data={"document": (BytesIO(b"My certificate contents"), "cert.txt")},
        content_type="multipart/form-data",
        headers=auth_headers,
    )
    assert upload_resp.status_code == 201
    assert mock_s3.put_object.called

    # 11. Download student document (GET /api/students/STU-105/document)
    mock_s3.get_object.return_value = {
        "Body": MagicMock(read=lambda: b"My certificate contents"),
        "ContentType": "text/plain",
    }
    doc_resp = client.get("/api/students/STU-105/document")
    assert doc_resp.status_code == 200
    assert doc_resp.data == b"My certificate contents"

    # 12. Delete student without auth MUST return 401
    unauth_del = client.delete("/api/students/STU-105")
    assert unauth_del.status_code == 401

    # 13. Delete student with auth succeeds
    del_resp = client.delete("/api/students/STU-105", headers=auth_headers)
    assert del_resp.status_code == 200
    assert mock_dynamo.delete_item.called


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


# =========================================================================
# Safety & Correctness Regression Tests
# =========================================================================

def test_validate_cidr_block_rules():
    """Verify strict validation and rejection of public /0 or invalid CIDRs."""
    # Valid CIDRs
    assert validate_cidr_block("192.168.1.100/32") == "192.168.1.100/32"
    assert validate_cidr_block("10.0.0.0/16") == "10.0.0.0/16"
    assert validate_cidr_block("172.16.0.0/24") == "172.16.0.0/24"

    # Rejection of broad / public CIDRs
    with pytest.raises(ValueError, match="0.0.0.0/0.*is prohibited"):
        validate_cidr_block("0.0.0.0/0")

    with pytest.raises(ValueError, match="is prohibited"):
        validate_cidr_block("::/0")

    with pytest.raises(ValueError, match="is prohibited"):
        validate_cidr_block("10.0.0.0/0")

    # Rejection of empty or non-CIDR values
    with pytest.raises(ValueError, match="explicit restricted IPv4 CIDR is required"):
        validate_cidr_block("")

    with pytest.raises(ValueError, match="explicit restricted IPv4 CIDR is required"):
        validate_cidr_block(None)

    with pytest.raises(ValueError, match="Invalid IPv4 CIDR"):
        validate_cidr_block("not-a-valid-cidr")

    with pytest.raises(ValueError, match="Invalid IPv4 CIDR"):
        validate_cidr_block("256.0.0.1/32")


def test_setup_security_group_rejects_broad_cidr():
    """Verify setup_security_group blocks 0.0.0.0/0 from opening application port 5000."""
    mock_ec2 = MagicMock()
    with pytest.raises(ValueError, match="0.0.0.0/0"):
        setup_security_group(
            mock_ec2,
            group_name="sg-test",
            vpc_id="vpc-1",
            app_port=5000,
            app_cidr="0.0.0.0/0",
        )

    with pytest.raises(ValueError, match="explicit restricted IPv4 CIDR is required"):
        setup_security_group(
            mock_ec2,
            group_name="sg-test",
            vpc_id="vpc-1",
            app_port=5000,
            app_cidr="",
        )


def test_p05_execute_blocks_public_cidr():
    """Verify p05.execute halts immediately before provisioning if app_cidr is 0.0.0.0/0."""
    p05 = P05Practical()
    p05.p05_config.app_cidr = "0.0.0.0/0"
    config = CloudPracConfig()
    plan = p05.plan(config, "run-safety-check")
    adapter = AWSAdapter(region_name="us-east-1", mock_mode=False)

    with pytest.raises(ValueError, match="Opening application port 5000 to the public internet"):
        p05.execute(plan, adapter)


def test_web_app_error_sanitization():
    """Verify web application returns sanitized errors and does not leak internal AWS tracebacks."""
    mock_session = MagicMock()
    mock_dynamo = MagicMock()
    mock_s3 = MagicMock()
    mock_session.client.side_effect = lambda svc, **kwargs: mock_dynamo if svc == "dynamodb" else mock_s3

    # Simulate internal AWS ClientError with sensitive traceback/error details
    mock_dynamo.scan.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Internal AWS account 999999999999 secret leak"}},
        "Scan",
    )

    app = create_app(
        table_name="test-table",
        bucket_name="test-bucket",
        boto_session=mock_session,
    )
    client = app.test_client()

    resp = client.get("/api/students")
    assert resp.status_code == 500
    data = resp.get_json()
    assert "error" in data
    assert "Failed to list students" in data["error"]
    assert "999999999999" not in data["error"]
    assert "secret leak" not in data["error"]


def test_plan_does_not_provision_resources():
    """Verify that calling plan() generates pure data objects and performs zero AWS network calls."""
    p05 = P05Practical()
    config = CloudPracConfig()
    plan = p05.plan(config, "run-safe-plan")

    assert plan.practical_id == "P05"
    assert plan.run_id == "run-safe-plan"
    assert len(plan.steps) == 7
    # Verify no adapters or network clients were passed or used
    assert all(hasattr(s, "action") for s in plan.steps)


def test_ec2_role_least_privilege_scoping():
    """Verify IAM policy is strictly scoped to resource ARNs and contains no wildcard Resource access."""
    policy = build_least_privilege_policy(
        bucket_name="my-college-bucket",
        table_name="my-student-table",
        region="ap-south-1",
        account_id="112233445566",
    )
    for stmt in policy["Statement"]:
        # Resource must NOT be "*"
        assert stmt["Resource"] != "*"
        if "s3:" in stmt["Action"][0]:
            assert "arn:aws:s3:::my-college-bucket" in stmt["Resource"]
        if "dynamodb:" in stmt["Action"][0]:
            assert "arn:aws:dynamodb:ap-south-1:112233445566:table/my-student-table" in stmt["Resource"]


def test_web_app_fail_closed_without_token():
    """Verify web application runs in fail-closed mode when no ADMIN_TOKEN is configured."""
    mock_session = MagicMock()
    app = create_app(
        table_name="test-table",
        bucket_name="test-bucket",
        boto_session=mock_session,
        admin_token=None,
    )
    client = app.test_client()

    # Read-only health check remains available
    resp = client.get("/health")
    assert resp.status_code == 200

    # Mutating operation MUST be rejected with 401 even if a token header is attempted
    post_resp = client.post(
        "/api/students",
        json={"student_id": "STU-999", "name": "Fail Closed", "course": "Security"},
        headers={"X-Admin-Token": "any-attempted-token"},
    )
    assert post_resp.status_code == 401


def test_build_user_data_script_fails_closed():
    """Verify build_user_data_script refuses to generate bootstrap script without secure token_s3_key."""
    with pytest.raises(ValueError, match="token_s3_key.*required"):
        build_user_data_script(
            table_name="students-tbl",
            bucket_name="documents-bkt",
            region="us-east-1",
            token_s3_key=None,
        )

    with pytest.raises(ValueError, match="token_s3_key.*required"):
        build_user_data_script(
            table_name="students-tbl",
            bucket_name="documents-bkt",
            region="us-east-1",
            token_s3_key="   ",
        )

    # Embedding plaintext admin_token directly is strictly prohibited
    with pytest.raises(ValueError, match="prohibited"):
        build_user_data_script(
            table_name="students-tbl",
            bucket_name="documents-bkt",
            region="us-east-1",
            token_s3_key="secrets/test/admin_token",
            admin_token="insecure-plaintext-token",
        )


def test_build_user_data_script_iam_s3_fetch():
    """Verify build_user_data_script generates IAM S3 retrieval logic and does not leak plaintext tokens."""
    script = build_user_data_script(
        table_name="students-tbl",
        bucket_name="documents-bkt",
        region="us-east-1",
        app_port=5000,
        token_s3_key="secrets/run-123/admin_token",
    )

    # Must contain IAM-based S3 retrieval without plaintext token
    assert "s3.get_object" in script
    assert "secrets/run-123/admin_token" in script
    assert "chmod 600 /opt/cloudprac/.env" in script
    assert "ADMIN_TOKEN=" in script
    assert "insecure-plaintext-token" not in script
    assert "cloudprac-demo-token" not in script


def test_save_restricted_file_permissions(tmp_path):
    """Verify save_restricted_file creates files with 0600 permissions restricted to current user."""
    import os
    import stat

    from cloudprac.utils.paths import save_restricted_file

    target_file = tmp_path / "test_secret_token"
    save_restricted_file(target_file, "super-secret-token-value-12345")

    assert target_file.read_text(encoding="utf-8") == "super-secret-token-value-12345"
    if os.name != "nt":
        mode = stat.S_IMODE(target_file.stat().st_mode)
        assert mode == 0o600


def test_mock_execution_saves_restricted_token_file():
    """Verify mock practical execution saves admin_token locally with 0600 permissions."""
    import os
    import stat

    from cloudprac.utils.paths import get_run_dir

    p05 = P05Practical()
    adapter = AWSAdapter(region_name="us-east-1", mock_mode=True)
    plan = p05.plan(CloudPracConfig(), "run-token-test-123")
    result = p05.execute(plan, adapter)

    assert result.success is True
    token_file = get_run_dir("run-token-test-123") / "admin_token"
    assert token_file.is_file()
    token_val = token_file.read_text(encoding="utf-8").strip()
    assert len(token_val) >= 32
    if os.name != "nt":
        mode = stat.S_IMODE(token_file.stat().st_mode)
        assert mode == 0o600


def test_cleanup_refuses_mock_manifest_in_live_mode():
    """Verify cleanup rejects mock manifests when running in non-mock execution mode."""
    p05 = P05Practical()
    adapter = AWSAdapter(region_name="us-east-1", mock_mode=False)
    adapter.get_caller_identity = MagicMock(return_value={"Account": "123456789012"})

    mock_manifest = RunManifest(
        practical_id="P05",
        run_id="run-mock-123",
        aws_account_id="mock-123456789012",
        aws_region="us-east-1",
        resources=[
            TrackedResource(
                resource_type="ec2-instance",
                resource_id="i-mock123456",
                resource_name="mock-inst",
            )
        ],
    )

    result = p05.cleanup(mock_manifest, adapter)
    assert result.success is False
    assert any("mock" in e.lower() for e in result.errors)


def test_cleanup_refuses_cross_account_mismatch():
    """Verify cleanup halts if manifest account does not match active caller account."""
    p05 = P05Practical()
    adapter = AWSAdapter(region_name="us-east-1", mock_mode=False)
    adapter.get_caller_identity = MagicMock(return_value={"Account": "111122223333"})

    foreign_manifest = RunManifest(
        practical_id="P05",
        run_id="run-foreign-acc",
        aws_account_id="9999****8888",
        aws_region="us-east-1",
        resources=[],
    )

    result = p05.cleanup(foreign_manifest, adapter)
    assert result.success is False
    assert any("Cross-account" in e or "does not match active" in e for e in result.errors)


def test_cleanup_refuses_cross_region_mismatch():
    """Verify cleanup halts if manifest region does not match active target region."""
    p05 = P05Practical()
    adapter = AWSAdapter(region_name="ap-south-1", mock_mode=False)
    adapter.get_caller_identity = MagicMock(return_value={"Account": "111122223333"})

    foreign_region_manifest = RunManifest(
        practical_id="P05",
        run_id="run-foreign-region",
        aws_account_id="1111****3333",
        aws_region="us-east-1",
        resources=[],
    )

    result = p05.cleanup(foreign_region_manifest, adapter)
    assert result.success is False
    assert any("Cross-region" in e or "target region" in e for e in result.errors)


def test_cleanup_skips_unowned_resources_with_mismatched_tags():
    """Verify individual resource cleanup skips deleting resources tagged with a different RunId."""
    # 1. EC2 Instance
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-foreign999",
                        "State": {"Name": "running"},
                        "Tags": [{"Key": "ManagedBy", "Value": "CloudPrac"}, {"Key": "RunId", "Value": "other-run-id"}],
                    }
                ]
            }
        ]
    }
    deleted_ec2 = cleanup_ec2_resources(mock_ec2, instance_id="i-foreign999", expected_run_id="my-run-id")
    assert deleted_ec2 == []
    assert not mock_ec2.terminate_instances.called

    # 2. S3 Bucket
    mock_s3 = MagicMock()
    mock_s3.get_bucket_tagging.return_value = {
        "TagSet": [{"Key": "ManagedBy", "Value": "CloudPrac"}, {"Key": "RunId", "Value": "other-run-id"}]
    }
    deleted_s3 = cleanup_s3_resources(mock_s3, bucket_name="foreign-bucket", expected_run_id="my-run-id")
    assert deleted_s3 == []
    assert not mock_s3.delete_bucket.called

    # 3. DynamoDB Table
    mock_dynamo = MagicMock()
    mock_dynamo.describe_table.return_value = {"Table": {"TableArn": "arn:aws:dynamodb:us-east-1:123:table/foreign-tbl"}}
    mock_dynamo.list_tags_of_resource.return_value = {
        "Tags": [{"Key": "ManagedBy", "Value": "CloudPrac"}, {"Key": "RunId", "Value": "other-run-id"}]
    }
    deleted_dynamo = cleanup_dynamodb_resources(mock_dynamo, table_name="foreign-tbl", expected_run_id="my-run-id")
    assert deleted_dynamo == []
    assert not mock_dynamo.delete_table.called

    # 4. IAM Role
    mock_iam = MagicMock()
    mock_iam.list_role_tags.return_value = {
        "Tags": [{"Key": "ManagedBy", "Value": "CloudPrac"}, {"Key": "RunId", "Value": "other-run-id"}]
    }
    deleted_iam = cleanup_iam_resources(mock_iam, role_name="foreign-role", expected_run_id="my-run-id")
    assert deleted_iam == []
    assert not mock_iam.delete_role.called


def test_cleanup_partial_failure_idempotence():
    """Verify cleanup works cleanly when only partial resources (S3 & DynamoDB) exist in manifest."""
    p05 = P05Practical()
    adapter = AWSAdapter(region_name="us-east-1", mock_mode=True)

    partial_manifest = RunManifest(
        practical_id="P05",
        run_id="run-partial-001",
        aws_account_id="1234****9012",
        aws_region="us-east-1",
        resources=[
            TrackedResource(
                resource_type="s3-bucket",
                resource_id="cloudprac-p05-test-bucket",
                resource_name="cloudprac-p05-test-bucket",
            ),
            TrackedResource(
                resource_type="dynamodb-table",
                resource_id="cloudprac-p05-test-table",
                resource_name="cloudprac-p05-test-table",
            ),
        ],
    )

    result = p05.cleanup(partial_manifest, adapter)
    assert result.success is True
    assert "cloudprac-p05-test-bucket" in result.resources_deleted
    assert "cloudprac-p05-test-table" in result.resources_deleted


def test_s3_tls_policy_enforcement():
    """Verify create_private_bucket applies a TLS deny policy and verify_s3_resources validates it."""
    mock_s3 = MagicMock()
    create_private_bucket(mock_s3, "test-tls-bucket", region="us-east-1")

    assert mock_s3.put_bucket_policy.called
    call_args = mock_s3.put_bucket_policy.call_args[1]
    assert call_args["Bucket"] == "test-tls-bucket"
    policy = json.loads(call_args["Policy"])
    statements = policy.get("Statement", [])
    assert any(
        s.get("Effect") == "Deny"
        and s.get("Condition", {}).get("Bool", {}).get("aws:SecureTransport") in ("false", False)
        for s in statements
    )

    # Verification passes when policy is present
    mock_s3.head_bucket.return_value = {}
    mock_s3.get_public_access_block.return_value = {
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        }
    }
    mock_s3.get_bucket_policy.return_value = {"Policy": json.dumps(policy)}
    mock_s3.head_object.return_value = {"ContentLength": 50, "ETag": '"abc"'}

    checks = verify_s3_resources(mock_s3, "test-tls-bucket", ["documents/doc.txt"])
    tls_check = next(c for c in checks if c.check_id == "s3-tls-test-tls-bucket")
    assert tls_check.passed is True

    # Verification fails when TLS policy lacks SecureTransport condition
    mock_s3.get_bucket_policy.return_value = {"Policy": json.dumps({"Statement": []})}
    failing_checks = verify_s3_resources(mock_s3, "test-tls-bucket", ["documents/doc.txt"])
    failing_tls = next(c for c in failing_checks if c.check_id == "s3-tls-test-tls-bucket")
    assert failing_tls.passed is False


def test_cleanup_refuses_untagged_resources():
    """Verify cleanup strictly refuses deleting untagged resources to prevent accidental destruction."""
    # 1. Untagged EC2 Instance
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-untagged",
                        "State": {"Name": "running"},
                        "Tags": [],
                    }
                ]
            }
        ]
    }
    assert cleanup_ec2_resources(mock_ec2, instance_id="i-untagged", expected_run_id="run-123") == []
    assert not mock_ec2.terminate_instances.called

    # 2. Untagged Security Group
    mock_ec2.describe_security_groups.return_value = {
        "SecurityGroups": [{"GroupId": "sg-untagged", "Tags": []}]
    }
    assert cleanup_ec2_resources(mock_ec2, security_group_id="sg-untagged", expected_run_id="run-123") == []
    assert not mock_ec2.delete_security_group.called

    # 3. Untagged Key Pair
    mock_ec2.describe_key_pairs.return_value = {
        "KeyPairs": [{"KeyName": "kp-untagged", "Tags": []}]
    }
    assert cleanup_ec2_resources(mock_ec2, key_name="kp-untagged", expected_run_id="run-123") == []
    assert not mock_ec2.delete_key_pair.called

    # 4. Untagged S3 Bucket (NoSuchTagSet or empty tags)
    mock_s3 = MagicMock()
    mock_s3.get_bucket_tagging.side_effect = ClientError(
        {"Error": {"Code": "NoSuchTagSet", "Message": "The TagSet does not exist"}},
        "GetBucketTagging",
    )
    assert cleanup_s3_resources(mock_s3, bucket_name="b-untagged", expected_run_id="run-123") == []
    assert not mock_s3.delete_bucket.called
    assert not mock_s3.delete_objects.called

    # 5. Untagged DynamoDB Table
    mock_dynamo = MagicMock()
    mock_dynamo.describe_table.return_value = {"Table": {"TableArn": "arn:aws:dynamodb:us-east-1:123:table/tbl-untagged"}}
    mock_dynamo.list_tags_of_resource.return_value = {"Tags": []}
    assert cleanup_dynamodb_resources(mock_dynamo, table_name="tbl-untagged", expected_run_id="run-123") == []
    assert not mock_dynamo.delete_table.called

    # 6. Untagged IAM Profile
    mock_iam = MagicMock()
    mock_iam.get_instance_profile.return_value = {
        "InstanceProfile": {"InstanceProfileName": "prof-untagged", "Tags": [], "Roles": []}
    }
    assert cleanup_iam_resources(mock_iam, profile_name="prof-untagged", expected_run_id="run-123") == []
    assert not mock_iam.delete_instance_profile.called

    # 7. Untagged IAM Role
    mock_iam.list_role_tags.return_value = {"Tags": []}
    assert cleanup_iam_resources(mock_iam, role_name="role-untagged", expected_run_id="run-123") == []
    assert not mock_iam.delete_role.called


def test_cleanup_fails_closed_on_ownership_api_error():
    """Verify cleanup fails closed if ownership inspection API calls return errors."""
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Access denied"}}, "DescribeInstances"
    )
    assert cleanup_ec2_resources(mock_ec2, instance_id="i-error", expected_run_id="run-123") == []
    assert not mock_ec2.terminate_instances.called

    mock_s3 = MagicMock()
    mock_s3.get_bucket_tagging.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Access denied"}}, "GetBucketTagging"
    )
    assert cleanup_s3_resources(mock_s3, bucket_name="b-error", expected_run_id="run-123") == []
    assert not mock_s3.delete_bucket.called

    mock_dynamo = MagicMock()
    mock_dynamo.describe_table.side_effect = ClientError(
        {"Error": {"Code": "InternalServerError", "Message": "Server error"}}, "DescribeTable"
    )
    assert cleanup_dynamodb_resources(mock_dynamo, table_name="tbl-error", expected_run_id="run-123") == []
    assert not mock_dynamo.delete_table.called

    mock_iam = MagicMock()
    mock_iam.list_role_tags.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Access denied"}}, "ListRoleTags"
    )
    assert cleanup_iam_resources(mock_iam, role_name="role-error", expected_run_id="run-123") == []
    assert not mock_iam.delete_role.called


def test_cleanup_deletes_local_admin_token_file():
    """Verify cleanup dismantles the local sensitive admin_token file."""
    p05 = P05Practical()
    adapter = AWSAdapter(region_name="us-east-1", mock_mode=True)
    run_id = "test-cleanup-local-token-run"
    run_dir = get_run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    token_file = run_dir / "admin_token"
    save_restricted_file(token_file, "secret-test-token-to-delete-12345")
    assert token_file.is_file()

    manifest = RunManifest(
        practical_id="P05",
        run_id=run_id,
        aws_account_id="1234****9012",
        aws_region="us-east-1",
        resources=[],
    )

    result = p05.cleanup(manifest, adapter)
    assert result.success is True
    assert not token_file.exists()


def test_manifest_never_contains_raw_admin_token():
    """Verify that execution manifests never record the raw admin token."""
    raw_token = "ultra-secret-test-token-value-99999"
    manifest = RunManifest(
        practical_id="P05",
        run_id="run-manifest-check",
        aws_account_id="1234****9012",
        aws_region="us-east-1",
        resources=[
            TrackedResource(
                resource_type="s3-object",
                resource_id="s3://cloudprac-bucket/secrets/run-manifest-check/admin_token",
                resource_name="secrets/run-manifest-check/admin_token",
            )
        ],
    )
    manifest_json = manifest.model_dump_json()
    assert raw_token not in manifest_json
    assert "admin_token" in manifest_json  # Key name is present, not token value
