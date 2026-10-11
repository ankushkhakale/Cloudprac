"""Domain models and data structures for CloudPrac."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class PracticalStatus(str, Enum):
    """Lifecycle status of a practical module."""

    NOT_CONFIGURED = "NOT CONFIGURED"
    CONFIGURED = "CONFIGURED"
    PLANNED = "PLANNED"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    VERIFIED = "VERIFIED"
    CLEANED_UP = "CLEANED_UP"
    FAILED = "FAILED"


class PracticalMetadata(BaseModel):
    """Metadata describing a Cloud Computing practical module."""

    id: str = Field(description="Unique practical identifier, e.g. P01")
    title: str = Field(description="Title of practical assignment")
    description: str = Field(description="Summary of assignment scope")
    category: str = Field(default="Cloud Infrastructure", description="Domain category")
    aws_services: List[str] = Field(default_factory=list, description="AWS services involved")
    status: PracticalStatus = Field(
        default=PracticalStatus.NOT_CONFIGURED,
        description="Current readiness status of this practical module",
    )
    estimated_cost: str = Field(
        default="$0.00 (Free Tier)",
        description="Estimated operational cost",
    )
    prerequisites: List[str] = Field(
        default_factory=list,
        description="Prerequisites required before running",
    )
    syllabus_source: Optional[str] = Field(
        default=None,
        description="Reference to university/college syllabus requirement",
    )


class ExecutionPlanStep(BaseModel):
    """An individual step in a practical's proposed execution plan."""

    step_number: int
    action: str = Field(description="Operation to perform, e.g. CREATE_BUCKET")
    resource_type: str = Field(description="AWS resource type, e.g. AWS::S3::Bucket")
    resource_name: str = Field(description="Deterministic name or identifier")
    description: str = Field(description="Explanation of what this step does")
    is_destructive: bool = Field(default=False, description="Whether this mutates/deletes state")
    estimated_cost: str = Field(default="$0.00")


class ExecutionPlan(BaseModel):
    """Complete dry-run execution plan for a practical."""

    practical_id: str
    run_id: str
    aws_region: str = "us-east-1"
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    steps: List[ExecutionPlanStep] = Field(default_factory=list)
    estimated_total_cost: str = "$0.00"
    warnings: List[str] = Field(default_factory=list)


class TrackedResource(BaseModel):
    """An AWS resource created by CloudPrac and tracked for ownership and cleanup."""

    resource_id: str
    resource_type: str
    resource_name: str
    arn: Optional[str] = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    tags: Dict[str, str] = Field(default_factory=dict)
    status: str = "created"


class RunManifest(BaseModel):
    """Manifest of all resources provisioned during an execution run."""

    run_id: str
    practical_id: str
    started_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: Optional[str] = None
    aws_region: str = "us-east-1"
    aws_account_id: str = "unknown"
    resources: List[TrackedResource] = Field(default_factory=list)


class ExecutionResult(BaseModel):
    """Outcome of running a practical."""

    success: bool
    run_id: str
    practical_id: str
    message: str
    steps_executed: int = 0
    manifest: Optional[RunManifest] = None
    errors: List[str] = Field(default_factory=list)
    outputs: Dict[str, Any] = Field(default_factory=dict)


class VerificationCheck(BaseModel):
    """A single assertion check against real AWS resource state."""

    check_id: str
    name: str
    description: str
    expected: str
    actual: str
    passed: bool
    evidence: Optional[Dict[str, Any]] = None


class VerificationResult(BaseModel):
    """Full verification outcome for a practical."""

    success: bool
    run_id: str
    practical_id: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    checks: List[VerificationCheck] = Field(default_factory=list)
    summary: str = ""


class CleanupResult(BaseModel):
    """Outcome of resource cleanup operations."""

    success: bool
    run_id: str
    practical_id: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    resources_deleted: List[str] = Field(default_factory=list)
    resources_absent: List[str] = Field(default_factory=list)
    resources_failed: List[str] = Field(default_factory=list)
    resources_unverified: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_overall_success(self) -> "CleanupResult":
        """Ensure failed or unverified resources or errors can never produce an overall success."""
        if (self.resources_failed or self.resources_unverified or self.errors) and self.success:
            self.success = False
        return self
