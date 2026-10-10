"""DynamoDB table creation, record insertion, verification, and cleanup for Practical 01."""

import time
from typing import Any, Dict, List, Optional, Tuple
from botocore.exceptions import ClientError

from cloudprac.core.models import VerificationCheck
from cloudprac.utils.logging import get_logger

logger = get_logger()


def create_dynamodb_table(
    dynamodb_client: Any,
    table_name: str,
    billing_mode: str = "PAY_PER_REQUEST",
    tags: Optional[Dict[str, str]] = None,
) -> str:
    """Create a DynamoDB table with string partition key 'id' and On-Demand billing."""
    tag_list = [{"Key": k, "Value": v} for k, v in (tags or {}).items()]

    logger.info(f"Creating DynamoDB table '{table_name}' with BillingMode={billing_mode}...")
    dynamodb_client.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
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


def insert_sample_records(dynamodb_client: Any, table_name: str, items: List[Dict[str, Any]]) -> int:
    """Insert structured sample items into the DynamoDB table using PutItem."""
    inserted_count = 0
    for raw_item in items:
        # Convert raw dictionary to DynamoDB wire format
        db_item: Dict[str, Any] = {}
        for key, val in raw_item.items():
            if isinstance(val, (int, float)):
                db_item[key] = {"N": str(val)}
            else:
                db_item[key] = {"S": str(val)}

        logger.info(f"Inserting item '{raw_item.get('id')}' into '{table_name}'...")
        dynamodb_client.put_item(
            TableName=table_name,
            Item=db_item,
        )
        inserted_count += 1

    return inserted_count


def retrieve_record(dynamodb_client: Any, table_name: str, item_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve an item by primary key using strongly consistent reads."""
    resp = dynamodb_client.get_item(
        TableName=table_name,
        Key={"id": {"S": item_id}},
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


def verify_dynamodb_resources(
    dynamodb_client: Any,
    table_name: str,
    expected_items: List[Dict[str, Any]],
) -> List[VerificationCheck]:
    """Perform independent verification on DynamoDB table status and retrieved record contents."""
    checks: List[VerificationCheck] = []

    # 1. Table existence & status check
    try:
        desc_resp = dynamodb_client.describe_table(TableName=table_name)
        table_desc = desc_resp.get("Table", {})
        status = table_desc.get("TableStatus", "UNKNOWN")
        arn = table_desc.get("TableArn", "UNKNOWN")

        checks.append(
            VerificationCheck(
                check_id="DDB-01",
                name="DynamoDB Table Status",
                description="Verify NoSQL database table status is ACTIVE",
                expected="ACTIVE",
                actual=status,
                passed=(status == "ACTIVE"),
                evidence={"TableArn": arn, "TableStatus": status},
            )
        )
    except Exception as e:
        checks.append(
            VerificationCheck(
                check_id="DDB-01",
                name="DynamoDB Table Status",
                description="Verify NoSQL database table status is ACTIVE",
                expected="ACTIVE",
                actual=f"Error: {e}",
                passed=False,
            )
        )
        return checks

    # 2. Key schema verification check
    key_schema = table_desc.get("KeySchema", [])
    has_id_hash = any(k.get("AttributeName") == "id" and k.get("KeyType") == "HASH" for k in key_schema)
    checks.append(
        VerificationCheck(
            check_id="DDB-02",
            name="DynamoDB Partition Key Schema",
            description="Verify partition key is string 'id'",
            expected="id (HASH)",
            actual="id (HASH)" if has_id_hash else str(key_schema),
            passed=has_id_hash,
        )
    )

    # 3. Item retrieval and value assertion check
    retrieved_all = True
    for item in expected_items:
        item_id = item["id"]
        retrieved = retrieve_record(dynamodb_client, table_name, item_id)
        if not retrieved or retrieved.get("name") != item.get("name"):
            retrieved_all = False
            break

    checks.append(
        VerificationCheck(
            check_id="DDB-03",
            name="DynamoDB Record Insertion & Retrieval",
            description="Verify sample records were stored and retrieved with GetItem",
            expected=f"{len(expected_items)} verified records",
            actual=f"{len(expected_items)} records verified" if retrieved_all else "Record mismatch",
            passed=retrieved_all,
            evidence={"VerifiedRecordsCount": len(expected_items)},
        )
    )

    return checks


def cleanup_dynamodb_resources(dynamodb_client: Any, table_name: str) -> Tuple[List[str], List[str]]:
    """Safely delete the practical DynamoDB table."""
    deleted: List[str] = []
    failed: List[str] = []

    try:
        logger.info(f"Deleting DynamoDB table '{table_name}'...")
        dynamodb_client.delete_table(TableName=table_name)
        deleted.append(f"DynamoDB Table: {table_name}")
    except Exception as e:
        logger.error(f"Failed to delete DynamoDB table {table_name}: {e}")
        failed.append(f"DynamoDB Table {table_name}: {e}")

    return deleted, failed
