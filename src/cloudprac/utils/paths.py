"""Path resolution and directory management for CloudPrac."""

import os
from pathlib import Path
from typing import Any, Dict, List

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


def save_restricted_file(file_path: Path, content: str) -> Path:
    """Save content to a local file with permissions restricted strictly to the current user (0600)."""
    import stat

    file_path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(str(file_path), flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(str(file_path), stat.S_IRUSR | stat.S_IWUSR)
    else:
        file_path.write_text(content, encoding="utf-8")
    return file_path


def list_all_runs() -> List[Dict[str, Any]]:
    """Discover all recorded execution runs from ~/.cloudprac/runs.

    Returns a list of run metadata dictionaries, sorted newest first.
    """
    import json

    runs_dir = get_runs_dir()
    if not runs_dir.exists():
        return []

    runs: List[Dict[str, Any]] = []
    for item in runs_dir.iterdir():
        if item.is_dir():
            manifest_file = item / "manifest.json"
            if manifest_file.is_file():
                try:
                    data = json.loads(manifest_file.read_text(encoding="utf-8"))
                    runs.append(
                        {
                            "run_id": data.get("run_id", item.name),
                            "practical_id": data.get("practical_id", "Unknown"),
                            "started_at": data.get("started_at", ""),
                            "aws_region": data.get("aws_region", ""),
                            "resource_count": len(data.get("resources", [])),
                            "path": str(item),
                        }
                    )
                except Exception:
                    runs.append(
                        {
                            "run_id": item.name,
                            "practical_id": "Unknown",
                            "started_at": "",
                            "aws_region": "",
                            "resource_count": 0,
                            "path": str(item),
                        }
                    )
    runs.sort(key=lambda r: (r.get("started_at", ""), r.get("run_id", "")), reverse=True)
    return runs
