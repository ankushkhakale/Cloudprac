# CloudPrac v0.1.0 — Product Completion Sprint (Preview 1)

CloudPrac is an AWS Cloud Computing Practical Automation Engine engineered specifically for students and instructors running directly in **AWS CloudShell**.

## What's Included

- **One-Command CloudShell Installer (`install.sh`)**: Sets up Python runtime, checks ambient AWS STS credentials, configures PATH, and launches the student menu in a single command.
- **Interactive Student TUI Menu (`cloudprac menu` or `cloudprac`)**: Clean, numbered Rich interface providing 1-click execution, dry-run planning, verification, lab reporting, and cleanup.
- **Automated Network Security Discovery**: Auto-detects the student's public egress IP via AWS CheckIP service with a 2-second timeout and locks EC2 security groups to `<client-ip>/32`. Public `0.0.0.0/0` exposure is blocked.
- **Reference Implementation — Practical P05 (Student Record Management)**:
  - Automates DynamoDB table creation, schema setup, and initial sample student records.
  - Provisions private S3 bucket with Block Public Access, SSE-S3 encryption, and TLS-enforcing bucket policies.
  - Launches EC2 instance with Amazon Linux 2023, least-privilege IAM profile, and systemd Flask application.
  - Secure out-of-band admin token generation and delivery via private S3 and local restricted files (`0600`).
- **Interactive Student Lab Demonstration Guide**: Formatted panel presenting exact `curl` commands to test API health, query DynamoDB records, test authenticated student creation, retrieve S3 documents, and clean up.
- **Run Discovery & Cleanup**: Discovers previous runs from `~/.cloudprac/runs/`, displays resource counts, and allows one-click guarded teardown.
- **Comprehensive Offline Test Suite**: 67 automated unit and integration tests covering positive flows, network failures, timeouts, ownership validation, and security boundaries.

## Current Limitations & Notes

- P05 is tested extensively offline with mocked AWS adapters; live end-to-end testing should be conducted with appropriate IAM permissions in a sandbox AWS account.
- P01 is designated as a local VMware virtualization lab. P02–P04 and P06–P08 remain locked in `NOT CONFIGURED` status until college syllabus specifications are provided.
- AWS resources (particularly public IPv4 addresses) may incur small hourly charges. Always perform cleanup when evaluation is finished.

## Safety & Security

- Zero credentials logged or committed to Git.
- Least-privilege IAM policies scoped strictly to run-specific ARNs.
- Guarded cleanup strictly refuses to delete resources without matching ownership tags.
