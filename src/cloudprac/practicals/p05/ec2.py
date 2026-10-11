"""EC2 provisioning, user-data bootstrap, verification, and cleanup for Practical 05."""

import base64
import ipaddress
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from botocore.exceptions import ClientError

from cloudprac.core.models import (
    VerificationCheck,
)
from cloudprac.utils.logging import get_logger
from cloudprac.utils.paths import get_cloudprac_home, save_restricted_file

logger = get_logger()


def validate_cidr_block(cidr: Optional[str], param_name: str = "app_cidr") -> str:
    """Validate that CIDR is an explicit, restricted IPv4 block.

    Rejects unspecified (None/empty) or broad (/0) CIDRs such as 0.0.0.0/0 to protect student records.
    """
    if not cidr or not cidr.strip():
        raise ValueError(
            f"An explicit restricted IPv4 CIDR is required for {param_name} "
            "(e.g., --app-cidr <your-ip>/32 or your VPC CIDR). An unspecified CIDR is prohibited to protect student records."
        )
    cleaned = cidr.strip()
    try:
        net = ipaddress.ip_network(cleaned, strict=False)
    except ValueError as e:
        raise ValueError(f"Invalid IPv4 CIDR format for {param_name} ('{cleaned}'): {e}") from e

    if net.prefixlen == 0 or cleaned in ("0.0.0.0/0", "::/0"):
        raise ValueError(
            f"Opening application port to the public internet ('{cleaned}') is prohibited "
            "to protect student records. Specify an explicit restricted CIDR (e.g. --app-cidr <your-ip>/32)."
        )
    return cleaned


def get_default_or_first_vpc(ec2_client: Any) -> Tuple[str, str]:
    """Find a default VPC and a subnet that auto-assigns public IPs.

    Returns (vpc_id, subnet_id).  Prefers the default VPC and, within it,
    a subnet whose ``MapPublicIpOnLaunch`` flag is ``True`` so that EC2
    instances automatically receive a public IPv4 address.  Falls back to
    the first available subnet and logs a warning — the caller is responsible
    for explicitly requesting a public IP at launch time.
    """
    try:
        vpcs_resp = ec2_client.describe_vpcs(
            Filters=[{"Name": "isDefault", "Values": ["true"]}]
        )
        vpcs = vpcs_resp.get("Vpcs", [])
        if not vpcs:
            all_vpcs_resp = ec2_client.describe_vpcs()
            vpcs = all_vpcs_resp.get("Vpcs", [])

        if not vpcs:
            raise RuntimeError(
                "No VPC found in the selected AWS Region. "
                "Run 'aws ec2 create-default-vpc' to create a default VPC before continuing."
            )

        vpc_id = vpcs[0]["VpcId"]

        subnets_resp = ec2_client.describe_subnets(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )
        subnets = subnets_resp.get("Subnets", [])
        if not subnets:
            raise RuntimeError(
                f"VPC '{vpc_id}' contains no subnets. At least one subnet is required to launch an EC2 instance."
            )

        # Prefer a subnet that auto-assigns public IPs (MapPublicIpOnLaunch=True)
        public_subnets = [s for s in subnets if s.get("MapPublicIpOnLaunch", False)]
        if public_subnets:
            subnet_id = public_subnets[0]["SubnetId"]
            logger.debug(f"Selected public subnet '{subnet_id}' (MapPublicIpOnLaunch=True) in VPC '{vpc_id}'.")
        else:
            subnet_id = subnets[0]["SubnetId"]
            logger.warning(
                f"No subnet with MapPublicIpOnLaunch=True found in VPC '{vpc_id}'. "
                f"Using subnet '{subnet_id}'. A public IP will be explicitly requested at launch "
                "to ensure external reachability; this requires the subnet to have an Internet Gateway attached."
            )

        return vpc_id, subnet_id
    except ClientError as e:
        logger.error(f"Error querying VPCs/Subnets: {e}")
        raise



def find_latest_al2023_ami(ec2_client: Any, ssm_client: Optional[Any] = None, architecture: str = "x86_64") -> str:
    """Discover the latest available Amazon Linux 2023 AMI without hard-coding."""
    if ssm_client:
        try:
            param_name = f"/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-{architecture}"
            resp = ssm_client.get_parameter(Name=param_name)
            ami_id = resp.get("Parameter", {}).get("Value")
            if ami_id and ami_id.startswith("ami-"):
                return ami_id
        except Exception as e:
            logger.debug(f"SSM AMI lookup failed or not permitted, falling back to DescribeImages: {e}")

    try:
        images_resp = ec2_client.describe_images(
            Owners=["amazon"],
            Filters=[
                {"Name": "name", "Values": [f"al2023-ami-2023.*-{architecture}"]},
                {"Name": "state", "Values": ["available"]},
                {"Name": "image-type", "Values": ["machine"]},
            ],
        )
        images = images_resp.get("Images", [])
        if not images:
            raise RuntimeError(
                f"No available Amazon Linux 2023 AMI found for architecture '{architecture}' in this region."
            )

        images.sort(key=lambda x: x.get("CreationDate", ""), reverse=True)
        return images[0]["ImageId"]
    except ClientError as e:
        logger.error(f"Failed to describe EC2 images: {e}")
        raise


