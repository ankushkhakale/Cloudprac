"""Comprehensive reliability, preview, verification, and cleanup regression tests for P05."""

import socket
import urllib.error
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from cloudprac.adapters.aws_client import AWSAdapter
from cloudprac.core.engine import ExecutionEngine
from cloudprac.core.models import CleanupResult, RunManifest, TrackedResource
from cloudprac.core.planner import generate_plan_id
from cloudprac.practicals.p05.ec2 import launch_ec2_instance
from cloudprac.practicals.p05.practical import P05Practical
from cloudprac.practicals.p05.preview import (
    is_real_public_ip,
    probe_endpoint,
    sanitize_url_for_logging,
    verify_application_and_preview,
)
from cloudprac.practicals.p05.s3 import cleanup_s3_resources
from cloudprac.utils.config import CloudPracConfig

# ==============================================================================
# 1. Real Public IP Assignment & Rejection of Placeholders
# ==============================================================================


def test_is_real_public_ip_rejects_placeholders_and_invalid_formats():
    """Verify that RFC 5737 testnets, private IPs, loopbacks, and invalid strings are strictly rejected."""
    # Placeholders / Testnets (RFC 5737)
    for placeholder in ["198.51.100.25", "198.51.100.1", "192.0.2.1", "203.0.113.50"]:
        is_valid, reason = is_real_public_ip(placeholder)
        assert is_valid is False
        assert "Placeholder / documentation testnet" in reason

    # Private RFC 1918 addresses
    for priv in ["10.0.0.1", "172.16.0.20", "192.168.1.100"]:
        is_valid, reason = is_real_public_ip(priv)
        assert is_valid is False
        assert "Private RFC1918 address" in reason

    # Loopback
    is_valid, reason = is_real_public_ip("127.0.0.1")
    assert is_valid is False
    assert "Loopback address" in reason

    # Missing / None / undefined strings
    for empty_val in [None, "", "   ", "none", "None", "null", "undefined"]:
        is_valid, reason = is_real_public_ip(empty_val)
        assert is_valid is False

    # Valid public IPv4 addresses
    for valid_ip in ["54.200.10.25", "3.80.20.1", "13.234.50.12", "142.250.190.46"]:
        is_valid, reason = is_real_public_ip(valid_ip)
        assert is_valid is True
        assert "Valid public IPv4 address" in reason


# ==============================================================================
# 2. Resilient HTTP Endpoint Probing & URL Sanitization
# ==============================================================================


def test_probe_endpoint_handles_timeouts_and_crashes_gracefully():
    """Verify probe_endpoint captures network timeouts, refusal, and HTTP errors without throwing unhandled exceptions."""
    # 1. Connection Refused
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError(ConnectionRefusedError("Connection refused")),
    ):
        ok, code, msg, body = probe_endpoint("http://54.200.10.25:5000/health", timeout=1.0)
        assert ok is False
        assert code == 0
        assert "Connection refused" in msg
        assert body is None

    # 2. Socket Timeout
    with patch("urllib.request.urlopen", side_effect=socket.timeout("timed out")):
        ok, code, msg, body = probe_endpoint("http://54.200.10.25:5000/health", timeout=2.0)
        assert ok is False
        assert code == 0
        assert "Socket timed out" in msg

    # 3. HTTP 500 Internal Server Error
    mock_err = urllib.error.HTTPError(
        url="http://54.200.10.25:5000/api/students",
        code=500,
        msg="Internal Server Error",
        hdrs={},
        fp=None,
    )
    with patch("urllib.request.urlopen", side_effect=mock_err):
        ok, code, msg, body = probe_endpoint("http://54.200.10.25:5000/api/students")
        assert ok is False
        assert code == 500
        assert "HTTP 500" in msg


def test_sanitize_url_for_logging_redacts_tokens_and_credentials():
    """Verify URLs with embedded tokens or passwords have sensitive fragments redacted before logging."""
    url1 = "http://54.200.10.25:5000/api/students?admin_token=secret123&format=json"
    clean1 = sanitize_url_for_logging(url1)
    assert "secret123" not in clean1
    assert "admin_token=[REDACTED]" in clean1
    assert "format=json" in clean1

    url2 = "http://admin:supersecret@54.200.10.25:5000/dashboard"
    clean2 = sanitize_url_for_logging(url2)
    assert "supersecret" not in clean2
    assert "***@54.200.10.25:5000" in clean2


# ==============================================================================
# 3. Application & Preview Verification Workflow
# ==============================================================================


def test_verify_application_and_preview_fails_immediately_on_placeholder_or_missing_ip():
    """Verify that when no valid public IP is assigned, all preview checks fail without attempting network traffic."""
    # Missing IP
    checks = verify_application_and_preview(public_ip=None, app_port=5000)
    assert len(checks) >= 6
    assert all(c.passed is False for c in checks)
    assert checks[0].check_id == "ec2-public-ip-assigned"
    assert "No IP address assigned" in checks[0].actual
    assert any("Skipped: No real public IP assigned" in c.actual for c in checks[1:])

    # Placeholder IP
    checks_placeholder = verify_application_and_preview(public_ip="198.51.100.25", app_port=5000)
    assert checks_placeholder[0].passed is False
    assert "Placeholder / documentation testnet" in checks_placeholder[0].actual


