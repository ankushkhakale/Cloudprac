"""Interactive TUI menu for students in AWS CloudShell."""

import json

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from cloudprac.adapters.aws_client import AWSAdapter
from cloudprac.adapters.preflight import (
    detect_public_ip,
    is_running_in_cloudshell,
    run_preflight_checks,
)
from cloudprac.cli.ui import (
    print_banner,
    print_error,
    print_p05_demonstration_guide,
    print_plan_table,
    print_practicals_table,
    print_preflight_table,
    print_success,
    print_verification_table,
    print_warning,
)
from cloudprac.core.engine import ExecutionEngine
from cloudprac.core.planner import ExecutionPlanner
from cloudprac.core.registry import get_registry
from cloudprac.core.verifier import VerificationEngine
from cloudprac.reporting.generator import ReportGenerator
from cloudprac.utils.config import load_config
from cloudprac.utils.paths import get_run_dir, list_all_runs

console = Console()


def display_menu_header() -> None:
    """Print the interactive main menu header."""
    print_banner(is_cloudshell=is_running_in_cloudshell())
    console.print(
        Panel(
            "[bold white]Welcome to CloudPrac — College Cloud Computing Lab Suite[/bold white]\n"
            "[dim]Automated deployment, verification, and guided demonstration for AWS practicals.[/dim]",
            border_style="cyan",
            padding=(0, 2),
        )
    )


def print_menu_options() -> None:
    """Display the available menu actions."""
    table = Table(
        title="[bold cyan]Available Actions[/bold cyan]",
        border_style="cyan",
        header_style="bold magenta",
        show_header=True,
    )
    table.add_column("Option", style="bold yellow", width=8, justify="center")
    table.add_column("Action", style="bold white", min_width=32)
    table.add_column("Description", style="dim", min_width=40)

    table.add_row("1", "Run Practical P05", "Automate EC2 + S3 + DynamoDB student management lab")
    table.add_row("2", "Preview P05 Plan", "Dry-run preview of AWS resources without deploying")
    table.add_row("3", "Verify Deployment", "Run automated health and state checks on active AWS resources")
    table.add_row("4", "Generate Lab Report", "Produce formatted Markdown & JSON submission report")
    table.add_row("5", "Clean Up Cloud Resources", "Safely destroy resources created during a lab run")
    table.add_row("6", "View Syllabus Practicals", "Inspect all P01–P08 college syllabus practical modules")
    table.add_row("7", "Run Preflight Diagnostics", "Test CloudShell environment, Python, and AWS credentials")
    table.add_row("0", "Exit", "Close CloudPrac")

    console.print(table)
    console.print()


def _resolve_app_cidr() -> str:
    """Prompt or auto-detect student's client IP CIDR."""
    console.print("[dim]Checking public egress IP for security group rule...[/dim]")
    detected = detect_public_ip()
    default_ip = detected or "192.0.2.1/32"

    if detected:
        console.print(f"[bold green]✔ Auto-detected public egress IP:[/bold green] [bold cyan]{detected}[/bold cyan]")
        choice = Prompt.ask(
            "Press Enter to use this IP, or enter custom IPv4 CIDR",
            default=detected,
        )
        return choice.strip()
    else:
        console.print("[yellow]Notice:[/yellow] Could not auto-detect public egress IP (offline or firewall-blocked).")
        choice = Prompt.ask(
            "Enter your client IPv4 CIDR (e.g. 203.0.113.10/32 or test 192.0.2.1/32)",
            default=default_ip,
        )
        return choice.strip()


