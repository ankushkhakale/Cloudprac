# CloudPrac v0.1.0 — Preview 1

CloudPrac is a Python CLI project designed to help students automate
and explore cloud-computing practicals.

## What's included

- CLI commands for listing and inspecting practicals.
- Planning and execution workflows for configured practicals.
- P05: Student Record Management using EC2, S3 and DynamoDB.
- Verification, reporting and resource-cleanup workflows.
- Offline automated tests.

## Current limitations

- P05 has been tested with mocked AWS services, not a complete live AWS deployment.
- P02–P04 and P06–P08 are listed but are not yet configured for full automation.
- AWS provisioning has not been verified end to end.
- AWS resources may incur charges. Review the plan before provisioning.

## Requirements

- Python version supported by the package metadata.
- AWS CLI/Boto3 configuration and appropriate IAM permissions for AWS operations.

## Safety

Use your own AWS account and credentials. Never share AWS access keys
or admin tokens. Review planned resources and clean up resources after
your lab session.

This is an early preview intended for feedback and educational testing.