def test_verify_application_and_preview_full_successful_suite():
    """Verify that verify_application_and_preview executes the full suite: preview, /health, read, auth mutation, read-back."""
    valid_ip = "54.200.10.25"
    admin_token = "secure-unique-admin-token-xyz-12345"

    def mock_probe(url, method="GET", headers=None, data=None, timeout=5.0):
        if url.endswith("/health"):
            return True, 200, "HTTP 200 OK", {"status": "healthy"}
        if url.endswith("/api/students") and method == "GET":
            return (
                True,
                200,
                "HTTP 200 OK",
                {"students": [{"student_id": "STU-001", "name": "Alice"}]},
            )
        if url.endswith("/api/students/STU-001") and method == "GET":
            return True, 200, "HTTP 200 OK", {"student_id": "STU-001", "name": "Alice"}
        if url.endswith("/api/students") and method == "POST":
            # Assert admin token header was sent
            assert headers.get("X-Admin-Token") == admin_token
            return True, 201, "HTTP 201 Created", {"message": "Created"}
        if "/api/students/VERIF-" in url and method == "GET":
            sid = url.split("/")[-1]
            return True, 200, "HTTP 200 OK", {"student_id": sid, "name": "Verification Student"}
        if "/api/students/VERIF-" in url and method == "DELETE":
            return True, 200, "HTTP 200 OK", {"message": "Deleted"}
        if url.endswith("/"):
            return True, 200, "HTTP 200 OK", None
        return True, 200, "HTTP 200 OK", None

    with patch("cloudprac.practicals.p05.preview.probe_endpoint", side_effect=mock_probe):
        checks = verify_application_and_preview(
            public_ip=valid_ip,
            app_port=5000,
            admin_token=admin_token,
            run_id="test-run-99",
        )

        assert len(checks) == 7
        assert all(c.passed is True for c in checks)
        check_ids = [c.check_id for c in checks]
        assert "ec2-public-ip-assigned" in check_ids
        assert "preview-endpoint-accessible" in check_ids
        assert "app-health-check" in check_ids
        assert "app-read-students" in check_ids
        assert "app-read-single-student" in check_ids
        assert "app-auth-mutation" in check_ids
        assert "app-mutation-readback" in check_ids


# ==============================================================================
# 4. Distinct Plan IDs vs Execution Run IDs
# ==============================================================================


def test_distinct_plan_id_and_run_id_separation():
    """Verify planner generates PLAN-P05-... IDs and execution generates distinct run IDs."""
    plan_id = generate_plan_id("P05")
    assert plan_id.startswith("PLAN-P05-")

    p05 = P05Practical()
    config = CloudPracConfig()
    adapter = AWSAdapter(mock_mode=True)
    engine = ExecutionEngine(config=config, adapter=adapter)
    plan = engine.planner.plan(p05)

    assert plan.run_id.startswith("PLAN-P05-")

    # When engine executes, a fresh execution run_id is generated
    res = engine.run_practical(p05, run_id=None, auto_verify=False, auto_cleanup=False)

    assert res.run_id.startswith("P05-")
    assert not res.run_id.startswith("PLAN-")
    assert res.run_id != plan.run_id


# ==============================================================================
# 5. Verification Fails Closed on Missing Run Manifest
# ==============================================================================


def test_verify_fails_closed_when_manifest_missing_in_mock_and_live_modes():
    """Verify that calling verify on a nonexistent run ID fails closed without false positive mock passes."""
    p05 = P05Practical()

    # Mock mode
    mock_adapter = AWSAdapter(mock_mode=True)
    res_mock = p05.verify("nonexistent-run-id-999", mock_adapter)
    assert res_mock.success is False
    assert len(res_mock.checks) == 1
    assert res_mock.checks[0].check_id == "manifest-exists"
    assert res_mock.checks[0].passed is False

    # Live mode
    live_adapter = AWSAdapter(mock_mode=False)
    live_adapter.get_caller_identity = MagicMock(return_value={"Account": "123456789012"})
    res_live = p05.verify("nonexistent-run-id-999", live_adapter)
    assert res_live.success is False
    assert res_live.checks[0].passed is False


# ==============================================================================
# 6. EC2 IAM Instance Profile Eventual Consistency Retry
# ==============================================================================


def test_launch_ec2_instance_retries_on_iam_eventual_consistency():
    """Verify launch_ec2_instance catches InvalidParameterValue for iamInstanceProfile and retries."""
    mock_ec2 = MagicMock()

    # First call raises InvalidParameterValue due to IAM propagation delay
    # Second call succeeds
    error_response = {
        "Error": {
            "Code": "InvalidParameterValue",
            "Message": "Value (cloudprac-p05-profile) for parameter iamInstanceProfile.name is invalid. Invalid IAM Instance Profile name",
        }
    }
    client_error = ClientError(error_response, "RunInstances")

    mock_ec2.run_instances.side_effect = [
        client_error,
        {"Instances": [{"InstanceId": "i-propagated123"}]},
    ]

    with patch("time.sleep", return_value=None):
        inst_id = launch_ec2_instance(
            ec2_client=mock_ec2,
            image_id="ami-12345",
            instance_type="t2.micro",
            subnet_id="subnet-123",
            security_group_id="sg-123",
            instance_profile_name="cloudprac-p05-profile",
        )

    assert inst_id == "i-propagated123"
    assert mock_ec2.run_instances.call_count == 2


# ==============================================================================
# 7. Cleanup Absence, Deletion, and Unverified State Separation
# ==============================================================================


