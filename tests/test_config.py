"""Unit tests for configuration loading and validation."""

from pathlib import Path
from cloudprac.utils.config import CloudPracConfig, load_config, save_config


def test_default_config():
    """Verify default configuration values."""
    cfg = CloudPracConfig()
    assert cfg.default_region == "us-east-1"
    assert cfg.safe_mode is True
    assert cfg.auto_cleanup is False
    assert cfg.output_format == "rich"


def test_config_save_and_load(tmp_path: Path):
    """Verify configuration serialization and reload."""
    test_file = tmp_path / "test_config.yaml"
    cfg = CloudPracConfig(
        default_region="eu-west-1",
        student_name="Alice Smith",
        student_id="CS101-042",
        safe_mode=True,
    )
    save_config(cfg, test_file)
    assert test_file.exists()

    loaded = load_config(test_file)
    assert loaded.default_region == "eu-west-1"
    assert loaded.student_name == "Alice Smith"
    assert loaded.student_id == "CS101-042"
