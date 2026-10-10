"""Abstract contract and interfaces for Cloud Computing practicals."""

from abc import ABC, abstractmethod
from typing import Any, Dict

from cloudprac.core.models import (
    CleanupResult,
    ExecutionPlan,
    ExecutionResult,
    PracticalMetadata,
    RunManifest,
    VerificationResult,
)
from cloudprac.utils.config import CloudPracConfig


class PracticalError(Exception):
    """Base exception for practical errors."""


class PracticalNotConfiguredError(PracticalError):
    """Raised when an operation is attempted on an unconfigured practical placeholder."""


class PracticalExecutionError(PracticalError):
    """Raised when an execution step fails."""


class PracticalContract(ABC):
    """Execution and verification contract that every practical module must implement."""

    @property
    @abstractmethod
    def metadata(self) -> PracticalMetadata:
        """Return metadata describing the practical module."""

    @abstractmethod
    def inspect(self) -> Dict[str, Any]:
        """Return detailed inspection information, instructions, and syllabus references."""

    @abstractmethod
    def plan(self, config: CloudPracConfig, run_id: str) -> ExecutionPlan:
        """Generate a dry-run execution plan without modifying any AWS resources."""

    @abstractmethod
    def execute(self, plan: ExecutionPlan, context: Any) -> ExecutionResult:
        """Execute the planned AWS operations in a controlled manner."""

    @abstractmethod
    def verify(self, run_id: str, context: Any) -> VerificationResult:
        """Verify that the expected AWS resources exist and match requirements."""

    @abstractmethod
    def cleanup(self, manifest: RunManifest, context: Any) -> CleanupResult:
        """Safely destroy only the AWS resources provisioned during this run."""