def test_cleanup_separates_absent_deleted_and_unverified_resources():
    """Verify cleanup distinguishes already absent resources from deleted ones and reports unverified state."""
    p05 = P05Practical()

    manifest = RunManifest(
        practical_id="P05",
        run_id="run-cleanup-split-001",
        aws_account_id="1234****9012",
        aws_region="us-east-1",
        resources=[
            TrackedResource(
                resource_type="s3-bucket",
                resource_id="already-absent-bucket",
                resource_name="already-absent-bucket",
            ),
            TrackedResource(
                resource_type="dynamodb-table",
                resource_id="deleted-table",
                resource_name="deleted-table",
            ),
        ],
    )

    mock_s3 = MagicMock()
    mock_dynamodb = MagicMock()

    # S3 bucket is already absent prior to cleanup (ownership check encounters NoSuchBucket)
    mock_s3.get_bucket_tagging.side_effect = ClientError(
        {"Error": {"Code": "NoSuchBucket"}}, "GetBucketTagging"
    )

    # DynamoDB table is present and owned, deletion succeeds
    mock_dynamodb.describe_table.return_value = {
        "Table": {"TableArn": "arn:aws:dynamodb:us-east-1:123456789012:table/deleted-table"}
    }
    mock_dynamodb.list_tags_of_resource.return_value = {
        "Tags": [
            {"Key": "ManagedBy", "Value": "CloudPrac"},
            {"Key": "RunId", "Value": "run-cleanup-split-001"},
        ]
    }
    mock_dynamodb.delete_table.return_value = {}

    adapter = AWSAdapter(region_name="us-east-1", mock_mode=False)
    adapter.get_caller_identity = MagicMock(return_value={"Account": "123456789012"})

    def mock_get_client(service, region_name=None):
        return {"s3": mock_s3, "dynamodb": mock_dynamodb, "ec2": MagicMock(), "iam": MagicMock()}[
            service
        ]

    adapter.get_client = mock_get_client

    cleanup_res = p05.cleanup(manifest, adapter)

    assert cleanup_res.success is True
    assert "s3-bucket:already-absent-bucket" in cleanup_res.resources_absent
    assert "dynamodb-table:deleted-table" in cleanup_res.resources_deleted
    assert len(cleanup_res.resources_failed) == 0


def test_cleanup_drains_s3_versions_and_delete_markers():
    """Verify cleanup_s3_resources drains both object versions and delete markers to prevent BucketNotEmpty."""
    mock_s3 = MagicMock()

    mock_s3.get_bucket_tagging.return_value = {
        "TagSet": [
            {"Key": "ManagedBy", "Value": "CloudPrac"},
            {"Key": "RunId", "Value": "run-version-test"},
        ]
    }
    mock_s3.list_objects_v2.return_value = {"Contents": []}
    mock_s3.list_object_versions.return_value = {
        "Versions": [
            {"Key": "doc1.txt", "VersionId": "v1"},
            {"Key": "doc1.txt", "VersionId": "v2"},
        ],
        "DeleteMarkers": [{"Key": "doc1.txt", "VersionId": "dm1"}],
    }
    mock_s3.delete_objects.return_value = {}
    mock_s3.delete_bucket.return_value = {}

    deleted = cleanup_s3_resources(
        s3_client=mock_s3,
        bucket_name="versioned-test-bucket",
        expected_run_id="run-version-test",
    )

    assert "s3-bucket:versioned-test-bucket" in deleted
    assert mock_s3.delete_objects.called
    call_args = mock_s3.delete_objects.call_args[1]
    deleted_items = call_args["Delete"]["Objects"]
    assert len(deleted_items) == 3
    keys_deleted = [item["Key"] for item in deleted_items]
    assert "doc1.txt" in keys_deleted
    assert mock_s3.delete_bucket.called


def test_cleanup_s3_handles_paginated_versions_and_delete_markers():
    """Verify cleanup_s3_resources handles paginated list_object_versions calls."""
    mock_s3 = MagicMock()
    mock_s3.get_bucket_tagging.return_value = {
        "TagSet": [
            {"Key": "ManagedBy", "Value": "CloudPrac"},
            {"Key": "RunId", "Value": "run-page-test"},
        ]
    }
    mock_s3.list_objects_v2.return_value = {"Contents": []}

    # Page 1 truncated, Page 2 final
    mock_s3.list_object_versions.side_effect = [
        {
            "IsTruncated": True,
            "NextKeyMarker": "page1-doc.txt",
            "NextVersionIdMarker": "ver-page-1",
            "Versions": [{"Key": "page1-doc.txt", "VersionId": "v1"}],
            "DeleteMarkers": [{"Key": "page1-marker.txt", "VersionId": "dm1"}],
        },
        {
            "IsTruncated": False,
            "Versions": [{"Key": "page2-doc.txt", "VersionId": "v2"}],
            "DeleteMarkers": [],
        },
    ]
    mock_s3.delete_objects.return_value = {}
    mock_s3.delete_bucket.return_value = {}

    deleted = cleanup_s3_resources(
        s3_client=mock_s3,
        bucket_name="paginated-test-bucket",
        expected_run_id="run-page-test",
    )

    assert "s3-bucket:paginated-test-bucket" in deleted
    assert mock_s3.list_object_versions.call_count == 2
    # Verify second page used KeyMarker and VersionIdMarker
    second_call_kwargs = mock_s3.list_object_versions.call_args_list[1][1]
    assert second_call_kwargs.get("KeyMarker") == "page1-doc.txt"
    assert second_call_kwargs.get("VersionIdMarker") == "ver-page-1"
    assert mock_s3.delete_objects.call_count == 2


