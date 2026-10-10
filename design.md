# CloudPrac — Architecture & Technical Design

## 1. System Overview
CloudPrac is structured as a modular Python package adhering to clean architecture principles:

```
src/cloudprac/
├── __init__.py
├── __version__.py
├── cli/                 # CLI entry point, Typer app, subcommands, formatting
│   ├── __init__.py
│   ├── main.py          # Typer app entry point and command routing
│   ├── commands/        # Subcommands: list, inspect, plan, run, verify, report, cleanup, preflight
│   └── ui.py            # Rich console output, banners, tables, and progress indicators
├── core/                # Core engine, domain models, contracts, and lifecycle
│   ├── __init__.py
│   ├── contract.py      # Abstract PracticalContract interface
│   ├── models.py        # Pydantic/dataclass models (Plan, Result, Manifest, Status)
│   ├── registry.py      # Practical registration, lookup, and discovery
│   ├── planner.py       # Execution planner
│   ├── engine.py        # Controlled execution engine with safety guards
│   ├── verifier.py      # Verification evaluation engine
│   └── cleaner.py       # Scoped cleanup and rollback engine
├── adapters/            # AWS service adapters and CLI abstractions
│   ├── __init__.py
│   ├── aws_client.py    # Boto3 session & client factory with mock support
│   ├── preflight.py     # CloudShell environment, IAM identity, region checks
│   └── cloudformation.py# CloudFormation stack helpers where applicable
├── reporting/           # Report generation and evidence collation
│   ├── __init__.py
│   ├── generator.py     # Markdown and JSON report generator
│   └── evidence.py      # Evidence artifact management
└── utils/               # Common utilities
    ├── __init__.py
    ├── config.py        # Configuration management
    ├── logging.py       # Structured logging to console and disk
    └── paths.py         # Deterministic path resolver (~/.cloudprac/)
```

## 2. Practical Lifecycle & Contract

Every practical must implement the `PracticalContract`:

```python
class PracticalContract(ABC):
    @property
    @abstractmethod
    def metadata(self) -> PracticalMetadata: ...

    @abstractmethod
    def inspect(self) -> PracticalDetails: ...

    @abstractmethod
    def plan(self, config: PracticalConfig) -> ExecutionPlan: ...

    @abstractmethod
    def execute(self, plan: ExecutionPlan, ctx: ExecutionContext) -> ExecutionResult: ...

    @abstractmethod
    def verify(self, ctx: ExecutionContext) -> VerificationResult: ...

    @abstractmethod
    def cleanup(self, manifest: RunManifest, ctx: ExecutionContext) -> CleanupResult: ...
```

### States of a Practical
- `NOT_CONFIGURED` (Placeholder for P01–P08 until real college syllabus is provided)
- `CONFIGURED`
- `PLANNED`
- `EXECUTED`
- `VERIFIED`
- `CLEANED_UP`

Unconfigured practicals are strictly blocked from execution, planning with cloud interaction, verification, and cleanup.

## 3. Storage & Run History
All persistent data resides under `~/.cloudprac/`:
- `~/.cloudprac/config.yaml`: Global student configuration (default AWS region, output format).
- `~/.cloudprac/logs/cloudprac.log`: Structured rotating log file.
- `~/.cloudprac/runs/<run_id>/`:
  - `plan.json`: The execution plan generated prior to run.
  - `manifest.json`: List of AWS resource ARNs/IDs provisioned during execution with timestamps and tags.
  - `result.json`: Execution output and step status.
  - `verification.json`: Real AWS assertions and outcome.
  - `report.md`: Markdown summary report for submission.
  - `report.json`: Machine-readable report.

## 4. Resource Tagging & Ownership
All AWS resources provisioned by CloudPrac MUST include mandatory tags:
- `ManagedBy`: `CloudPrac`
- `PracticalId`: e.g. `P01`
- `RunId`: `<run_uuid>`
- `CreatedAt`: `<iso8601_timestamp>`

The cleanup engine relies on the run manifest combined with these tags to prevent deleting pre-existing or external AWS resources.

## 5. Security & CloudShell Constraints
- Always uses ambient AWS credentials (instance profile / CloudShell IAM identity via default Boto3 session).
- Never requests, parses, or logs AWS access keys or secret keys.
- Read-only operations (`list`, `inspect`, `preflight`, offline `plan`) make zero mutation API calls.
- Mutation commands require affirmative terminal confirmation unless explicit `--yes` is provided in non-interactive pipelines.
