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
    """Verify registry starts with P05 configured and P01-P04, P06-P08 as placeholders."""
    reg = PracticalRegistry()
    ids = reg.list_ids()
    assert ids == [f"P{i:02d}" for i in range(1, 9)]

    # P05 is configured
    assert reg.is_configured("P05")
    assert reg.get("P05").metadata.status == PracticalStatus.CONFIGURED
    assert "Student Record Management" in reg.get("P05").metadata.title

    # P01 is local VMware/Ubuntu practical
    p01 = reg.get("P01")
    assert p01 is not None
    assert p01.metadata.status == PracticalStatus.NOT_CONFIGURED
    assert p01.metadata.estimated_cost == "Not estimated"
    assert "VMware Workstation Pro" in p01.metadata.description
    assert p01.is_local is True

    # P02-P04 and P06-P08 remain unconfigured placeholders
    for pid in ["P02", "P03", "P04", "P06", "P07", "P08"]:
        assert not reg.is_configured(pid)
        p = reg.get(pid)
        assert p is not None
        assert p.metadata.status == PracticalStatus.NOT_CONFIGURED
        assert p.metadata.estimated_cost == "Not estimated"


def test_registry_case_insensitive_lookup():
    """Verify lookups work regardless of case or prefix."""
    reg = PracticalRegistry()
    assert reg.get("p05") is not None
    assert reg.get("5") is not None
    assert reg.get("P5") is not None
    assert reg.get("P05") is not None
    assert reg.get("P01") is not None
    assert reg.get("nonexistent") is None

