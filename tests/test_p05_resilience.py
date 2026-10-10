"""Resilience, partial failure, delayed readiness, and cleanup tests for P05."""

import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from cloudprac.adapters.aws_client import AWSAdapter
from cloudprac.core.models import RunManifest, TrackedResource
from cloudprac.practicals.p05.dynamodb import cleanup_dynamodb_resources
from cloudprac.practicals.p05.ec2 import (
    build_user_data_script,
    check_application_health,
    cleanup_ec2_resources,
    wait_for_instance_running,
)
from cloudprac.practicals.p05.iam import cleanup_iam_resources
from cloudprac.practicals.p05.practical import P05Practical
from cloudprac.practicals.p05.s3 import cleanup_s3_resources
from cloudprac.utils.config import CloudPracConfig
from cloudprac.utils.paths import get_run_dir

# ==============================================================================
# 1. Failed Bootstrap Tests
# ==============================================================================


def test_failed_bootstrap_instance_terminates():
    """Verify wait_for_instance_running raises RuntimeError if instance terminates during bootstrap."""
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-failedbootstrap123",
                        "State": {"Name": "terminated"},
                    }
                ]
            }
        ]
    }

    with pytest.raises(RuntimeError) as exc_info:
        wait_for_instance_running(mock_ec2, "i-failedbootstrap123", max_timeout=10)

    assert "unexpectedly entered 'terminated' state" in str(exc_info.value)


def test_failed_bootstrap_health_check_times_out():
    """Verify check_application_health returns False when Gunicorn / user-data fails to start."""
    with patch("urllib.request.urlopen", side_effect=OSError("Connection refused")):
        healthy, msg = check_application_health("198.51.100.10", app_port=5000, max_timeout=1, poll_interval=1)

    assert healthy is False
    assert "did not respond with HTTP 200" in msg
    assert "bootstrap script or application service may still be installing dependencies" in msg


def test_failed_bootstrap_invalid_user_data_fails_closed():
    """Verify build_user_data_script fails closed if plaintext token is passed or S3 key is missing."""
    with pytest.raises(ValueError, match="Embedding admin_token directly in user-data is prohibited"):
        build_user_data_script(
            table_name="tbl",
            bucket_name="bkt",
            region="us-east-1",
            admin_token="insecure-plaintext-token",
        )

    with pytest.raises(ValueError, match="A secure secret delivery path"):
        build_user_data_script(
            table_name="tbl",
            bucket_name="bkt",
            region="us-east-1",
            token_s3_key="",
        )


# ==============================================================================
# 2. Delayed Readiness Tests
# ==============================================================================


def test_delayed_readiness_instance_polling():
    """Verify wait_for_instance_running polls through 'pending' states until 'running'."""
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.side_effect = [
        {"Reservations": [{"Instances": [{"InstanceId": "i-delay1", "State": {"Name": "pending"}}]}]},
        {"Reservations": [{"Instances": [{"InstanceId": "i-delay1", "State": {"Name": "pending"}}]}]},
        {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-delay1",
                            "State": {"Name": "running"},
                            "PublicIpAddress": "198.51.100.77",
                        }
                    ]
                }
            ]
        },
    ]

    with patch("time.sleep", return_value=None):
        instance = wait_for_instance_running(mock_ec2, "i-delay1", max_timeout=30)

    assert instance["State"]["Name"] == "running"
    assert instance["PublicIpAddress"] == "198.51.100.77"
    assert mock_ec2.describe_instances.call_count == 3


def test_delayed_readiness_health_polling():
    """Verify check_application_health retries through temporary errors until HTTP 200 OK."""
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = b'{"status":"healthy"}'
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", side_effect=[OSError("Connection refused"), OSError("Service Unavailable"), mock_response]):
        with patch("time.sleep", return_value=None):
            healthy, msg = check_application_health("198.51.100.77", app_port=5000, max_timeout=30, poll_interval=1)

    assert healthy is True
    assert "Application healthy (HTTP 200)" in msg


# ==============================================================================
# 3. Interrupted Provisioning Tests
# ==============================================================================