def test_cleanup_s3_fails_and_raises_when_delete_objects_returns_errors():
    """Verify cleanup_s3_resources raises RuntimeError when delete_objects reports errors."""
    mock_s3 = MagicMock()
    mock_s3.get_bucket_tagging.return_value = {
        "TagSet": [
            {"Key": "ManagedBy", "Value": "CloudPrac"},
            {"Key": "RunId", "Value": "run-err-test"},
        ]
    }
    mock_s3.list_objects_v2.return_value = {"Contents": [{"Key": "protected-doc.txt"}]}
    mock_s3.delete_objects.return_value = {
        "Errors": [{"Key": "protected-doc.txt", "Code": "AccessDenied", "Message": "Access Denied"}]
    }

    with pytest.raises(RuntimeError) as exc_info:
        cleanup_s3_resources(
            s3_client=mock_s3,
            bucket_name="err-bucket",
            expected_run_id="run-err-test",
        )
    assert "Failed to delete 1 objects from 'err-bucket'" in str(exc_info.value)
    assert "AccessDenied" in str(exc_info.value)
    # Ensure delete_bucket is not called when object deletion fails
    assert not mock_s3.delete_bucket.called


def test_cleanup_s3_does_not_swallow_client_error_during_version_listing():
    """Verify cleanup_s3_resources propagates ClientError instead of swallowing exceptions."""
    mock_s3 = MagicMock()
    mock_s3.get_bucket_tagging.return_value = {
        "TagSet": [
            {"Key": "ManagedBy", "Value": "CloudPrac"},
            {"Key": "RunId", "Value": "run-s3-fail"},
        ]
    }
    mock_s3.list_objects_v2.return_value = {"Contents": []}
    mock_s3.list_object_versions.side_effect = ClientError(
        {"Error": {"Code": "InternalError", "Message": "S3 failure"}},
        "ListObjectVersions",
    )

    with pytest.raises(ClientError) as exc_info:
        cleanup_s3_resources(
            s3_client=mock_s3,
            bucket_name="s3-fail-bucket",
            expected_run_id="run-s3-fail",
        )
    assert exc_info.value.response["Error"]["Code"] == "InternalError"
    assert not mock_s3.delete_bucket.called


def test_cleanup_result_model_validator_never_allows_success_with_failed_or_unverified_resources():
    """Ensure CleanupResult model validation forces success=False whenever failures exist."""
    res1 = CleanupResult(
        success=True,
        run_id="run-1",
        practical_id="P05",
        resources_failed=["s3-bucket:b1"],
    )
    assert res1.success is False

    res2 = CleanupResult(
        success=True,
        run_id="run-2",
        practical_id="P05",
        resources_unverified=["ec2-instance:i-123"],
    )
    assert res2.success is False

    res3 = CleanupResult(
        success=True,
        run_id="run-3",
        practical_id="P05",
        errors=["Database connection failed"],
    )
    assert res3.success is False

    # Fully successful cleanup without failures
    res4 = CleanupResult(
        success=True,
        run_id="run-4",
        practical_id="P05",
        resources_deleted=["s3-bucket:b1"],
        resources_absent=["dynamodb-table:tbl1"],
    )
    assert res4.success is True


# ==============================================================================
# 8. Region Resolution: AWS_REGION Takes Precedence over AWS_DEFAULT_REGION
# ==============================================================================


def test_resolve_region_priority_chain(monkeypatch):
    """Verify resolve_region applies the correct priority: explicit > AWS_REGION > AWS_DEFAULT_REGION > default."""
    from cloudprac.adapters.aws_client import resolve_region

    # 1. Explicit always wins
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    assert resolve_region("us-west-2") == "us-west-2"

    # 2. AWS_REGION beats AWS_DEFAULT_REGION
    assert resolve_region(None) == "eu-west-1"

    # 3. AWS_DEFAULT_REGION used when AWS_REGION is absent
    monkeypatch.delenv("AWS_REGION", raising=False)
    assert resolve_region(None) == "ap-south-1"

    # 4. Hard-coded fallback when neither env var is set
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    assert resolve_region(None) == "us-east-1"


def test_aws_adapter_picks_up_aws_region_env_var(monkeypatch):
    """AWSAdapter must read AWS_REGION (CloudShell default) not just AWS_DEFAULT_REGION."""
    monkeypatch.setenv("AWS_REGION", "ap-southeast-1")
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)

    from cloudprac.adapters.aws_client import AWSAdapter

    adapter = AWSAdapter()
    assert adapter.region == "ap-southeast-1"


# ==============================================================================
# 9. EC2 Subnet Selection Prefers MapPublicIpOnLaunch=True
# ==============================================================================


def test_get_default_or_first_vpc_prefers_public_subnet():
    """Verify get_default_or_first_vpc selects a subnet with MapPublicIpOnLaunch=True over a private one."""
    from cloudprac.practicals.p05.ec2 import get_default_or_first_vpc

    mock_ec2 = MagicMock()
    mock_ec2.describe_vpcs.return_value = {"Vpcs": [{"VpcId": "vpc-default"}]}
    mock_ec2.describe_subnets.return_value = {
        "Subnets": [
            {"SubnetId": "subnet-private", "MapPublicIpOnLaunch": False},
            {"SubnetId": "subnet-public", "MapPublicIpOnLaunch": True},
        ]
    }

    vpc_id, subnet_id = get_default_or_first_vpc(mock_ec2)
    assert vpc_id == "vpc-default"
    assert subnet_id == "subnet-public"


