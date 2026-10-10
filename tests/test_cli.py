"""Unit tests for CloudPrac CLI command parsing and output."""

import pytest
from typer.testing import CliRunner

from cloudprac.cli.main import app

runner = CliRunner()


def test_cli_version():
    """Verify cloudprac --version displays the expected version."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "CloudPrac version 0.1.0" in result.output


def test_cli_list_contains_all_placeholders():
    """Verify cloudprac list displays P01 through P08 as NOT CONFIGURED."""
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    for i in range(1, 9):
        assert f"P{i:02d}" in result.output
    assert "NOT CONFIGURED" in result.output


def test_cli_inspect_p01():
    """Verify cloudprac inspect P01 details."""
    result = runner.invoke(app, ["inspect", "P01"])
    assert result.exit_code == 0
    assert "Module ID: P01" in result.output
    assert "NOT CONFIGURED" in result.output
    assert "Prerequisites" in result.output


def test_cli_inspect_invalid():
    """Verify cloudprac inspect returns error on invalid ID."""
    result = runner.invoke(app, ["inspect", "P99"])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_cli_plan_unconfigured_blocks_safely():
    """Verify cloudprac plan safely aborts on unconfigured practicals."""
    result = runner.invoke(app, ["plan", "P01"])
    assert result.exit_code == 1
    assert "NOT CONFIGURED" in result.output
    assert "Accidental AWS resource creation was safely prevented" in result.output


def test_cli_run_unconfigured_blocks_safely():
    """Verify cloudprac run safely aborts on unconfigured practicals."""
    result = runner.invoke(app, ["run", "P01"])
    assert result.exit_code == 1
    assert "NOT CONFIGURED" in result.output
    assert "Execution is locked to prevent creating unintentional AWS resources" in result.output


def test_cli_verify_unconfigured_blocks_safely():
    """Verify cloudprac verify safely aborts on unconfigured practicals."""
    result = runner.invoke(app, ["verify", "P01"])
    assert result.exit_code == 1
    assert "NOT CONFIGURED" in result.output


def test_cli_cleanup_unconfigured_blocks_safely():
    """Verify cloudprac cleanup safely aborts on unconfigured practicals."""
    result = runner.invoke(app, ["cleanup", "P01", "--run-id", "test-run"])
    assert result.exit_code == 1
    assert "NOT CONFIGURED" in result.output


def test_cli_preflight():
    """Verify cloudprac preflight runs diagnostics in mock mode."""
    result = runner.invoke(app, ["preflight"])
    assert result.exit_code == 0
    assert "Environment Preflight Diagnostics" in result.output
    assert "PASS" in result.output
