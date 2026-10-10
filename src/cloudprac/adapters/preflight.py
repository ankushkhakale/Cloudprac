"""Preflight environment checks for AWS CloudShell and local execution."""

import os
import shutil
import subprocess
import sys
from typing import List, Optional

from pydantic import BaseModel, Field

from cloudprac.adapters.aws_client import AWSAdapter, mask_account_id
from cloudprac.utils.paths import get_cloudprac_home


class PreflightCheckItem(BaseModel):
    """Result of an individual environment preflight check."""

    name: str
    description: str
    passed: bool
    details: str
    is_critical: bool = True


class PreflightReport(BaseModel):
    """Aggregate preflight health report."""

    all_passed: bool
    is_cloudshell: bool
    checks: List[PreflightCheckItem] = Field(default_factory=list)


def check_python_version() -> PreflightCheckItem:
    """Verify runtime Python meets requirements."""
    version = sys.version_info
    passed = version >= (3, 10)
    details = f"Python {version.major}.{version.minor}.{version.micro}"
    return PreflightCheckItem(
        name="Python Version",
        description="Python 3.10 or newer runtime required",
        passed=passed,
        details=details,
        is_critical=True,
    )


def check_aws_cli() -> PreflightCheckItem:
    """Check for AWS CLI installation and accessibility."""
    cli_path = shutil.which("aws")
    if not cli_path:
        return PreflightCheckItem(
            name="AWS CLI",
            description="Official AWS CLI v2 installation",
            passed=False,
            details="AWS CLI not found in PATH",
            is_critical=False,
        )

    try:
        res = subprocess.run(
            [cli_path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        version_str = (res.stdout or res.stderr).strip().splitlines()[0]
        return PreflightCheckItem(
            name="AWS CLI",
            description="Official AWS CLI v2 installation",
            passed=True,
            details=f"Found: {version_str}",
            is_critical=False,
        )
    except Exception as e:
        return PreflightCheckItem(
            name="AWS CLI",
            description="Official AWS CLI v2 installation",
            passed=False,
            details=f"Error executing AWS CLI: {e}",
            is_critical=False,
        )


def check_aws_credentials(adapter: AWSAdapter) -> PreflightCheckItem:
    """Check whether ambient AWS credentials can authenticate with STS."""
    identity = adapter.get_caller_identity()
    if identity.get("IsMock"):
        return PreflightCheckItem(
            name="AWS Identity & STS",
            description="Authentication via ambient CloudShell/IAM credentials",
            passed=True,
            details="Running in Mock/Dry-Run Mode (Test ARN)",
            is_critical=True,
        )

    account = identity.get("Account")
    if account and account != "unavailable":
        masked = mask_account_id(account)
        arn = identity.get("Arn", "unknown")
        return PreflightCheckItem(
            name="AWS Identity & STS",
            description="Authentication via ambient CloudShell/IAM credentials",
            passed=True,
            details=f"Authenticated as {arn} (Account: {masked})",
            is_critical=True,
        )

    err = identity.get("Error", "No credentials found")
    return PreflightCheckItem(
        name="AWS Identity & STS",
        description="Authentication via ambient CloudShell/IAM credentials",
        passed=False,
        details=f"Authentication failed: {err}",
        is_critical=True,
    )


def check_aws_region(adapter: AWSAdapter) -> PreflightCheckItem:
    """Verify target AWS region is specified."""
    region = adapter.region
    passed = bool(region and len(region) >= 4)
    return PreflightCheckItem(
        name="AWS Region",
        description="Target AWS Region configuration",
        passed=passed,
        details=f"Region: {region}" if passed else "No valid AWS region configured",
        is_critical=True,
    )


def check_storage_access() -> PreflightCheckItem:
    """Verify write access to local CloudPrac storage directory."""
    home = get_cloudprac_home()
    try:
        home.mkdir(parents=True, exist_ok=True)
        test_file = home / ".write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        return PreflightCheckItem(
            name="CloudPrac Storage",
            description="Filesystem access to ~/.cloudprac/",
            passed=True,
            details=f"Writable at {home}",
            is_critical=True,
        )
    except Exception as e:
        return PreflightCheckItem(
            name="CloudPrac Storage",
            description="Filesystem access to ~/.cloudprac/",
            passed=False,
            details=f"Cannot write to {home}: {e}",
            is_critical=True,
        )


def is_running_in_cloudshell() -> bool:
    """Detect if current runtime environment is AWS CloudShell."""
    if "AWS_EXECUTION_ENV" in os.environ and "CloudShell" in os.environ["AWS_EXECUTION_ENV"]:
        return True
    if os.environ.get("CLOUDSHELL") == "true":
        return True
    # Check for standard AWS CloudShell user home or markers
    if os.path.exists("/usr/bin/cloudshell-main") or os.environ.get("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI"):
        return True
    return False


def detect_public_ip(timeout: float = 2.0) -> Optional[str]:
    """Detect current public/egress IP via AWS checkip or fallback service.

    Returns a '/32' CIDR string if detected, or None if offline or unreachable.
    """
    import ipaddress
    import urllib.request

    endpoints = [
        "https://checkip.amazonaws.com",
        "https://api.ipify.org",
    ]
    for url in endpoints:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "CloudPrac/Preflight"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    raw_ip = resp.read().decode("utf-8").strip()
                    parsed = ipaddress.ip_address(raw_ip)
                    if isinstance(parsed, ipaddress.IPv4Address) and not parsed.is_private and not parsed.is_loopback:
                        return f"{raw_ip}/32"
        except Exception:
            continue
    return None


def run_preflight_checks(adapter: Optional[AWSAdapter] = None) -> PreflightReport:
    """Execute all preflight environment diagnostics."""
    act_adapter = adapter or AWSAdapter()
    checks: List[PreflightCheckItem] = [
        check_python_version(),
        check_aws_cli(),
        check_aws_credentials(act_adapter),
        check_aws_region(act_adapter),
        check_storage_access(),
    ]

    all_passed = all(c.passed for c in checks if c.is_critical)
    cloudshell = is_running_in_cloudshell()

    return PreflightReport(
        all_passed=all_passed,
        is_cloudshell=cloudshell,
        checks=checks,
    )