def test_get_default_or_first_vpc_fallback_to_private_subnet_when_no_public_subnet():
    """Verify fallback to first subnet when no public subnet is available (no error; caller must request IP explicitly)."""
    from cloudprac.practicals.p05.ec2 import get_default_or_first_vpc

    mock_ec2 = MagicMock()
    mock_ec2.describe_vpcs.return_value = {"Vpcs": [{"VpcId": "vpc-default"}]}
    mock_ec2.describe_subnets.return_value = {
        "Subnets": [
            {"SubnetId": "subnet-private-a", "MapPublicIpOnLaunch": False},
            {"SubnetId": "subnet-private-b", "MapPublicIpOnLaunch": False},
        ]
    }

    vpc_id, subnet_id = get_default_or_first_vpc(mock_ec2)
    # Falls back gracefully; first subnet chosen
    assert subnet_id == "subnet-private-a"


# ==============================================================================
# 10. launch_ec2_instance Uses AssociatePublicIpAddress=True via NetworkInterfaces
# ==============================================================================


def test_launch_ec2_instance_requests_public_ip_via_network_interface():
    """Verify that launch_ec2_instance passes AssociatePublicIpAddress=True on the primary network interface."""
    from cloudprac.practicals.p05.ec2 import launch_ec2_instance

    mock_ec2 = MagicMock()
    mock_ec2.run_instances.return_value = {"Instances": [{"InstanceId": "i-publicip123"}]}

    with patch("time.sleep", return_value=None):
        inst_id = launch_ec2_instance(
            ec2_client=mock_ec2,
            image_id="ami-abcdef",
            instance_type="t2.micro",
            subnet_id="subnet-private-xyz",
            security_group_id="sg-xyz",
        )

    assert inst_id == "i-publicip123"
    call_kwargs = mock_ec2.run_instances.call_args[1]
    net_ifaces = call_kwargs.get("NetworkInterfaces", [])
    assert len(net_ifaces) == 1
    primary = net_ifaces[0]
    assert primary["DeviceIndex"] == 0
    assert primary["AssociatePublicIpAddress"] is True
    assert primary["SubnetId"] == "subnet-private-xyz"
    assert "sg-xyz" in primary["Groups"]
    # SubnetId and SecurityGroupIds must NOT appear at top level when using NetworkInterfaces
    assert "SubnetId" not in call_kwargs
    assert "SecurityGroupIds" not in call_kwargs


# ==============================================================================
# 11. Termination Wait Loop Does Not Crash on Empty Reservations
# ==============================================================================


def test_cleanup_ec2_termination_wait_handles_empty_reservations():
    """Verify cleanup_ec2_resources handles DescribeInstances returning empty Reservations (instance gone) gracefully."""
    from cloudprac.practicals.p05.ec2 import cleanup_ec2_resources

    mock_ec2 = MagicMock()

    # Ownership check: instance present with correct tags
    ownership_desc = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "State": {"Name": "running"},
                        "Tags": [
                            {"Key": "ManagedBy", "Value": "CloudPrac"},
                            {"Key": "RunId", "Value": "run-termwait-001"},
                        ],
                    }
                ]
            }
        ]
    }
    # After terminate: first poll returns empty Reservations (instance gone)
    empty_desc = {"Reservations": []}

    mock_ec2.describe_instances.side_effect = [ownership_desc, empty_desc]
    mock_ec2.terminate_instances.return_value = {
        "TerminatingInstances": [{"InstanceId": "i-termwait"}]
    }

    with patch("time.sleep", return_value=None):
        deleted = cleanup_ec2_resources(
            ec2_client=mock_ec2,
            instance_id="i-termwait",
            expected_run_id="run-termwait-001",
        )

    assert "ec2-instance:i-termwait" in deleted
    # Must have called describe_instances exactly twice (ownership + first poll)
    assert mock_ec2.describe_instances.call_count == 2


# ==============================================================================
# 12. wait_for_instance_running: InvalidInstanceID.NotFound is Transient
# ==============================================================================


def test_wait_for_instance_running_retries_on_not_found_then_succeeds():
    """
    Regression test for the live failure:
      EC2 Error: InvalidInstanceID.NotFound when calling DescribeInstances:
      instance ID i-063d9c7acc316374d does not exist

    Root cause: DescribeInstances may return NotFound for up to ~30s after
    RunInstances completes (EC2 control-plane propagation).  The fix retries
    this specific error code instead of propagating it as a fatal exception.
    """
    from botocore.exceptions import ClientError as BotoCoreClientError

    from cloudprac.practicals.p05.ec2 import wait_for_instance_running

    mock_ec2 = MagicMock()

    not_found_error = BotoCoreClientError(
        {
            "Error": {
                "Code": "InvalidInstanceID.NotFound",
                "Message": "instance ID i-063d9c7acc316374d does not exist",
            }
        },
        "DescribeInstances",
    )
    running_response = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-063d9c7acc316374d",
                        "State": {"Name": "running"},
                        "PublicIpAddress": "54.200.10.25",
                    }
                ]
            }
        ]
    }

    # First two calls raise NotFound; third succeeds with running state
    mock_ec2.describe_instances.side_effect = [not_found_error, not_found_error, running_response]

    with patch("time.sleep", return_value=None):
        result = wait_for_instance_running(mock_ec2, "i-063d9c7acc316374d", max_timeout=60)

    assert result["State"]["Name"] == "running"
    assert result["PublicIpAddress"] == "54.200.10.25"
    assert mock_ec2.describe_instances.call_count == 3


