"""Controlled execution engine orchestrating practical lifecycles."""

import json
from typing import Optional

from cloudprac.adapters.aws_client import AWSAdapter
from cloudprac.core.cleaner import CleanupEngine
from cloudprac.core.contract import PracticalContract, PracticalNotConfiguredError
from cloudprac.core.models import (
    CleanupResult,
    ExecutionResult,
    PracticalStatus,
    RunManifest,
    VerificationResult,
)
from cloudprac.core.planner import ExecutionPlanner, generate_run_id
from cloudprac.core.verifier import VerificationEngine
from cloudprac.reporting.generator import ReportGenerator
from cloudprac.utils.config import CloudPracConfig
from cloudprac.utils.logging import get_logger
from cloudprac.utils.paths import get_run_dir

logger = get_logger()


class ExecutionEngine:
    """Coordinates planning, execution, verification, and cleanup for practicals."""

    def __init__(
        self,
        config: Optional[CloudPracConfig] = None,
        adapter: Optional[AWSAdapter] = None,
    ) -> None:
        self.config = config or CloudPracConfig()
        self.adapter = adapter or AWSAdapter()
        self.planner = ExecutionPlanner(self.config)
        self.verifier = VerificationEngine(self.adapter)
        self.cleaner = CleanupEngine(self.adapter)
        self.reporter = ReportGenerator(self.config)

    def run_practical(
        self,
        practical: PracticalContract,
        run_id: Optional[str] = None,
        auto_verify: bool = True,
        auto_cleanup: bool = False,
    ) -> ExecutionResult:
        """Execute a practical module through the safe controlled lifecycle."""
        if practical.metadata.status == PracticalStatus.NOT_CONFIGURED:
            raise PracticalNotConfiguredError(
                f"Practical {practical.metadata.id} is NOT CONFIGURED. "
                "Execution prevented to protect cloud resources."
            )

        active_run_id = run_id or generate_run_id(practical.metadata.id)
        logger.info(f"Starting execution for {practical.metadata.id} (Run ID: {active_run_id})")

        # 1. Plan
        plan = self.planner.plan(practical, active_run_id)

        # 2. Execute
        run_dir = get_run_dir(active_run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            exec_result = practical.execute(plan, self.adapter)
        except Exception as e:
            logger.error(f"Practical execution failed with exception: {e}")
            manifest = None
            manifest_file = run_dir / "manifest.json"
            if manifest_file.is_file():
                try:
                    manifest = RunManifest.model_validate_json(manifest_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
            exec_result = ExecutionResult(
                practical_id=practical.metadata.id,
                run_id=active_run_id,
                success=False,
                message=f"Execution failed or was interrupted: {e}",
                steps_executed=len(manifest.resources) if manifest else 0,
                errors=[str(e)],
                manifest=manifest,
                outputs={},
            )

        if exec_result.manifest:
            manifest_file = run_dir / "manifest.json"
            with open(manifest_file, "w", encoding="utf-8") as f:
                json.dump(exec_result.manifest.model_dump(), f, indent=2)

        result_file = run_dir / "result.json"
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(exec_result.model_dump(), f, indent=2)

        # 3. Verify
        verif_result: Optional[VerificationResult] = None
        if auto_verify and exec_result.success:
            verif_result = self.verifier.verify(practical, active_run_id)

        # 4. Cleanup if requested
        cleanup_result: Optional[CleanupResult] = None
        if auto_cleanup and exec_result.manifest:
            cleanup_result = self.cleaner.cleanup(practical, active_run_id)

        # 5. Generate Evidence Report
        identity = self.adapter.get_caller_identity()
        self.reporter.generate_report(
            practical=practical,
            run_id=active_run_id,
            plan=plan,
            execution_result=exec_result,
            verification_result=verif_result,
            cleanup_result=cleanup_result,
            aws_region=self.adapter.region,
            account_id=identity.get("Account", "unknown"),
        )

        return exec_result
