
import csv
import hashlib
import json
import os
import secrets
import time
import uuid
from pathlib import Path

from fastapi import (
    FastAPI,
    UploadFile,
    File,
    HTTPException,
    Request,
    Body,
    Form,
)
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from backend.database import get_connection, initialize_database
from backend.inspector import inspect_csv
from backend.reconciliation import reconcile_csv_files
from backend.agent import analyze_findings


BASE_DIR = Path(__file__).resolve().parent.parent

MAX_UPLOAD_SIZE = 2 * 1024 * 1024
SESSION_INACTIVITY_SECONDS = 24 * 60 * 60
SESSION_COOKIE_NAME = "sample_check_session"

COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"

# Allowed website origins.
# Local origins are used during development.
# Add the public HTTPS domain through ALLOWED_ORIGINS when deploying.
ALLOWED_ORIGINS = {
    origin.strip().rstrip("/")
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://127.0.0.1:8000,http://localhost:8000",
    ).split(",")
    if origin.strip()
}

app = FastAPI(
    title="Sample Check",
    description="AI-assisted laboratory sample intake and exception resolution",
    version="1.8.0",
)

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "frontend" / "static"),
    name="static",
)

templates = Jinja2Templates(
    directory=BASE_DIR / "frontend" / "templates"
)


# =========================================
# VISITOR SESSION MANAGEMENT
# =========================================

def hash_session_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_visitor_session():
    """Create a new server-side visitor session."""

    now = time.time()
    session_id = uuid.uuid4().hex
    token = secrets.token_urlsafe(32)
    token_hash = hash_session_token(token)

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO visitor_sessions (
                id,
                token_hash,
                created_at,
                last_seen,
                expires_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                token_hash,
                now,
                now,
                now + SESSION_INACTIVITY_SECONDS,
            ),
        )

    return session_id, token


@app.middleware("http")
async def visitor_session_middleware(request: Request, call_next):
    """Validate requests and manage visitor sessions."""

    # =====================================
    # CSRF / ORIGIN VALIDATION
    # =====================================

    # These methods can change application data.
    # Browser requests must originate from an allowed website.
    if (
        request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and request.url.path.startswith("/api/")
    ):
        origin = request.headers.get("origin")

        if not origin or origin.rstrip("/") not in ALLOWED_ORIGINS:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "Request origin not allowed."
                },
            )

    # =====================================
    # VISITOR SESSION VALIDATION
    # =====================================

    token = request.cookies.get(SESSION_COOKIE_NAME)
    session = None
    now = time.time()

    if token:
        token_hash = hash_session_token(token)

        with get_connection() as conn:
            session = conn.execute(
                """
                SELECT id, expires_at
                FROM visitor_sessions
                WHERE token_hash = ?
                """,
                (token_hash,),
            ).fetchone()

            if session and session["expires_at"] > now:
                conn.execute(
                    """
                    UPDATE visitor_sessions
                    SET last_seen = ?,
                        expires_at = ?
                    WHERE id = ?
                    """,
                    (
                        now,
                        now + SESSION_INACTIVITY_SECONDS,
                        session["id"],
                    ),
                )
            else:
                session = None

    if session:
        session_id = session["id"]
        new_token = None
    else:
        session_id, new_token = create_visitor_session()

    request.state.session_id = session_id

    response = await call_next(request)

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=new_token or token,
        max_age=SESSION_INACTIVITY_SECONDS,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )

    return response


def get_session_id(request: Request):
    return request.state.session_id


# =========================================
# INSPECTION HELPERS
# =========================================

