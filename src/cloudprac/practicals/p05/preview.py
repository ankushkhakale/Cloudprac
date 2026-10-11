"""Web preview, connectivity diagnostics, and live application verification for Practical 05."""

import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from cloudprac.core.models import VerificationCheck
from cloudprac.utils.logging import get_logger

logger = get_logger()

# Disallowed placeholder and documentation IP ranges
RESERVED_TEST_NETWORKS = [
    ipaddress.ip_network("198.51.100.0/24"),  # TEST-NET-2 (RFC 5737)
    ipaddress.ip_network("192.0.2.0/24"),     # TEST-NET-1 (RFC 5737)
    ipaddress.ip_network("203.0.113.0/24"),   # TEST-NET-3 (RFC 5737)
]


def sanitize_url_for_logging(url: str) -> str:
    """Redact sensitive query parameters and credentials from URLs before logging."""
    try:
        parsed = urllib.parse.urlsplit(url)
        # Redact password in userinfo if present
        netloc = parsed.netloc
        if "@" in netloc:
            creds, host = netloc.split("@", 1)
            netloc = f"***@{host}"
        # Redact query params that look like tokens or keys
        query_parts = []
        for param in parsed.query.split("&"):
            if not param:
                continue
            key = param.split("=")[0]
            if re.search(r"(token|secret|key|auth|password)", key, re.IGNORECASE):
                query_parts.append(f"{key}=[REDACTED]")
            else:
                query_parts.append(param)
        clean_query = "&".join(query_parts)
        return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, clean_query, parsed.fragment))
    except Exception:
        return "[REDACTED_URL]"


def is_real_public_ip(ip_str: Optional[str]) -> Tuple[bool, str]:
    """Validate that an IP string is a real, assigned public IPv4 address and not a placeholder."""
    if not ip_str or not str(ip_str).strip() or str(ip_str).lower() in ("none", "null", "undefined", ""):
        return False, "No IP address assigned"

    cleaned = str(ip_str).strip()
    try:
        addr = ipaddress.ip_address(cleaned)
    except ValueError:
        return False, f"Invalid IP address format: '{cleaned}'"

    if not isinstance(addr, ipaddress.IPv4Address):
        return False, f"Expected IPv4 address, got '{cleaned}'"

    if addr.is_loopback:
        return False, f"Loopback address '{cleaned}' is not an externally accessible public IP"

    for net in RESERVED_TEST_NETWORKS:
        if addr in net:
            return False, f"Placeholder / documentation testnet IP '{cleaned}' (in {net}) is prohibited"

    if addr.is_private:
        return False, f"Private RFC1918 address '{cleaned}' is not an externally accessible public IP"

    return True, "Valid public IPv4 address"


def probe_endpoint(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    data: Optional[bytes] = None,
    timeout: float = 5.0,
) -> Tuple[bool, int, str, Optional[Any]]:
    """Probe an HTTP endpoint safely, returning status, sanitized message, and optional JSON.

    Handles connection refusal, timeouts, server crashes, and HTTP errors without throwing.
    """
    req_headers = {
        "User-Agent": "CloudPrac-PreviewProbe/1.0",
        **(headers or {}),
    }

    try:
        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = response.status
            body_bytes = response.read()
            body_text = body_bytes.decode("utf-8", errors="replace")

            parsed_json = None
            if "application/json" in response.headers.get("Content-Type", ""):
                try:
                    parsed_json = json.loads(body_text)
                except Exception:
                    pass

            return True, status_code, f"HTTP {status_code} OK", parsed_json
    except urllib.error.HTTPError as e:
        status_code = e.code
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        return False, status_code, f"HTTP {status_code}: {err_body or e.reason}", None
    except urllib.error.URLError as e:
        reason = str(e.reason)
        if isinstance(e.reason, socket.timeout) or "timed out" in reason.lower():
            return False, 0, f"Connection timed out after {timeout}s (security group CIDR or firewall may be dropping traffic)", None
        if isinstance(e.reason, ConnectionRefusedError) or "connection refused" in reason.lower():
            return False, 0, "Connection refused (application service may still be starting or has crashed)", None
        return False, 0, f"Network error: {reason}", None
    except socket.timeout:
        return False, 0, f"Socket timed out after {timeout}s", None
    except Exception as e:
        return False, 0, f"Unexpected connection error: {e}", None


