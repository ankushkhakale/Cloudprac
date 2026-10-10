"""Rich terminal user interface styling and layout for CloudPrac."""

from typing import Any, Dict, List, Optional

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
        elif meta.status == PracticalStatus.CONFIGURED:
            status_badge = "[bold green]CONFIGURED[/bold green]"
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
        "\n[dim]* Note: P01 is a local VMware/Ubuntu virtualization lab. Modules P02–P04 and P06–P08 remain in [yellow]NOT CONFIGURED[/yellow] status.[/dim]\n"
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
    body.append("Module ID: ", style="bold cyan")
    body.append(f"{pid}\n")
    body.append("Title: ", style="bold cyan")
    body.append(f"{title}\n")
    body.append("Status: ", style="bold cyan")
    if status == PracticalStatus.NOT_CONFIGURED.value:
        body.append(f"{status}\n", style="bold yellow")
    else:
        body.append(f"{status}\n", style="bold green")

    body.append("\nDescription:\n", style="bold white")
    body.append(f"{description}\n\n")

    if notice:
        body.append(f"Notice: {notice}\n\n", style="yellow")

    if prereqs:
        body.append("Prerequisites:\n", style="bold white")
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


def print_p05_demonstration_guide(
    run_id: str,
    public_ip: str,
    app_port: int = 5000,
    token_file_path: Optional[str] = None,
    key_file_path: Optional[str] = None,
) -> None:
    """Render practical demonstration instructions for students and evaluators.

    Security Requirement:
    Administrative tokens MUST NEVER be transmitted over unencrypted HTTP across the internet.
    Instead, secure administrative operations are demonstrated via encrypted SSH loopback
    or encrypted SSH port-forwarding tunnels.
    """
    url = f"http://{public_ip}:{app_port}"
    key_disp = key_file_path or f"~/.cloudprac/keys/cloudprac-p05-key-{run_id}.pem"
    token_read = f"cat {token_file_path}" if token_file_path else f"cat ~/.cloudprac/runs/{run_id}/admin_token"

    content = Text()
    content.append("🎓 Student Lab Demonstration Guide\n", style="bold green")
    content.append("Your application is operational and sample student records are active in DynamoDB.\n\n", style="white")

    content.append("1. Web Application Public Inspection (Read-Only):\n", style="bold cyan")
    content.append(f"   URL: {url}\n", style="bold white underline")
    content.append(f"   Health Check: curl -s {url}/health\n", style="bold yellow")
    content.append(f"   List Students: curl -s {url}/api/students\n", style="bold yellow")
    content.append(f"   Retrieve Document: curl -s {url}/api/students/STU-001/document\n\n", style="bold yellow")

    content.append("2. Secure Authenticated Administration (Encrypted in Transit):\n", style="bold cyan")
    content.append("   🔒 Security Notice: Admin tokens must NEVER be sent over unencrypted HTTP.\n", style="yellow")
    content.append("   Use either of the two encrypted methods below:\n\n", style="dim")

    content.append("   Method A — Encrypted SSH Remote Execution (Zero Overhead):\n", style="bold green")
    content.append(
        f"   ssh -i {key_disp} ec2-user@{public_ip} \\\n"
        f"     'curl -s -X POST http://127.0.0.1:{app_port}/api/students \\\n"
        f'        -H "Content-Type: application/json" \\\n'
        f"        -H \"X-Admin-Token: $(sudo grep ADMIN_TOKEN /opt/cloudprac/.env | cut -d= -f2)\" \\\n"
        f'        -d \'{{"student_id":"S1099","name":"Demonstration Student","course":"Cloud Computing","year":"4"}}\'\'\n\n',
        style="bold yellow",
    )

    content.append("   Method B — Encrypted SSH Local Port Forwarding Tunnel:\n", style="bold green")
    content.append(
        f"   # 1. Open encrypted SSH background tunnel\n"
        f"   ssh -i {key_disp} -N -L {app_port}:127.0.0.1:{app_port} ec2-user@{public_ip} &\n"
        f"   # 2. Transmit authenticated mutation through encrypted tunnel\n"
        f"   curl -s -X POST http://127.0.0.1:{app_port}/api/students \\\n"
        f'     -H "Content-Type: application/json" \\\n'
        f'     -H "X-Admin-Token: $({token_read})" \\\n'
        f'     -d \'{{"student_id":"S1099","name":"Demonstration Student","course":"Cloud Computing","year":"4"}}\'\n\n',
        style="bold yellow",
    )

    content.append("3. Generate Evidence Report for Lab Submission:\n", style="bold cyan")
    content.append(f"   cloudprac report P05 --run-id {run_id}\n\n", style="bold yellow")

    content.append("4. Clean Up All AWS Resources When Done:\n", style="bold cyan")
    content.append(f"   cloudprac cleanup P05 --run-id {run_id}\n", style="bold red")

    console.print(
        Panel(
            content,
            title=f"Practical P05 Demonstration — Run {run_id}",
            border_style="green",
            padding=(1, 2),
        )
    )
