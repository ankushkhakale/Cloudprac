"""CloudPrac CLI entry point and command router using Typer."""

import sys
from typing import Optional
import typer
from rich.console import Console

from cloudprac.__version__ import __version__
from cloudprac.adapters.aws_client import AWSAdapter
from cloudprac.adapters.preflight import is_running_in_cloudshell, run_preflight_checks
from cloudprac.cli.ui import (
    print_banner,
    print_error,
    print_inspect_panel,
    print_plan_table,
    print_practicals_table,
    print_preflight_table,
    print_success,
    print_verification_table,
    print_warning,
)
from cloudprac.core.contract import PracticalNotConfiguredError
from cloudprac.core.engine import ExecutionEngine
from cloudprac.core.models import PracticalStatus
from cloudprac.core.planner import ExecutionPlanner
from cloudprac.core.registry import get_registry, normalize_practical_id
from cloudprac.core.verifier import VerificationEngine
from cloudprac.reporting.generator import ReportGenerator
from cloudprac.utils.config import load_config, save_config
from cloudprac.utils.logging import setup_logging
from cloudprac.utils.paths import get_run_dir

app = typer.Typer(
    name="cloudprac",
    help="AWS Cloud Computing Practical Automation Engine for AWS CloudShell.",
    no_args_is_help=False,
    add_completion=False,
)

console = Console()


def version_callback(value: bool) -> None:
    """Print application version and exit."""
    if value:
        console.print(f"[bold cyan]CloudPrac[/bold cyan] version [bold white]{__version__}[/bold white]")
        raise typer.Exit(0)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-v",
        help="Show CloudPrac version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Enable detailed debug logging.",
    ),
) -> None:
    """CloudPrac — AWS Cloud Computing Practical Automation Engine."""
    setup_logging(verbose=verbose)
    if ctx.invoked_subcommand is None:
        print_banner(is_cloudshell=is_running_in_cloudshell())
        console.print("[dim]Use [bold white]cloudprac --help[/bold white] or [bold white]cloudprac list[/bold white] to view available practicals.[/dim]\n")


@app.command("list")
def list_practicals() -> None:
    """List all college Cloud Computing practical modules (P01–P08)."""
    registry = get_registry()
    practicals = registry.list_all()
    print_banner(is_cloudshell=is_running_in_cloudshell())
    print_practicals_table(practicals)


@app.command("inspect")
def inspect_practical(
    practical_id: str = typer.Argument(..., help="Practical ID (e.g. P01, P02, 1)"),
) -> None:
    """Inspect requirements, prerequisites, and syllabus status of a practical."""
    registry = get_registry()
    pid = normalize_practical_id(practical_id)
    practical = registry.get(pid)

    if not practical:
        print_error(f"Practical '{practical_id}' not found. Available IDs: {', '.join(registry.list_ids())}")
        raise typer.Exit(1)

    details = practical.inspect()
    print_inspect_panel(details)


@app.command("plan")
def plan_practical(
    practical_id: str = typer.Argument(..., help="Practical ID (e.g. P01, 1)"),
) -> None:
    """Generate a dry-run execution plan without modifying any AWS resources."""
    registry = get_registry()
    pid = normalize_practical_id(practical_id)
    practical = registry.get(pid)

    if not practical:
        print_error(f"Practical '{practical_id}' not found.")
        raise typer.Exit(1)

    config = load_config()
    planner = ExecutionPlanner(config)

    try:
        plan = planner.plan(practical)
        print_plan_table(plan)
    except PracticalNotConfiguredError as e:
        print_warning(str(e))
        console.print(
            "\n[dim]Accidental AWS resource creation was safely prevented.\n"
            "Provide the official syllabus assignment statement to configure this practical.[/dim]\n"
        )
        raise typer.Exit(1)


@app.command("run")
def run_practical(
    practical_id: str = typer.Argument(..., help="Practical ID (e.g. P01, 1)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt for safe execution."),
    no_verify: bool = typer.Option(False, "--no-verify", help="Skip automatic verification after execution."),
    auto_cleanup: bool = typer.Option(False, "--cleanup", help="Trigger cleanup immediately after run."),
) -> None:
    """Safely execute a practical's AWS operations."""
    registry = get_registry()
    pid = normalize_practical_id(practical_id)
    practical = registry.get(pid)

    if not practical:
        print_error(f"Practical '{practical_id}' not found.")
        raise typer.Exit(1)

    if practical.metadata.status == PracticalStatus.NOT_CONFIGURED:
        print_warning(
            f"Practical {pid} is NOT CONFIGURED.\n\n"
            "Official college requirements have not yet been provided.\n"
            "Execution is locked to prevent creating unintentional AWS resources."
        )
        raise typer.Exit(1)

    config = load_config()
    adapter = AWSAdapter(region_name=config.default_region)
    engine = ExecutionEngine(config=config, adapter=adapter)

    try:
        result = engine.run_practical(
            practical=practical,
            auto_verify=not no_verify,
            auto_cleanup=auto_cleanup,
        )
        if result.success:
            print_success(f"Practical {pid} executed successfully. Run ID: {result.run_id}")
        else:
            print_error(f"Execution encountered errors: {'; '.join(result.errors)}")
            raise typer.Exit(1)
    except Exception as e:
        print_error(f"Failed to run practical {pid}: {e}")
        raise typer.Exit(1)