def verify_application_and_preview(
    public_ip: Optional[str],
    app_port: int = 5000,
    admin_token: Optional[str] = None,
    run_id: str = "",
    timeout: float = 6.0,
) -> List[VerificationCheck]:
    """Execute live application, preview, and authenticated CRUD verification checks."""
    checks: List[VerificationCheck] = []
    clean_run = run_id.replace("-", "").lower()[:6] or "test"

    # 1. Real Public IP Assignment Check
    is_valid_ip, ip_msg = is_real_public_ip(public_ip)
    checks.append(
        VerificationCheck(
            check_id="ec2-public-ip-assigned",
            name="EC2 Real Public IP Assignment",
            description="Verify instance has an assigned real public IPv4 address (no placeholder IPs)",
            passed=is_valid_ip,
            expected="Valid assigned public IPv4 address",
            actual=f"{public_ip} ({ip_msg})" if public_ip else ip_msg,
        )
    )

    if not is_valid_ip:
        # If no valid public IP exists, all HTTP application and preview checks must fail explicitly
        for check_id, check_name in [
            ("preview-endpoint-accessible", "Web Preview Landing Page"),
            ("app-health-check", "Application /health Endpoint"),
            ("app-read-students", "Read Students API (GET /api/students)"),
            ("app-read-single-student", "Read Student Detail API (GET /api/students/STU-001)"),
            ("app-auth-mutation", "Authenticated Student Mutation (POST /api/students)"),
            ("app-mutation-readback", "Mutation Read-Back (GET /api/students/<sid>)"),
        ]:
            checks.append(
                VerificationCheck(
                    check_id=check_id,
                    name=check_name,
                    description=f"Verify {check_name}",
                    passed=False,
                    expected="HTTP response from live application",
                    actual="Skipped: No real public IP assigned to EC2 instance",
                )
            )
        return checks

    base_url = f"http://{public_ip}:{app_port}"

    # 2. Web Preview Landing Page Check (GET /)
    preview_url = f"{base_url}/"
    ok, code, msg, _ = probe_endpoint(preview_url, timeout=timeout)
    checks.append(
        VerificationCheck(
            check_id="preview-endpoint-accessible",
            name="Web Preview Landing Page (GET /)",
            description=f"Verify web application preview endpoint responds at {preview_url}",
            passed=ok and code == 200,
            expected="HTTP 200 OK with valid HTML landing page",
            actual=f"HTTP {code} ({msg})" if not ok else f"HTTP {code} OK",
        )
    )

    # 3. Application /health Endpoint Check
    health_url = f"{base_url}/health"
    ok, code, msg, health_json = probe_endpoint(health_url, timeout=timeout)
    is_healthy = ok and code == 200 and isinstance(health_json, dict) and health_json.get("status") == "healthy"
    checks.append(
        VerificationCheck(
            check_id="app-health-check",
            name="Application /health Endpoint",
            description="Verify Flask application /health endpoint returns HTTP 200 with healthy JSON",
            passed=is_healthy,
            expected="HTTP 200 with JSON status: 'healthy'",
            actual=f"HTTP {code} ({health_json or msg})",
        )
    )

    # 4. Read Sample Records (GET /api/students)
    students_url = f"{base_url}/api/students"
    ok, code, msg, students_json = probe_endpoint(students_url, timeout=timeout)
    has_records = (
        ok
        and code == 200
        and isinstance(students_json, dict)
        and len(students_json.get("students", [])) > 0
    )
    student_count = len(students_json.get("students", [])) if isinstance(students_json, dict) else 0
    checks.append(
        VerificationCheck(
            check_id="app-read-students",
            name="Read Students API (GET /api/students)",
            description="Verify student records can be read via the running application API",
            passed=has_records,
            expected="HTTP 200 with at least 1 student record",
            actual=f"HTTP {code} with {student_count} records" if ok else f"HTTP {code}: {msg}",
        )
    )

    # 5. Read Single Student (GET /api/students/STU-001)
    stu1_url = f"{base_url}/api/students/STU-001"
    ok, code, msg, stu1_json = probe_endpoint(stu1_url, timeout=timeout)
    stu1_valid = (
        ok
        and code == 200
        and isinstance(stu1_json, dict)
        and stu1_json.get("student_id") == "STU-001"
    )
    checks.append(
        VerificationCheck(
            check_id="app-read-single-student",
            name="Read Student Detail (GET /api/students/STU-001)",
            description="Verify specific student record can be retrieved via application API",
            passed=stu1_valid,
            expected="HTTP 200 with student_id 'STU-001'",
            actual=f"HTTP {code} ({stu1_json.get('name') if isinstance(stu1_json, dict) else msg})",
        )
    )

    # 6. Authenticated Mutation via Documented Secure Method (POST /api/students with X-Admin-Token)
    mutation_sid = f"VERIF-{clean_run}"
    mutation_payload = json.dumps({
        "student_id": mutation_sid,
        "name": "Verification Student",
        "course": "Cloud Security & Automation",
        "year": "2026",
    }).encode("utf-8")

    auth_headers = {
        "Content-Type": "application/json",
    }
    if admin_token:
        auth_headers["X-Admin-Token"] = admin_token

    post_url = f"{base_url}/api/students"
    ok, code, msg, post_json = probe_endpoint(
        post_url,
        method="POST",
        headers=auth_headers,
        data=mutation_payload,
        timeout=timeout,
    )
    mutation_success = ok and code == 201
    checks.append(
        VerificationCheck(
            check_id="app-auth-mutation",
            name="Authenticated Student Mutation (POST /api/students)",
            description="Perform authenticated student record creation using secure X-Admin-Token header",
            passed=mutation_success,
            expected="HTTP 201 Created",
            actual=f"HTTP {code} ({msg})",
        )
    )

    # 7. Mutation Read-Back Verification (GET /api/students/<sid>)
    readback_url = f"{base_url}/api/students/{mutation_sid}"
    rb_ok, rb_code, rb_msg, rb_json = probe_endpoint(readback_url, timeout=timeout)
    readback_verified = (
        rb_ok
        and rb_code == 200
        and isinstance(rb_json, dict)
        and rb_json.get("student_id") == mutation_sid
    )
    checks.append(
        VerificationCheck(
            check_id="app-mutation-readback",
            name="Mutation Read-Back (GET /api/students/<sid>)",
            description="Verify that the authenticated mutation was committed and can be read back",
            passed=readback_verified,
            expected=f"HTTP 200 with student_id '{mutation_sid}'",
            actual=f"HTTP {rb_code} ({rb_json.get('name') if isinstance(rb_json, dict) else rb_msg})",
        )
    )

    # Clean up test verification record if created
    if mutation_success:
        try:
            del_url = f"{base_url}/api/students/{mutation_sid}"
            probe_endpoint(del_url, method="DELETE", headers=auth_headers, timeout=timeout)
        except Exception:
            pass

    return checks
