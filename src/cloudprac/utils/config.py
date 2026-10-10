"""Configuration management and validation for CloudPrac."""

from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, Field

from cloudprac.utils.paths import ensure_cloudprac_dirs, get_config_path


class CloudPracConfig(BaseModel):
    """Global configuration settings for CloudPrac."""

    default_region: str = Field(
        default="us-east-1",
        description="Default AWS region to target if not explicitly overridden.",
    )
    student_name: str = Field(
        default="",
        description="Name of the student for practical evidence reporting.",
    )
    student_id: str = Field(
        default="",
        description="Roll number / Student ID for submission reports.",
    )
    safe_mode: bool = Field(
        default=True,
        description="Enforces strict dry-run planning and approval before any AWS mutation.",
    )
    auto_cleanup: bool = Field(
        default=False,
        description="Whether to automatically prompt for cleanup after successful run and verification.",
    )
    output_format: str = Field(
        default="rich",
        description="Console output format: rich, json, or plain.",
    )


def load_config(config_path: Optional[Path] = None) -> CloudPracConfig:
    """Load configuration from YAML file or return defaults if absent/invalid."""
    path = config_path or get_config_path()
    if not path.is_file():
        return CloudPracConfig()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return CloudPracConfig(**data)
    except Exception:
        # Fall back to safe defaults on parse error
        return CloudPracConfig()


def save_config(config: CloudPracConfig, config_path: Optional[Path] = None) -> None:
    """Save configuration to YAML file."""
    path = config_path or get_config_path()
    ensure_cloudprac_dirs()
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config.model_dump(), f, default_flow_style=False, sort_keys=False)
