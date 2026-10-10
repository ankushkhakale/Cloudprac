"""Placeholder practical implementations for unconfigured modules (P01–P08)."""

from typing import Any, Dict, Optional

from cloudprac.core.contract import PracticalContract, PracticalNotConfiguredError
from cloudprac.core.models import (
    CleanupResult,
    ExecutionPlan,
    ExecutionResult,
    PracticalMetadata,
    PracticalStatus,
    RunManifest,
    VerificationResult,
)
from cloudprac.utils.config import CloudPracConfig


class PlaceholderPractical(PracticalContract):
    """Safe placeholder for a practical module whose college specifications are pending."""

    def __init__(self, practical_id: str, title: Optional[str] = None):
        self._id = practical_id.upper()
        default_title = f"Practical {self._id} (Pending Syllabus Specification)"
        self._metadata = PracticalMetadata(
            id=self._id,
            title=title or default_title,
            description=(
                f"Official assignment requirements for {self._id} have not yet been provided. "
                "This module is safely locked in NOT CONFIGURED state. It cannot execute, plan, "
                "or provision AWS resources until real requirements are supplied."
            ),
            category="Pending Specification",
            aws_services=[],
            status=PracticalStatus.NOT_CONFIGURED,
            estimated_cost="$0.00",
            prerequisites=["Official college syllabus / assignment problem statement required"],
            syllabus_source=None,
        )

    @property
    def metadata(self) -> PracticalMetadata:
        return self._metadata

    def inspect(self) -> Dict[str, Any]:
        return {
            "id": self._metadata.id,
            "title": self._metadata.title,
            "status": self._metadata.status.value,
            "description": self._metadata.description,
            "configured": False,
            "notice": (
                f"Practical {self._id} is NOT CONFIGURED. Provide the real college problem "
                "statement and grading rubric to unlock execution and verification."
            ),
            "prerequisites": self._metadata.prerequisites,
        }

    def plan(self, config: CloudPracConfig, run_id: str) -> ExecutionPlan:
        raise PracticalNotConfiguredError(
            f"Cannot generate execution plan: Practical {self._id} is NOT CONFIGURED. "
            "Supply assignment specifications first."
        )

    def execute(self, plan: ExecutionPlan, context: Any) -> ExecutionResult:
        raise PracticalNotConfiguredError(
            f"Cannot execute: Practical {self._id} is NOT CONFIGURED. "
            "Prevented accidental AWS operations."
        )

    def verify(self, run_id: str, context: Any) -> VerificationResult:
        raise PracticalNotConfiguredError(
            f"Cannot verify: Practical {self._id} is NOT CONFIGURED. "
            "No postconditions or assertions defined."
        )

    def cleanup(self, manifest: RunManifest, context: Any) -> CleanupResult:
        raise PracticalNotConfiguredError(
            f"Cannot cleanup: Practical {self._id} is NOT CONFIGURED. "
            "No tracked resources exist for this module."
        )
