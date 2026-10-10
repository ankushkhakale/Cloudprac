# CloudPrac — Product Goals & Roadmap

## 1. Product Vision
CloudPrac is a single, installable Python CLI/TUI application designed to help college students execute, verify, document, and clean up eight AWS Cloud Computing practicals directly inside browser-based AWS CloudShell.

The goal is to deliver a dependable engineering platform, not a loose collection of ad-hoc bash scripts.

## 2. Core Goals
- **Single Entry Point**: Student runs `cloudprac` or subcommands (`list`, `inspect`, `plan`, `run`, `verify`, `report`, `cleanup`).
- **CloudShell Native**: Lightweight footprint, fast startup, zero heavyweight background daemons, zero external database requirements.
- **Strict Safety**: Read-only commands never mutate AWS state. Destructive or billable actions require explicit user confirmation.
- **Transparent Planning**: Every practical execution generates a deterministic dry-run plan detailing proposed operations, expected resources, and estimated cost implications.
- **Resource Tracking & Rollback**: All created resources are deterministically named, tagged, and recorded in a local run manifest. The cleanup engine safely destroys only resources created by the run.
- **Truthful Verification**: Verification inspects real AWS resource states against actual rubric postconditions. No mocked outcomes or fabricated evidence.
- **Automated Evidence & Reporting**: Generates clean Markdown and JSON reports with configuration parameters, AWS identifiers, timestamped check results, and execution logs.
- **Extensible Registry**: A clean `PracticalContract` interface allowing future practicals (P01–P08) to plug in without modifying core engine logic.

## 3. Non-Goals
- Do NOT invent or fabricate arbitrary AWS practical definitions prior to official syllabus submission.
- Do NOT support multi-cloud (AWS only).
- Do NOT maintain external persistent databases (PostgreSQL, SQLite daemons, Docker containers). Local file-based runs under `~/.cloudprac/` are standard.
- Do NOT perform real AWS operations during offline unit testing or local packaging checks.

## 4. Implementation Milestones

### Milestone 0: Workspace Discovery & Foundation Architecture (Current)
- Review workspace specifications, inspect Git & GitHub MCP context.
- Document baseline architecture, safety rules, and implementation sequence.
- Establish acceptance criteria.

### Milestone 1: Application Foundation & CLI Architecture
- Setup standard Python packaging (`pyproject.toml`, console script `cloudprac`).
- Typer CLI framework with Rich terminal rendering.
- Registry discovery for P01–P08 marked clearly as `NOT CONFIGURED` placeholders.
- Preflight environment check command (`cloudprac preflight`).
- Local run storage and logging initialization under `~/.cloudprac/`.

### Milestone 2: Safe Execution Framework & Core Abstractions
- Implementation of `PracticalContract`, `ExecutionPlan`, `ExecutionResult`, `VerificationResult`.
- Guarded execution engine with dry-run capabilities.
- AWS Service Adapter abstraction with mocked client support.
- Evidence and report generator (Markdown + JSON).
- Guarded cleanup engine backed by resource run manifests.

### Milestone 3: Automated Quality & Mocked Test Suite
- Comprehensive pytest test suite covering CLI commands, registry lookups, parameter validation, execution guards, and reporting.
- 100% offline execution safety: no live AWS credentials required.
- Isolation testing with clean virtual environment validation.

### Milestone 4: Packaging & CloudShell Documentation
- Production-ready packaging setup.
- Step-by-step AWS CloudShell installation and execution guide.
- Security and permission documentation.

### Milestone 5: Practical Implementation (Upon syllabus delivery)
- Incrementally implement P01 through P08 once actual college assignment specifications are provided.
