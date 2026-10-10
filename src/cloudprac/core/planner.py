"""Execution planner for CloudPrac practical modules."""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from cloudprac.core.contract import PracticalContract, PracticalNotConfiguredError
from cloudprac.core.models import ExecutionPlan, PracticalStatus
from cloudprac.utils.config import CloudPracConfig
from cloudprac.utils.paths import get_run_dir


def generate_run_id(practical_id: str) -> str:
    """Generate a deterministic and timestamped run identifier."""
    now_str = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    short_uuid = uuid.uuid4().hex[:6]
    return f"{practical_id.upper()}-{now_str}-{short_uuid}"


class ExecutionPlanner:
    """Generates and manages dry-run execution plans."""

    def __init__(self, config: Optional[CloudPracConfig] = None) -> None:
        self.config = config or CloudPracConfig()

    def plan(self, practical: PracticalContract, run_id: Optional[str] = None) -> ExecutionPlan:
        """Create a dry-run execution plan for a practical."""
        if practical.metadata.status == PracticalStatus.NOT_CONFIGURED:
            if getattr(practical, "is_local", False):
                raise PracticalNotConfiguredError(
                    f"Practical {practical.metadata.id} is a local virtualization practical (VMware/Ubuntu). "
                    "It cannot be planned or run inside AWS CloudShell."
                )
            raise PracticalNotConfiguredError(
                f"Practical {practical.metadata.id} is NOT CONFIGURED. "
                "Cannot generate an execution plan until syllabus instructions are provided."
            )


        active_run_id = run_id or generate_run_id(practical.metadata.id)
        plan = practical.plan(self.config, active_run_id)

        # Persist plan to run directory
        run_dir = get_run_dir(active_run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        plan_file = run_dir / "plan.json"
        with open(plan_file, "w", encoding="utf-8") as f:
            json.dump(plan.model_dump(), f, indent=2)

        return plan
