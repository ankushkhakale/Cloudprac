"""Amazon DynamoDB table creation, student record management, verification, and cleanup for Practical 05."""

import time
from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError

from cloudprac.core.models import VerificationCheck
from cloudprac.utils.logging import get_logger

logger = get_logger()


def create_student_table(
    dynamodb_client: Any,
    table_name: str,
    billing_mode: str = "PAY_PER_REQUEST",
    tags: Optional[Dict[str, str]] = None,
) -> str:
    """Create a DynamoDB table for student records with 'student_id' as string partition key."""
    tag_list = [{"Key": k, "Value": v} for k, v in (tags or {}).items()]

    logger.info(
        f"Creating DynamoDB student table '{table_name}' (PartitionKey=student_id, BillingMode={billing_mode})..."
    )
    dynamodb_client.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": "student_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "student_id", "AttributeType": "S"}],
        BillingMode=billing_mode,
        Tags=tag_list if tag_list else [],
    )
    return table_name


def wait_for_table_active(dynamodb_client: Any, table_name: str, max_timeout: int = 120) -> Dict[str, Any]:
    """Poll until DynamoDB table status transitions to 'ACTIVE'."""
    start_time = time.time()
    while time.time() - start_time < max_timeout:
        resp = dynamodb_client.describe_table(TableName=table_name)
        table_desc = resp.get("Table", {})
        status = table_desc.get("TableStatus")
        if status == "ACTIVE":
            logger.info(f"DynamoDB table '{table_name}' is ACTIVE.")
            return table_desc
        time.sleep(3)

    raise TimeoutError(f"DynamoDB table '{table_name}' did not become ACTIVE within {max_timeout}s.")


def insert_student_record(dynamodb_client: Any, table_name: str, record: Dict[str, Any]) -> str:
    """Insert a single student record into the DynamoDB table using PutItem."""
    db_item: Dict[str, Any] = {}
    for key, val in record.items():
        if val is None:
            continue
        if isinstance(val, (int, float)):
            db_item[key] = {"N": str(val)}
        else:
            db_item[key] = {"S": str(val)}

    student_id = str(record.get("student_id", ""))
    logger.info(f"Inserting student record '{student_id}' into '{table_name}'...")
    dynamodb_client.put_item(
        TableName=table_name,
        Item=db_item,
    )
    return student_id


def insert_student_records(dynamodb_client: Any, table_name: str, records: List[Dict[str, Any]]) -> int:
    """Insert multiple student records into the DynamoDB table."""
    count = 0
    for rec in records:
        insert_student_record(dynamodb_client, table_name, rec)
        count += 1
    return count


