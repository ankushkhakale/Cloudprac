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

# Authoritative syllabus metadata for unconfigured practicals
OFFICIAL_SYLLABUS: Dict[str, Dict[str, Any]] = {
    "P01": {
        "title": "Installation and Configuration of Virtualization Architecture",
        "description": (
            "Configure and demonstrate basic CPU, network, and storage virtualization "
            "using VMware Workstation Pro and Ubuntu."
        ),
        "category": "Local Virtualization",
        "is_local": True,
        "prerequisites": [
            "Local host computer with virtualization enabled (Intel VT-x / AMD-V)",
            "VMware Workstation Pro installed locally",
            "Ubuntu Desktop/Server ISO image",
        ],
        "notice": (
            "Practical P01 is a local virtualization practical using VMware Workstation Pro "
            "and Ubuntu on your personal computer. It does not run inside AWS CloudShell "
            "and does not provision AWS cloud resources."
        ),
    },
    "P02": {
        "title": "Customer Data Management",
        "description": (
            "A business wants to store customer names, contact details, and purchase information "
            "on the cloud for easy access and management."
        ),
        "category": "Cloud Database & Storage",
        "is_local": False,
        "prerequisites": ["Official college assignment workflow specification required"],
        "notice": (
            "Practical P02 is NOT CONFIGURED. Official assignment requirements and cloud "
            "architecture have not yet been implemented."
        ),
    },
    "P03": {
        "title": "Employee Attendance System",
        "description": (
            "A company wants to maintain employee attendance records on the cloud, "
            "accessible to employees and managers."
        ),
        "category": "Cloud Database & Storage",
        "is_local": False,
        "prerequisites": ["Official college assignment workflow specification required"],
        "notice": (
            "Practical P03 is NOT CONFIGURED. Official assignment requirements and cloud "
            "architecture have not yet been implemented."
        ),
    },
    "P04": {
        "title": "Online Billing System",
        "description": (
            "A small shop wants to store customer bills and sales records on the cloud "
            "so the owner can access them anytime."
        ),
        "category": "Cloud Database & Storage",
        "is_local": False,
        "prerequisites": ["Official college assignment workflow specification required"],
        "notice": (
            "Practical P04 is NOT CONFIGURED. Official assignment requirements and cloud "
            "architecture have not yet been implemented."
        ),
    },
    "P06": {
        "title": "EC2, S3 and DynamoDB Implementation: Employee Record Management",
        "description": (
            "A company wants to store employee information in DynamoDB, upload employee documents "
            "to S3, and use EC2 to host an application for accessing employee records."
        ),
        "category": "Compute, Storage & Database",
        "is_local": False,
        "prerequisites": ["Official college assignment workflow specification required"],
        "notice": (
            "Practical P06 is NOT CONFIGURED. Workflow specification pending implementation."
        ),
    },
    "P07": {
        "title": "EC2, S3 and DynamoDB Implementation: Library Management",
        "description": (
            "A library wants to store book details and issue records in DynamoDB, store "
            "book-related files and images in S3, and use EC2 to run a simple library management application."
        ),
        "category": "Compute, Storage & Database",
        "is_local": False,
        "prerequisites": ["Official college assignment workflow specification required"],
        "notice": (
            "Practical P07 is NOT CONFIGURED. Workflow specification pending implementation."
        ),
    },
    "P08": {
        "title": "Implementation of the CIA Model",
        "description": (
            "Demonstrate confidentiality, integrity, and availability using basic Linux security "
            "commands: encrypt a file, generate and verify its SHA-256 hash, run a simple web server, "
            "and demonstrate unauthorized access in a controlled environment."
        ),
        "category": "Cloud Security & Governance",
        "is_local": False,
        "prerequisites": [
            "Isolated Linux target environment (e.g., dedicated EC2 instance)",
            "Linux security tools (OpenSSL, sha256sum, curl)",
        ],
        "notice": (
            "Practical P08 is NOT CONFIGURED. Requires an isolated Linux target environment. "
            "Do not assume AWS CloudShell can host every required service."
        ),
    },
}


class PlaceholderPractical(PracticalContract):
    """Safe placeholder for a practical module whose cloud workflow is pending or local."""

    def __init__(self, practical_id: str, title: Optional[str] = None):
        self._id = practical_id.upper()
        syllabus_info = OFFICIAL_SYLLABUS.get(self._id, {})
        default_title = syllabus_info.get("title", f"Practical {self._id} (Pending Syllabus Specification)")
        description = syllabus_info.get(
            "description",
            f"Official assignment requirements for {self._id} have not yet been implemented.",
        )
        category = syllabus_info.get("category", "Pending Specification")
        prerequisites = syllabus_info.get(
            "prerequisites",
            ["Official college syllabus / assignment problem statement required"],
        )
        self._is_local = syllabus_info.get("is_local", False)
        self._custom_notice = syllabus_info.get(
            "notice",
            f"Practical {self._id} is NOT CONFIGURED. Execution is locked to prevent accidental operations.",
        )

        self._metadata = PracticalMetadata(
            id=self._id,
            title=title or default_title,
            description=description,
            category=category,
            aws_services=[],
            status=PracticalStatus.NOT_CONFIGURED,
            estimated_cost="Not estimated",
            prerequisites=prerequisites,
            syllabus_source=f"College Syllabus Practical {self._id}",
        )

    @property
    def metadata(self) -> PracticalMetadata:
        return self._metadata

    @property
    def is_local(self) -> bool:
        return self._is_local

    def inspect(self) -> Dict[str, Any]:
        return {
            "id": self._metadata.id,
            "title": self._metadata.title,
            "status": self._metadata.status.value,
            "description": self._metadata.description,
            "category": self._metadata.category,
            "configured": False,
            "is_local": self._is_local,
            "estimated_cost": self._metadata.estimated_cost,
            "notice": self._custom_notice,
            "prerequisites": self._metadata.prerequisites,
        }

    def plan(self, config: CloudPracConfig, run_id: str) -> ExecutionPlan:
        if self._is_local:
            raise PracticalNotConfiguredError(
                f"Practical {self._id} is a local virtualization practical (VMware/Ubuntu). "
                "It cannot be planned or run inside AWS CloudShell."
            )
        raise PracticalNotConfiguredError(
            f"Cannot generate execution plan: Practical {self._id} is NOT CONFIGURED. "
            "Supply assignment specifications first."
        )

    def execute(self, plan: ExecutionPlan, context: Any) -> ExecutionResult:
        if self._is_local:
            raise PracticalNotConfiguredError(
                f"Practical {self._id} is a local virtualization practical (VMware/Ubuntu). "
                "It cannot execute in AWS CloudShell."
            )
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

