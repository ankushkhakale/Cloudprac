# CloudPrac

**CloudPrac** is a reliable, installable Python CLI application engineered for students and instructors to execute, verify, document, and clean up eight AWS Cloud Computing practicals directly within browser-based **AWS CloudShell**.

---

## 1. Vision & Architecture

CloudPrac is built as a complete software engineering application rather than loose shell scripts:

```
cloudprac
├── cli/              # Typer CLI application, commands, and Rich terminal formatting
├── core/             # PracticalContract, registry, execution engine, verifier, cleaner
├── adapters/         # AWS Boto3 adapter layer, preflight diagnostics, ambient IAM identity
├── reporting/        # Structured Markdown & JSON evidence generator
└── utils/            # Config validation, structured file logging, path resolution
```

### Key Principles:
- **CloudShell Native**: Minimal memory footprint, fast startup, zero background daemons or external databases.
- **Ambient Identity**: Uses the active CloudShell IAM identity; never hard-codes or logs credentials.
- **Safety First**: P01–P08 are strict placeholders until the official college syllabus is supplied. Unconfigured modules cannot execute or provision AWS resources.
- **Transparent Planning**: Generates deterministic dry-run plans before executing cloud operations.
- **Deterministic Tracking & Cleanup**: Every resource provisioned by CloudPrac is tagged and recorded in a local run manifest (`~/.cloudprac/runs/<run_id>/manifest.json`). The cleanup engine only deletes resources created by that run, preserving existing infrastructure.
- **Truthful Evidence**: Verification checks real AWS resource states against explicit rubric postconditions without mocked outputs or fabricated evidence.

---

## 2. Quickstart

### Prerequisites
- Python 3.10+
- AWS CloudShell or any environment with AWS CLI v2 and active IAM credentials

### Installation

#### From Source (CloudShell / Local):
```bash
git clone https://github.com/ankushkhakale/Cloudprac.git
cd Cloudprac
pip install .
```

#### Development (Editable Install):
```bash
uv venv .venv
source .venv/bin/activate
uv pip install -e .
```

---

## 3. CLI Command Reference

### Check Version & Environment
```bash
# Display version
cloudprac --version

# Run diagnostic environment preflight
cloudprac preflight
```

### Discover Practicals
```bash
# List all practical modules (P01–P08)
cloudprac list

# Inspect module requirements, description, and status
cloudprac inspect P01
```

### Execution Lifecycle (When Configured)
```bash
# Generate a dry-run execution plan without touching AWS
cloudprac plan P01

# Execute the planned AWS operations
cloudprac run P01

# Run AWS postcondition assertions and verify state
cloudprac verify P01

# Inspect or regenerate submission reports (Markdown and JSON)
cloudprac report P01

# Safely destroy provisioned resources tracked in the run manifest
cloudprac cleanup P01 --run-id P01-20261010-120000-abcd12
```

---

## 4. Current Practical Status (P01–P08)

All 8 practical slots are initialized as **NOT CONFIGURED** placeholders:

| Module ID | Status | Note |
| :--- | :--- | :--- |
| **P01** | `NOT CONFIGURED` | Awaiting university/college syllabus assignment |
| **P02** | `NOT CONFIGURED` | Awaiting university/college syllabus assignment |
| **P03** | `NOT CONFIGURED` | Awaiting university/college syllabus assignment |
| **P04** | `NOT CONFIGURED` | Awaiting university/college syllabus assignment |
| **P05** | `NOT CONFIGURED` | Awaiting university/college syllabus assignment |
| **P06** | `NOT CONFIGURED` | Awaiting university/college syllabus assignment |
| **P07** | `NOT CONFIGURED` | Awaiting university/college syllabus assignment |
| **P08** | `NOT CONFIGURED` | Awaiting university/college syllabus assignment |

> **Safety Guarantee**: Attempting to run, plan, or verify an unconfigured module will immediately halt with a clear explanation, preventing any accidental AWS charges or resource mutations.

---

## 5. Testing & Quality Assurance

All unit tests run **100% offline** without requiring live AWS credentials:

```bash
pytest
```

Run test suite with verbose output:
```bash
.venv/bin/pytest -v
```

---

## 6. License

MIT License. Designed for educational use in Cloud Computing coursework.