def get_latest_inspection_id(conn, session_id):
    row = conn.execute(
        """
        SELECT id
        FROM inspections
        WHERE session_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()

    return row["id"] if row else None


def get_latest_inspection_stats(conn, session_id):
    inspection_id = get_latest_inspection_id(conn, session_id)

    if inspection_id is None:

        return {
            "inspection_id": None,
            "total_samples": 0,
            "total_findings": 0,
            "open_findings": 0,
            "resolved_findings": 0,
        }

    total_samples = conn.execute(
        """
        SELECT COUNT(*)
        FROM samples
        WHERE inspection_id = ?
          AND session_id = ?
        """,
        (inspection_id, session_id),
    ).fetchone()[0]

    total_findings = conn.execute(
        """
        SELECT COUNT(*)
        FROM findings
        WHERE inspection_id = ?
          AND session_id = ?
        """,
        (inspection_id, session_id),
    ).fetchone()[0]

    open_findings = conn.execute(
        """
        SELECT COUNT(*)
        FROM findings
        WHERE inspection_id = ?
          AND session_id = ?
          AND status = 'Open'
        """,
        (inspection_id, session_id),
    ).fetchone()[0]

    resolved_findings = conn.execute(
        """
        SELECT COUNT(*)
        FROM findings
        WHERE inspection_id = ?
          AND session_id = ?
          AND status = 'Resolved'
        """,
        (inspection_id, session_id),
    ).fetchone()[0]

    return {
        "inspection_id": inspection_id,
        "total_samples": total_samples,
        "total_findings": total_findings,
        "open_findings": open_findings,
        "resolved_findings": resolved_findings,
    }


# =========================================
# CUSTOMER AND HISTORICAL DATA
# =========================================

def normalize_customer_code(customer_code):
    return customer_code.strip().upper()


def get_or_create_customer(conn, session_id, customer_code, customer_name=None):
    """Create or retrieve a customer inside the current visitor workspace."""

    customer_code = normalize_customer_code(customer_code)
    customer_name = (customer_name or "").strip()

    internal_customer_code = f"{session_id}::{customer_code}"

    customer = conn.execute(
        """
        SELECT id, customer_name
        FROM customers
        WHERE session_id = ?
          AND customer_code = ?
        """,
        (session_id, internal_customer_code),
    ).fetchone()

    if customer:
        if customer_name and customer_name != customer["customer_name"]:
            conn.execute(
                """
                UPDATE customers
                SET customer_name = ?
                WHERE id = ?
                  AND session_id = ?
                """,
                (customer_name, customer["id"], session_id),
            )

        return customer["id"]

    if not customer_name:
        customer_name = customer_code

    cursor = conn.execute(
        """
        INSERT INTO customers (
            customer_code,
            customer_name,
            session_id
        )
        VALUES (?, ?, ?)
        """,
        (
            internal_customer_code,
            customer_name,
            session_id,
        ),
    )

    return cursor.lastrowid


def get_error_intelligence(session_id, customer_code):
    customer_code = normalize_customer_code(customer_code)
    internal_customer_code = f"{session_id}::{customer_code}"

    with get_connection() as conn:
        customer = conn.execute(
            """
            SELECT id, customer_name
            FROM customers
            WHERE session_id = ?
              AND customer_code = ?
            """,
            (session_id, internal_customer_code),
        ).fetchone()

        if not customer:
            return {
                "customer_code": customer_code,
                "customer_name": None,
                "submission_count": 0,
                "recurring_errors": [],
                "checklist": [],
                "history": [],
            }

        customer_id = customer["id"]

        history = conn.execute(
            """
            SELECT
                id,
                total_samples,
                error_count,
                submitted_at
            FROM submission_history
            WHERE customer_id = ?
            ORDER BY id DESC
            """,
            (customer_id,),
        ).fetchall()

        patterns = conn.execute(
            """
            SELECT
                e.issue_type,
                COUNT(DISTINCT e.submission_id) AS submission_count,
                COUNT(*) AS total_occurrences
            FROM submission_errors e
            JOIN submission_history h
                ON h.id = e.submission_id
            WHERE h.customer_id = ?
            GROUP BY e.issue_type
            ORDER BY submission_count DESC, total_occurrences DESC
            """,
            (customer_id,),
        ).fetchall()

    recurring_errors = [
        {
            "issue_type": row["issue_type"],
            "submission_count": row["submission_count"],
            "total_occurrences": row["total_occurrences"],
        }
        for row in patterns
        if row["submission_count"] >= 2
    ]

    guidance = {
        "Missing from lab manifest":
            "Verify that every customer-ordered sample appears in the laboratory manifest.",
        "Unexpected sample in lab manifest":
            "Check that every manifest sample has a corresponding customer order.",
        "Conflicting sample_type":
            "Confirm that sample types match across the customer order and laboratory manifest.",
        "Duplicate sample ID":
            "Check for repeated sample identifiers before submitting the files.",
        "Missing patient_code":
            "Ensure the required patient_code field is completed for every sample.",
        "Missing collection_date":
            "Check that collection dates are present for every sample.",
        "Missing sample_type":
            "Check that sample types are completed for every sample.",
    }

    checklist = [
        {
            "issue_type": item["issue_type"],
            "instruction": guidance.get(
                item["issue_type"],
                f"Review previous occurrences of {item['issue_type']}.",
            ),
            "previous_submissions": item["submission_count"],
        }
        for item in recurring_errors
    ]

    return {
        "customer_code": customer_code,
        "customer_name": customer["customer_name"],
        "submission_count": len(history),
        "recurring_errors": recurring_errors,
        "checklist": checklist,
        "history": [dict(row) for row in history],
    }


def save_reconciliation_history(
    session_id,
    result,
    customer_code,
    customer_name=None,
):
    customer_code = normalize_customer_code(customer_code)
    findings = result.get("findings", [])

    with get_connection() as conn:
        customer_id = get_or_create_customer(
            conn,
            session_id,
            customer_code,
            customer_name,
        )

        previous_patterns = conn.execute(
            """
            SELECT DISTINCT e.issue_type
            FROM submission_errors e
            JOIN submission_history h
                ON h.id = e.submission_id
            WHERE h.customer_id = ?
            """,
            (customer_id,),
        ).fetchall()

        previous_issue_types = {
            row["issue_type"] for row in previous_patterns
        }

        for finding in findings:
            finding["is_repeat"] = (
                finding.get("issue_type") in previous_issue_types
            )

        cursor = conn.execute(
            """
            INSERT INTO submission_history (
                customer_id,
                submission_type,
                total_samples,
                error_count
            )
            VALUES (?, 'Reconciliation', ?, ?)
            """,
            (
                customer_id,
                result.get("customer_order_count", 0),
                len(findings),
            ),
        )

        submission_id = cursor.lastrowid

        for finding in findings:
            conn.execute(
                """
                INSERT INTO submission_errors (
                    submission_id,
                    sample_id,
                    issue_type,
                    description,
                    severity
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    submission_id,
                    finding.get("sample_id", ""),
                    finding.get("issue_type", "Unknown issue"),
                    finding.get("description", ""),
                    finding.get("severity", "Medium"),
                ),
            )

    return get_error_intelligence(session_id, customer_code)


