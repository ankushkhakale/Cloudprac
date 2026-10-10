"""Student Record Management Flask Web Application for Practical 05.

Designed to run on the EC2 instance using ambient IAM instance profile credentials,
and also testable locally in offline unit test suites.
"""

import os
import re
from typing import Any, Dict, Optional
from flask import Flask, jsonify, request, render_template_string, Response

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CloudPrac P05 — Student Record Management</title>
    <style>
        :root {
            --bg: #0f172a;
            --surface: #1e293b;
            --border: #334155;
            --primary: #38bdf8;
            --text: #f8fafc;
            --muted: #94a3b8;
            --accent: #22c55e;
            --danger: #ef4444;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
        body { background: var(--bg); color: var(--text); padding: 2rem; line-height: 1.5; }
        .container { max-width: 900px; margin: 0 auto; }
        header { border-bottom: 1px solid var(--border); padding-bottom: 1.5rem; margin-bottom: 2rem; }
        h1 { font-size: 1.8rem; color: var(--primary); margin-bottom: 0.5rem; }
        .badge { display: inline-block; padding: 0.2rem 0.6rem; border-radius: 4px; font-size: 0.8rem; font-weight: bold; background: #0369a1; color: white; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 2rem; }
        @media (max-width: 768px) { .grid { grid-template-columns: 1fr; } }
        .card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1.25rem; }
        .card h2 { font-size: 1.2rem; color: var(--primary); margin-bottom: 1rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }
        label { display: block; font-size: 0.85rem; color: var(--muted); margin-bottom: 0.25rem; }
        input, select { width: 100%; padding: 0.5rem; background: #0f172a; border: 1px solid var(--border); border-radius: 4px; color: white; margin-bottom: 0.75rem; }
        button { background: var(--primary); color: #0f172a; border: none; padding: 0.6rem 1.2rem; border-radius: 4px; font-weight: bold; cursor: pointer; }
        button:hover { opacity: 0.9; }
        table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
        th, td { text-align: left; padding: 0.75rem; border-bottom: 1px solid var(--border); font-size: 0.9rem; }
        th { color: var(--muted); }
        .success { color: var(--accent); }
        .error { color: var(--danger); }
        .doc-link { color: var(--primary); text-decoration: none; }
        .doc-link:hover { text-decoration: underline; }
    </style>
</head>
<body>
<div class="container">
    <header>
        <span class="badge">AWS CloudPrac P05</span>
        <h1>Student Record Management</h1>
        <p style="color: var(--muted);">Running on Amazon EC2 &bull; Records in Amazon DynamoDB &bull; Documents in Amazon S3</p>
    </header>

    <div class="grid">
        <div class="card">
            <h2>Add Student Record</h2>
            <form id="addStudentForm" onsubmit="addStudent(event)">
                <label>Student ID</label>
                <input type="text" id="student_id" placeholder="e.g. STU-104" required>
                <label>Full Name</label>
                <input type="text" id="name" placeholder="e.g. Ananya Rao" required>
                <label>Course</label>
                <input type="text" id="course" placeholder="e.g. B.Tech Computer Science" required>
                <label>Email</label>
                <input type="email" id="email" placeholder="e.g. ananya@college.edu" required>
                <label>Academic Year</label>
                <input type="text" id="year" placeholder="e.g. 2nd Year" required>
                <button type="submit">Save Student Record</button>
            </form>
            <div id="addResult" style="margin-top: 0.5rem;"></div>
        </div>

        <div class="card">
            <h2>Upload Student Document (S3)</h2>
            <form id="uploadDocForm" onsubmit="uploadDocument(event)">
                <label>Student ID</label>
                <input type="text" id="doc_student_id" placeholder="e.g. STU-104" required>
                <label>Select Document File (Max 5MB)</label>
                <input type="file" id="doc_file" required>
                <button type="submit">Upload to Private S3</button>
            </form>
            <div id="uploadResult" style="margin-top: 0.5rem;"></div>
        </div>
    </div>

    <div class="card">
        <h2>Existing Student Records (DynamoDB)</h2>
        <button onclick="loadStudents()" style="margin-bottom: 1rem; font-size: 0.85rem; padding: 0.4rem 0.8rem;">Refresh Records</button>
        <table id="studentsTable">
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Name</th>
                    <th>Course</th>
                    <th>Email</th>
                    <th>Year</th>
                    <th>Document</th>
                </tr>
            </thead>
            <tbody id="studentsBody">
                <tr><td colspan="6" style="text-align: center; color: var(--muted);">Loading student records...</td></tr>
            </tbody>
        </table>
    </div>
</div>

<script>
async function loadStudents() {
    try {
        const res = await fetch('/api/students');
        const data = await res.json();
        const tbody = document.getElementById('studentsBody');
        tbody.innerHTML = '';
        if (!data.students || data.students.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--muted);">No student records found.</td></tr>';
            return;
        }
        data.students.forEach(s => {
            const tr = document.createElement('tr');
            const docCell = s.document_key ? `<a class="doc-link" href="/api/students/${s.student_id}/document" target="_blank">View Document</a>` : '<span style="color:var(--muted)">None</span>';
            tr.innerHTML = `
                <td><strong>${s.student_id}</strong></td>
                <td>${s.name || ''}</td>
                <td>${s.course || ''}</td>
                <td>${s.email || ''}</td>
                <td>${s.year || ''}</td>
                <td>${docCell}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error(e);
    }
}

async function addStudent(e) {
    e.preventDefault();
    const sid = document.getElementById('student_id').value;
    const name = document.getElementById('name').value;
    const course = document.getElementById('course').value;
    const email = document.getElementById('email').value;
    const year = document.getElementById('year').value;
    const resDiv = document.getElementById('addResult');

    try {
        const resp = await fetch('/api/students', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ student_id: sid, name: name, course: course, email: email, year: year })
        });
        const data = await resp.json();
        if (resp.ok) {
            resDiv.innerHTML = '<span class="success">Record added successfully!</span>';
            document.getElementById('addStudentForm').reset();
            loadStudents();
        } else {
            resDiv.innerHTML = `<span class="error">${data.error || 'Failed to add record'}</span>`;
        }
    } catch (err) {
        resDiv.innerHTML = `<span class="error">Network error: ${err}</span>`;
    }
}

async function uploadDocument(e) {
    e.preventDefault();
    const sid = document.getElementById('doc_student_id').value;
    const fileInput = document.getElementById('doc_file');
    const resDiv = document.getElementById('uploadResult');

    if (!fileInput.files.length) return;
    const formData = new FormData();
    formData.append('document', fileInput.files[0]);

    try {
        const resp = await fetch(`/api/students/${sid}/document`, {
            method: 'POST',
            body: formData
        });
        const data = await resp.json();
        if (resp.ok) {
            resDiv.innerHTML = '<span class="success">Document uploaded to S3!</span>';
            document.getElementById('uploadDocForm').reset();
            loadStudents();
        } else {
            resDiv.innerHTML = `<span class="error">${data.error || 'Upload failed'}</span>`;
        }
    } catch (err) {
        resDiv.innerHTML = `<span class="error">Network error: ${err}</span>`;
    }
}

loadStudents();
</script>
</body>
</html>
"""


def create_app(
    table_name: Optional[str] = None,
    bucket_name: Optional[str] = None,
    boto_session: Optional[Any] = None,
) -> Flask:
    """Create configured Flask application instance."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB max request size

    dynamo_table_name = table_name or os.environ.get("DYNAMODB_TABLE", "cloudprac-p05-students")
    s3_bucket_name = bucket_name or os.environ.get("S3_BUCKET", "cloudprac-p05-documents")
    region_name = os.environ.get("AWS_DEFAULT_REGION", os.environ.get("AWS_REGION", "us-east-1"))

    # Boto3 client initialization
    if boto_session is not None:
        dynamodb = boto_session.client("dynamodb")
        s3 = boto_session.client("s3")
    else:
        import boto3
        dynamodb = boto3.client("dynamodb", region_name=region_name)
        s3 = boto3.client("s3", region_name=region_name)

    @app.route("/health", methods=["GET"])
    def health():
        """Health check endpoint confirming application and AWS bindings."""
        return jsonify({
            "status": "healthy",
            "practical": "P05",
            "service": "student-record-manager",
            "dynamodb_table": dynamo_table_name,
            "s3_bucket": s3_bucket_name,
            "region": region_name,
        }), 200

    @app.route("/", methods=["GET"])
    def index():
        """Web application user interface."""
        return render_template_string(HTML_TEMPLATE)

    @app.route("/api/students", methods=["GET"])
    def list_students():
        """List all student records from DynamoDB."""
        try:
            resp = dynamodb.scan(TableName=dynamo_table_name)
            items = resp.get("Items", [])
            records = []
            for raw in items:
                record = {}
                for k, v in raw.items():
                    if "S" in v:
                        record[k] = v["S"]
                    elif "N" in v:
                        record[k] = int(v["N"]) if "." not in v["N"] else float(v["N"])
                    else:
                        record[k] = str(v)
                records.append(record)
            return jsonify({"students": records, "count": len(records)}), 200
        except Exception as e:
            return jsonify({"error": f"Failed to list students: {str(e)}"}), 500

    @app.route("/api/students", methods=["POST"])
    def add_student():
        """Add a new student record to DynamoDB."""
        data = request.get_json(silent=True)
        if not data or not isinstance(data, dict):
            return jsonify({"error": "Invalid JSON body provided."}), 400

        student_id = str(data.get("student_id", "")).strip()
        name = str(data.get("name", "")).strip()
        course = str(data.get("course", "")).strip()

        if not student_id:
            return jsonify({"error": "Field 'student_id' is required."}), 400
        if not name:
            return jsonify({"error": "Field 'name' is required."}), 400
        if not course:
            return jsonify({"error": "Field 'course' is required."}), 400

        # Safe input sanitization
        if not re.match(r"^[a-zA-Z0-9_-]+$", student_id):
            return jsonify({"error": "Field 'student_id' must contain only alphanumeric, dash, or underscore characters."}), 400

        item = {
            "student_id": {"S": student_id},
            "name": {"S": name},
            "course": {"S": course},
            "email": {"S": str(data.get("email", "")).strip()},
            "year": {"S": str(data.get("year", "")).strip()},
        }
        if data.get("document_key"):
            item["document_key"] = {"S": str(data.get("document_key")).strip()}

        try:
            dynamodb.put_item(
                TableName=dynamo_table_name,
                Item=item,
            )
            return jsonify({"message": f"Student '{student_id}' created successfully.", "student_id": student_id}), 201
        except Exception as e:
            return jsonify({"error": f"DynamoDB operation failed: {str(e)}"}), 500

    @app.route("/api/students/<student_id>", methods=["GET"])
    def get_student(student_id: str):
        """Retrieve a specific student record from DynamoDB."""
        try:
            resp = dynamodb.get_item(
                TableName=dynamo_table_name,
                Key={"student_id": {"S": student_id}},
                ConsistentRead=True,
            )
            raw = resp.get("Item")
            if not raw:
                return jsonify({"error": f"Student '{student_id}' not found."}), 404

            record = {}
            for k, v in raw.items():
                if "S" in v:
                    record[k] = v["S"]
                elif "N" in v:
                    record[k] = int(v["N"]) if "." not in v["N"] else float(v["N"])
                else:
                    record[k] = str(v)
            return jsonify(record), 200
        except Exception as e:
            return jsonify({"error": f"Failed to retrieve student: {str(e)}"}), 500

    @app.route("/api/students/<student_id>", methods=["PUT"])
    def update_student(student_id: str):
        """Update fields for an existing student record."""
        data = request.get_json(silent=True)
        if not data or not isinstance(data, dict):
            return jsonify({"error": "Invalid JSON body provided."}), 400

        update_parts = []
        expr_names = {}
        expr_values = {}

        allowed_fields = ["name", "course", "email", "year", "document_key"]
        idx = 0
        for f in allowed_fields:
            if f in data:
                pkey = f"#f{idx}"
                pval = f":v{idx}"
                update_parts.append(f"{pkey} = {pval}")
                expr_names[pkey] = f
                expr_values[pval] = {"S": str(data[f]).strip()}
                idx += 1

        if not update_parts:
            return jsonify({"error": "No valid updatable fields provided."}), 400

        try:
            resp = dynamodb.update_item(
                TableName=dynamo_table_name,
                Key={"student_id": {"S": student_id}},
                UpdateExpression="SET " + ", ".join(update_parts),
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_values,
                ReturnValues="ALL_NEW",
            )
            raw = resp.get("Attributes", {})
            record = {}
            for k, v in raw.items():
                record[k] = v.get("S", v.get("N", str(v)))
            return jsonify({"message": f"Student '{student_id}' updated.", "record": record}), 200
        except Exception as e:
            return jsonify({"error": f"Failed to update student: {str(e)}"}), 500

    @app.route("/api/students/<student_id>", methods=["DELETE"])
    def delete_student(student_id: str):
        """Delete a student record from DynamoDB."""
        try:
            dynamodb.delete_item(
                TableName=dynamo_table_name,
                Key={"student_id": {"S": student_id}},
            )
            return jsonify({"message": f"Student '{student_id}' deleted successfully."}), 200
        except Exception as e:
            return jsonify({"error": f"Failed to delete student: {str(e)}"}), 500

    @app.route("/api/students/<student_id>/document", methods=["POST"])
    def upload_document(student_id: str):
        """Upload a student document to private S3 and link to DynamoDB record."""
        if "document" not in request.files:
            # Check if JSON content was supplied
            raw_text = request.form.get("text")
            if raw_text:
                file_bytes = raw_text.encode("utf-8")
                filename = "record.txt"
                content_type = "text/plain"
            else:
                return jsonify({"error": "No document file provided in request."}), 400
        else:
            file_item = request.files["document"]
            if not file_item.filename:
                return jsonify({"error": "Empty filename."}), 400
            filename = os.path.basename(file_item.filename)
            file_bytes = file_item.read()
            content_type = file_item.content_type or "application/octet-stream"

        if len(file_bytes) > 5 * 1024 * 1024:
            return jsonify({"error": "Document size exceeds 5 MB limit."}), 413

        safe_filename = re.sub(r"[^a-zA-Z0-9_.-]", "_", filename)
        object_key = f"documents/{student_id}-{safe_filename}"

        try:
            # 1. Upload to S3
            s3.put_object(
                Bucket=s3_bucket_name,
                Key=object_key,
                Body=file_bytes,
                ContentType=content_type,
            )

            # 2. Update student record in DynamoDB with document_key
            dynamodb.update_item(
                TableName=dynamo_table_name,
                Key={"student_id": {"S": student_id}},
                UpdateExpression="SET #dk = :dk",
                ExpressionAttributeNames={"#dk": "document_key"},
                ExpressionAttributeValues={":dk": {"S": object_key}},
            )

            return jsonify({
                "message": f"Document uploaded successfully for student '{student_id}'.",
                "bucket": s3_bucket_name,
                "document_key": object_key,
                "size_bytes": len(file_bytes),
            }), 201
        except Exception as e:
            return jsonify({"error": f"Failed to store document: {str(e)}"}), 500

    @app.route("/api/students/<student_id>/document", methods=["GET"])
    def download_document(student_id: str):
        """Retrieve a student document from private S3 safely."""
        try:
            # 1. Look up student record to get document_key
            resp = dynamodb.get_item(
                TableName=dynamo_table_name,
                Key={"student_id": {"S": student_id}},
            )
            raw = resp.get("Item")
            if not raw or "document_key" not in raw:
                return jsonify({"error": f"No document linked to student '{student_id}'."}), 404

            doc_key = raw["document_key"]["S"]

            # 2. Fetch object from S3
            s3_obj = s3.get_object(Bucket=s3_bucket_name, Key=doc_key)
            content = s3_obj["Body"].read()
            content_type = s3_obj.get("ContentType", "application/octet-stream")

            return Response(
                content,
                mimetype=content_type,
                headers={"Content-Disposition": f"inline; filename={os.path.basename(doc_key)}"},
            )
        except Exception as e:
            return jsonify({"error": f"Failed to retrieve document: {str(e)}"}), 500

    return app
