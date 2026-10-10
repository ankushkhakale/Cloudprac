"""Guarded cleanup engine for restoring AWS environment after practical run."""

import json
from typing import Any, Optional

from cloudprac.core.contract import PracticalContract, PracticalNotConfiguredError
from cloudprac.core.models import CleanupResult, PracticalStatus, RunManifest
from cloudprac.utils.logging import get_logger
from cloudprac.utils.paths import get_run_dir

logger = get_logger()


class CleanupEngine:
    """Safely cleans up only the resources tracked in a run manifest."""

    def __init__(self, context: Optional[Any] = None) -> None:
        self.context = context

    def cleanup(self, practical: PracticalContract, run_id: str) -> CleanupResult:
        """Execute guarded cleanup based on tracked manifest."""
        if practical.metadata.status == PracticalStatus.NOT_CONFIGURED:
            raise PracticalNotConfiguredError(
                f"Practical {practical.metadata.id} is NOT CONFIGURED. "
                "No cleanup operations exist."
            )

        run_dir = get_run_dir(run_id)
        manifest_file = run_dir / "manifest.json"

        if not manifest_file.is_file():
            return CleanupResult(
                success=True,
                run_id=run_id,
                practical_id=practical.metadata.id,
                resources_deleted=[],
                resources_failed=[],
                errors=[f"No manifest found for run {run_id}. No tracked resources to clean up."],
            )

        try:
            with open(manifest_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            manifest = RunManifest(**data)
        except Exception as e:
            return CleanupResult(
                success=False,
                run_id=run_id,
                practical_id=practical.metadata.id,
                resources_deleted=[],
                resources_failed=[],
                errors=[f"Failed to load run manifest: {e}"],
            )

        result = practical.cleanup(manifest, self.context)

        # Save cleanup result to run directory
        cleanup_file = run_dir / "cleanup.json"
        with open(cleanup_file, "w", encoding="utf-8") as f:
            json.dump(result.model_dump(), f, indent=2)

        return result
