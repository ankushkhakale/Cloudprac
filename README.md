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
| **P05** | **EC2, S3 and DynamoDB Implementation: Student Record Management** | AWS Cloud (EC2, S3, DynamoDB) | **`CONFIGURED`** | Unverified exact cost (Free Tier eligible resources + billable public IPv4) |
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
   - In-Transit Encryption: HTTPS/TLS enforced via bucket policy (`aws:SecureTransport: "false"` Deny condition).
   - At-Rest Server-Side Encryption: Amazon S3-managed keys (`AES256` / SSE-S3 default encryption; does not claim or require custom KMS keys or client-side encryption).
   - Least-Privilege Scoping: EC2 instance role has read-only `s3:GetObject` on `secrets/*`, while `s3:PutObject` is strictly scoped to `documents/*`.
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

### One-Command AWS CloudShell Experience (Recommended for Students)

Open **AWS CloudShell** in the AWS Management Console and execute:
```bash
bash <(curl -sSL https://raw.githubusercontent.com/ankushkhakale/Cloudprac/main/install.sh)
```
Or clone and run the installer locally:
```bash
git clone https://github.com/ankushkhakale/Cloudprac.git
cd Cloudprac
./install.sh
```

The installer verifies your Python environment (3.10+), installs CloudPrac to your user path (`~/.local/bin`), verifies active ambient IAM credentials, and immediately launches the **CloudPrac Interactive Menu**.

#### Development / Local Install:
```bash
git clone https://github.com/ankushkhakale/Cloudprac.git
cd Cloudprac
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

---

## 5. Student Workflow: Interactive TUI Menu

Running `cloudprac` without subcommands in an interactive terminal (or explicitly via `cloudprac menu`) opens the student lab suite:

```
  [1] Run Practical P05        — Fully automated EC2 + S3 + DynamoDB student management lab
  [2] Preview P05 Plan         — Dry-run preview of AWS resources without deploying
  [3] Verify Deployment        — Run automated health and state assertions on active AWS resources
  [4] Generate Lab Report      — Produce formatted Markdown & JSON submission report
  [5] Clean Up Cloud Resources — Safely destroy resources created during a lab run
  [6] View Syllabus Practicals — Inspect all P01–P08 college syllabus practical modules
  [7] Run Preflight Diagnostics— Test CloudShell environment, Python, and AWS credentials
  [0] Exit
```

### Automatic Egress IP Discovery & Restricted Security Groups
Students do not need to look up their public IP address manually. CloudPrac automatically contacts AWS `checkip.amazonaws.com`, validates the public IPv4 address, and provisions the Security Group ingress rule strictly for `<your-ip>/32`. Students can accept the detected IP with one keystroke (Enter) or pass a custom CIDR. Broad `0.0.0.0/0` exposure is strictly rejected.

---

## 6. Step-by-Step CLI Workflow (Command-Line Mode)

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
cloudprac plan P05 --app-cidr <your-ip>/32
```
Options available:
- `--region <region>`: AWS Region (e.g. `us-east-1`, default: `us-east-1`)
- `--instance-type <type>`: EC2 instance type (default: `t2.micro`)
- `--app-port <port>`: Application port (default: `5000`)
- `--app-cidr <cidr>`: Inbound IPv4 CIDR restriction for web app (**REQUIRED**: Must be an explicit restricted CIDR such as `<your-ip>/32` or your VPC CIDR. Broad `0.0.0.0/0` access is strictly blocked to protect student records. Alias: `--cidr <cidr>`.)
- `--ssh-cidr <cidr>`: Inbound IPv4 CIDR restriction for SSH port 22 (default: `127.0.0.1/32`)