@app.command("verify")
def verify_practical(
    practical_id: str = typer.Argument(..., help="Practical ID (e.g. P01, 1)"),
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Specific run ID to verify against."),
) -> None:
    """Verify postcondition states on AWS for an executed practical."""
    registry = get_registry()
    pid = normalize_practical_id(practical_id)
    practical = registry.get(pid)

    if not practical:
        print_error(f"Practical '{practical_id}' not found.")
        raise typer.Exit(1)

    if practical.metadata.status == PracticalStatus.NOT_CONFIGURED:
        print_warning(
            f"Practical {pid} is NOT CONFIGURED.\n\n"
            "No postconditions or assertions are defined for this placeholder."
        )
        raise typer.Exit(1)

    config = load_config()
    adapter = AWSAdapter(region_name=config.default_region)
    verifier = VerificationEngine(adapter)

    try:
        active_run_id = run_id or f"{pid}-verify"
        result = verifier.verify(practical, active_run_id)
        print_verification_table(result)
        if not result.success:
            raise typer.Exit(1)
    except Exception as e:
        print_error(f"Verification failed: {e}")
        raise typer.Exit(1)


@app.command("report")
def report_practical(
    practical_id: str = typer.Argument(..., help="Practical ID (e.g. P01, 1)"),
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Run ID of the execution."),
) -> None:
    """Inspect or generate Markdown and JSON reports for a run."""
    registry = get_registry()
    pid = normalize_practical_id(practical_id)
    practical = registry.get(pid)

    if not practical:
        print_error(f"Practical '{practical_id}' not found.")
        raise typer.Exit(1)

    config = load_config()
    reporter = ReportGenerator(config)

    active_run_id = run_id or f"{pid}-latest"
    paths = reporter.generate_report(practical, active_run_id)

    print_success(f"Evidence reports generated:\n- Markdown: {paths['markdown']}\n- JSON: {paths['json']}")


@app.command("cleanup")
def cleanup_practical(
    practical_id: str = typer.Argument(..., help="Practical ID (e.g. P01, 1)"),
    run_id: str = typer.Option(..., "--run-id", help="Required Run ID whose manifest should be cleaned."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Safely destroy only the AWS resources provisioned during a specific run."""
    registry = get_registry()
    pid = normalize_practical_id(practical_id)
    practical = registry.get(pid)

    if not practical:
        print_error(f"Practical '{practical_id}' not found.")
        raise typer.Exit(1)

    if practical.metadata.status == PracticalStatus.NOT_CONFIGURED:
        print_warning(
            f"Practical {pid} is NOT CONFIGURED.\n"
            "No tracked resources exist for this placeholder module."
        )
        raise typer.Exit(1)

    run_dir = get_run_dir(run_id)
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        print_error(f"No run manifest found for Run ID '{run_id}'. Refusing unmanifested cleanup.")
        raise typer.Exit(1)

    if not yes:
        confirmed = typer.confirm(f"Are you sure you want to clean up resources from run {run_id}?")
        if not confirmed:
            console.print("[dim]Cleanup cancelled.[/dim]")
            raise typer.Exit(0)

    config = load_config()
    adapter = AWSAdapter(region_name=config.default_region)
    engine = ExecutionEngine(config=config, adapter=adapter)

    cleanup_res = engine.cleaner.cleanup(practical, run_id)
    if cleanup_res.success:
        print_success(f"Cleanup completed. Deleted {len(cleanup_res.resources_deleted)} resources.")
    else:
        print_error(f"Cleanup encountered issues: {'; '.join(cleanup_res.errors)}")
        raise typer.Exit(1)


@app.command("preflight")
def preflight() -> None:
    """Run diagnostics on AWS CloudShell environment, Python, and credentials."""
    config = load_config()
    adapter = AWSAdapter(region_name=config.default_region)
    report = run_preflight_checks(adapter)
    print_banner(is_cloudshell=report.is_cloudshell)
    print_preflight_table(report)

    if report.all_passed:
        print_success("Environment preflight checks passed. Ready for CloudPrac operations.")
    else:
        print_warning("Some environment checks did not pass. Check diagnostics above.")


if __name__ == "__main__":
    app()
