"""Evidence and report generator producing Markdown and JSON outputs."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from cloudprac.adapters.aws_client import mask_account_id
from cloudprac.core.contract import PracticalContract
from cloudprac.core.models import (
    CleanupResult,
    ExecutionPlan,
    ExecutionResult,
    RunManifest,
    VerificationResult,
)
from cloudprac.utils.config import CloudPracConfig
from cloudprac.utils.paths import get_run_dir


class ReportGenerator:
    """Generates Markdown and JSON reports for college practical submission."""

    def __init__(self, config: Optional[CloudPracConfig] = None) -> None:
        self.config = config or CloudPracConfig()

    def generate_report(
        self,
        practical: PracticalContract,
        run_id: str,
        plan: Optional[ExecutionPlan] = None,
        execution_result: Optional[ExecutionResult] = None,
        verification_result: Optional[VerificationResult] = None,
        cleanup_result: Optional[CleanupResult] = None,
        aws_region: str = "us-east-1",
        account_id: str = "unknown",
    ) -> Dict[str, Path]:
        """Compile run artifacts and write report.md and report.json."""
        run_dir = get_run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

        meta = practical.metadata
        masked_acc = mask_account_id(account_id)
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # Compile structured data
        report_data: Dict[str, Any] = {
            "practical": {
                "id": meta.id,
                "title": meta.title,
                "description": meta.description,
                "category": meta.category,
                "status": meta.status.value,
            },
            "run": {
                "run_id": run_id,
                "generated_at": now_iso,
                "aws_region": aws_region,
                "aws_account": masked_acc,
            },
            "student": {
                "name": self.config.student_name or "Not Specified",
                "id": self.config.student_id or "Not Specified",
            },
            "plan": plan.model_dump() if plan else None,
            "execution": execution_result.model_dump() if execution_result else None,
            "verification": verification_result.model_dump() if verification_result else None,
            "cleanup": cleanup_result.model_dump() if cleanup_result else None,
        }

        # Write report.json
        json_path = run_dir / "report.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)

        # Write report.md
        md_lines = [
            f"# AWS Cloud Computing Practical Report: {meta.id} — {meta.title}",
            "",
            "## 1. Student & Environment Metadata",
            f"- **Student Name**: {self.config.student_name or 'N/A'}",
            f"- **Student ID / Roll No**: {self.config.student_id or 'N/A'}",
            f"- **Run ID**: `{run_id}`",
            f"- **Date & Time**: {now_iso}",
            f"- **AWS Region**: `{aws_region}`",
            f"- **AWS Account**: `{masked_acc}`",
            f"- **Module Status**: **{meta.status.value}**",
            "",
            "## 2. Practical Overview",
            f"> {meta.description}",
            "",
        ]

        if meta.aws_services:
            md_lines.extend([
                "**AWS Services Utilized:**",
                ", ".join(f"`{s}`" for s in meta.aws_services),
                "",
            ])

        # Plan section
        md_lines.append("## 3. Execution Plan")
        if plan and plan.steps:
            md_lines.extend([
                "| Step | Action | Resource Type | Resource Name | Est. Cost |",
                "| :--- | :--- | :--- | :--- | :--- |",
            ])
            for s in plan.steps:
                md_lines.append(
                    f"| {s.step_number} | `{s.action}` | `{s.resource_type}` | `{s.resource_name}` | {s.estimated_cost} |"
                )
            md_lines.extend(["", f"**Estimated Total Cost**: {plan.estimated_total_cost}", ""])
        else:
            md_lines.extend(["*No execution plan steps recorded.*", ""])

        # Verification section
        md_lines.append("## 4. Verification & Postcondition Evidence")
        if verification_result and verification_result.checks:
            overall = "PASSED" if verification_result.success else "FAILED"
            md_lines.extend([
                f"**Overall Verification Status**: **{overall}**",
                "",
                "| Check ID | Verification Assertion | Expected | Actual | Outcome |",
                "| :--- | :--- | :--- | :--- | :--- |",
            ])
            for c in verification_result.checks:
                badge = "[PASS]" if c.passed else "[FAIL]"
                md_lines.append(
                    f"| `{c.check_id}` | {c.name} | `{c.expected}` | `{c.actual}` | **{badge}** |"
                )
            md_lines.append("")
        else:
            md_lines.extend(["*No verification checks recorded.*", ""])

        # Cleanup section
        md_lines.append("## 5. Resource Cleanup")
        if cleanup_result:
            del_count = len(cleanup_result.resources_deleted)
            fail_count = len(cleanup_result.resources_failed)
            md_lines.extend([
                f"- **Cleanup Executed**: Yes",
                f"- **Resources Deleted**: {del_count}",
                f"- **Resources Failed**: {fail_count}",
            ])
            if cleanup_result.errors:
                md_lines.append(f"- **Errors**: {'; '.join(cleanup_result.errors)}")
            md_lines.append("")
        else:
            md_lines.extend(["*No cleanup operations recorded.*", ""])

        md_path = run_dir / "report.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines))

        return {"json": json_path, "markdown": md_path}