# =========================================
# LATEST RECONCILIATION AND AI REPORT
# =========================================

def save_latest_reconciliation(
    session_id,
    customer_code,
    customer_name,
    result,
):
    """Save the latest reconciliation for this visitor only."""

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO session_latest_results (
                session_id,
                customer_code,
                customer_name,
                result_json,
                ai_report_json,
                updated_at
            )
            VALUES (?, ?, ?, ?, NULL, CURRENT_TIMESTAMP)
            ON CONFLICT(session_id)
            DO UPDATE SET
                customer_code = excluded.customer_code,
                customer_name = excluded.customer_name,
                result_json = excluded.result_json,
                ai_report_json = NULL,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                session_id,
                customer_code,
                customer_name,
                json.dumps(result),
            ),
        )


def save_latest_ai_report(session_id, ai_report):
    """Save the latest AI report for this visitor only."""

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO session_latest_results (
                session_id,
                ai_report_json,
                updated_at
            )
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(session_id)
            DO UPDATE SET
                ai_report_json = excluded.ai_report_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                session_id,
                json.dumps(ai_report),
            ),
        )


# =========================================
# STARTUP
# =========================================

@app.on_event("startup")
def startup():
    initialize_database()


# =========================================
# DASHBOARD
# =========================================

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    session_id = get_session_id(request)

    with get_connection() as conn:
        inspection_id = get_latest_inspection_id(conn, session_id)

        if inspection_id is None:
            samples = []
            findings = []
        else:
            samples = conn.execute(
                """
                SELECT *
                FROM samples
                WHERE inspection_id = ?
                  AND session_id = ?
                ORDER BY id DESC
                LIMIT 100
                """,
                (inspection_id, session_id),
            ).fetchall()

            findings = conn.execute(
                """
                SELECT *
                FROM findings
                WHERE inspection_id = ?
                  AND session_id = ?
                ORDER BY id DESC
                LIMIT 100
                """,
                (inspection_id, session_id),
            ).fetchall()

        stats = get_latest_inspection_stats(conn, session_id)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "title": "Sample Check",
            "samples": [dict(row) for row in samples],
            "findings": [dict(row) for row in findings],
            "stats": stats,
        },
    )


