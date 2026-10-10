"""Configuration models for Practical 05 (Student Record Management using EC2, S3, and DynamoDB)."""

from typing import Optional
from pydantic import BaseModel, Field


class P05Config(BaseModel):
    """Configuration options for Practical 05 execution."""

    region: Optional[str] = Field(
        default=None,
        description="Target AWS Region override (defaults to ambient configuration).",
    )
    instance_type: str = Field(
        default="t2.micro",
        description="EC2 instance type (e.g. t2.micro or t3.micro).",
    )
    ami_id: Optional[str] = Field(
        default=None,
        description="Specific Amazon Linux 2023 AMI ID. If None, auto-discovered via AWS EC2/SSM API.",
    )
    key_name: Optional[str] = Field(
        default=None,
        description="Name of EC2 Key Pair. If None, a deterministic run key pair is created.",
    )
    create_key_pair: bool = Field(
        default=True,
        description="Whether to create an EC2 key pair if key_name is not provided.",
    )
    save_key_file: bool = Field(
        default=True,
        description="Whether to save the downloaded private key file locally to ~/.cloudprac/keys/.",
    )
    app_port: int = Field(
        default=5000,
        description="Port for the student-record management web application on EC2.",
    )
    app_cidr: Optional[str] = Field(
        default=None,
        description="Optional IPv4 CIDR range allowed to access the web application (port 5000).",
    )
    ssh_cidr: Optional[str] = Field(
        default=None,
        description="Optional CIDR IP range to allow SSH access (port 22). Default is no inbound SSH.",
    )
    bucket_name: Optional[str] = Field(
        default=None,
        description="S3 bucket name for student documents. If None, auto-generated using account ID and run ID.",
    )
    table_name: Optional[str] = Field(
        default=None,
        description="DynamoDB table name for student records. If None, auto-generated with run ID.",
    )
    dynamodb_billing_mode: str = Field(
        default="PAY_PER_REQUEST",
        description="DynamoDB billing mode (defaults to PAY_PER_REQUEST for zero idle cost).",
    )
    iam_role_name: Optional[str] = Field(
        default=None,
        description="IAM role name for EC2 instance. If None, auto-generated with run ID.",
    )
    iam_profile_name: Optional[str] = Field(
        default=None,
        description="IAM instance profile name for EC2 instance. If None, auto-generated with run ID.",
    )
