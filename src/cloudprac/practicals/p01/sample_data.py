"""Sample data definitions for Practical 01 (S3 and DynamoDB)."""

from typing import Any, Dict, List


def get_default_dynamodb_items() -> List[Dict[str, Any]]:
    """Return structured sample records for DynamoDB insertion."""
    return [
        {
            "id": "item-001",
            "name": "Notebook",
            "category": "stationery",
            "quantity": 10,
            "unit_price": "4.99",
        },
        {
            "id": "item-002",
            "name": "USB-C Cable",
            "category": "accessories",
            "quantity": 25,
            "unit_price": "12.50",
        },
        {
            "id": "item-003",
            "name": "Lab Journal",
            "category": "stationery",
            "quantity": 5,
            "unit_price": "8.75",
        },
    ]


def get_sample_file_content(run_id: str, student_name: str = "") -> str:
    """Generate sample file text to upload to Amazon S3."""
    return (
        f"CloudPrac Practical 01: S3 Storage Demonstration\n"
        f"Run Identifier: {run_id}\n"
        f"Student: {student_name or 'Cloud Computing Lab Student'}\n"
        f"Description: This file verifies Amazon S3 object storage upload, metadata retrieval, "
        f"listing, downloading, and SHA-256 integrity comparison.\n"
    )