# =========================================
# DEMO DOWNLOAD
# =========================================

@app.get("/demo/sample_check_demo.csv")
async def download_demo():
    demo_file = BASE_DIR / "sample_data" / "sample_check_demo.csv"
    print("DEMO CSV PATH:", demo_file.resolve())
    print("DEMO CSV EXISTS:", demo_file.exists())

    if not demo_file.exists():
        raise HTTPException(
            status_code=404,
            detail="Demo CSV file not found.",
        )

    return FileResponse(
        path=demo_file,
        filename="sample_check_demo.csv",
        media_type="text/csv",
        headers={"Cache-Control": "no-store"},
    )


# =========================================
# SINGLE-FILE SAMPLE INSPECTION
# =========================================

@app.post("/api/upload")
async def upload_samples(
    request: Request,
    file: UploadFile = File(...),
):
    session_id = get_session_id(request)

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="Please upload a CSV file.",
        )

    content = await file.read(MAX_UPLOAD_SIZE + 1)
    await file.close()

    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail="Maximum upload size is 2 MB.",
        )

    try:
        csv_content = content.decode("utf-8-sig")
        samples, findings = inspect_csv(csv_content)

    except (UnicodeDecodeError, csv.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not samples:
        raise HTTPException(
            status_code=400,
            detail="The CSV contains no sample records.",
        )

    try:
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO inspections (
                    total_samples,
                    finding_count,
                    session_id
                )
                VALUES (?, ?, ?)
                """,
                (len(samples), len(findings), session_id),
            )

            inspection_id = cursor.lastrowid

            for sample in samples:
                sample_id = sample["sample_id"]
                record_id = sample["_record_id"]

                has_issue = any(
                    finding["sample_id"] in {record_id, sample_id}
                    for finding in findings
                )

                conn.execute(
                    """
                    INSERT INTO samples (
                        sample_id,
                        patient_code,
                        sample_type,
                        collection_date,
                        status,
                        inspection_id,
                        session_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record_id,
                        sample["patient_code"],
                        sample["sample_type"],
                        sample["collection_date"],
                        "Needs Review" if has_issue else "Received",
                        inspection_id,
                        session_id,
                    ),
                )

            for finding in findings:
                conn.execute(
                    """
                    INSERT INTO findings (
                        sample_id,
                        issue_type,
                        description,
                        severity,
                        status,
                        inspection_id,
                        session_id
                    )
                    VALUES (?, ?, ?, ?, 'Open', ?, ?)
                    """,
                    (
                        finding["sample_id"],
                        finding["issue_type"],
                        finding["description"],
                        finding["severity"],
                        inspection_id,
                        session_id,
                    ),
                )

    except Exception as exc:
        print(f"Database upload error: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Could not save the uploaded records.",
        )

    affected_records = {
        finding["sample_id"] for finding in findings
    }

    clean_samples = sum(
        1
        for sample in samples
        if (
            sample["_record_id"] not in affected_records
            and sample["sample_id"] not in affected_records
        )
    )

    return {
        "message": "Inspection completed successfully.",
        "inspection_id": inspection_id,
        "total_samples": len(samples),
        "total_findings": len(findings),
        "clean_samples": clean_samples,
        "samples": samples,
        "findings": findings,
    }


