# CloudPrac — Product Goals & Roadmap

## 1. Product Vision
CloudPrac is a single, installable Python CLI application designed to help college students execute, verify, document, and clean up AWS Cloud Computing practicals directly inside browser-based AWS CloudShell or local development environments.

The goal is to deliver a dependable engineering platform, not a loose collection of ad-hoc bash scripts.

## 2. Core Goals
- **Single Entry Point**: Student runs `cloudprac` with intuitive subcommands (`list`, `inspect`, `plan`, `run`, `verify`, `report`, `cleanup`).
- **Authoritative Syllabus Alignment**: Registry reflects the 8 official practicals (P01–P08).
- **Clear Execution Boundaries**: P01 is documented as a local VMware/Ubuntu practical; P05 is the first end-to-end AWS cloud practical.
- **CloudShell Native**: Lightweight footprint, fast startup, zero heavyweight background daemons, zero external database requirements.
- **Strict Safety**: Read-only commands never mutate AWS state. Destructive or billable actions require explicit user confirmation.
- **Transparent Planning**: Every practical execution generates a deterministic dry-run plan detailing proposed operations, expected resources, and estimated cost implications.
- **Resource Tracking & Rollback**: All created resources are deterministically named, tagged, and recorded in a local run manifest. The cleanup engine safely destroys only resources created by the run.
- **Truthful Verification**: Verification inspects real AWS resource states and live application health against actual rubric postconditions. No mocked outcomes or fabricated evidence.
- **Automated Evidence & Reporting**: Generates clean Markdown and JSON reports with configuration parameters, AWS identifiers, timestamped check results, and execution logs.
- **Extensible Architecture**: A clean `PracticalContract` interface allowing future practicals to plug in without modifying core engine logic.

## 3. Authoritative Practical Syllabus

1. **P01 — Installation and Configuration of Virtualization Architecture**: Local VMware Workstation Pro + Ubuntu virtualization practical.
2. **P02 — Customer Data Management**: Cloud database management (awaiting specification).
3. **P03 — Employee Attendance System**: Cloud attendance system (awaiting specification).
4. **P04 — Online Billing System**: Cloud billing and sales records (awaiting specification).
5. **P05 — EC2, S3 and DynamoDB Implementation: Student Record Management**: College student details in DynamoDB, student documents in S3, and web application on EC2. **(IMPLEMENTED)**
6. **P06 — EC2, S3 and DynamoDB Implementation: Employee Record Management**: Corporate employee records on AWS (awaiting specification).
7. **P07 — EC2, S3 and DynamoDB Implementation: Library Management**: Library book records and files on AWS (awaiting specification).
8. **P08 — Implementation of the CIA Model**: Confidentiality, integrity, and availability on isolated Linux / EC2 target (awaiting specification).

## 4. Implementation Status
- **P05 (Student Record Management)**: Completed end to end. Includes Boto3 adapters for EC2, S3, DynamoDB, and IAM, a responsive Flask web app running under systemd on Amazon Linux 2023, independent assertions across all three services, evidence reporting, and scoped cleanup.
- **P01**: Documented as local virtualization; safely prevented from cloud execution.
- **P02–P04, P06–P08**: Kept in `NOT CONFIGURED` status with `Not estimated` cost until respective college assignment workflows are designed.
