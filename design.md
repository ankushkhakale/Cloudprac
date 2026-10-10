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
│   ├── models.py        # Pydantic models (Plan, Result, Manifest, Status, TrackedResource)
│   ├── registry.py      # Practical registration, lookup, and discovery
│   ├── placeholders.py  # Authoritative syllabus placeholder definitions (P01–P08)
│   ├── planner.py       # Execution planner
│   ├── engine.py        # Controlled execution engine with safety guards
│   ├── verifier.py      # Verification evaluation engine
│   └── cleaner.py       # Scoped cleanup and rollback engine
├── practicals/          # Concrete practical implementations
│   └── p05/             # P05: Student Record Management using EC2, S3, and DynamoDB
│       ├── config.py    # P05Config (regions, instance types, ports, CIDRs, names)
│       ├── sample_data.py # Schema & sample student documents generator
│       ├── s3.py        # Private S3 bucket, BPA, encryption, upload/download, SHA-256
│       ├── dynamodb.py  # DynamoDB table (PAY_PER_REQUEST), CRUD operations, verify
│       ├── iam.py       # Least-privilege IAM policy & EC2 instance profile
│       ├── web_app.py   # Flask student-record management WSGI application
│       ├── ec2.py       # AMI lookup, VPC/subnet, security group, user-data bootstrap, health
│       └── practical.py # P05Practical implementing PracticalContract
├── adapters/            # AWS service adapters and CLI abstractions
│   ├── __init__.py
│   ├── aws_client.py    # Boto3 session & client factory with mock support
│   └── preflight.py     # Environment, IAM identity, and region preflight checks
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
- `NOT_CONFIGURED`: Default state for unimplemented practicals (P02–P04, P06–P08) and local virtualization lab (P01).
- `CONFIGURED`: Fully implemented and validated workflow (P05).
- `PLANNED`: Dry-run execution plan generated.
- `EXECUTED`: AWS resources provisioned and recorded in run manifest.
- `VERIFIED`: Independent postcondition assertions and health checks executed.
- `CLEANED_UP`: Provisioned resources destroyed safely according to manifest.

Unconfigured practicals and local practicals are strictly blocked from cloud planning or execution to prevent unintended actions or billing.

## 3. Storage & Run History
All persistent run artifacts reside under `~/.cloudprac/`:
- `~/.cloudprac/config.yaml`: Global student configuration.
- `~/.cloudprac/logs/cloudprac.log`: Structured rotating log file.
- `~/.cloudprac/keys/`: Restrictive directory (`0600`) for generated EC2 SSH key pairs.
- `~/.cloudprac/runs/<run_id>/`:
  - `plan.json`: The execution plan generated prior to run.
  - `manifest.json`: List of AWS resource ARNs/IDs provisioned during execution with timestamps and tags.
  - `result.json`: Execution output and step status.
  - `verification.json`: Real AWS assertions and outcome.
  - `report.md`: Markdown summary report for lab submission.
  - `report.json`: Machine-readable report.

## 4. Resource Tagging & Ownership
All AWS resources provisioned by CloudPrac MUST include mandatory tags:
- `ManagedBy`: `CloudPrac`
- `PracticalId`: e.g. `P05`
- `RunId`: `<run_uuid>`
- `CreatedAt`: `<iso8601_timestamp>`

The cleanup engine relies on the run manifest combined with these tags to prevent deleting pre-existing or external AWS resources.

## 5. Security & CloudShell Constraints
- Always uses ambient AWS credentials (instance profile / CloudShell IAM identity via default Boto3 session).
- Never requests, parses, or logs AWS access keys or secret keys.
- EC2 applications use least-privilege IAM instance profiles to communicate with S3 and DynamoDB; zero credentials stored in code or user-data.
- Read-only operations (`list`, `inspect`, `preflight`, offline `plan`) make zero mutation API calls.
- Mutation commands require affirmative terminal confirmation unless explicit `--yes` is provided in non-interactive pipelines.