def test_wait_for_instance_running_escalates_non_transient_client_error():
    """
    A ClientError that is NOT InvalidInstanceID.NotFound (e.g. AuthFailure) must
    be raised immediately — not silently swallowed or retried indefinitely.
    """
    from botocore.exceptions import ClientError as BotoCoreClientError

    from cloudprac.practicals.p05.ec2 import wait_for_instance_running

    mock_ec2 = MagicMock()
    auth_error = BotoCoreClientError(
        {"Error": {"Code": "AuthFailure", "Message": "Not authorised"}},
        "DescribeInstances",
    )
    mock_ec2.describe_instances.side_effect = auth_error

    with patch("time.sleep", return_value=None):
        with pytest.raises(RuntimeError, match="AuthFailure"):
            wait_for_instance_running(mock_ec2, "i-realinstance123", max_timeout=30)

    # Should stop after the first non-transient error, not exhaust the timeout
    assert mock_ec2.describe_instances.call_count == 1


def test_wait_for_instance_running_rejects_invalid_instance_id():
    """validate_instance_id check: empty or malformed IDs are rejected before any API call."""
    from cloudprac.practicals.p05.ec2 import wait_for_instance_running

    mock_ec2 = MagicMock()
    with pytest.raises(ValueError, match="invalid instance ID"):
        wait_for_instance_running(mock_ec2, "", max_timeout=10)

    with pytest.raises(ValueError, match="invalid instance ID"):
        wait_for_instance_running(mock_ec2, "not-an-id", max_timeout=10)

    mock_ec2.describe_instances.assert_not_called()


def test_launch_ec2_instance_raises_on_empty_instances_in_response():
    """RunInstances returning an empty Instances list must raise RuntimeError, not IndexError."""
    from cloudprac.practicals.p05.ec2 import launch_ec2_instance

    mock_ec2 = MagicMock()
    # AWS returns HTTP 200 but Instances list is empty (should never happen in practice
    # but we must not crash with an opaque IndexError)
    mock_ec2.run_instances.return_value = {"Instances": []}

    with patch("time.sleep", return_value=None):
        with pytest.raises(RuntimeError, match="no instance ID"):
            launch_ec2_instance(
                ec2_client=mock_ec2,
                image_id="ami-abc",
                instance_type="t2.micro",
                subnet_id="subnet-xyz",
                security_group_id="sg-xyz",
            )


def test_wait_for_instance_running_bounded_not_found_raises_diagnostic_error():
    """
    When DescribeInstances repeatedly fails with InvalidInstanceID.NotFound beyond
    max_not_found_attempts, wait_for_instance_running must fail with a clear diagnostic
    error detailing the instance ID, targeted region, account, and recovery guidance.
    """
    from botocore.exceptions import ClientError as BotoCoreClientError

    from cloudprac.practicals.p05.ec2 import wait_for_instance_running

    mock_ec2 = MagicMock()
    not_found_error = BotoCoreClientError(
        {
            "Error": {
                "Code": "InvalidInstanceID.NotFound",
                "Message": "The instance ID does not exist",
            }
        },
        "DescribeInstances",
    )
    mock_ec2.describe_instances.side_effect = not_found_error

    with patch("time.sleep", return_value=None):
        with pytest.raises(RuntimeError) as exc_info:
            wait_for_instance_running(
                mock_ec2,
                "i-063d9c7acc316374d",
                max_timeout=60,
                region="ap-south-1",
                account_id="123456789012",
                max_not_found_attempts=4,
            )

    err = str(exc_info.value)
    assert "i-063d9c7acc316374d" in err
    assert "ap-south-1" in err
    assert "123456789012" in err
    assert "does not exist in region 'ap-south-1'" in err
    assert "cloudprac cleanup P05" in err
    assert mock_ec2.describe_instances.call_count == 4


def test_wait_for_instance_running_timeout_never_found_raises_diagnostic_error():
    """
    When wait_for_instance_running times out without ever finding the instance,
    it must raise RuntimeError with diagnostic region and account context.
    """
    from botocore.exceptions import ClientError as BotoCoreClientError

    from cloudprac.practicals.p05.ec2 import wait_for_instance_running

    mock_ec2 = MagicMock()
    not_found_error = BotoCoreClientError(
        {
            "Error": {
                "Code": "InvalidInstanceID.NotFound",
                "Message": "The instance ID does not exist",
            }
        },
        "DescribeInstances",
    )
    mock_ec2.describe_instances.side_effect = not_found_error

    # Simulate timeout reached
    times = iter([0.0, 0.0, 5.0, 100.0])
    with patch("time.time", side_effect=lambda: next(times, 100.0)):
        with patch("time.sleep", return_value=None):
            with pytest.raises(RuntimeError) as exc_info:
                wait_for_instance_running(
                    mock_ec2,
                    "i-notfoundtimeout",
                    max_timeout=10,
                    region="eu-west-1",
                    account_id="999988887777",
                    max_not_found_attempts=20,
                )

    err = str(exc_info.value)
    assert "i-notfoundtimeout" in err
    assert "eu-west-1" in err
    assert "999988887777" in err
    assert "does not exist in region 'eu-west-1'" in err


