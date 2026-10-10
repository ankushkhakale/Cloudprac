"""Rich terminal user interface styling and layout for CloudPrac."""

from typing import Any, Dict, List
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from cloudprac.__version__ import __version__
from cloudprac.adapters.preflight import PreflightReport
from cloudprac.core.contract import PracticalContract
from cloudprac.core.models import ExecutionPlan, PracticalStatus, VerificationResult

console = Console()


def print_banner(is_cloudshell: bool = False) -> None:
    """Print the CloudPrac terminal header banner."""
    title_text = Text()
    title_text.append("☁ CloudPrac ", style="bold cyan")
    title_text.append(f"v{__version__}", style="dim")
    title_text.append(" — AWS Cloud Computing Practical Automation Engine\n", style="bold white")

    env_badge = "[bold green]AWS CloudShell[/bold green]" if is_cloudshell else "[dim]Local/Dev Environment[/dim]"
    title_text.append(f"Runtime: {env_badge}  |  Provider: [bold yellow]AWS[/bold yellow]", style="white")

    console.print(Panel(title_text, border_style="cyan", padding=(0, 2)))


def print_practicals_table(practicals: List[PracticalContract]) -> None:
    """Render table of all registered practical modules."""
    table = Table(
        title="AWS Cloud Computing Practicals (Syllabus Modules)",
        border_style="cyan",
        header_style="bold magenta",
    )
    table.add_column("ID", style="bold cyan", width=6)
    table.add_column("Title", style="white", min_width=32)
    table.add_column("Status", justify="center", width=18)
    table.add_column("Est. Cost", justify="right", width=14)
    table.add_column("AWS Services", style="dim", min_width=20)

    for p in practicals:
        meta = p.metadata
        if meta.status == PracticalStatus.NOT_CONFIGURED:
            status_badge = "[yellow]NOT CONFIGURED[/yellow]"
        elif meta.status == PracticalStatus.VERIFIED:
            status_badge = "[bold green]VERIFIED[/bold green]"
        elif meta.status == PracticalStatus.EXECUTED:
            status_badge = "[bold blue]EXECUTED[/bold blue]"
        else:
            status_badge = f"[cyan]{meta.status.value}[/cyan]"

        services_str = ", ".join(meta.aws_services) if meta.aws_services else "[dim]pending[/dim]"
        table.add_row(
            meta.id,
            meta.title,
            status_badge,
            meta.estimated_cost,
            services_str,
        )

    console.print(table)
    console.print(
        "\n[dim]* Note: Modules P01–P08 remain in [yellow]NOT CONFIGURED[/yellow] status "
        "until college practical instructions are provided.[/dim]\n"
    )


def print_inspect_panel(details: Dict[str, Any]) -> None:
    """Render inspection details for a single practical."""
    pid = details.get("id", "Unknown")
    title = details.get("title", "")
    status = details.get("status", "")
    description = details.get("description", "")
    notice = details.get("notice", "")
    prereqs = details.get("prerequisites", [])

    body = Text()
    body.append(f"Module ID: ", style="bold cyan")
    body.append(f"{pid}\n")
    body.append(f"Title: ", style="bold cyan")
    body.append(f"{title}\n")
    body.append(f"Status: ", style="bold cyan")
    if status == PracticalStatus.NOT_CONFIGURED.value:
        body.append(f"{status}\n", style="bold yellow")
    else:
        body.append(f"{status}\n", style="bold green")

    body.append(f"\nDescription:\n", style="bold white")
    body.append(f"{description}\n\n")

    if notice:
        body.append(f"Notice: {notice}\n\n", style="yellow")

    if prereqs:
        body.append(f"Prerequisites:\n", style="bold white")
        for req in prereqs:
            body.append(f"  • {req}\n", style="dim")

    console.print(Panel(body, title=f"Practical Inspection: {pid}", border_style="cyan"))


def print_plan_table(plan: ExecutionPlan) -> None:
    """Render dry-run execution plan steps."""
    table = Table(
        title=f"Execution Plan: {plan.practical_id} (Run ID: {plan.run_id})",
        border_style="yellow",
        header_style="bold yellow",
    )
    table.add_column("Step", justify="center", width=6)
    table.add_column("Action", style="bold cyan", width=22)
    table.add_column("Resource Type", style="white", width=26)
    table.add_column("Resource Name", style="magenta", min_width=20)
    table.add_column("Est. Cost", justify="right", width=12)

    for step in plan.steps:
        table.add_row(
            str(step.step_number),
            step.action,
            step.resource_type,
            step.resource_name,
            step.estimated_cost,
        )

    console.print(table)
    console.print(f"\n[bold]Estimated Total Cost:[/bold] [green]{plan.estimated_total_cost}[/green]")
    if plan.warnings:
        console.print("\n[bold yellow]Warnings / Cautions:[/bold yellow]")
        for w in plan.warnings:
            console.print(f"  [yellow]⚠ {w}[/yellow]")
    console.print()


def print_verification_table(result: VerificationResult) -> None:
    """Render verification assertions and outcomes."""
    status_str = "[bold green]PASSED[/bold green]" if result.success else "[bold red]FAILED[/bold red]"
    table = Table(
        title=f"Verification Report: {result.practical_id} — {status_str}",
        border_style="green" if result.success else "red",
        header_style="bold cyan",
    )
    table.add_column("Check ID", style="bold cyan", width=10)
    table.add_column("Assertion Name", style="white", min_width=25)
    table.add_column("Expected", style="dim", min_width=15)
    table.add_column("Actual", style="dim", min_width=15)
    table.add_column("Result", justify="center", width=10)

    for c in result.checks:
        badge = "[bold green]PASS[/bold green]" if c.passed else "[bold red]FAIL[/bold red]"
        table.add_row(c.check_id, c.name, c.expected, c.actual, badge)

    console.print(table)
    if result.summary:
        console.print(f"\n[dim]{result.summary}[/dim]\n")


def print_preflight_table(report: PreflightReport) -> None:
    """Render environment preflight diagnostics."""
    status_str = "[bold green]READY[/bold green]" if report.all_passed else "[bold yellow]ATTENTION NEEDED[/bold yellow]"
    table = Table(
        title=f"Environment Preflight Diagnostics — {status_str}",
        border_style="cyan",
        header_style="bold magenta",
    )
    table.add_column("Check", style="bold cyan", width=24)
    table.add_column("Status", justify="center", width=10)
    table.add_column("Diagnostic Details", style="white", min_width=40)

    for c in report.checks:
        badge = "[bold green]PASS[/bold green]" if c.passed else (
            "[bold red]FAIL[/bold red]" if c.is_critical else "[yellow]WARN[/yellow]"
        )
        table.add_row(c.name, badge, c.details)

    console.print(table)


def print_error(message: str) -> None:
    """Print error panel."""
    console.print(Panel(f"[bold red]Error:[/bold red] {message}", border_style="red"))


def print_success(message: str) -> None:
    """Print success panel."""
    console.print(Panel(f"[bold green]Success:[/bold green] {message}", border_style="green"))


def print_warning(message: str) -> None:
    """Print warning panel."""
    console.print(Panel(f"[bold yellow]Warning:[/bold yellow] {message}", border_style="yellow"))
