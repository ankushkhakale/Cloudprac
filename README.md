# CloudPrac

**CloudPrac** is a reliable, installable Python CLI application engineered for students and instructors to execute, verify, document, and clean up AWS Cloud Computing practicals directly within browser-based **AWS CloudShell** or a local development environment.

---

## 1. Vision & Architecture

CloudPrac is built as a complete software engineering application rather than loose shell scripts:

```
cloudprac
├── cli/              # Typer CLI application, subcommands, and Rich terminal formatting
├── core/             # PracticalContract, registry, execution engine, verifier, cleaner
├── practicals/       # Concrete practical modules
│   └── p05/          # P05: Student Record Management using EC2, S3, and DynamoDB
├── adapters/         # AWS Boto3 adapter layer, preflight diagnostics, ambient IAM identity
├── reporting/        # Structured Markdown & JSON evidence generator
└── utils/            # Config validation, structured file logging, path resolution
```

### Key Principles:
- **CloudShell Native**: Minimal memory footprint, fast startup, zero background daemons or external databases.
- **Ambient Identity**: Uses the active CloudShell IAM identity or local AWS credentials; never hard-codes or logs secrets.
- **Strict Safety**: Non-configured practicals (P02–P04, P06–P08) cannot execute or provision cloud resources. All operations require dry-run planning and explicit user approval before cloud provisioning.
- **Local vs Cloud Distinction**: Clearly distinguishes local virtualization labs (P01) from AWS cloud practicals (P05).
- **Deterministic Tracking & Cleanup**: Every resource provisioned by CloudPrac is tagged and recorded in a local run manifest (`~/.cloudprac/runs/<run_id>/manifest.json`). The cleanup engine only deletes resources created by that run, preserving existing infrastructure.
- **Truthful Evidence**: Verification checks real AWS resource states and live application health against explicit rubric postconditions without mocked outputs or fabricated evidence.

---

## 2. Official Syllabus Practicals (P01–P08)

CloudPrac's authoritative registry aligns with the official college curriculum:

| Practical ID | Official Syllabus Title | Execution Target | Status | Cost Estimate |
| :--- | :--- | :--- | :--- | :--- |
| **P01** | **Installation and Configuration of Virtualization Architecture** | Local VMware Workstation Pro + Ubuntu | `NOT CONFIGURED` *(Local lab)* | Not estimated |
| **P02** | **Customer Data Management** | AWS Cloud | `NOT CONFIGURED` | Not estimated |
| **P03** | **Employee Attendance System** | AWS Cloud | `NOT CONFIGURED` | Not estimated |
| **P04** | **Online Billing System** | AWS Cloud | `NOT CONFIGURED` | Not estimated |
| **P05** | **EC2, S3 and DynamoDB Implementation: Student Record Management** | AWS Cloud (EC2, S3, DynamoDB) | **`CONFIGURED`** | Free Tier eligible *(< $0.05)* |
| **P06** | **EC2, S3 and DynamoDB Implementation: Employee Record Management** | AWS Cloud | `NOT CONFIGURED` | Not estimated |
| **P07** | **EC2, S3 and DynamoDB Implementation: Library Management** | AWS Cloud | `NOT CONFIGURED` | Not estimated |
| **P08** | **Implementation of the CIA Model** | Isolated Linux / EC2 | `NOT CONFIGURED` | Not estimated |

### Local Virtualization vs AWS Cloud Execution
- **P01** is a local hypervisor laboratory requiring VMware Workstation Pro and an Ubuntu ISO on the student's personal computer. It demonstrates CPU, network, and storage virtualization. It **does not run inside AWS CloudShell** and does not provision AWS resources. The CLI explicitly protects students by blocking cloud planning or execution for P01.
- **P05** is the first fully configured and implemented AWS cloud workflow.

---

## 3. Practical P05: Student Record Management (EC2, S3, DynamoDB)

### Problem Statement
A college wants to store student details in DynamoDB, upload student documents to S3, and use EC2 to run a simple application for managing student records.

### Architecture & Components

