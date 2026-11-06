import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "sample_check.db"

LEGACY_SESSION_ID = "legacy-existing-records"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database():
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS visitor_sessions (
                id TEXT PRIMARY KEY,
                token_hash TEXT NOT NULL UNIQUE,
                created_at REAL NOT NULL,
                last_seen REAL NOT NULL,
                expires_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sample_id TEXT NOT NULL,
                patient_code TEXT,
                sample_type TEXT,
                collection_date TEXT,
                status TEXT DEFAULT 'Received',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS findings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sample_id TEXT NOT NULL,
                issue_type TEXT NOT NULL,
                description TEXT NOT NULL,
                severity TEXT DEFAULT 'Medium',
                status TEXT DEFAULT 'Open',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS inspections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                total_samples INTEGER DEFAULT 0,
                finding_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_code TEXT NOT NULL UNIQUE,
                customer_name TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS submission_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                submission_type TEXT DEFAULT 'Reconciliation',
                total_samples INTEGER DEFAULT 0,
                error_count INTEGER DEFAULT 0,
                submitted_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (customer_id)
                    REFERENCES customers(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS submission_errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                submission_id INTEGER NOT NULL,
                sample_id TEXT,
                issue_type TEXT NOT NULL,
                description TEXT,
                severity TEXT DEFAULT 'Medium',
                FOREIGN KEY (submission_id)
                    REFERENCES submission_history(id)
                    ON DELETE CASCADE
            );
                        CREATE TABLE IF NOT EXISTS session_latest_results (
                session_id TEXT PRIMARY KEY,
                customer_code TEXT,
                customer_name TEXT,
                result_json TEXT,
                ai_report_json TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Add new columns without deleting existing records.
        columns_to_add = {
            "samples": "session_id TEXT",
            "findings": "session_id TEXT",
            "inspections": "session_id TEXT",
            "customers": "session_id TEXT",
        }

        for table, column_definition in columns_to_add.items():
            column_name = column_definition.split()[0]

            columns = {
                row["name"]
                for row in conn.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()
            }

            if column_name not in columns:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column_definition}"
                )

        # Preserve all existing records in a private legacy workspace.
        for table in ("samples", "findings", "inspections", "customers"):
            conn.execute(
                f"""
                UPDATE {table}
                SET session_id = ?
                WHERE session_id IS NULL
                """,
                (LEGACY_SESSION_ID,),
            )

        # Add inspection_id to older databases if it is not present.
        for table in ("samples", "findings"):
            columns = {
                row["name"]
                for row in conn.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()
            }

            if "inspection_id" not in columns:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN inspection_id INTEGER"
                )

        # Group older records into inspections using their timestamps.
        timestamps = conn.execute("""
            SELECT created_at FROM samples
            WHERE inspection_id IS NULL

            UNION

            SELECT created_at FROM findings
            WHERE inspection_id IS NULL

            ORDER BY created_at
        """).fetchall()

        for timestamp_row in timestamps:
            timestamp = timestamp_row["created_at"]

            existing_inspection = conn.execute(
                """
                SELECT id
                FROM inspections
                WHERE created_at = ?
                  AND session_id = ?
                LIMIT 1
                """,
                (timestamp, LEGACY_SESSION_ID),
            ).fetchone()

            if existing_inspection:
                inspection_id = existing_inspection["id"]
            else:
                total_samples = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM samples
                    WHERE created_at = ?
                      AND inspection_id IS NULL
                    """,
                    (timestamp,),
                ).fetchone()[0]

                finding_count = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM findings
                    WHERE created_at = ?
                      AND inspection_id IS NULL
                    """,
                    (timestamp,),
                ).fetchone()[0]

                cursor = conn.execute(
                    """
                    INSERT INTO inspections (
                        total_samples,
                        finding_count,
                        created_at,
                        session_id
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        total_samples,
                        finding_count,
                        timestamp,
                        LEGACY_SESSION_ID,
                    ),
                )

                inspection_id = cursor.lastrowid

            conn.execute(
                """
                UPDATE samples
                SET inspection_id = ?
                WHERE created_at = ?
                  AND inspection_id IS NULL
                """,
                (inspection_id, timestamp),
            )

            conn.execute(
                """
                UPDATE findings
                SET inspection_id = ?
                WHERE created_at = ?
                  AND inspection_id IS NULL
                """,
                (inspection_id, timestamp),
            )

        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_samples_inspection
                ON samples(inspection_id);

            CREATE INDEX IF NOT EXISTS idx_findings_inspection
                ON findings(inspection_id);

            CREATE INDEX IF NOT EXISTS idx_samples_session
                ON samples(session_id);

            CREATE INDEX IF NOT EXISTS idx_findings_session
                ON findings(session_id);

            CREATE INDEX IF NOT EXISTS idx_inspections_session
                ON inspections(session_id);

            CREATE INDEX IF NOT EXISTS idx_customers_session
                ON customers(session_id);

            CREATE INDEX IF NOT EXISTS idx_submission_customer
                ON submission_history(customer_id);

            CREATE INDEX IF NOT EXISTS idx_submission_errors_type
                ON submission_errors(issue_type);
        """)