def menu_run_p05() -> None:
    """Handle end-to-end execution of Practical P05 from interactive menu."""
    registry = get_registry()
    practical = registry.get("P05")
    if not practical:
        print_error("Practical P05 is not found in registry.")
        return

    config = load_config()
    adapter = AWSAdapter(region_name=config.default_region)

    console.print("\n[bold cyan]─── Step 1: Network Access Configuration ───[/bold cyan]")
    app_cidr = _resolve_app_cidr()
    practical.p05_config.app_cidr = app_cidr

    console.print("\n[bold cyan]─── Step 2: Dry-Run Execution Plan ───[/bold cyan]")
    engine = ExecutionEngine(config=config, adapter=adapter)
    plan = engine.planner.plan(practical)
    print_plan_table(plan)

    console.print("[bold yellow]Caution:[/bold yellow] This will provision real AWS resources (EC2, S3, DynamoDB) in your account.")
    if not Confirm.ask("Do you want to proceed with provisioning?", default=True):
        console.print("[dim]Execution cancelled by user. No cloud resources were modified.[/dim]\n")
        return

    console.print("\n[bold cyan]─── Step 3: Executing Cloud Provisioning & Deployment ───[/bold cyan]")
    try:
        result = engine.run_practical(
            practical=practical,
            run_id=plan.run_id,
            auto_verify=True,
            auto_cleanup=False,
        )
        if not result.success:
            print_error(f"Execution encountered errors: {'; '.join(result.errors)}")
            return

        print_success(f"Practical P05 executed successfully! Run ID: [bold white]{result.run_id}[/bold white]")

        # Verification
        console.print("\n[bold cyan]─── Step 4: Automated Verification ───[/bold cyan]")
        verifier = VerificationEngine(adapter)
        verify_res = verifier.verify(practical, result.run_id)
        print_verification_table(verify_res)

        # Generate report
        reporter = ReportGenerator(config)
        report_paths = reporter.generate_report(practical, result.run_id)
        console.print(f"[dim]Evidence report saved to: {report_paths.get('markdown')}[/dim]")

        # Lab Demonstration Guide
        console.print("\n[bold cyan]─── Step 5: Practical Demonstration Guide ───[/bold cyan]")
        public_ip = result.outputs.get("public_ip", "198.51.100.25")
        app_port = result.outputs.get("app_port", 5000)
        run_dir = get_run_dir(result.run_id)
        token_file = run_dir / "admin_token"
        token_path_str = str(token_file) if token_file.exists() else None

        print_p05_demonstration_guide(
            run_id=result.run_id,
            public_ip=public_ip,
            app_port=app_port,
            token_file_path=token_path_str,
            key_file_path=result.outputs.get("key_file"),
        )

        console.print()
        if Confirm.ask("Do you want to clean up all cloud resources now?", default=False):
            console.print("\n[bold red]Executing Immediate Resource Cleanup...[/bold red]")
            cleanup_res = engine.cleaner.cleanup(practical, result.run_id)
            if cleanup_res.success:
                print_success(f"Cleanup completed. Deleted {len(cleanup_res.resources_deleted)} resources.")
            else:
                print_error(f"Cleanup errors: {'; '.join(cleanup_res.errors)}")

    except Exception as e:
        print_error(f"Failed to execute P05: {e}")


def menu_plan_p05() -> None:
    """Generate dry-run plan for P05 without AWS changes."""
    registry = get_registry()
    practical = registry.get("P05")
    if not practical:
        print_error("Practical P05 not found.")
        return

    config = load_config()
    detected = detect_public_ip() or "192.0.2.1/32"
    practical.p05_config.app_cidr = detected

    planner = ExecutionPlanner(config)
    plan = planner.plan(practical)
    print_plan_table(plan)
    console.print(f"[dim]Using candidate CIDR: {detected}. Run option [1] to execute.[/dim]\n")


def menu_verify() -> None:
    """Verify an executed practical run."""
    runs = list_all_runs()
    default_run_id = runs[0]["run_id"] if runs else ""

    if runs:
        console.print("[dim]Recent execution runs:[/dim]")
        for idx, r in enumerate(runs[:5], 1):
            console.print(f"  {idx}. [bold cyan]{r['run_id']}[/bold cyan] ({r['practical_id']}) — {r['resource_count']} resources")
        console.print()

    run_id = Prompt.ask("Enter Run ID to verify", default=default_run_id)
    if not run_id:
        print_error("No Run ID provided.")
        return

    registry = get_registry()
    practical = registry.get("P05")
    config = load_config()
    adapter = AWSAdapter(region_name=config.default_region)
    verifier = VerificationEngine(adapter)

    try:
        res = verifier.verify(practical, run_id)
        print_verification_table(res)
    except Exception as e:
        print_error(f"Verification failed: {e}")


