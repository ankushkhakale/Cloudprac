"""Unit and integration tests for interactive TUI menu, IP detection, demonstration guide, and run discovery."""

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cloudprac.adapters.preflight import detect_public_ip
from cloudprac.cli.main import app
from cloudprac.cli.menu import interactive_menu
from cloudprac.cli.ui import print_p05_demonstration_guide
from cloudprac.utils.paths import list_all_runs

runner = CliRunner()


def test_detect_public_ip_success():
    """Verify detect_public_ip extracts public IPv4 and appends /32."""
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = b"54.239.28.85\n"
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = detect_public_ip(timeout=1.0)
        assert res == "54.239.28.85/32"


def test_detect_public_ip_rejects_private_or_loopback():
    """Verify detect_public_ip rejects RFC1918 private or loopback IPs."""
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = b"127.0.0.1\n"
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = detect_public_ip(timeout=1.0)
        assert res is None


def test_detect_public_ip_handles_network_timeout():
    """Verify detect_public_ip returns None on connection error without raising."""
    with patch("urllib.request.urlopen", side_effect=TimeoutError("Request timed out")):
        res = detect_public_ip(timeout=0.1)
        assert res is None


def test_list_all_runs_discovery(tmp_path: Path, monkeypatch):
    """Verify list_all_runs parses manifest files from ~/.cloudprac/runs/."""
    monkeypatch.setenv("CLOUDPRAC_HOME", str(tmp_path))
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True)

    # Run 1: valid manifest
    run1 = runs_dir / "P05-run-001"
    run1.mkdir()
    (run1 / "manifest.json").write_text(
        '{"run_id":"P05-run-001","practical_id":"P05","started_at":"2026-10-10T12:00:00Z","resources":[{"resource_id":"i-1"}]}',
        encoding="utf-8",
    )

    # Run 2: valid manifest
    run2 = runs_dir / "P05-run-002"
    run2.mkdir()
    (run2 / "manifest.json").write_text(
        '{"run_id":"P05-run-002","practical_id":"P05","started_at":"2026-10-10T14:00:00Z","resources":[{"resource_id":"i-2"},{"resource_id":"s3-1"}]}',
        encoding="utf-8",
    )

    discovered = list_all_runs()
    assert len(discovered) == 2
    # Should be sorted newest first (run2 then run1)
    assert discovered[0]["run_id"] == "P05-run-002"
    assert discovered[0]["resource_count"] == 2
    assert discovered[1]["run_id"] == "P05-run-001"
    assert discovered[1]["resource_count"] == 1


def test_print_p05_demonstration_guide_content():
    """Verify print_p05_demonstration_guide renders all essential demonstration instructions."""
    from rich.console import Console

    buffer = io.StringIO()
    test_console = Console(file=buffer, color_system=None)

    with patch("cloudprac.cli.ui.console", test_console):
        print_p05_demonstration_guide(
            run_id="test-run-123",
            public_ip="198.51.100.50",
            app_port=5000,
            token_file_path="/tmp/test_token",
        )

    output = buffer.getvalue()
    assert "Student Lab Demonstration Guide" in output
    assert "http://198.51.100.50:5000" in output
    assert "curl -s http://198.51.100.50:5000/health" in output
    assert "curl -s http://198.51.100.50:5000/api/students" in output
    assert "Admin tokens must NEVER be sent" in output
    assert "Method A" in output
    assert "Method B" in output
    assert "http://127.0.0.1:5000/api/students" in output
    assert "http://198.51.100.50:5000/api/students -H \"X-Admin-Token:" not in output

    assert "cloudprac report P05 --run-id test-run-123" in output
    assert "cloudprac cleanup P05 --run-id test-run-123" in output



def test_cli_run_p05_presents_demonstration_guide_in_mock_mode(monkeypatch):
    """Verify cloudprac run P05 --yes outputs demonstration guide upon completion."""
    monkeypatch.setenv("CLOUDPRAC_MOCK_AWS", "1")
    result = runner.invoke(app, ["run", "P05", "--yes"])
    assert result.exit_code == 0
    assert "Practical P05 executed successfully" in result.output
    assert "Student Lab Demonstration Guide" in result.output
    assert "curl -s http://198.51.100.25:5000/health" in result.output
    assert "cloudprac cleanup P05 --run-id" in result.output


def test_interactive_menu_exit_option():
    """Verify menu option 0 exits cleanly."""
    with patch("rich.prompt.Prompt.ask", return_value="0"):
        interactive_menu()


def test_interactive_menu_list_and_exit():
    """Verify menu option 6 lists practicals and then option 0 exits."""
    responses = ["6", "0"]
    with patch("rich.prompt.Prompt.ask", side_effect=responses):
        interactive_menu()
