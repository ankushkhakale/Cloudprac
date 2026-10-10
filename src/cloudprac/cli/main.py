import json
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
    region: Optional[str] = typer.Option(None, "--region", "-r", help="Target AWS region override."),
    instance_type: Optional[str] = typer.Option(None, "--instance-type", "-t", help="EC2 instance type override."),
    key_name: Optional[str] = typer.Option(None, "--key-name", "-k", help="EC2 key pair name override."),
    ssh_cidr: Optional[str] = typer.Option(None, "--ssh-cidr", help="Allowed IPv4 CIDR range for SSH ingress."),
) -> None:
    """Generate a dry-run execution plan without modifying any AWS resources."""
    registry = get_registry()
    pid = normalize_practical_id(practical_id)
    practical = registry.get(pid)

    if not practical:
        print_error(f"Practical '{practical_id}' not found.")
        raise typer.Exit(1)

    if hasattr(practical, "p01_config"):
        if region:
            practical.p01_config.region = region
        if instance_type:
            practical.p01_config.instance_type = instance_type
        if key_name:
            practical.p01_config.key_name = key_name
        if ssh_cidr:
            practical.p01_config.ssh_cidr = ssh_cidr

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
    region: Optional[str] = typer.Option(None, "--region", "-r", help="Target AWS region override."),
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="AWS CLI profile name."),
    instance_type: Optional[str] = typer.Option(None, "--instance-type", "-t", help="EC2 instance type override."),
    key_name: Optional[str] = typer.Option(None, "--key-name", "-k", help="EC2 Key pair name override."),
    ssh_cidr: Optional[str] = typer.Option(None, "--ssh-cidr", help="Allowed IPv4 CIDR range for SSH ingress."),
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

    if hasattr(practical, "p01_config"):
        if region:
            practical.p01_config.region = region
        if instance_type:
            practical.p01_config.instance_type = instance_type
        if key_name:
            practical.p01_config.key_name = key_name
        if ssh_cidr:
            practical.p01_config.ssh_cidr = ssh_cidr

    config = load_config()
    target_region = region or config.default_region
    adapter = AWSAdapter(region_name=target_region, profile_name=profile)
    engine = ExecutionEngine(config=config, adapter=adapter)

    # 1. Preview dry-run plan
    plan = engine.planner.plan(practical)
    print_plan_table(plan)

    # 2. Confirmation prompt if not --yes
    if not yes:
        console.print("[bold yellow]Caution:[/bold yellow] This practical will provision real AWS resources in your account.")
        confirmed = typer.confirm("Do you approve this execution plan and wish to proceed?")
        if not confirmed:
            console.print("[dim]Execution cancelled by user. No cloud resources were modified.[/dim]")
            raise typer.Exit(0)

    try:
        result = engine.run_practical(
            practical=practical,
            run_id=plan.run_id,
            auto_verify=not no_verify,
            auto_cleanup=auto_cleanup,
        )
        if result.success:
            print_success(f"Practical {pid} executed successfully. Run ID: {result.run_id}")
            if not no_verify:
                console.print(f"[dim]Use [bold white]cloudprac report {pid} --run-id {result.run_id}[/bold white] to view submission report.[/dim]")
                console.print(f"[dim]When lab demonstration is complete, run [bold white]cloudprac cleanup {pid} --run-id {result.run_id}[/bold white] to destroy provisioned resources.[/dim]\n")
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
    region: Optional[str] = typer.Option(None, "--region", "-r", help="Target AWS region override."),
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="AWS CLI profile name."),
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
    target_region = region or config.default_region
    adapter = AWSAdapter(region_name=target_region, profile_name=profile)
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
    region: Optional[str] = typer.Option(None, "--region", "-r", help="Target AWS region override."),
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="AWS CLI profile name."),
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

    # Preview resources to be deleted
    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        resources = manifest_data.get("resources", [])
        if resources:
            console.print(f"\n[bold yellow]Cleanup Preview for Run '{run_id}':[/bold yellow]")
            for r in resources:
                console.print(f"  • [red]DELETE[/red] {r.get('resource_type')}: [bold]{r.get('resource_id')}[/bold]")
            console.print()
    except Exception as e:
        console.print(f"[dim]Could not preview manifest: {e}[/dim]")

    if not yes:
        confirmed = typer.confirm(f"Are you sure you want to clean up these resources from AWS?")
        if not confirmed:
            console.print("[dim]Cleanup cancelled. Resources were retained.[/dim]")
            raise typer.Exit(0)

    config = load_config()
    target_region = region or config.default_region
    adapter = AWSAdapter(region_name=target_region, profile_name=profile)
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