```
                   ┌──────────────────────────────────────────────┐
                   │                  Amazon EC2                  │
                   │      Amazon Linux 2023 (t2.micro/t3.micro)   │
                   │                                              │
Student / Browser ─┼─► Port 5000: Flask Web App (systemd service) │
(Restricted CIDR)  │                                              │
                   │   Attached IAM Role (Least Privilege)        │
                   └───────────────┬──────────────────────┬───────┘
                                   │                      │
                                   ▼                      ▼
                     ┌──────────────────┐    ┌─────────────────────────┐
                     │    Amazon S3     │    │     Amazon DynamoDB     │
                     │  Private Bucket  │    │      Students Table     │
                     │   (BPA + SSE)    │    │ (student_id, PAY_PER_REQ)│
                     └──────────────────┘    └─────────────────────────┘
```

1. **Amazon DynamoDB (Database)**:
   - Table name: `cloudprac-p05-students-<run_id>`
   - Partition Key: `student_id` (String)
   - Billing Mode: `PAY_PER_REQUEST` (On-Demand; zero idle cost)
   - Schema: `student_id`, `name`, `course`, `email`, `year`, `document_key`
   - Pre-seeded with sample records and validated via CRUD operations (`PutItem`, `GetItem` with ConsistentRead, `UpdateItem`, `DeleteItem`).

2. **Amazon S3 (Document Storage)**:
   - Private bucket: `cloudprac-p05-<account_id>-<run_id>`
   - Block Public Access enabled across all 4 settings.
   - Server-Side Encryption: `AES256` (SSE-S3).
   - Document upload/download with SHA-256 integrity verification.

3. **Amazon EC2 (Compute & Application Hosting)**:
   - Discovers latest official Amazon Linux 2023 AMI dynamically.
   - Uses default VPC and active subnet.
   - Restricted Security Group: opens application port `5000` to configured CIDR (`/32` or user CIDR) and optional restricted SSH.
   - Attached **IAM Instance Profile**: grants least-privilege access strictly to the P05 S3 bucket and DynamoDB table. **Zero AWS access keys** in code, user-data, or Git.
   - Automated bootstrap via `user-data` installing Flask and Gunicorn under systemd (`cloudprac-app.service`).

4. **Web Application Functionality**:
   - `GET /health`: Health check endpoint returning status and service metadata.
   - `GET /api/students`: List all student records from DynamoDB.
   - `POST /api/students`: Add new student with input validation.
   - `GET /api/students/<student_id>`: Retrieve specific student.
   - `PUT /api/students/<student_id>`: Update student details.
   - `DELETE /api/students/<student_id>`: Delete student record.
   - `POST /api/students/<student_id>/document`: Upload student document to private S3 and link key in DynamoDB.
   - `GET /api/students/<student_id>/document`: Safely stream student document from S3 via EC2 backend.

---

## 4. Quickstart & Installation

### Prerequisites
- Python 3.10+
- AWS CloudShell or local terminal with AWS CLI v2 and active IAM credentials

### Installation

#### Development / Local Install:
```bash
git clone https://github.com/ankushkhakale/Cloudprac.git
cd Cloudprac
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

---

## 5. Step-by-Step P05 Workflow

### Step 1: Preflight Check
Verify Python environment, AWS CLI, and active STS identity:
```bash
cloudprac preflight
```

### Step 2: Discover and Inspect Practicals
```bash
# List all 8 practicals
cloudprac list

# Inspect P05 details and prerequisites
cloudprac inspect P05

# Inspect P01 local virtualization notice
cloudprac inspect P01
```

### Step 3: Plan P05 (Dry Run)
Generate a 7-step execution plan without modifying AWS:
```bash
cloudprac plan P05
```
Options available:
- `--region <region>`: AWS Region (e.g. `us-east-1`)
- `--instance-type <type>`: EC2 instance type (default: `t2.micro`)
- `--app-port <port>`: Application port (default: `5000`)
- `--app-cidr <cidr>`: Inbound CIDR restriction for web app (default: `0.0.0.0/0`)

### Step 4: Execute P05 (Provision & Deploy)
```bash
# Interactive execution (prompts for confirmation before creating cloud resources)
cloudprac run P05

