"""Test fixtures and isolation setup for CloudPrac test suite."""

import shutil
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from cloudprac.utils.paths import ENV_CLOUDPRAC_HOME


@pytest.fixture(autouse=True)
def isolated_cloudprac_env(monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Isolate CloudPrac home directory and force AWS mock mode for all tests."""
    temp_dir = tempfile.mkdtemp(prefix="cloudprac_test_")
    monkeypatch.setenv(ENV_CLOUDPRAC_HOME, temp_dir)
    monkeypatch.setenv("CLOUDPRAC_MOCK_AWS", "1")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    yield Path(temp_dir)

    shutil.rmtree(temp_dir, ignore_errors=True)
