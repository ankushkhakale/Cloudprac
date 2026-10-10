# CloudPrac

**CloudPrac** is a reliable, installable Python CLI application engineered for students and instructors to execute, verify, document, and clean up AWS Cloud Computing practicals directly within browser-based **AWS CloudShell**.

---

## 1. Vision & Architecture

CloudPrac is built as a complete software engineering application rather than loose shell scripts:

```
cloudprac
├── cli/              # Typer CLI application, commands, and Rich terminal formatting
├── core/             # PracticalContract, registry, execution engine, verifier, cleaner
├── practicals/       # Concrete practical modules (P01 implemented, P02-P08 extensible)
│   └── p01/          # Practical 01: EC2, S3, and DynamoDB implementation
├── adapters/         # AWS Boto3 adapter layer, preflight diagnostics, ambient IAM identity
├── reporting/        # Structured Markdown & JSON evidence generator
└── utils/            # Config validation, structured file logging, path resolution
```

### Key Principles:
- **CloudShell Native**: Minimal memory footprint, fast startup, zero background daemons or external databases.
- **Ambient Identity**: Uses the active CloudShell IAM identity; never hard-codes or logs credentials.
- **Safety First**: Non-configured practicals (P02–P08) cannot execute or provision cloud resources. All operations require dry-run planning and explicit user approval before cloud provisioning.
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

# Run diagnostic environment preflight (checks Python, AWS CLI, STS identity, storage)
cloudprac preflight
```

### Discover Practicals
```bash
# List all practical modules (P01–P08)
cloudprac list

# Inspect module requirements, description, and status
cloudprac inspect P01
```

### Execution Lifecycle for Practical 01
```bash
# Generate a dry-run execution plan without modifying AWS
cloudprac plan P01

# Run with custom region or instance type options
cloudprac plan P01 --region us-east-1 --instance-type t2.micro

# Execute planned AWS operations (with interactive confirmation)
cloudprac run P01

# Execute non-interactively (for automated lab pipelines)
cloudprac run P01 --yes

# Run AWS postcondition assertions and verify state
cloudprac verify P01 --run-id <run_id>

# Inspect or regenerate submission reports (Markdown and JSON)
cloudprac report P01 --run-id <run_id>