def test_p05_execution_failure_persists_instance_to_manifest_and_allows_cleanup(tmp_path):
    """
    Regression test verifying requirement 4 & 6:
    When EC2 launch succeeds and returns an instance ID, but subsequent wait_for_instance_running
    fails, the manifest on disk MUST record the instance ID, and cleanup must be able to remove it.
    """
    from botocore.exceptions import ClientError as BotoCoreClientError

    from cloudprac.core.models import ExecutionPlan
    from cloudprac.practicals.p05.practical import P05Practical

    practical = P05Practical()
    practical.p05_config.app_cidr = "192.0.2.1/32"

    mock_adapter = MagicMock(spec=AWSAdapter)
    mock_adapter.mock_mode = False
    mock_adapter.region_name = "us-east-1"
    mock_adapter.get_caller_identity.return_value = {"Account": "123456789012"}

    mock_s3 = MagicMock()
    mock_dynamodb = MagicMock()
    mock_iam = MagicMock()
    mock_ec2 = MagicMock()

    mock_adapter.get_client.side_effect = lambda service, **kwargs: {
        "s3": mock_s3,
        "dynamodb": mock_dynamodb,
        "iam": mock_iam,
        "ec2": mock_ec2,
    }.get(service, MagicMock())

    # Mock DynamoDB active status
    mock_dynamodb.describe_table.return_value = {"Table": {"TableStatus": "ACTIVE"}}

    # Mock prerequisite steps
    mock_ec2.describe_subnets.return_value = {
        "Subnets": [{"SubnetId": "subnet-test123", "VpcId": "vpc-test123"}]
    }
    mock_ec2.create_security_group.return_value = {"GroupId": "sg-test123"}
    mock_ec2.describe_images.return_value = {"Images": [{"ImageId": "ami-test123"}]}
    mock_ec2.create_key_pair.return_value = {"KeyMaterial": "fake-key", "KeyName": "key-test"}
    mock_ec2.run_instances.return_value = {"Instances": [{"InstanceId": "i-manifestpersist"}]}

    # Fail wait_for_instance_running
    not_found_err = BotoCoreClientError(
        {"Error": {"Code": "InvalidInstanceID.NotFound", "Message": "Not found"}},
        "DescribeInstances",
    )
    mock_ec2.describe_instances.side_effect = not_found_err

    run_id = "test-persist-fail-001"
    plan = ExecutionPlan(
        practical_id="P05",
        run_id=run_id,
        aws_account_id="123456789012",
        aws_region="us-east-1",
        actions=[],
    )

    with patch("cloudprac.practicals.p05.practical.get_run_dir", return_value=tmp_path / run_id):
        with patch("cloudprac.practicals.p05.practical.save_restricted_file"):
            with patch("time.sleep", return_value=None):
                result = practical.execute(plan, mock_adapter)

    # 1. Execution must report failure
    assert result.success is False
    assert any("EC2 Error" in e for e in result.errors)

    # 2. Manifest on disk must contain the created EC2 instance ID
    manifest_file = tmp_path / run_id / "manifest.json"
    assert manifest_file.exists()
    manifest_content = manifest_file.read_text(encoding="utf-8")
    assert "i-manifestpersist" in manifest_content

    # 3. Cleanup must target that instance
    mock_ec2.terminate_instances.return_value = {
        "TerminatingInstances": [{"InstanceId": "i-manifestpersist"}]
    }
    ownership_desc = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "State": {"Name": "running"},
                        "Tags": [
                            {"Key": "ManagedBy", "Value": "CloudPrac"},
                            {"Key": "RunId", "Value": run_id},
                        ],
                    }
                ]
            }
        ]
    }
    # Reset mock_ec2 describe_instances for cleanup
    mock_ec2.describe_instances.side_effect = [ownership_desc, {"Reservations": []}]

    manifest_obj = RunManifest.model_validate_json(manifest_file.read_text(encoding="utf-8"))
    with patch("cloudprac.practicals.p05.practical.get_run_dir", return_value=tmp_path / run_id):
        with patch("time.sleep", return_value=None):
            cleanup_result = practical.cleanup(manifest_obj, mock_adapter)

    assert "ec2-instance:i-manifestpersist" in cleanup_result.resources_deleted


# ==============================================================================
# 13. Empty Reservations / Instances Handling in Cleanup and Public IP Polling
# ==============================================================================


def test_cleanup_ec2_handles_empty_reservations_when_already_absent_without_index_error(tmp_path):
    """
    Regression test for:
      Cleanup fails with 'list index out of range' when DescribeInstances returns
      empty Reservations (instance does not exist or was never created).
    """
    from cloudprac.adapters.aws_client import AWSAdapter
    from cloudprac.core.models import RunManifest, TrackedResource
    from cloudprac.practicals.p05.practical import P05Practical

    practical = P05Practical()
    mock_adapter = MagicMock(spec=AWSAdapter)
    mock_adapter.mock_mode = False
    mock_adapter.region_name = "ap-south-1"
    mock_adapter.get_caller_identity.return_value = {"Account": "123456789012"}

    mock_ec2 = MagicMock()
    mock_adapter.get_client.side_effect = lambda service, **kwargs: {
        "ec2": mock_ec2,
    }.get(service, MagicMock())

    run_id = "P05-20261010-183146-05faba"
    manifest = RunManifest(
        practical_id="P05",
        run_id=run_id,
        aws_region="ap-south-1",
        aws_account_id="1234****9012",
        resources=[
            TrackedResource(
                resource_type="ec2-instance",
                resource_id="i-05faba123456789ab",
                resource_name=f"cloudprac-p05-app-{run_id}",
            )
        ],
    )

    # DescribeInstances returns empty Reservations (instance absent)
    mock_ec2.describe_instances.return_value = {"Reservations": []}

    with patch("cloudprac.practicals.p05.practical.get_run_dir", return_value=tmp_path / run_id):
        with patch("time.sleep", return_value=None):
            result = practical.cleanup(manifest, mock_adapter)

    # Must NOT crash with IndexError: list index out of range
    assert result.success is True
    assert "ec2-instance:i-05faba123456789ab" in result.resources_absent
    assert len(result.errors) == 0