def menu_report() -> None:
    """Generate and display report paths for a run."""
    runs = list_all_runs()
    default_run_id = runs[0]["run_id"] if runs else ""

    run_id = Prompt.ask("Enter Run ID for report generation", default=default_run_id)
    if not run_id:
        print_error("No Run ID provided.")
        return

    registry = get_registry()
    practical = registry.get("P05")
    config = load_config()
    reporter = ReportGenerator(config)

    try:
        paths = reporter.generate_report(practical, run_id)
        print_success(f"Reports generated:\n• Markdown: {paths['markdown']}\n• JSON: {paths['json']}")
    except Exception as e:
        print_error(f"Report generation failed: {e}")


def menu_cleanup() -> None:
    """Display previous runs and perform guarded cleanup."""
    runs = list_all_runs()
    if not runs:
        print_warning("No recorded execution runs found in ~/.cloudprac/runs.")
        return

    table = Table(
        title="[bold yellow]Existing Execution Runs[/bold yellow]",
        border_style="yellow",
        header_style="bold cyan",
    )
    table.add_column("#", justify="center", width=4)
    table.add_column("Run ID", style="bold white", min_width=20)
    table.add_column("Practical", style="cyan", width=10)
    table.add_column("Started At", style="dim", min_width=22)
    table.add_column("Resources", justify="right", width=12)

    for idx, r in enumerate(runs, 1):
        table.add_row(
            str(idx),
            r["run_id"],
            r["practical_id"],
            r["started_at"] or "N/A",
            str(r["resource_count"]),
        )

    console.print(table)
    choice = Prompt.ask("\nEnter number of run to clean up (or 0 to cancel)", default="1")
    if choice == "0" or not choice.isdigit():
        console.print("[dim]Cleanup cancelled.[/dim]\n")
        return

    idx = int(choice) - 1
    if idx < 0 or idx >= len(runs):
        print_error("Invalid selection.")
        return

    selected = runs[idx]
    run_id = selected["run_id"]
    pid = selected["practical_id"]

    # Preview resources from manifest
    run_dir = get_run_dir(run_id)
    manifest_path = run_dir / "manifest.json"
    if manifest_path.is_file():
        try:
            m_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            res_list = m_data.get("resources", [])
            console.print(f"\n[bold yellow]Resources to be deleted for Run '{run_id}':[/bold yellow]")
            for r in res_list:
                console.print(f"  • [red]DELETE[/red] {r.get('resource_type')}: [bold]{r.get('resource_id')}[/bold]")
            console.print()
        except Exception as e:
            console.print(f"[dim]Could not read manifest preview: {e}[/dim]")

    if not Confirm.ask(f"Are you sure you want to delete all resources for run '{run_id}'?", default=False):
        console.print("[dim]Cleanup cancelled. Resources preserved.[/dim]\n")
        return

    registry = get_registry()
    practical = registry.get(pid) or registry.get("P05")
    config = load_config()
    adapter = AWSAdapter(region_name=config.default_region)
    engine = ExecutionEngine(config=config, adapter=adapter)

    res = engine.cleaner.cleanup(practical, run_id)
    if res.success:
        print_success(f"Cleanup completed successfully. Deleted {len(res.resources_deleted)} resources.")
    else:
        print_error(f"Cleanup encountered issues: {'; '.join(res.errors)}")


def interactive_menu() -> None:
    """Primary interactive CLI loop for students."""
    display_menu_header()

    while True:
        try:
            print_menu_options()
            choice = Prompt.ask("[bold cyan]Enter choice (0–7)[/bold cyan]", choices=["0", "1", "2", "3", "4", "5", "6", "7"], default="1")

            if choice == "1":
                menu_run_p05()
            elif choice == "2":
                menu_plan_p05()
            elif choice == "3":
                menu_verify()
            elif choice == "4":
                menu_report()
            elif choice == "5":
                menu_cleanup()
            elif choice == "6":
                print_practicals_table(get_registry().list_all())
            elif choice == "7":
                config = load_config()
                adapter = AWSAdapter(region_name=config.default_region)
                report = run_preflight_checks(adapter)
                print_preflight_table(report)
            elif choice == "0":
                console.print("\n[bold cyan]Goodbye![/bold cyan] Have a great lab session.\n")
                break

            console.print("\n" + "─" * 60 + "\n")
        except (KeyboardInterrupt, EOFError):
            console.print("\n\n[dim]Exiting CloudPrac menu.[/dim]\n")
            break
