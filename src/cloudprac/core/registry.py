"""Practical registry and discovery mechanism."""

import re
from typing import Dict, List, Optional

from cloudprac.core.contract import PracticalContract
from cloudprac.core.models import PracticalStatus
from cloudprac.core.placeholders import PlaceholderPractical


def normalize_practical_id(raw_id: str) -> str:
    """Normalize user-entered ID strings like '1', 'p1', 'p01', 'P1', 'P01' to canonical 'P01'."""
    clean = raw_id.strip().upper()
    # Check if format is digits only: '1' -> 'P01'
    if clean.isdigit():
        num = int(clean)
        return f"P{num:02d}"

    # Match P1 -> P01, P01 -> P01
    match = re.match(r"^P(\d+)$", clean)
    if match:
        num = int(match.group(1))
        return f"P{num:02d}"

    return clean


class PracticalRegistry:
    """Registry maintaining all available Cloud Computing practical modules."""

    def __init__(self) -> None:
        self._practicals: Dict[str, PracticalContract] = {}
        self._register_placeholders()

    def _register_placeholders(self) -> None:
        """Register default practicals: P05 configured, P01-P04 and P06-P08 as placeholders."""
        # P01 to P04 are placeholders (P01 is local VMware/Ubuntu practical)
        for i in range(1, 5):
            pid = f"P{i:02d}"
            self._practicals[pid] = PlaceholderPractical(pid)

        # P05 is the official AWS Student Record Management practical
        try:
            from cloudprac.practicals.p05.practical import P05Practical
            self._practicals["P05"] = P05Practical()
        except ImportError:
            self._practicals["P05"] = PlaceholderPractical("P05")

        # P06 to P08 are placeholders
        for i in range(6, 9):
            pid = f"P{i:02d}"
            self._practicals[pid] = PlaceholderPractical(pid)

    def register(self, practical: PracticalContract, overwrite: bool = False) -> None:
        """Register a practical module implementation."""
        pid = normalize_practical_id(practical.metadata.id)
        if pid in self._practicals and not overwrite:
            existing = self._practicals[pid]
            if existing.metadata.status != PracticalStatus.NOT_CONFIGURED:
                raise ValueError(f"Practical {pid} is already registered with an active implementation.")
        self._practicals[pid] = practical

    def get(self, practical_id: str) -> Optional[PracticalContract]:
        """Look up a practical module by its ID."""
        pid = normalize_practical_id(practical_id)
        return self._practicals.get(pid)

    def list_all(self) -> List[PracticalContract]:
        """Return all registered practical modules sorted by ID."""
        return sorted(self._practicals.values(), key=lambda p: p.metadata.id)

    def list_ids(self) -> List[str]:
        """Return all registered practical IDs sorted."""
        return sorted(self._practicals.keys())

    def is_configured(self, practical_id: str) -> bool:
        """Check if a practical module has a configured implementation."""
        practical = self.get(practical_id)
        if not practical:
            return False
        return practical.metadata.status != PracticalStatus.NOT_CONFIGURED


# Global registry singleton
_registry_instance: Optional[PracticalRegistry] = None


def get_registry() -> PracticalRegistry:
    """Get or create the global PracticalRegistry instance."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = PracticalRegistry()
    return _registry_instance