### Step 4: Execute P05 (Provision & Deploy)
```bash
# Interactive execution (prompts for confirmation before creating cloud resources)
cloudprac run P05 --app-cidr <your-ip>/32

# Non-interactive execution (for automated testing / scripted labs)
cloudprac run P05 --app-cidr <your-ip>/32 --yes
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

### Web Application Authentication & Access Control
- **Inbound CIDR Restriction**: Application port 5000 is restricted exclusively to the administrator-specified `--app-cidr` (e.g. `203.0.113.10/32` or your VPC CIDR). Public ingress (`0.0.0.0/0`) is strictly rejected.
- **Admin Authentication**: Mutating API operations (`POST`, `PUT`, `DELETE`) require token authentication via the `X-Admin-Token` header or `Authorization: Bearer <token>`. Query-string authentication (`?token=...`) is strictly rejected to prevent credentials from being recorded in web access logs.
- **Secure Secret Delivery**: The admin token is never embedded in EC2 user data, bootstrap scripts, or console logs. For each run, a unique 32-byte cryptographically secure token is generated, stored in the private S3 bucket, and fetched at runtime by the EC2 instance using attached IAM instance profile credentials.
- **Local Credential Storage**: The token is saved locally to `~/.cloudprac/runs/<run_id>/admin_token` with `0600` permissions (restricted strictly to the current user).
- **Encrypted Administrative Access**: Administrative tokens must **never** be sent over unencrypted HTTP across the internet. Use either of the two low-friction, secure methods:
  ```bash
  # Method A: Encrypted SSH Remote Execution (Zero overhead, token never leaves host)
  ssh -i ~/.cloudprac/keys/<key_name>.pem ec2-user@<EC2-IP> \
    'curl -s -X POST http://127.0.0.1:5000/api/students \
       -H "Content-Type: application/json" \
       -H "X-Admin-Token: $(sudo grep ADMIN_TOKEN /opt/cloudprac/.env | cut -d= -f2)" \
       -d "{\"student_id\": \"STU-105\", \"name\": \"Kavya Menon\", \"course\": \"B.Tech CS\"}"'

  # Method B: Encrypted SSH Local Port Forwarding Tunnel
  ssh -i ~/.cloudprac/keys/<key_name>.pem -N -L 5000:127.0.0.1:5000 ec2-user@<EC2-IP> &
  curl -s -X POST http://127.0.0.1:5000/api/students \
    -H "Content-Type: application/json" \
    -H "X-Admin-Token: $(cat ~/.cloudprac/runs/<run_id>/admin_token)" \
    -d '{"student_id": "STU-105", "name": "Kavya Menon", "course": "B.Tech CS"}'
  ```

### S3 Data Protection & Encryption Disclosures
- **In-Transit Encryption**: All communication between clients, the EC2 instance, and Amazon S3 uses HTTPS/TLS. Furthermore, an explicit bucket policy is attached to the private S3 bucket denying any requests where `aws:SecureTransport` is `false`.
- **Default Server-Side Encryption (SSE-S3)**: Amazon S3 automatically applies default server-side encryption with Amazon S3-managed AES-256 keys (`AES256` / SSE-S3). No customer-managed AWS KMS keys (SSE-KMS) or client-side cryptography are configured or claimed, avoiding KMS pricing overhead while meeting AWS baseline security benchmarks.
- **Block Public Access**: All four S3 Block Public Access settings (`BlockPublicAcls`, `IgnorePublicAcls`, `BlockPublicPolicy`, `RestrictPublicBuckets`) are enforced on bucket creation.
- **Least-Privilege Scoping**: The attached EC2 IAM instance profile is strictly scoped: `s3:GetObject` on `secrets/*` (read-only token access), `s3:PutObject` strictly on `documents/*` (prevents overwriting or tampering with tokens), and `s3:ListBucket` on the bucket root.

### Cost Transparency & Disclosures
- **Unverified Exact Cost**: CloudPrac does not guarantee that practical deployments are free or will cost less than $0.05. Actual charges depend on individual account Free Tier status, AWS pricing regions, and runtime.
- **Billable Public IPv4 Addresses**: Since February 2024, AWS charges ~$0.005/hour for all public IPv4 addresses attached to EC2 instances across all accounts, including Free Tier accounts.
- **Standard Service Rates**: EC2 compute (`t2.micro` / `t3.micro`), EBS root volume (8 GB gp3), Amazon S3 storage/requests, and Amazon DynamoDB operations consume account allowances or incur standard AWS on-demand charges.
- **Cost Minimization**: Always run `cloudprac cleanup P05 --run-id <run_id>` immediately after finishing laboratory demonstration and verification.

### Partial Failure Recovery & Fail-Closed Cleanup Ownership
CloudPrac implements incremental manifest checkpointing at every resource creation stage:
1. **Stage 1 (S3 Bucket & Object)**: Bucket, initial document, and admin token are tracked in `manifest.json`.
2. **Stage 2 (DynamoDB Table & Records)**: Table and sample items are appended and checkpointed.
3. **Stage 3 (IAM Role & Instance Profile)**: Profile and role are appended and checkpointed.
4. **Stage 4 (Security Group & Key Pair)**: Networking resources are appended and checkpointed.
5. **Stage 5 (EC2 Virtual Machine)**: Instance ID is appended and checkpointed.

If a failure or interruption occurs at any stage (e.g. EC2 launch fails due to regional capacity), running:
```bash
cloudprac cleanup P05 --run-id <run_id>
```
reads the checkpointed manifest and cleanly dismantles every resource created up to the point of failure.

**Ownership & Deletion Safety**:
- **Affirmative Tag Matching**: Cleanup verifies `ManagedBy == 'CloudPrac'` and `RunId == <run_id>` before destroying any EC2 instance, security group, key pair, S3 bucket, DynamoDB table, or IAM role/profile.
- **Fail-Closed on Missing or Mismatched Tags**: Resources lacking tags or tagged with a different RunId are strictly skipped.
- **Fail-Closed on API Inspection Errors**: If describing or reading tags encounters an error (e.g. `AccessDenied` or network timeout), the cleanup engine immediately aborts deletion of that resource to prevent accidental data loss.
- **Secret Object & Local Credential Cleanup**: The S3 secret token object (`secrets/<run_id>/admin_token`) and local restricted credential file (`~/.cloudprac/runs/<run_id>/admin_token`) are cleanly deleted upon cleanup completion.

---

## 7. Testing & Quality Assurance

All unit and mock tests run **100% offline** without live credentials:

```bash
.venv/bin/pytest -v
```

### Test Suite Highlights (59 tests passing):
- **CLI Suite**: `list`, `inspect`, `plan`, `run`, `verify`, `report`, `cleanup`, `preflight`.
- **Registry & Safety**: P01 local virtualization notice and safety blocking, unconfigured practicals P02–P04 and P06–P08 strictly prevented from planning or execution.
- **P05 Modules**:
  - `ec2.py`: AMI dynamic lookup, VPC/subnet resolution, CIDR validation rules, security group rules, EC2 launch, state polling, user-data bootstrap script generation.
  - `s3.py`: Bucket creation with regional LocationConstraint handling, Block Public Access, TLS bucket policy enforcement, upload, download, and SHA-256 integrity hashing.
  - `dynamodb.py`: Table creation, active waiting, CRUD operations (`PutItem`, `GetItem`, `UpdateItem`, `DeleteItem`).
  - `iam.py`: Least-privilege IAM policy generation (scoped document/secret statements), instance profile lifecycle, independent resource cleanup.
  - `web_app.py`: Real Flask application with token authentication, file extension verification, sanitized error responses, `/health`, `/api/students`, and document endpoints tested via Flask test client.
- **Security & Failure Regressions**:
  - S3 bucket policy TLS in-transit encryption enforcement (`aws:SecureTransport: "false"` Deny).
  - IAM least-privilege scoping: token object is read-only, PutObject restricted to `documents/*`.
  - Fail-closed cleanup: untagged resources and mismatched RunIds strictly refused across EC2, S3, DynamoDB, and IAM.
  - Cleanup ownership API errors fail closed without deleting resources.
  - Local admin token file (`0600`) safely deleted during cleanup.
  - Run manifests strictly verify zero raw admin token exposure.
  - Public CIDR rejection (`0.0.0.0/0`), plan side-effect prevention, error sanitization.
- **Full End-to-End Mock Lifecycle**: Tests planner, engine, verifier, reporter, and cleaner through `ExecutionEngine` in mock mode.

---

## 8. License

MIT License. Designed for educational use in Cloud Computing coursework.