def test_wait_for_instance_running_extracts_public_ip_from_network_interfaces():
    """
    When top-level PublicIpAddress is missing or empty, wait_for_instance_running
    must extract the public IP from NetworkInterfaces[0].Association.PublicIp.
    """
    from cloudprac.practicals.p05.ec2 import wait_for_instance_running

    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-eniip123",
                        "State": {"Name": "running"},
                        "PublicIpAddress": "",  # Empty top-level
                        "NetworkInterfaces": [
                            {
                                "DeviceIndex": 0,
                                "Association": {
                                    "PublicIp": "13.235.45.67",
                                },
                            }
                        ],
                    }
                ]
            }
        ]
    }

    with patch("time.sleep", return_value=None):
        instance = wait_for_instance_running(mock_ec2, "i-eniip123", max_timeout=30)

    assert instance["PublicIpAddress"] == "13.235.45.67"


def test_wait_for_instance_running_polls_until_public_ip_assigned():
    """
    When require_public_ip=True, wait_for_instance_running must poll through
    'running without IP' until the public IP appears.
    """
    from cloudprac.practicals.p05.ec2 import wait_for_instance_running

    mock_ec2 = MagicMock()
    # Cycle 1: running but no IP yet
    cycle1 = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-delayedip",
                        "State": {"Name": "running"},
                        "PublicIpAddress": None,
                    }
                ]
            }
        ]
    }
    # Cycle 2: running with public IP populated
    cycle2 = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-delayedip",
                        "State": {"Name": "running"},
                        "PublicIpAddress": "13.235.99.11",
                    }
                ]
            }
        ]
    }
    mock_ec2.describe_instances.side_effect = [cycle1, cycle2]

    with patch("time.sleep", return_value=None):
        instance = wait_for_instance_running(
            mock_ec2,
            "i-delayedip",
            max_timeout=30,
            require_public_ip=True,
        )

    assert instance["PublicIpAddress"] == "13.235.99.11"
    assert mock_ec2.describe_instances.call_count == 2


def test_p05_includes_name_tag_and_respects_aws_region_env(monkeypatch, tmp_path):
    """
    Verify that P05:
    1. Resolves region from AWS_REGION (e.g. ap-south-1 in CloudShell) rather than default us-east-1.
    2. Tags the EC2 instance with 'Name': 'cloudprac-p05-app-<clean_run>' so it matches console filters.
    """
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)

    from cloudprac.adapters.aws_client import AWSAdapter
    from cloudprac.practicals.p05.practical import P05Practical
    from cloudprac.utils.config import CloudPracConfig

    config = CloudPracConfig()
    practical = P05Practical()
    practical.p05_config.app_cidr = "192.0.2.1/32"

    # 1. Plan must resolve to ap-south-1
    plan = practical.plan(config, "test-mumbai-001")
    assert plan.aws_region == "ap-south-1"

    # 2. Execution must tag with Name and use ap-south-1
    mock_adapter = MagicMock(spec=AWSAdapter)
    mock_adapter.mock_mode = False
    mock_adapter.region_name = "ap-south-1"
    mock_adapter.get_caller_identity.return_value = {"Account": "123456789012"}

    mock_s3 = MagicMock()
    mock_dynamodb = MagicMock()
    mock_iam = MagicMock()
    mock_ec2 = MagicMock()

    mock_adapter.get_client.side_effect = lambda service, **kwargs: {
        "s3": mock_s3,
        "dynamodb": mock_dynamodb,
        "iam": mock_iam,
        "ec2": mock_ec2,
    }.get(service, MagicMock())

    mock_dynamodb.describe_table.return_value = {"Table": {"TableStatus": "ACTIVE"}}
    mock_ec2.describe_subnets.return_value = {
        "Subnets": [{"SubnetId": "subnet-mumbai", "VpcId": "vpc-mumbai"}]
    }
    mock_ec2.create_security_group.return_value = {"GroupId": "sg-mumbai"}
    mock_ec2.describe_images.return_value = {"Images": [{"ImageId": "ami-mumbai"}]}
    mock_ec2.create_key_pair.return_value = {"KeyMaterial": "fake", "KeyName": "key-mumbai"}
    mock_ec2.run_instances.return_value = {"Instances": [{"InstanceId": "i-mumbai123"}]}
    mock_ec2.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-mumbai123",
                        "State": {"Name": "running"},
                        "PublicIpAddress": "13.235.1.2",
                    }
                ]
            }
        ]
    }

    with patch(
        "cloudprac.practicals.p05.practical.get_run_dir", return_value=tmp_path / "test-mumbai-001"
    ):
        with patch("cloudprac.practicals.p05.practical.save_restricted_file"):
            with patch(
                "cloudprac.practicals.p05.practical.check_application_health",
                return_value=(True, "OK"),
            ):
                with patch("time.sleep", return_value=None):
                    result = practical.execute(plan, mock_adapter)

    assert result.success is True
    # Confirm RunInstances received Name tag
    call_kwargs = mock_ec2.run_instances.call_args[1]
    tag_specs = call_kwargs.get("TagSpecifications", [])
    instance_tags = next(
        (ts["Tags"] for ts in tag_specs if ts.get("ResourceType") == "instance"), []
    )
    name_tag = next((t["Value"] for t in instance_tags if t.get("Key") == "Name"), None)
    assert name_tag is not None
    assert "cloudprac-p05-app-" in name_tag
