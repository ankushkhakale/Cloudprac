"""Configuration models for Practical 01 (EC2, S3, DynamoDB)."""

from typing import Optional
from pydantic import BaseModel, Field


class P01Config(BaseModel):
    """Configuration options for Practical 01 execution."""

    region: Optional[str] = Field(
        default=None,
        description="Target AWS Region override (defaults to CloudPrac or ambient configuration).",
    )
    instance_type: str = Field(
        default="t2.micro",
        description="EC2 instance type (e.g. t2.micro or t3.micro).",
    )
    ami_id: Optional[str] = Field(
        default=None,
        description="Specific Amazon Linux 2023 AMI ID. If None, auto-discovered via AWS EC2 API.",
    )
    key_name: Optional[str] = Field(
        default=None,
        description="Name of EC2 Key Pair. If None, a deterministic run key pair is created.",
    )
    ssh_cidr: Optional[str] = Field(
        default=None,
        description="Optional CIDR IP range to allow SSH access (port 22). Default is no inbound SSH.",
    )
    create_key_pair: bool = Field(
        default=True,
        description="Whether to create an EC2 key pair if key_name is not provided.",
    )
    save_key_file: bool = Field(
        default=True,
        description="Whether to save the downloaded private key file locally to ~/.cloudprac/keys/.",
    )
    bucket_name: Optional[str] = Field(
        default=None,
        description="S3 bucket name. If None, auto-generated using account ID and run ID.",
    )
    table_name: Optional[str] = Field(
        default=None,
        description="DynamoDB table name. If None, auto-generated with run ID.",
    )
    dynamodb_billing_mode: str = Field(
        default="PAY_PER_REQUEST",
        description="DynamoDB billing mode (defaults to PAY_PER_REQUEST for zero idle cost).",
    )
