"""Unit tests for AWS adapter and preflight checks in mock mode."""

from cloudprac.adapters.aws_client import AWSAdapter, mask_account_id
from cloudprac.adapters.preflight import run_preflight_checks


def test_mask_account_id():
    """Verify masking behaves properly."""
    assert mask_account_id("123456789012") == "1234****9012"
    assert mask_account_id("987654321098") == "9876****1098"
    assert mask_account_id("123") == "********"


def test_mock_caller_identity():
    """Verify mock mode yields offline identity safely without hitting STS."""
    adapter = AWSAdapter(mock_mode=True)
    identity = adapter.get_caller_identity()
    assert identity["IsMock"] is True
    assert identity["Account"] == "123456789012"
    assert "user/cloudprac-student" in identity["Arn"]


def test_preflight_in_mock_mode():
    """Verify preflight completes successfully in mock environment."""
    adapter = AWSAdapter(mock_mode=True)
    report = run_preflight_checks(adapter)
    assert report.all_passed is True
    assert len(report.checks) >= 5