def test_interrupted_provisioning_partial_manifest_saved(tmp_path, monkeypatch):
    """Verify checkpointed manifest is written to disk when EC2 launch fails after S3 and DynamoDB creation."""
    monkeypatch.setenv("CLOUDPRAC_HOME", str(tmp_path))

    p05 = P05Practical()
    p05.p05_config.app_cidr = "198.51.100.1/32"

    mock_s3 = MagicMock()
    mock_dynamodb = MagicMock()
    mock_iam = MagicMock()
    mock_ec2 = MagicMock()
    mock_ssm = MagicMock()

    # S3 succeeds
    mock_s3.create_bucket.return_value = {}
    mock_s3.put_public_access_block.return_value = {}
    mock_s3.put_bucket_encryption.return_value = {}
    mock_s3.put_bucket_policy.return_value = {}
    mock_s3.put_object.return_value = {}

    # DynamoDB succeeds
    mock_dynamodb.create_table.return_value = {"TableDescription": {"TableStatus": "CREATING"}}
    mock_dynamodb.describe_table.return_value = {"Table": {"TableStatus": "ACTIVE", "TableArn": "arn:aws:dynamodb:us-east-1:123:table/tbl"}}
    mock_dynamodb.batch_write_item.return_value = {}

    # IAM succeeds
    mock_iam.create_role.return_value = {}
    mock_iam.put_role_policy.return_value = {}
    mock_iam.create_instance_profile.return_value = {}
    mock_iam.add_role_to_instance_profile.return_value = {}

    # EC2 fails on run_instances
    mock_ec2.describe_vpcs.return_value = {"Vpcs": [{"VpcId": "vpc-test"}]}
    mock_ec2.describe_subnets.return_value = {"Subnets": [{"SubnetId": "subnet-test"}]}
    mock_ec2.describe_images.return_value = {"Images": [{"ImageId": "ami-12345678", "CreationDate": "2026-01-01"}]}
    mock_ec2.create_security_group.return_value = {"GroupId": "sg-test1234"}
    mock_ec2.authorize_security_group_ingress.return_value = {}
    mock_ec2.create_key_pair.return_value = {"KeyMaterial": "fake-pem"}
    mock_ec2.run_instances.side_effect = ClientError(
        {"Error": {"Code": "InsufficientInstanceCapacity", "Message": "Out of t2.micro capacity"}},
        "RunInstances",
    )

    adapter = AWSAdapter(region_name="us-east-1", mock_mode=False)
    adapter.get_caller_identity = MagicMock(return_value={"Account": "123456789012"})

    def mock_get_client(service, region_name=None):
        clients = {
            "s3": mock_s3,
            "dynamodb": mock_dynamodb,
            "iam": mock_iam,
            "ec2": mock_ec2,
            "ssm": mock_ssm,
        }
        return clients[service]

    adapter.get_client = mock_get_client

    plan = p05.plan(CloudPracConfig(), run_id="run-interrupted-001")
    result = p05.execute(plan, adapter)

    # Execution failed
    assert result.success is False
    assert any("InsufficientInstanceCapacity" in e for e in result.errors)

    # Checkpoint manifest exists on disk and contains S3 and DynamoDB resources
    run_dir = get_run_dir("run-interrupted-001")
    manifest_file = run_dir / "manifest.json"
    assert manifest_file.is_file()

    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    resource_types = [r["resource_type"] for r in manifest_data["resources"]]
    assert "s3-bucket" in resource_types
    assert "dynamodb-table" in resource_types
    assert "iam-instance-profile" in resource_types
    assert "security-group" in resource_types
    assert "ec2-instance" not in resource_types


# ==============================================================================
# 4. Resources Left Behind After Partial Failure Cleanup
# ==============================================================================


def test_resources_left_behind_after_partial_failure_cleanup():
    """Verify cleanup destroys all partial resources left behind when EC2 failed, without error on missing resources."""
    p05 = P05Practical()

    # Manifest with only S3, DynamoDB, and IAM resources (no EC2 instance)
    partial_manifest = RunManifest(
        practical_id="P05",
        run_id="run-leftbehind-001",
        aws_account_id="1234****9012",
        aws_region="us-east-1",
        resources=[
            TrackedResource(
                resource_type="s3-bucket",
                resource_id="leftbehind-bucket",
                resource_name="leftbehind-bucket",
            ),
            TrackedResource(
                resource_type="dynamodb-table",
                resource_id="leftbehind-table",
                resource_name="leftbehind-table",
            ),
            TrackedResource(
                resource_type="iam-instance-profile",
                resource_id="leftbehind-prof",
                resource_name="leftbehind-prof",
            ),
            TrackedResource(
                resource_type="iam-role",
                resource_id="leftbehind-role",
                resource_name="leftbehind-role",
            ),
        ],
    )

    mock_s3 = MagicMock()
    mock_dynamodb = MagicMock()
    mock_iam = MagicMock()
    mock_ec2 = MagicMock()

    # S3 ownership and deletion
    mock_s3.get_bucket_tagging.return_value = {
        "TagSet": [{"Key": "ManagedBy", "Value": "CloudPrac"}, {"Key": "RunId", "Value": "run-leftbehind-001"}]
    }
    mock_s3.list_objects_v2.return_value = {"Contents": []}
    mock_s3.delete_bucket.return_value = {}

    # DynamoDB ownership and deletion
    mock_dynamodb.describe_table.return_value = {
        "Table": {"TableArn": "arn:aws:dynamodb:us-east-1:123456789012:table/leftbehind-table"}
    }
    mock_dynamodb.list_tags_of_resource.return_value = {
        "Tags": [{"Key": "ManagedBy", "Value": "CloudPrac"}, {"Key": "RunId", "Value": "run-leftbehind-001"}]
    }
    mock_dynamodb.delete_table.return_value = {}

    # IAM ownership and deletion
    mock_iam.get_instance_profile.return_value = {
        "InstanceProfile": {
            "InstanceProfileName": "leftbehind-prof",
            "Tags": [{"Key": "ManagedBy", "Value": "CloudPrac"}, {"Key": "RunId", "Value": "run-leftbehind-001"}],
            "Roles": [],
        }
    }
    mock_iam.delete_instance_profile.return_value = {}
    mock_iam.list_role_tags.return_value = {
        "Tags": [{"Key": "ManagedBy", "Value": "CloudPrac"}, {"Key": "RunId", "Value": "run-leftbehind-001"}]
    }
    mock_iam.list_role_policies.return_value = {"PolicyNames": []}
    mock_iam.delete_role.return_value = {}

    adapter = AWSAdapter(region_name="us-east-1", mock_mode=False)
    adapter.get_caller_identity = MagicMock(return_value={"Account": "123456789012"})

    def mock_get_client(service, region_name=None):
        return {"s3": mock_s3, "dynamodb": mock_dynamodb, "iam": mock_iam, "ec2": mock_ec2}[service]

    adapter.get_client = mock_get_client

    cleanup_res = p05.cleanup(partial_manifest, adapter)

    assert cleanup_res.success is True
    assert "s3-bucket:leftbehind-bucket" in cleanup_res.resources_deleted
    assert "dynamodb-table:leftbehind-table" in cleanup_res.resources_deleted
    assert "iam-instance-profile:leftbehind-prof" in cleanup_res.resources_deleted
    assert "iam-role:leftbehind-role" in cleanup_res.resources_deleted


