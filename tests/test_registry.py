"""Unit tests for practical registry and ID normalization."""

import pytest

from cloudprac.core.contract import PracticalContract
from cloudprac.core.models import PracticalMetadata, PracticalStatus
from cloudprac.core.registry import PracticalRegistry, normalize_practical_id


def test_normalize_practical_id():
    """Verify various forms of input normalize to Pxx format."""
    assert normalize_practical_id("1") == "P01"
    assert normalize_practical_id("01") == "P01"
    assert normalize_practical_id("p1") == "P01"
    assert normalize_practical_id("P1") == "P01"
    assert normalize_practical_id("p01") == "P01"
    assert normalize_practical_id("P01") == "P01"
    assert normalize_practical_id("8") == "P08"
    assert normalize_practical_id("P08") == "P08"


def test_registry_initialization():
    """Verify registry starts with P01 configured and P02-P08 as placeholders."""
    reg = PracticalRegistry()
    ids = reg.list_ids()
    assert ids == [f"P{i:02d}" for i in range(1, 9)]

    # P01 is now configured
    assert reg.is_configured("P01")
    assert reg.get("P01").metadata.status == PracticalStatus.CONFIGURED

    # P02 through P08 remain unconfigured placeholders
    for pid in [f"P{i:02d}" for i in range(2, 9)]:
        assert not reg.is_configured(pid)
        p = reg.get(pid)
        assert p is not None
        assert p.metadata.status == PracticalStatus.NOT_CONFIGURED


def test_registry_case_insensitive_lookup():
    """Verify lookups work regardless of case or prefix."""
    reg = PracticalRegistry()
    assert reg.get("p01") is not None
    assert reg.get("1") is not None
    assert reg.get("P1") is not None
    assert reg.get("nonexistent") is None
