"""Sample data definitions for Practical 05: Student Record Management."""

from typing import Any, Dict, List


def get_default_student_records(bucket_name: str = "") -> List[Dict[str, Any]]:
    """Return structured sample student records for DynamoDB insertion."""
    return [
        {
            "student_id": "STU-001",
            "name": "Aarav Sharma",
            "course": "B.Tech Computer Science",
            "email": "aarav.sharma@college.edu",
            "year": "3rd Year",
            "document_key": "documents/STU-001-admission-certificate.txt",
        },
        {
            "student_id": "STU-002",
            "name": "Priya Patel",
            "course": "B.Tech Information Technology",
            "email": "priya.patel@college.edu",
            "year": "3rd Year",
            "document_key": "documents/STU-002-id-verification.txt",
        },
        {
            "student_id": "STU-003",
            "name": "Rohan Verma",
            "course": "M.Tech Cloud Computing",
            "email": "rohan.verma@college.edu",
            "year": "1st Year",
            "document_key": "documents/STU-003-transcript.txt",
        },
    ]


def get_sample_student_document(student_id: str, student_name: str, run_id: str) -> str:
    """Generate sample document text for a student to upload to private S3."""
    return (
        f"====================================================\n"
        f"COLLEGE OF ENGINEERING — STUDENT DOCUMENT ARCHIVE\n"
        f"====================================================\n"
        f"Student ID:     {student_id}\n"
        f"Student Name:   {student_name}\n"
        f"Run Identifier: {run_id}\n"
        f"Document Type:  Admission & Verification Certificate\n"
        f"Storage Tier:   Amazon S3 Private Document Vault\n"
        f"Security Note:  Restricted Access via EC2 Instance Profile\n"
        f"====================================================\n"
        f"This document is cryptographically verified with SHA-256 integrity.\n"
    )