def get_student_record(dynamodb_client: Any, table_name: str, student_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a student record by student_id primary key using strongly consistent reads."""
    resp = dynamodb_client.get_item(
        TableName=table_name,
        Key={"student_id": {"S": student_id}},
        ConsistentRead=True,
    )
    raw = resp.get("Item")
    if not raw:
        return None

    # Unmarshal DynamoDB format back to plain python dict
    plain: Dict[str, Any] = {}
    for k, v in raw.items():
        if "S" in v:
            plain[k] = v["S"]
        elif "N" in v:
            plain[k] = int(v["N"]) if "." not in v["N"] else float(v["N"])
        else:
            plain[k] = str(v)
    return plain


def list_student_records(dynamodb_client: Any, table_name: str) -> List[Dict[str, Any]]:
    """Scan and list student records from the DynamoDB table."""
    resp = dynamodb_client.scan(TableName=table_name)
    items = resp.get("Items", [])
    records: List[Dict[str, Any]] = []
    for raw in items:
        plain: Dict[str, Any] = {}
        for k, v in raw.items():
            if "S" in v:
                plain[k] = v["S"]
            elif "N" in v:
                plain[k] = int(v["N"]) if "." not in v["N"] else float(v["N"])
            else:
                plain[k] = str(v)
        records.append(plain)
    return records


def update_student_record(
    dynamodb_client: Any,
    table_name: str,
    student_id: str,
    updates: Dict[str, Any],
) -> Dict[str, Any]:
    """Update fields of an existing student record."""
    update_expr_parts = []
    expr_names = {}
    expr_values = {}

    for i, (k, v) in enumerate(updates.items()):
        if k == "student_id":
            continue
        placeholder_key = f"#k{i}"
        placeholder_val = f":v{i}"
        update_expr_parts.append(f"{placeholder_key} = {placeholder_val}")
        expr_names[placeholder_key] = k
        if isinstance(v, (int, float)):
            expr_values[placeholder_val] = {"N": str(v)}
        else:
            expr_values[placeholder_val] = {"S": str(v)}

    if not update_expr_parts:
        return get_student_record(dynamodb_client, table_name, student_id) or {}

    update_expression = "SET " + ", ".join(update_expr_parts)
    resp = dynamodb_client.update_item(
        TableName=table_name,
        Key={"student_id": {"S": student_id}},
        UpdateExpression=update_expression,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
        ReturnValues="ALL_NEW",
    )
    raw = resp.get("Attributes", {})
    plain: Dict[str, Any] = {}
    for k, v in raw.items():
        if "S" in v:
            plain[k] = v["S"]
        elif "N" in v:
            plain[k] = int(v["N"]) if "." not in v["N"] else float(v["N"])
        else:
            plain[k] = str(v)
    return plain


def delete_student_record(dynamodb_client: Any, table_name: str, student_id: str) -> bool:
    """Delete a student record by student_id primary key."""
    dynamodb_client.delete_item(
        TableName=table_name,
        Key={"student_id": {"S": student_id}},
    )
    return True


def verify_dynamodb_resources(
    dynamodb_client: Any,
    table_name: str,
    expected_students: List[Dict[str, Any]],
) -> List[VerificationCheck]:
    """Perform independent verification on DynamoDB table status, partition key, and student records."""
    checks: List[VerificationCheck] = []

    # 1. Verify Table Existence and ACTIVE Status
    try:
        desc = dynamodb_client.describe_table(TableName=table_name)
        tbl = desc.get("Table", {})
        status = tbl.get("TableStatus")
        key_schema = tbl.get("KeySchema", [])
        hash_key = next((k["AttributeName"] for k in key_schema if k.get("KeyType") == "HASH"), None)
        billing_mode = tbl.get("BillingModeSummary", {}).get("BillingMode", tbl.get("BillingMode", "UNKNOWN"))

        checks.append(
            VerificationCheck(
                check_id=f"dynamodb-active-{table_name}",
                name="DynamoDB Table ACTIVE Status",
                description="Verify DynamoDB table status is ACTIVE",
                passed=status == "ACTIVE",
                expected="TableStatus == 'ACTIVE'",
                actual=f"TableStatus is '{status}'",
            )
        )
        checks.append(
            VerificationCheck(
                check_id=f"dynamodb-schema-{table_name}",
                name="DynamoDB Schema (Partition Key student_id)",
                description="Verify partition key is string student_id",
                passed=hash_key == "student_id",
                expected="Partition key 'student_id'",
                actual=f"Partition key is '{hash_key}'",
            )
        )
        checks.append(
            VerificationCheck(
                check_id=f"dynamodb-billing-{table_name}",
                name="DynamoDB Billing Mode (PAY_PER_REQUEST)",
                description="Verify on-demand billing mode to prevent idle cost",
                passed=billing_mode == "PAY_PER_REQUEST",
                expected="BillingMode == 'PAY_PER_REQUEST'",
                actual=f"BillingMode is '{billing_mode}'",
            )
        )
    except Exception as e:
        checks.append(
            VerificationCheck(
                check_id=f"dynamodb-active-{table_name}",
                name="DynamoDB Table Inspection",
                description="Verify DynamoDB table exists and is accessible",
                passed=False,
                expected=f"Table '{table_name}' active and accessible",
                actual=f"DescribeTable failed: {e}",
            )
        )
        return checks

    # 2. Verify Sample Student Records via Consistent GetItem
    for expected in expected_students:
        sid = expected.get("student_id", "")
        try:
            item = get_student_record(dynamodb_client, table_name, sid)
            if not item:
                checks.append(
                    VerificationCheck(
                        check_id=f"dynamodb-student-{sid}",
                        name=f"DynamoDB Student Record: {sid}",
                        description=f"Verify student record {sid} exists",
                        passed=False,
                        expected=f"Record {sid} found in table",
                        actual=f"Record {sid} was not returned by GetItem",
                    )
                )
            else:
                name_match = item.get("name") == expected.get("name")
                course_match = item.get("course") == expected.get("course")
                all_match = name_match and course_match
                checks.append(
                    VerificationCheck(
                        check_id=f"dynamodb-student-{sid}",
                        name=f"DynamoDB Student Record: {sid}",
                        description=f"Verify student record {sid} contents match sample",
                        passed=all_match,
                        expected=f"Student '{expected.get('name')}', Course '{expected.get('course')}'",
                        actual=f"Student '{item.get('name')}', Course '{item.get('course')}'",
                    )
                )
        except Exception as e:
            checks.append(
                VerificationCheck(
                    check_id=f"dynamodb-student-{sid}",
                    name=f"DynamoDB Student Record: {sid}",
                    description=f"Verify student record {sid} exists",
                    passed=False,
                    expected=f"Record {sid} verified",
                    actual=f"Error querying {sid}: {e}",
                )
            )


    return checks


def cleanup_dynamodb_resources(
    dynamodb_client: Any,
    table_name: str,
    expected_run_id: Optional[str] = None,
) -> List[str]:
    """Delete the DynamoDB table cleanly.

    Enforces ownership validation against expected_run_id and handles already-deleted tables idempotently.
    """
    deleted: List[str] = []

    # Verify ownership before deletion
    if expected_run_id:
        try:
            desc = dynamodb_client.describe_table(TableName=table_name)
            table_arn = desc.get("Table", {}).get("TableArn")
            if not table_arn:
                logger.error(
                    f"Could not retrieve TableArn for table '{table_name}'. "
                    "Skipping deletion to prevent accidental destruction."
                )
                return []
            tags_resp = dynamodb_client.list_tags_of_resource(ResourceArn=table_arn)
            tags = {t["Key"]: t["Value"] for t in tags_resp.get("Tags", [])}
            is_owned = tags.get("ManagedBy") == "CloudPrac" and tags.get("RunId") == expected_run_id
            if not is_owned:
                logger.error(
                    f"Ownership check failed for DynamoDB table '{table_name}': "
                    f"Tags {tags} do not verify ownership (expected ManagedBy=CloudPrac, RunId={expected_run_id}). "
                    "Skipping deletion to prevent accidental destruction."
                )
                return []
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code in ("ResourceNotFoundException", "TableNotFoundException"):
                logger.info(f"DynamoDB table '{table_name}' not found. Already cleaned up.")
                return []
            logger.error(
                f"Ownership check failed for DynamoDB table '{table_name}': {e}. "
                "Skipping deletion to prevent accidental destruction."
            )
            return []
        except Exception as e:
            logger.error(
                f"Unexpected error inspecting tags on table '{table_name}': {e}. "
                "Skipping deletion to prevent accidental destruction."
            )
            return []

    try:
        logger.info(f"Deleting DynamoDB table '{table_name}'...")
        dynamodb_client.delete_table(TableName=table_name)
        deleted.append(f"dynamodb-table:{table_name}")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in ("ResourceNotFoundException", "TableNotFoundException"):
            logger.info(f"DynamoDB table '{table_name}' already gone.")
        else:
            logger.error(f"Failed to delete DynamoDB table '{table_name}': {e}")
            raise
    return deleted
