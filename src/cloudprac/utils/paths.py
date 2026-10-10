"""Path resolution and directory management for CloudPrac."""

import os
from pathlib import Path

ENV_CLOUDPRAC_HOME = "CLOUDPRAC_HOME"


def get_cloudprac_home() -> Path:
    """Return the base directory for CloudPrac storage (~/.cloudprac or $CLOUDPRAC_HOME)."""
    custom_home = os.environ.get(ENV_CLOUDPRAC_HOME)
    if custom_home:
        return Path(custom_home).expanduser().resolve()
    return (Path.home() / ".cloudprac").resolve()


def get_config_path() -> Path:
    """Return path to global configuration file."""
    return get_cloudprac_home() / "config.yaml"


def get_logs_dir() -> Path:
    """Return directory for structured log files."""
    return get_cloudprac_home() / "logs"


def get_log_file_path() -> Path:
    """Return path to primary application log file."""
    return get_logs_dir() / "cloudprac.log"


def get_runs_dir() -> Path:
    """Return directory storing execution runs and reports."""
    return get_cloudprac_home() / "runs"


def get_run_dir(run_id: str) -> Path:
    """Return specific run directory for a given run ID."""
    return get_runs_dir() / run_id


def ensure_cloudprac_dirs() -> None:
    """Ensure essential CloudPrac directories exist on filesystem."""
    get_cloudprac_home().mkdir(parents=True, exist_ok=True)
    get_logs_dir().mkdir(parents=True, exist_ok=True)
    get_runs_dir().mkdir(parents=True, exist_ok=True)
