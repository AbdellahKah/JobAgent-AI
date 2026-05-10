"""
Persistent Job Database — SQLite storage for job tracking, deduplication, and application status.
"""

import sqlite3
import os
from datetime import datetime
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "jobs.db")


def get_connection():
    """Create a connection with row_factory for dict-like access."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Initialize database schema."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT DEFAULT '',
                description TEXT DEFAULT '',
                url TEXT DEFAULT '',
                url_is_fallback INTEGER DEFAULT 0,
                match_score INTEGER DEFAULT 0,
                status TEXT DEFAULT 'new',
                notes TEXT DEFAULT '',
                saved_at TEXT NOT NULL,
                applied_at TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            CREATE INDEX IF NOT EXISTS idx_jobs_company_title ON jobs(company, title);
        """)
    print("[DB] Database initialized at:", DB_PATH)


def save_job(job_data: dict) -> dict:
    """Save a job to the database. Returns the saved job with its ID."""
    now = datetime.now().isoformat()
    with get_db() as conn:
        # Check for duplicates (same title + company)
        existing = conn.execute(
            "SELECT id FROM jobs WHERE title = ? AND company = ?",
            (job_data.get("title", ""), job_data.get("company", ""))
        ).fetchone()

        if existing:
            # Update existing record
            conn.execute("""
                UPDATE jobs SET
                    location = ?, description = ?, url = ?, url_is_fallback = ?,
                    match_score = ?, updated_at = ?
                WHERE id = ?
            """, (
                job_data.get("location", ""),
                job_data.get("desc", ""),
                job_data.get("url", ""),
                1 if job_data.get("url_is_fallback", False) else 0,
                job_data.get("match", 0),
                now,
                existing["id"]
            ))
            job_id = existing["id"]
        else:
            # Insert new
            cursor = conn.execute("""
                INSERT INTO jobs (title, company, location, description, url, url_is_fallback,
                                  match_score, status, saved_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'saved', ?, ?)
            """, (
                job_data.get("title", ""),
                job_data.get("company", ""),
                job_data.get("location", ""),
                job_data.get("desc", ""),
                job_data.get("url", ""),
                1 if job_data.get("url_is_fallback", False) else 0,
                job_data.get("match", 0),
                now, now
            ))
            job_id = cursor.lastrowid

    return get_job_by_id(job_id)


def get_job_by_id(job_id: int) -> dict | None:
    """Get a single job by ID."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def get_all_jobs(status: str | None = None) -> list[dict]:
    """Get all saved jobs, optionally filtered by status."""
    with get_db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY updated_at DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY updated_at DESC"
            ).fetchall()
    return [dict(row) for row in rows]


def update_job_status(job_id: int, status: str, notes: str | None = None) -> dict | None:
    """Update a job's application status."""
    now = datetime.now().isoformat()
    valid_statuses = {"new", "saved", "applied", "interview", "offer", "rejected", "archived"}

    if status not in valid_statuses:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {valid_statuses}")

    with get_db() as conn:
        updates = ["status = ?", "updated_at = ?"]
        params = [status, now]

        if status == "applied":
            updates.append("applied_at = ?")
            params.append(now)

        if notes is not None:
            updates.append("notes = ?")
            params.append(notes)

        params.append(job_id)
        conn.execute(f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?", params)

    return get_job_by_id(job_id)


def delete_job(job_id: int) -> bool:
    """Delete a job from the database."""
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        return cursor.rowcount > 0


def find_duplicates(title: str, company: str) -> dict | None:
    """Check if a job already exists in the database."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE title = ? AND company = ?",
            (title, company)
        ).fetchone()
        return dict(row) if row else None


def get_stats() -> dict:
    """Get summary statistics of tracked jobs."""
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) as c FROM jobs").fetchone()["c"]
        by_status = conn.execute(
            "SELECT status, COUNT(*) as c FROM jobs GROUP BY status"
        ).fetchall()
    return {
        "total": total,
        "by_status": {row["status"]: row["c"] for row in by_status}
    }


# Initialize on import
init_db()