# =========================================
# CROSS-FILE RECONCILIATION
# =========================================

@app.post("/api/reconcile")
async def reconcile_samples(
    request: Request,
    customer_order: UploadFile = File(...),
    lab_manifest: UploadFile = File(...),
    customer_code: str = Form(...),
    customer_name: str = Form(default=""),
):
    session_id = get_session_id(request)

    customer_code = normalize_customer_code(customer_code)
    customer_name = customer_name.strip()

    if not customer_code or len(customer_code) > 80:
        raise HTTPException(
            status_code=400,
            detail="Customer code must contain between 1 and 80 characters.",
        )

    if len(customer_name) > 120:
        raise HTTPException(
            status_code=400,
            detail="Customer name cannot exceed 120 characters.",
        )

    for uploaded_file in [customer_order, lab_manifest]:
        if (
            not uploaded_file.filename
            or not uploaded_file.filename.lower().endswith(".csv")
        ):
            raise HTTPException(
                status_code=400,
                detail="Both files must be CSV files.",
            )

    try:
        order_bytes = await customer_order.read(MAX_UPLOAD_SIZE + 1)
        manifest_bytes = await lab_manifest.read(MAX_UPLOAD_SIZE + 1)
    finally:
        await customer_order.close()
        await lab_manifest.close()

    if len(order_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail="Customer order exceeds the 2 MB limit.",
        )

    if len(manifest_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail="Lab manifest exceeds the 2 MB limit.",
        )

    try:
        order_content = order_bytes.decode("utf-8-sig")
        manifest_content = manifest_bytes.decode("utf-8-sig")

        result = reconcile_csv_files(
            order_content,
            manifest_content,
        )

    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Could not read a CSV file. Please use UTF-8 encoding.",
        )

    except (ValueError, csv.Error) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        intelligence = save_reconciliation_history(
            session_id,
            result,
            customer_code,
            customer_name,
        )
    except Exception as exc:
        print(f"History save error: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Reconciliation completed, but submission history could not be saved.",
        )

    try:
        save_latest_reconciliation(
            session_id,
            customer_code,
            intelligence["customer_name"],
            result,
        )
    except Exception as exc:
        print(f"Latest reconciliation save error: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Reconciliation completed, but the latest result could not be saved.",
        )

    return {
        "message": "Cross-file reconciliation completed.",
        "customer_code": customer_code,
        "customer_name": intelligence["customer_name"],
        "customer_order_file": customer_order.filename,
        "lab_manifest_file": lab_manifest.filename,
        "result": result,
        "repeat_error_intelligence": intelligence,
    }


# =========================================
# RESTORE LATEST RECONCILIATION AND AI REPORT
# =========================================

@app.get("/api/latest-reconciliation")
async def get_latest_reconciliation(request: Request):
    session_id = get_session_id(request)

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                customer_code,
                customer_name,
                result_json,
                ai_report_json,
                updated_at
            FROM session_latest_results
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()

    if not row:
        return {
            "saved": False,
            "result": None,
            "ai_report": None,
        }

    result = (
        json.loads(row["result_json"])
        if row["result_json"]
        else None
    )

    ai_report = (
        json.loads(row["ai_report_json"])
        if row["ai_report_json"]
        else None
    )

    return {
        "saved": bool(result or ai_report),
        "customer_code": row["customer_code"],
        "customer_name": row["customer_name"],
        "result": result,
        "ai_report": ai_report,
        "updated_at": row["updated_at"],
    }


# =========================================
# REPEAT ERROR INTELLIGENCE
# =========================================