# Non-interactive execution (for automated testing/CloudShell labs)
cloudprac run P05 --yes
```

CloudPrac will:
1. Create private S3 bucket with Block Public Access and SSE-S3.
2. Upload sample student certificate and compute SHA-256 hash.
3. Create DynamoDB table with `student_id` partition key and insert sample records.
4. Create least-privilege IAM role and EC2 instance profile.
5. Create restricted Security Group and EC2 Key Pair.
6. Launch Amazon Linux 2023 EC2 instance with user-data bootstrap.
7. Record all resources in `~/.cloudprac/runs/<run_id>/manifest.json`.

### Step 5: Verify Deployment
Perform independent state assertions on AWS and verify the web application:
```bash
cloudprac verify P05 --run-id <run_id>
```
Verification performs:
- S3 bucket existence, Block Public Access confirmation, object existence.
- DynamoDB table `ACTIVE` status, schema validation, consistent read, live `UpdateItem` verification.
- EC2 instance `running` state check, instance profile attachment check, and application `/health` check.

### Step 6: Generate Submission Report
```bash
cloudprac report P05 --run-id <run_id>
```
Generates formatted `report.md` and `report.json` in `~/.cloudprac/runs/<run_id>/` with all evidence, resource IDs, and verification results without disclosing credentials.

### Step 7: Guarded Cleanup
Safely destroy only the resources provisioned during this run:
```bash
cloudprac cleanup P05 --run-id <run_id>
```
The cleanup engine previews tracked resources (EC2 instance, security group, key pair, IAM role & profile, S3 objects & bucket, DynamoDB table) and confirms destruction. Pre-existing resources are never touched.

---

## 6. Security, Permissions & Cost Controls

### Minimum IAM Permissions for P05 Execution
To execute P05, the student's IAM identity needs permissions for:
- **EC2**: `DescribeImages`, `DescribeVpcs`, `DescribeSubnets`, `DescribeKeyPairs`, `CreateKeyPair`, `DeleteKeyPair`, `DescribeSecurityGroups`, `CreateSecurityGroup`, `AuthorizeSecurityGroupIngress`, `DeleteSecurityGroup`, `RunInstances`, `DescribeInstances`, `TerminateInstances`, `CreateTags`
- **S3**: `CreateBucket`, `DeleteBucket`, `HeadBucket`, `PutPublicAccessBlock`, `GetPublicAccessBlock`, `PutBucketTagging`, `PutObject`, `GetObject`, `DeleteObject`, `ListBucket`
- **DynamoDB**: `CreateTable`, `DescribeTable`, `DeleteTable`, `PutItem`, `GetItem`, `UpdateItem`, `DeleteItem`, `Scan`
- **IAM**: `CreateRole`, `DeleteRole`, `PutRolePolicy`, `DeleteRolePolicy`, `CreateInstanceProfile`, `DeleteInstanceProfile`, `AddRoleToInstanceProfile`, `RemoveRoleFromInstanceProfile`, `PassRole`

### Cost Transparency
- **EC2 Compute & EBS**: Free Tier eligible (`t2.micro` / `t3.micro` + 8 GB gp3). Note: AWS charges for public IPv4 addresses (~$0.005/hour).
- **S3 & DynamoDB**: On-Demand requests and minimal storage fall well within monthly AWS Free Tier allowances.
- **Total estimated cost for a 30-minute student lab**: Less than **$0.05**.
- **Important**: Always run `cloudprac cleanup P05` after completing evaluation.

---

## 7. Testing & Quality Assurance

All unit and mock tests run **100% offline** without live credentials:

```bash
.venv/bin/pytest -v
```

### Test Suite Highlights (37 tests):
- **CLI Suite**: `list`, `inspect`, `plan`, `run`, `verify`, `report`, `cleanup`, `preflight`.
- **Registry & Safety**: P01 local virtualization notice and safety blocking, unconfigured practicals P02–P04 and P06–P08 strictly prevented from planning or execution.
- **P05 Modules**:
  - `ec2.py`: AMI dynamic lookup, VPC/subnet resolution, security group rules, EC2 launch, state polling, user-data bootstrap script generation.
  - `s3.py`: Bucket creation with regional LocationConstraint handling, Block Public Access, upload, download, and SHA-256 integrity hashing.
  - `dynamodb.py`: Table creation, active waiting, CRUD operations (`PutItem`, `GetItem`, `UpdateItem`, `DeleteItem`).
  - `iam.py`: Least-privilege IAM policy generation, instance profile lifecycle.
  - `web_app.py`: Real Flask application with `/health`, `/api/students`, and document endpoints tested via Flask test client.
- **Full End-to-End Mock Lifecycle**: Tests planner, engine, verifier, reporter, and cleaner through `ExecutionEngine` in mock mode.

---

## 8. License

MIT License. Designed for educational use in Cloud Computing coursework.