# ==============================================================================
# 5. Repeated Cleanup Idempotency Tests
# ==============================================================================


def test_repeated_cleanup_idempotency():
    """Verify executing cleanup on already-deleted resources returns success without error."""
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.side_effect = ClientError(
        {"Error": {"Code": "InvalidInstanceID.NotFound", "Message": "Instance does not exist"}},
        "DescribeInstances",
    )
    mock_ec2.describe_security_groups.side_effect = ClientError(
        {"Error": {"Code": "InvalidGroup.NotFound", "Message": "Security group does not exist"}},
        "DescribeSecurityGroups",
    )
    mock_ec2.describe_key_pairs.side_effect = ClientError(
        {"Error": {"Code": "InvalidKeyPair.NotFound", "Message": "Key pair does not exist"}},
        "DescribeKeyPairs",
    )

    mock_s3 = MagicMock()
    mock_s3.get_bucket_tagging.side_effect = ClientError(
        {"Error": {"Code": "NoSuchBucket", "Message": "Bucket does not exist"}},
        "GetBucketTagging",
    )

    mock_dynamodb = MagicMock()
    mock_dynamodb.describe_table.side_effect = ClientError(
        {"Error": {"Code": "ResourceNotFoundException", "Message": "Table does not exist"}},
        "DescribeTable",
    )

    mock_iam = MagicMock()
    mock_iam.get_instance_profile.side_effect = ClientError(
        {"Error": {"Code": "NoSuchEntity", "Message": "Instance profile does not exist"}},
        "GetInstanceProfile",
    )
    mock_iam.list_role_tags.side_effect = ClientError(
        {"Error": {"Code": "NoSuchEntity", "Message": "Role does not exist"}},
        "ListRoleTags",
    )

    # Repeated calls return cleanly without unhandled exceptions
    del_ec2 = cleanup_ec2_resources(mock_ec2, instance_id="i-gone", security_group_id="sg-gone", key_name="key-gone", expected_run_id="run-1")
    assert del_ec2 == []

    del_s3 = cleanup_s3_resources(mock_s3, bucket_name="bucket-gone", expected_run_id="run-1")
    assert del_s3 == []

    del_dynamo = cleanup_dynamodb_resources(mock_dynamodb, table_name="table-gone", expected_run_id="run-1")
    assert del_dynamo == []

    del_iam = cleanup_iam_resources(mock_iam, profile_name="prof-gone", role_name="role-gone", expected_run_id="run-1")
    assert del_iam == []


# ==============================================================================
# 6. Explicit Region Alignment Tests
# ==============================================================================


def test_plan_and_runtime_explicit_region_alignment():
    """Verify that execution plan, runtime provisioning, manifest, and cleaner align on the explicit region."""
    p05 = P05Practical()
    custom_region = "eu-west-1"
    p05.p05_config.region = custom_region

    config = CloudPracConfig()
    plan = p05.plan(config, "run-region-test")

    # 1. Plan uses the explicit region
    assert plan.aws_region == custom_region

    # 2. Mock execute receives and honors plan.aws_region
    adapter = AWSAdapter(region_name=custom_region, mock_mode=True)
    res = p05.execute(plan, adapter)

    assert res.manifest is not None
    assert res.manifest.aws_region == custom_region
    assert res.outputs.get("app_url") == f"http://198.51.100.25:{p05.p05_config.app_port}"

    # 3. Cleaner verifies region match
    cleanup_res = p05.cleanup(res.manifest, adapter)
    assert cleanup_res.success is True