# Preview and safely destroy provisioned resources tracked in the run manifest
cloudprac cleanup P01 --run-id <run_id>
```

---

## 4. Current Practical Status (P01–P08)

| Module ID | Title | Status | Description |
| :--- | :--- | :--- | :--- |
| **P01** | **EC2, S3 and DynamoDB** | **`CONFIGURED`** | **Storage bucket, NoSQL table, and EC2 VM lifecycle** |
| **P02** | Practical P02 | `NOT CONFIGURED` | Awaiting university/college syllabus assignment |
| **P03** | Practical P03 | `NOT CONFIGURED` | Awaiting university/college syllabus assignment |
| **P04** | Practical P04 | `NOT CONFIGURED` | Awaiting university/college syllabus assignment |
| **P05** | Practical P05 | `NOT CONFIGURED` | Awaiting university/college syllabus assignment |
| **P06** | Practical P06 | `NOT CONFIGURED` | Awaiting university/college syllabus assignment |
| **P07** | Practical P07 | `NOT CONFIGURED` | Awaiting university/college syllabus assignment |
| **P08** | Practical P08 | `NOT CONFIGURED` | Awaiting university/college syllabus assignment |

---

## 5. Practical 1: EC2, S3 and DynamoDB Implementation (P01)

### Learning Objectives
1. **Compute**: Discover the latest Amazon Linux 2023 AMI, configure a security group and EC2 key pair, and launch a virtual machine.
2. **Storage**: Provision an Amazon S3 bucket with Block Public Access, upload a sample file, inspect metadata, download, and verify SHA-256 integrity.
3. **Database**: Provision a NoSQL Amazon DynamoDB table with `PAY_PER_REQUEST` billing mode, insert structured items, and retrieve records using `GetItem`.
4. **Verification & Audit**: Independently assert postconditions across all three services.
5. **Clean Rollback**: Destroy only the resources provisioned during the lab run.

### Architecture & Execution Stages

```
Step 1: Security Group ──────> Create VPC Security Group (no open 0.0.0.0/0 ingress)
Step 2: Key Pair ────────────> Create EC2 Key Pair (save ~/.cloudprac/keys/<name>.pem with 0600)
Step 3: EC2 VM ──────────────> Launch Amazon Linux 2023 VM (wait until 'running')
Step 4: S3 Bucket ───────────> Create private bucket with Block Public Access
Step 5: S3 File Ops ─────────> Upload sample file, download, and verify SHA-256 checksum
Step 6: DynamoDB Table ──────> Create NoSQL table with string 'id' partition key
Step 7: DynamoDB Records ────> Insert 3 items and verify retrieval via GetItem
Step 8: Verification ────────> Execute independent assertions across EC2, S3, and DynamoDB
Step 9: Report Generation ───> Write report.md & report.json to ~/.cloudprac/runs/<run_id>/
```

### Minimum Required AWS Permissions (Least Privilege)
To execute Practical 01, the active IAM identity requires:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeVpcs",
        "ec2:DescribeSubnets",
        "ec2:DescribeImages",
        "ec2:DescribeKeyPairs",
        "ec2:CreateKeyPair",
        "ec2:DeleteKeyPair",
        "ec2:DescribeSecurityGroups",
        "ec2:CreateSecurityGroup",
        "ec2:AuthorizeSecurityGroupIngress",
        "ec2:DeleteSecurityGroup",
        "ec2:RunInstances",
        "ec2:DescribeInstances",
        "ec2:TerminateInstances",
        "ec2:CreateTags",
        "s3:CreateBucket",
        "s3:DeleteBucket",
        "s3:HeadBucket",
        "s3:PutPublicAccessBlock",
        "s3:GetPublicAccessBlock",
        "s3:PutBucketTagging",
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket",
        "dynamodb:CreateTable",
        "dynamodb:DescribeTable",
        "dynamodb:DeleteTable",
        "dynamodb:PutItem",
        "dynamodb:GetItem"
      ],
      "Resource": "*"
    }
  ]
}
```

### Security & Cost Considerations
- **No Hardcoded Keys**: The application uses ambient CloudShell credentials or standard AWS profile resolution.
- **Private Key Security**: Generated private keys (`.pem`) are stored in `~/.cloudprac/keys/` with restrictive file permissions (`0600` on POSIX). Keys are **never** logged, printed, or committed to Git.
- **Cost Awareness**:
  - EC2 instance usage is Free Tier eligible on `t2.micro` / `t3.micro`. Hourly compute, EBS, and public IPv4 charges apply if running beyond Free Tier limits.
  - S3 and DynamoDB On-Demand workloads in this practical fall well within AWS Free Tier request limits.
  - **Always execute cleanup** when the practical demonstration is complete:
    ```bash
    cloudprac cleanup P01 --run-id <run_id>
    ```

---

## 6. Testing & Quality Assurance

All unit and mock tests run **100% offline** without requiring live AWS credentials or cloud infrastructure:

```bash
# Run complete test suite (35 tests)
pytest -v
```

### Test Coverage Highlights:
- **CLI Commands**: `list`, `inspect`, `plan`, `run`, `verify`, `report`, `cleanup`, `preflight`.
- **Safety Guards**: Unconfigured practicals (P02–P08) are strictly blocked from execution.
- **P01 EC2**: AMI lookup, VPC discovery, KeyPair creation, Security Group ingress, launch, wait, verify.
- **P01 S3**: Bucket creation (us-east-1 and regional), Block Public Access, file upload/download, SHA-256 integrity.
- **P01 DynamoDB**: Table creation with `PAY_PER_REQUEST`, sample record insertion, `GetItem` consistent read verification.
- **End-to-End Mock**: Full execution, report generation, and guarded cleanup in mock mode.

---

## 7. License

MIT License. Designed for educational use in Cloud Computing coursework.