@app.get("/api/error-intelligence")
async def error_intelligence(
    request: Request,
    customer_code: str,
):
    if not customer_code.strip():
        raise HTTPException(
            status_code=400,
            detail="Customer code cannot be empty.",
        )

    return get_error_intelligence(
        get_session_id(request),
        customer_code,
    )


# =========================================
# SINGLE-FILE FINDINGS
# =========================================

@app.get("/api/findings")
async def get_findings(request: Request):
    session_id = get_session_id(request)

    with get_connection() as conn:
        inspection_id = get_latest_inspection_id(conn, session_id)

        if inspection_id is None:
            rows = []
        else:
            rows = conn.execute(
                """
                SELECT *
                FROM findings
                WHERE inspection_id = ?
                  AND session_id = ?
                ORDER BY id DESC
                LIMIT 100
                """,
                (inspection_id, session_id),
            ).fetchall()

    return {
        "inspection_id": inspection_id,
        "findings": [dict(row) for row in rows],
    }


@app.patch("/api/findings/{finding_id}/resolve")
async def resolve_finding(
    finding_id: int,
    request: Request,
):
    session_id = get_session_id(request)

    with get_connection() as conn:
        result = conn.execute(
            """
            UPDATE findings
            SET status = 'Resolved'
            WHERE id = ?
              AND session_id = ?
              AND status = 'Open'
            """,
            (finding_id, session_id),
        )

        if result.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Open finding not found in this workspace.",
            )

    return {
        "message": "Finding marked as resolved.",
        "finding_id": finding_id,
        "status": "Resolved",
    }


@app.get("/api/stats")
async def get_stats(request: Request):
    with get_connection() as conn:
        return get_latest_inspection_stats(
            conn,
            get_session_id(request),
        )


# =========================================
# VULTR AI INVESTIGATION
# =========================================

@app.post("/api/ai/analyze")
def analyze_open_findings(
    request: Request,
    payload: dict | None = Body(default=None),
):
    session_id = get_session_id(request)

    if payload is not None and "findings" in payload:
        findings_to_analyze = payload["findings"]

        if not isinstance(findings_to_analyze, list):
            raise HTTPException(
                status_code=400,
                detail="The findings field must be a list.",
            )

        if len(findings_to_analyze) > 100:
            raise HTTPException(
                status_code=400,
                detail="Too many findings. Maximum is 100.",
            )

        source = payload.get("source", "reconciliation")

    else:
        with get_connection() as conn:
            inspection_id = get_latest_inspection_id(conn, session_id)

            if inspection_id is None:
                rows = []
            else:
                rows = conn.execute(
                    """
                    SELECT sample_id, issue_type, description, severity
                    FROM findings
                    WHERE inspection_id = ?
                      AND session_id = ?
                      AND status = 'Open'
                    ORDER BY
                        CASE severity
                            WHEN 'High' THEN 1
                            WHEN 'Medium' THEN 2
                            ELSE 3
                        END,
                        id DESC
                    LIMIT 30
                    """,
                    (inspection_id, session_id),
                ).fetchall()

        findings_to_analyze = [dict(row) for row in rows]
        source = "database"

    if not all(isinstance(item, dict) for item in findings_to_analyze):
        raise HTTPException(
            status_code=400,
            detail="Each finding must be a JSON object.",
        )

    try:
        analysis = analyze_findings(findings_to_analyze)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    response_data = {
        "message": "AI analysis completed.",
        "model": "deepseek-v4.1-flash-1017",
        "analysis_source": source,
        "analyzed_findings": len(findings_to_analyze),
        "analysis": analysis,
    }

    try:
        save_latest_ai_report(session_id, response_data)
    except Exception as exc:
        print(f"AI report save error: {exc}")
        raise HTTPException(
            status_code=500,
            detail="AI analysis completed, but the report could not be saved.",
        )

    return response_data


# =========================================
# HEALTH
# =========================================

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "application": "Sample Check",
    }