def setup_key_pair(
    ec2_client: Any,
    key_name: str,
    save_local_file: bool = True,
) -> Tuple[str, Optional[Path]]:
    """Create or verify an EC2 key pair, saving private key locally if newly created."""
    keys_dir = get_cloudprac_home() / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)
    local_key_file = keys_dir / f"{key_name}.pem"

    try:
        ec2_client.describe_key_pairs(KeyNames=[key_name])
        logger.info(f"Using existing EC2 Key Pair '{key_name}'.")
        return key_name, local_key_file if local_key_file.exists() else None
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") != "InvalidKeyPair.NotFound":
            raise

    logger.info(f"Creating new EC2 Key Pair '{key_name}'...")
    create_resp = ec2_client.create_key_pair(
        KeyName=key_name,
        KeyType="rsa",
        KeyFormat="pem",
    )
    key_material = create_resp.get("KeyMaterial", "")

    if save_local_file and key_material:
        save_restricted_file(local_key_file, key_material)
        logger.info(f"Saved private key to '{local_key_file}' (permissions: 0600).")
        return key_name, local_key_file

    return key_name, None


def setup_security_group(
    ec2_client: Any,
    group_name: str,
    vpc_id: str,
    app_port: int = 5000,
    app_cidr: Optional[str] = None,
    ssh_cidr: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
) -> str:
    """Create a restricted security group allowing application port (5000) and optional SSH."""
    tag_list = [{"Key": k, "Value": v} for k, v in (tags or {}).items()]

    logger.info(f"Setting up security group '{group_name}' in VPC '{vpc_id}'...")
    try:
        sg_resp = ec2_client.create_security_group(
            GroupName=group_name,
            Description=f"CloudPrac P05 Student Record SG ({group_name})",
            VpcId=vpc_id,
            TagSpecifications=[
                {
                    "ResourceType": "security-group",
                    "Tags": tag_list,
                }
            ] if tag_list else [],
        )
        sg_id = sg_resp["GroupId"]
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "InvalidGroup.Duplicate":
            existing = ec2_client.describe_security_groups(
                Filters=[{"Name": "group-name", "Values": [group_name]}, {"Name": "vpc-id", "Values": [vpc_id]}]
            )
            sg_id = existing["SecurityGroups"][0]["GroupId"]
        else:
            raise

    # Ingress rule for Application port (e.g. 5000)
    # Strictly require explicit, restricted CIDR; broad 0.0.0.0/0 is prohibited
    target_app_cidr = validate_cidr_block(app_cidr, "app_cidr")
    try:
        ec2_client.authorize_security_group_ingress(
            GroupId=sg_id,
            IpPermissions=[
                {
                    "IpProtocol": "tcp",
                    "FromPort": app_port,
                    "ToPort": app_port,
                    "IpRanges": [{"CidrIp": target_app_cidr, "Description": f"CloudPrac P05 Web App (Port {app_port})"}],
                }
            ],
        )
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") != "InvalidPermission.Duplicate":
            raise

    # Inbound SSH rule (Only if explicit restricted CIDR is provided; never open SSH by default)
    if ssh_cidr:
        target_ssh_cidr = validate_cidr_block(ssh_cidr, "ssh_cidr")
        try:
            ec2_client.authorize_security_group_ingress(
                GroupId=sg_id,
                IpPermissions=[
                    {
                        "IpProtocol": "tcp",
                        "FromPort": 22,
                        "ToPort": 22,
                        "IpRanges": [{"CidrIp": target_ssh_cidr, "Description": "CloudPrac SSH Access"}],
                    }
                ],
            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "InvalidPermission.Duplicate":
                raise

    return sg_id


def build_user_data_script(
    table_name: str,
    bucket_name: str,
    region: str,
    app_port: int = 5000,
    token_s3_key: Optional[str] = None,
    admin_token: Optional[str] = None,
) -> str:
    """Generate shell user-data script to bootstrap the student-record Flask app on AL2023.

    Security & Secret Delivery:
    Plaintext admin tokens MUST NEVER be embedded directly into EC2 user-data, bootstrap scripts,
    or console logs (user-data is exposed via IMDS and describe-instance-attribute).
    Instead, the token is delivered via a private S3 object and fetched at runtime using the
    EC2 instance's attached IAM role credentials, writing to /opt/cloudprac/.env (mode 0600).
    Fails closed if a valid token_s3_key is missing or if plaintext token embedding is attempted.
    """
    if admin_token is not None:
        raise ValueError(
            "Embedding admin_token directly in user-data is prohibited to prevent secret leakage. "
            "Use token_s3_key to deliver credentials securely via private S3."
        )

    clean_s3_key = (token_s3_key or "").strip()
    if not clean_s3_key:
        raise ValueError(
            "A secure secret delivery path (token_s3_key) is required to bootstrap the EC2 application. "
            "Failing closed to prevent insecure unauthenticated deployment."
        )

    compact_app = f'''import os, re, boto3
from flask import Flask, jsonify, request, Response

app = Flask(__name__)
table_name = os.environ.get("DYNAMODB_TABLE", "{table_name}")
bucket_name = os.environ.get("S3_BUCKET", "{bucket_name}")
region = os.environ.get("AWS_DEFAULT_REGION", "{region}")
admin_token = os.environ.get("ADMIN_TOKEN", "").strip()
dynamodb = boto3.client("dynamodb", region_name=region)
s3 = boto3.client("s3", region_name=region)
ALLOWED_EXTS = {{".txt", ".pdf", ".csv", ".doc", ".docx", ".png", ".jpg", ".jpeg"}}

def auth_ok():
    if not admin_token: return False
    h = request.headers.get("X-Admin-Token", "").strip() or request.headers.get("Authorization", "").strip()
    if h.startswith("Bearer "): h = h[7:].strip()
    return bool(h and h == admin_token)

def valid_sid(s): return bool(re.match(r"^[a-zA-Z0-9_-]{{1,64}}$", s))

@app.route("/health")
def health():
    return jsonify({{"status": "healthy", "practical": "P05", "service": "student-record-manager", "table": table_name, "bucket": bucket_name, "region": region}}), 200

@app.route("/")
def home():
    return "<h1>CloudPrac P05 Student Record Management</h1><p>Operational on Amazon EC2 (Protected by token auth and restricted security group)</p>"

@app.route("/api/students", methods=["GET"])
def list_students():
    try:
        resp = dynamodb.scan(TableName=table_name)
        items = [{{k: v.get("S", v.get("N", str(v))) for k, v in item.items()}} for item in resp.get("Items", [])]
        return jsonify({{"students": items, "count": len(items)}}), 200
    except Exception:
        return jsonify({{"error": "Database query failed"}}), 500

@app.route("/api/students", methods=["POST"])
def add_student():
    if not auth_ok(): return jsonify({{"error": "Unauthorized. Provide valid X-Admin-Token header"}}), 401
    data = request.get_json(silent=True) or {{}}
    sid = str(data.get("student_id", "")).strip()
    name = str(data.get("name", "")).strip()
    course = str(data.get("course", "")).strip()
    if not sid or not name or not course: return jsonify({{"error": "student_id, name, and course required"}}), 400
    if not valid_sid(sid): return jsonify({{"error": "Invalid student_id format"}}), 400
    item = {{"student_id": {{"S": sid}}, "name": {{"S": name}}, "course": {{"S": course}}}}
    for f in ["email", "year", "document_key"]:
        if data.get(f): item[f] = {{"S": str(data[f])}}
    try:
        dynamodb.put_item(TableName=table_name, Item=item)
        return jsonify({{"message": f"Student {{sid}} created", "student_id": sid}}), 201
    except Exception:
        return jsonify({{"error": "Failed to create student"}}), 500

@app.route("/api/students/<sid>", methods=["GET"])
def get_student(sid):
    if not valid_sid(sid): return jsonify({{"error": "Invalid student_id format"}}), 400
    try:
        resp = dynamodb.get_item(TableName=table_name, Key={{"student_id": {{"S": sid}}}}, ConsistentRead=True)
        item = resp.get("Item")
        if not item: return jsonify({{"error": "Not found"}}), 404
        return jsonify({{k: v.get("S", v.get("N", str(v))) for k, v in item.items()}}), 200
    except Exception:
        return jsonify({{"error": "Database lookup failed"}}), 500

@app.route("/api/students/<sid>", methods=["PUT"])
def update_student(sid):
    if not auth_ok(): return jsonify({{"error": "Unauthorized. Provide valid X-Admin-Token header"}}), 401
    if not valid_sid(sid): return jsonify({{"error": "Invalid student_id format"}}), 400
    data = request.get_json(silent=True) or {{}}
    parts, names, vals = [], {{}}, {{}}
    for i, f in enumerate(["name", "course", "email", "year", "document_key"]):
        if f in data:
            parts.append(f"#f{{i}} = :v{{i}}")
            names[f"#f{{i}}"] = f
            vals[f":v{{i}}"] = {{"S": str(data[f])}}
    if not parts: return jsonify({{"error": "No update fields"}}), 400
    try:
        dynamodb.update_item(TableName=table_name, Key={{"student_id": {{"S": sid}}}},
            UpdateExpression="SET " + ", ".join(parts), ExpressionAttributeNames=names, ExpressionAttributeValues=vals)
        return jsonify({{"message": f"Student {{sid}} updated"}}), 200
    except Exception:
        return jsonify({{"error": "Update failed"}}), 500

@app.route("/api/students/<sid>", methods=["DELETE"])
def delete_student(sid):
    if not auth_ok(): return jsonify({{"error": "Unauthorized. Provide valid X-Admin-Token header"}}), 401
    if not valid_sid(sid): return jsonify({{"error": "Invalid student_id format"}}), 400
    try:
        dynamodb.delete_item(TableName=table_name, Key={{"student_id": {{"S": sid}}}})
        return jsonify({{"message": f"Student {{sid}} deleted"}}), 200
    except Exception:
        return jsonify({{"error": "Delete failed"}}), 500

@app.route("/api/students/<sid>/document", methods=["POST"])
def upload_doc(sid):
    if not auth_ok(): return jsonify({{"error": "Unauthorized. Provide valid X-Admin-Token header"}}), 401
    if not valid_sid(sid): return jsonify({{"error": "Invalid student_id format"}}), 400
    if "document" not in request.files: return jsonify({{"error": "No document"}}), 400
    f = request.files["document"]
    fname = f.filename or ""
    ext = os.path.splitext(fname)[1].lower()
    if ext not in ALLOWED_EXTS: return jsonify({{"error": "Unsupported file extension"}}), 400
    key = f"documents/{{sid}}-{{re.sub(r'[^a-zA-Z0-9_.-]', '_', fname)}}"
    try:
        body = f.read()
        if len(body) > 5 * 1024 * 1024: return jsonify({{"error": "File exceeds 5MB"}}), 413
        s3.put_object(Bucket=bucket_name, Key=key, Body=body, ContentType=f.content_type or "application/octet-stream")
        dynamodb.update_item(TableName=table_name, Key={{"student_id": {{"S": sid}}}},
            UpdateExpression="SET #dk = :dk", ExpressionAttributeNames={{"#dk": "document_key"}}, ExpressionAttributeValues={{":dk": {{"S": key}}}})
        return jsonify({{"message": "Uploaded", "key": key}}), 201
    except Exception:
        return jsonify({{"error": "Upload failed"}}), 500

@app.route("/api/students/<sid>/document", methods=["GET"])
def download_doc(sid):
    if not valid_sid(sid): return jsonify({{"error": "Invalid student_id format"}}), 400
    try:
        resp = dynamodb.get_item(TableName=table_name, Key={{"student_id": {{"S": sid}}}})
        key = resp.get("Item", {{}}).get("document_key", {{}}).get("S")
        if not key or not key.startswith("documents/") or ".." in key: return jsonify({{"error": "No document"}}), 404
        obj = s3.get_object(Bucket=bucket_name, Key=key)
        return Response(obj["Body"].read(), mimetype=obj.get("ContentType", "application/octet-stream"))
    except Exception:
        return jsonify({{"error": "Download failed"}}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port={app_port})
'''

    encoded_app_code = base64.b64encode(compact_app.encode("utf-8")).decode("ascii")

    script = f"""#!/bin/bash
set -e

# Log all output to bootstrap log
exec > >(tee /var/log/cloudprac-bootstrap.log|logger -t user-data -s 2>/dev/console) 2>&1
echo "=== CloudPrac P05 Student Record Application Bootstrap Starting ==="

# 1. Update and install Python 3 and pip
dnf update -y
dnf install -y python3 python3-pip

# 2. Install Flask, Boto3, and Gunicorn
pip3 install flask boto3 gunicorn

# 3. Create application directory
mkdir -p /opt/cloudprac
cd /opt/cloudprac

# 4. Securely fetch admin token from private S3 bucket using EC2 IAM Role credentials
# The admin token is NEVER embedded into user-data, bootstrap scripts, or console logs.
/usr/bin/python3 - <<'PYEOF'
import boto3, os, sys
try:
    s3 = boto3.client("s3", region_name="{region}")
    resp = s3.get_object(Bucket="{bucket_name}", Key="{clean_s3_key}")
    token = resp["Body"].read().decode("utf-8").strip()
    if not token or len(token) < 16:
        print("ERROR: Fetched admin token is empty or invalid. Failing closed.", file=sys.stderr)
        sys.exit(1)
    with open("/opt/cloudprac/.env", "w") as f:
        f.write(f"ADMIN_TOKEN={{token}}\\n")
    os.chmod("/opt/cloudprac/.env", 0o600)
    print("Successfully retrieved admin token via IAM role credentials into /opt/cloudprac/.env (mode 0600)")
except Exception as e:
    print(f"FATAL: Failed to retrieve admin token from S3 via instance IAM role: {{e}}", file=sys.stderr)
    sys.exit(1)
PYEOF

# Fail closed if .env was not created or is empty
if [ ! -f /opt/cloudprac/.env ] || [ ! -s /opt/cloudprac/.env ]; then
    echo "ERROR: /opt/cloudprac/.env missing or empty after token fetch. Halting bootstrap."
    exit 1
fi
chmod 600 /opt/cloudprac/.env

# 5. Write application code
echo "{encoded_app_code}" | base64 -d > /opt/cloudprac/app.py

# 6. Create systemd service
cat <<'EOF' > /etc/systemd/system/cloudprac-app.service
[Unit]
Description=CloudPrac P05 Student Record Web Application
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/cloudprac
EnvironmentFile=/opt/cloudprac/.env
Environment=DYNAMODB_TABLE={table_name}
Environment=S3_BUCKET={bucket_name}
Environment=AWS_DEFAULT_REGION={region}
ExecStart=/usr/bin/python3 -m gunicorn -w 2 -b 0.0.0.0:{app_port} app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# 7. Enable and start systemd service
systemctl daemon-reload
systemctl enable cloudprac-app.service
systemctl start cloudprac-app.service

echo "=== CloudPrac P05 Bootstrap Complete. Service running on port {app_port} ==="
"""
    return script



def launch_ec2_instance(
    ec2_client: Any,
    image_id: str,
    instance_type: str,
    subnet_id: str,
    security_group_id: str,
    instance_profile_name: Optional[str] = None,
    user_data_script: Optional[str] = None,
    key_name: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
) -> str:
    """Launch a single EC2 instance attached to instance profile and user-data script.

    Always requests a public IPv4 address via ``AssociatePublicIpAddress=True``
    on the primary network interface so the instance is reachable regardless of
    the subnet's ``MapPublicIpOnLaunch`` default setting.  Note that when
    ``NetworkInterfaces`` is specified, ``SubnetId`` and ``SecurityGroupIds``
    must be placed on the interface entry, not the top-level ``RunInstances``
    request — AWS rejects the call otherwise.
    """
    tag_list = [{"Key": k, "Value": v} for k, v in (tags or {}).items()]

    # Use NetworkInterfaces to explicitly request a public IP.
    # This overrides the subnet's MapPublicIpOnLaunch attribute, guaranteeing
    # reachability even in subnets that would otherwise not assign a public IP.
    launch_args: Dict[str, Any] = {
        "ImageId": image_id,
        "InstanceType": instance_type,
        "MinCount": 1,
        "MaxCount": 1,
        "NetworkInterfaces": [
            {
                "DeviceIndex": 0,
                "SubnetId": subnet_id,
                "Groups": [security_group_id],
                "AssociatePublicIpAddress": True,
            }
        ],
        "TagSpecifications": [
            {
                "ResourceType": "instance",
                "Tags": tag_list,
            },
            {
                "ResourceType": "volume",
                "Tags": tag_list,
            },
        ],
    }

    if key_name:
        launch_args["KeyName"] = key_name

    if instance_profile_name:
        launch_args["IamInstanceProfile"] = {"Name": instance_profile_name}

    if user_data_script:
        launch_args["UserData"] = user_data_script

    max_retries = 8
    retry_delay = 5
    for attempt in range(max_retries):
        try:
            logger.info(
                f"Launching EC2 instance ({instance_type}, AMI: {image_id}, public-IP=enabled)... "
                f"(attempt {attempt + 1}/{max_retries})"
            )
            resp = ec2_client.run_instances(**launch_args)
            instance_id = resp["Instances"][0]["InstanceId"]
            return instance_id
        except ClientError as e:
            err_msg = str(e)
            err_code = e.response.get("Error", {}).get("Code", "")
            if (
                err_code == "InvalidParameterValue"
                and ("iamInstanceProfile" in err_msg or "Invalid IAM Instance Profile" in err_msg)
                and attempt < max_retries - 1
            ):
                logger.warning(
                    f"IAM Instance Profile '{instance_profile_name}' is not yet available to EC2 ({e}). "
                    f"Retrying in {retry_delay}s (IAM eventual consistency)..."
                )
                time.sleep(retry_delay)
                continue

            raise


def wait_for_instance_running(ec2_client: Any, instance_id: str, max_timeout: int = 180) -> Dict[str, Any]:
    """Poll until instance enters 'running' state or timeout is reached."""
    start_time = time.time()
    while time.time() - start_time < max_timeout:
        resp = ec2_client.describe_instances(InstanceIds=[instance_id])
        reservations = resp.get("Reservations", [])
        if reservations and reservations[0].get("Instances"):
            instance = reservations[0]["Instances"][0]
            state = instance.get("State", {}).get("Name", "")
            if state == "running":
                return instance
            if state in ("terminated", "shutting-down"):
                raise RuntimeError(f"EC2 instance {instance_id} unexpectedly entered '{state}' state.")
        time.sleep(5)

    raise TimeoutError(f"EC2 instance {instance_id} did not transition to 'running' within {max_timeout}s.")


def check_application_health(
    public_ip: str,
    app_port: int = 5000,
    max_timeout: int = 120,
    poll_interval: int = 5,
) -> Tuple[bool, str]:
    """Poll the application /health endpoint.

    Explains why an instance being 'running' does NOT prove that its application is working.
    """
    if not public_ip:
        return False, "No public IP assigned to EC2 instance; cannot probe application health externally."

    health_url = f"http://{public_ip}:{app_port}/health"
    logger.info(f"Checking application health at {health_url}...")
    start_time = time.time()

    while time.time() - start_time < max_timeout:
        try:
            req = urllib.request.Request(health_url, headers={"User-Agent": "CloudPrac-HealthCheck"})
            with urllib.request.urlopen(req, timeout=4) as response:
                if response.status == 200:
                    body = response.read().decode("utf-8")
                    return True, f"Application healthy (HTTP 200). Response: {body}"
        except Exception as e:
            logger.debug(f"Application endpoint not yet ready ({e}), retrying in {poll_interval}s...")
        time.sleep(poll_interval)

    return False, (
        f"Application at {health_url} did not respond with HTTP 200 within {max_timeout}s. "
        "Notice: While the EC2 instance is in 'running' state, the bootstrap script or application "
        "service may still be installing dependencies or encountered an initialization issue."
    )


def verify_ec2_instance(
    ec2_client: Any,
    instance_id: str,
    expected_instance_type: str = "t2.micro",
    expected_profile_name: Optional[str] = None,
    public_ip: Optional[str] = None,
    app_port: int = 5000,
    check_http: bool = True,
) -> List[VerificationCheck]:
    """Perform independent verification on EC2 instance status, profile, and application health."""
    checks: List[VerificationCheck] = []

    try:
        resp = ec2_client.describe_instances(InstanceIds=[instance_id])
        reservations = resp.get("Reservations", [])
        if not reservations or not reservations[0].get("Instances"):
            checks.append(
                VerificationCheck(
                    check_id=f"ec2-exists-{instance_id}",
                    name="EC2 Instance Existence",
                    description=f"Verify instance {instance_id} exists",
                    passed=False,
                    expected=f"Instance {instance_id} exists",
                    actual="Instance not found in DescribeInstances",
                )
            )
            return checks

        inst = reservations[0]["Instances"][0]
        state = inst.get("State", {}).get("Name", "unknown")
        itype = inst.get("InstanceType", "")
        profile_arn = inst.get("IamInstanceProfile", {}).get("Arn", "")
        ip_assigned = inst.get("PublicIpAddress", public_ip or "none")

        # 1. State check
        checks.append(
            VerificationCheck(
                check_id=f"ec2-state-{instance_id}",
                name="EC2 Instance Running State",
                description="Verify instance has reached running state",
                passed=state == "running",
                expected="State == 'running'",
                actual=f"State is '{state}'",
            )
        )

        # 2. Instance Type check
        checks.append(
            VerificationCheck(
                check_id=f"ec2-type-{instance_id}",
                name="EC2 Instance Type",
                description="Verify instance type matches configured specification",
                passed=itype == expected_instance_type,
                expected=f"InstanceType == '{expected_instance_type}'",
                actual=f"InstanceType is '{itype}'",
            )
        )

        # 3. IAM Instance Profile check
        if expected_profile_name:
            profile_matched = expected_profile_name in profile_arn
            checks.append(
                VerificationCheck(
                    check_id=f"ec2-profile-{instance_id}",
                    name="EC2 IAM Instance Profile Attachment",
                    description="Verify least-privilege IAM profile is attached",
                    passed=profile_matched,
                    expected=f"Instance profile containing '{expected_profile_name}' attached",
                    actual=f"Attached profile ARN: '{profile_arn}'" if profile_arn else "No IAM instance profile attached",
                )
            )

        # 4. Application Health verification (Explaining running state != app healthy)
        if check_http and ip_assigned and ip_assigned != "none":
            healthy, msg = check_application_health(ip_assigned, app_port=app_port, max_timeout=30)
            checks.append(
                VerificationCheck(
                    check_id=f"ec2-app-health-{instance_id}",
                    name="EC2 Web Application Health Check",
                    description="Probe HTTP /health endpoint to verify application is operational",
                    passed=healthy,
                    expected=f"HTTP 200 from http://{ip_assigned}:{app_port}/health",
                    actual=msg,
                )
            )
    except Exception as e:
        checks.append(
            VerificationCheck(
                check_id=f"ec2-inspect-error-{instance_id}",
                name="EC2 Verification Query",
                description="Describe instance query",
                passed=False,
                expected="Successful DescribeInstances call",
                actual=f"Error querying instance: {e}",
            )
        )


    return checks


def cleanup_ec2_resources(
    ec2_client: Any,
    instance_id: Optional[str] = None,
    security_group_id: Optional[str] = None,
    key_name: Optional[str] = None,
    expected_run_id: Optional[str] = None,
) -> List[str]:
    """Terminate EC2 instance, delete security group, and delete key pair cleanly.

    Enforces ownership validation against expected_run_id and handles already-deleted resources idempotently.
    """
    deleted: List[str] = []

    # 1. Terminate Instance
    if instance_id:
        try:
            should_terminate = True
            if expected_run_id:
                try:
                    desc = ec2_client.describe_instances(InstanceIds=[instance_id])
                    resvs = desc.get("Reservations", [])
                    if resvs and resvs[0].get("Instances"):
                        inst = resvs[0]["Instances"][0]
                        st = inst.get("State", {}).get("Name")
                        if st == "terminated":
                            logger.info(f"EC2 instance '{instance_id}' is already terminated.")
                            deleted.append(f"ec2-instance:{instance_id}")
                            should_terminate = False
                        else:
                            tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
                            is_owned = tags.get("ManagedBy") == "CloudPrac" and tags.get("RunId") == expected_run_id
                            if not is_owned:
                                logger.error(
                                    f"Ownership check failed for EC2 instance '{instance_id}': "
                                    f"Tags {tags} do not verify ownership (expected ManagedBy=CloudPrac, RunId={expected_run_id}). "
                                    "Skipping termination to prevent accidental destruction."
                                )
                                should_terminate = False
                    else:
                        should_terminate = False
                except ClientError as e:
                    if e.response.get("Error", {}).get("Code") in ("InvalidInstanceID.NotFound", "InvalidInstanceID.Malformed"):
                        logger.info(f"EC2 instance '{instance_id}' not found. Already cleaned up.")
                        should_terminate = False
                    else:
                        logger.error(
                            f"Ownership check failed for EC2 instance '{instance_id}': {e}. "
                            "Skipping termination to prevent accidental destruction."
                        )
                        should_terminate = False
                except Exception as e:
                    logger.error(
                        f"Unexpected error inspecting tags on EC2 instance '{instance_id}': {e}. "
                        "Skipping termination to prevent accidental destruction."
                    )
                    should_terminate = False

            if should_terminate:
                logger.info(f"Terminating EC2 instance '{instance_id}'...")
                ec2_client.terminate_instances(InstanceIds=[instance_id])
                deleted.append(f"ec2-instance:{instance_id}")

                # Wait briefly for termination to avoid SG dependency block
                logger.info(f"Waiting for instance '{instance_id}' to terminate...")
                for _ in range(30):
                    time.sleep(4)
                    desc = ec2_client.describe_instances(InstanceIds=[instance_id])
                    reservations = desc.get("Reservations", [])
                    if not reservations or not reservations[0].get("Instances"):
                        # Instance no longer visible — treat as terminated
                        break
                    state = reservations[0]["Instances"][0].get("State", {}).get("Name", "")
                    if state in ("terminated", "shutting-down"):
                        break
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "InvalidInstanceID.NotFound":
                logger.warning(f"Could not terminate instance '{instance_id}': {e}")

    # 2. Delete Security Group
    if security_group_id:
        try:
            should_delete_sg = True
            if expected_run_id:
                try:
                    sg_desc = ec2_client.describe_security_groups(GroupIds=[security_group_id])
                    sgs = sg_desc.get("SecurityGroups", [])
                    if sgs:
                        tags = {t["Key"]: t["Value"] for t in sgs[0].get("Tags", [])}
                        is_owned = tags.get("ManagedBy") == "CloudPrac" and tags.get("RunId") == expected_run_id
                        if not is_owned:
                            logger.error(
                                f"Ownership check failed for Security Group '{security_group_id}': "
                                f"Tags {tags} do not verify ownership (expected ManagedBy=CloudPrac, RunId={expected_run_id}). "
                                "Skipping deletion to prevent accidental destruction."
                            )
                            should_delete_sg = False
                    else:
                        should_delete_sg = False
                except ClientError as e:
                    if e.response.get("Error", {}).get("Code") in ("InvalidGroup.NotFound", "InvalidGroupId.Malformed"):
                        logger.info(f"Security group '{security_group_id}' not found. Already cleaned up.")
                        should_delete_sg = False
                    else:
                        logger.error(
                            f"Ownership check failed for Security Group '{security_group_id}': {e}. "
                            "Skipping deletion to prevent accidental destruction."
                        )
                        should_delete_sg = False
                except Exception as e:
                    logger.error(
                        f"Unexpected error inspecting tags on Security Group '{security_group_id}': {e}. "
                        "Skipping deletion to prevent accidental destruction."
                    )
                    should_delete_sg = False

            if should_delete_sg:
                logger.info(f"Deleting security group '{security_group_id}'...")
                # Retry a few times in case instance ENI detach is delayed
                for attempt in range(6):
                    try:
                        ec2_client.delete_security_group(GroupId=security_group_id)
                        deleted.append(f"security-group:{security_group_id}")
                        break
                    except ClientError as e:
                        err_code = e.response.get("Error", {}).get("Code")
                        if err_code in ("InvalidGroup.NotFound", "InvalidGroupId.Malformed"):
                            logger.info(f"Security group '{security_group_id}' already gone.")
                            break
                        if "DependencyViolation" in str(e) and attempt < 5:
                            time.sleep(5)
                            continue
                        raise
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "InvalidGroup.NotFound":
                logger.warning(f"Could not delete security group '{security_group_id}': {e}")

    # 3. Delete Key Pair registration (Preserves local file if exists)
    if key_name:
        try:
            should_delete_kp = True
            if expected_run_id:
                try:
                    kp_desc = ec2_client.describe_key_pairs(KeyNames=[key_name], IncludePublicKey=False)
                    kps = kp_desc.get("KeyPairs", [])
                    if kps:
                        tags = {t["Key"]: t["Value"] for t in kps[0].get("Tags", [])}
                        is_owned = tags.get("ManagedBy") == "CloudPrac" and tags.get("RunId") == expected_run_id
                        if not is_owned:
                            logger.error(
                                f"Ownership check failed for Key Pair '{key_name}': "
                                f"Tags {tags} do not verify ownership (expected ManagedBy=CloudPrac, RunId={expected_run_id}). "
                                "Skipping deletion to prevent accidental destruction."
                            )
                            should_delete_kp = False
                    else:
                        should_delete_kp = False
                except ClientError as e:
                    if e.response.get("Error", {}).get("Code") in ("InvalidKeyPair.NotFound", "InvalidKeyPair.Duplicate"):
                        logger.info(f"Key pair '{key_name}' not found. Already cleaned up.")
                        should_delete_kp = False
                    else:
                        logger.error(
                            f"Ownership check failed for Key Pair '{key_name}': {e}. "
                            "Skipping deletion to prevent accidental destruction."
                        )
                        should_delete_kp = False
                except Exception as e:
                    logger.error(
                        f"Unexpected error inspecting tags on Key Pair '{key_name}': {e}. "
                        "Skipping deletion to prevent accidental destruction."
                    )
                    should_delete_kp = False

            if should_delete_kp:
                logger.info(f"Deleting EC2 Key Pair registration '{key_name}'...")
                ec2_client.delete_key_pair(KeyName=key_name)
                deleted.append(f"key-pair:{key_name}")
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "InvalidKeyPair.NotFound":
                logger.warning(f"Could not delete key pair '{key_name}': {e}")

    return deleted
