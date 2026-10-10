"""Verification engine for evaluating AWS resource state post-execution."""

import json
from pathlib import Path
from typing import Any, Optional

from cloudprac.core.contract import PracticalContract, PracticalNotConfiguredError
from cloudprac.core.models import PracticalStatus, VerificationResult
from cloudprac.utils.paths import get_run_dir


class VerificationEngine:
    """Coordinates postcondition verification against real AWS resource states."""

    def __init__(self, context: Optional[Any] = None) -> None:
        self.context = context

    def verify(self, practical: PracticalContract, run_id: str) -> VerificationResult:
        """Run verification assertions on a practical."""
        if practical.metadata.status == PracticalStatus.NOT_CONFIGURED:
            raise PracticalNotConfiguredError(
                f"Practical {practical.metadata.id} is NOT CONFIGURED. "
                "No verification assertions exist."
            )

        result = practical.verify(run_id, self.context)

        # Save verification result to run directory
        run_dir = get_run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        verification_file = run_dir / "verification.json"
        with open(verification_file, "w", encoding="utf-8") as f:
            json.dump(result.model_dump(), f, indent=2)

        return result
