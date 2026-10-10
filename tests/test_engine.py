"""Unit tests for controlled execution engine and lifecycle."""

from typing import Any, Dict
import pytest

from cloudprac.adapters.aws_client import AWSAdapter
from cloudprac.core.contract import PracticalContract, PracticalNotConfiguredError
from cloudprac.core.engine import ExecutionEngine
from cloudprac.core.models import (
    CleanupResult,
    ExecutionPlan,
    ExecutionPlanStep,
    ExecutionResult,
    PracticalMetadata,
    PracticalStatus,
    RunManifest,
    TrackedResource,
    VerificationCheck,
    VerificationResult,
)
from cloudprac.core.placeholders import PlaceholderPractical
from cloudprac.utils.config import CloudPracConfig
from cloudprac.utils.paths import get_run_dir


class MockConfiguredPractical(PracticalContract):
    """A sample configured practical module for verifying engine lifecycle."""

    def __init__(self, practical_id: str = "P99"):
        self._meta = PracticalMetadata(
            id=practical_id,
            title="Mock Configured S3 Assignment",
            description="Test assignment validating lifecycle",
            category="Storage",
            aws_services=["S3"],
            status=PracticalStatus.CONFIGURED,
            estimated_cost="$0.00",
        )

    @property
    def metadata(self) -> PracticalMetadata:
        return self._meta

    def inspect(self) -> Dict[str, Any]:
        return {"id": self._meta.id, "configured": True}

    def plan(self, config: CloudPracConfig, run_id: str) -> ExecutionPlan:
        return ExecutionPlan(
            practical_id=self._meta.id,
            run_id=run_id,
            steps=[
                ExecutionPlanStep(
                    step_number=1,
                    action="CREATE_BUCKET",
                    resource_type="AWS::S3::Bucket",
                    resource_name="cloudprac-mock-bucket",
                    description="Creates test bucket",
                )
            ],
            estimated_total_cost="$0.00",
        )

    def execute(self, plan: ExecutionPlan, context: Any) -> ExecutionResult:
        manifest = RunManifest(
            run_id=plan.run_id,
            practical_id=self._meta.id,
            resources=[
                TrackedResource(
                    resource_id="cloudprac-mock-bucket",
                    resource_type="AWS::S3::Bucket",
                    resource_name="cloudprac-mock-bucket",
                    tags={"ManagedBy": "CloudPrac", "RunId": plan.run_id},
                )
            ],
        )
        return ExecutionResult(
            success=True,
            run_id=plan.run_id,
            practical_id=self._meta.id,
            message="Successfully executed mock steps",
            steps_executed=1,
            manifest=manifest,
        )

    def verify(self, run_id: str, context: Any) -> VerificationResult:
        return VerificationResult(
            success=True,
            run_id=run_id,
            practical_id=self._meta.id,
            checks=[
                VerificationCheck(
                    check_id="CHK-01",
                    name="Bucket Exists",
                    description="Verify bucket exists",
                    expected="Active",
                    actual="Active",
                    passed=True,
                )
            ],
            summary="All mock checks passed.",
        )

    def cleanup(self, manifest: RunManifest, context: Any) -> CleanupResult:
        return CleanupResult(
            success=True,
            run_id=manifest.run_id,
            practical_id=self._meta.id,
            resources_deleted=["cloudprac-mock-bucket"],
            resources_failed=[],
        )


def test_unconfigured_practical_cannot_execute():
    """Verify unconfigured placeholder fails immediately when execution attempted."""
    practical = PlaceholderPractical("P01")
    engine = ExecutionEngine()
    with pytest.raises(PracticalNotConfiguredError):
        engine.run_practical(practical)


def test_configured_practical_full_lifecycle():
    """Verify configured practical completes planning, execution, verification, and cleanup."""
    practical = MockConfiguredPractical("P99")
    config = CloudPracConfig(student_name="Test Student", student_id="ST123")
    adapter = AWSAdapter(mock_mode=True)
    engine = ExecutionEngine(config=config, adapter=adapter)

    res = engine.run_practical(
        practical=practical,
        auto_verify=True,
        auto_cleanup=True,
    )

    assert res.success is True
    assert res.steps_executed == 1
    assert res.manifest is not None

    # Verify report artifacts were written to run directory
    run_dir = get_run_dir(res.run_id)
    assert (run_dir / "plan.json").is_file()
    assert (run_dir / "verification.json").is_file()
    assert (run_dir / "cleanup.json").is_file()
    assert (run_dir / "report.md").is_file()
    assert (run_dir / "report.json").is_file()

    # Verify report contents
    md_content = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "Test Student" in md_content
    assert "P99" in md_content
    assert "[PASS]" in md_content
