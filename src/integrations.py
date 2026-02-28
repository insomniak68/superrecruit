"""Integration API key management for external partners."""

import hashlib
import secrets
import json
from datetime import datetime
from .database import get_db


def _hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def init_integration_tables():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS integrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        api_key_hash TEXT NOT NULL UNIQUE,
        webhook_url TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS submissions (
        id TEXT PRIMARY KEY,
        integration_id INTEGER NOT NULL,
        candidate_id INTEGER,
        status TEXT DEFAULT 'accepted',
        callback_url TEXT,
        metadata TEXT DEFAULT '{}',
        results TEXT,
        error TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (integration_id) REFERENCES integrations(id)
    );
    CREATE TABLE IF NOT EXISTS webhook_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        submission_id TEXT NOT NULL,
        integration_id INTEGER NOT NULL,
        event TEXT NOT NULL,
        url TEXT NOT NULL,
        status_code INTEGER,
        attempt INTEGER DEFAULT 1,
        response_body TEXT,
        error TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (submission_id) REFERENCES submissions(id),
        FOREIGN KEY (integration_id) REFERENCES integrations(id)
    );
    """)
    conn.commit()
    conn.close()


def create_integration(name: str, webhook_url: str | None = None) -> tuple[dict, str]:
    """Create integration. Returns (integration_dict, raw_api_key)."""
    api_key = f"sr_live_{secrets.token_urlsafe(32)}"
    key_hash = _hash_key(api_key)
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO integrations (name, api_key_hash, webhook_url) VALUES (?,?,?)",
        (name, key_hash, webhook_url)
    )
    integration_id = cur.lastrowid
    conn.commit()
    row = conn.execute("SELECT * FROM integrations WHERE id=?", (integration_id,)).fetchone()
    conn.close()
    return dict(row), api_key


def authenticate_api_key(api_key: str) -> dict | None:
    """Validate API key, return integration or None."""
    key_hash = _hash_key(api_key)
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM integrations WHERE api_key_hash=? AND is_active=1", (key_hash,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_integrations() -> list[dict]:
    conn = get_db()
    rows = conn.execute("SELECT id, name, webhook_url, is_active, created_at FROM integrations ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def revoke_integration(integration_id: int) -> bool:
    conn = get_db()
    cur = conn.execute("UPDATE integrations SET is_active=0 WHERE id=?", (integration_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def create_submission(submission_id: str, integration_id: int, callback_url: str | None = None, metadata: dict | None = None):
    conn = get_db()
    conn.execute(
        "INSERT INTO submissions (id, integration_id, callback_url, metadata) VALUES (?,?,?,?)",
        (submission_id, integration_id, callback_url, json.dumps(metadata or {}))
    )
    conn.commit()
    conn.close()


def update_submission(submission_id: str, **kwargs):
    conn = get_db()
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k in ("status", "candidate_id", "results", "error"):
            sets.append(f"{k}=?")
            vals.append(v)
    if sets:
        sets.append("updated_at=?")
        vals.append(datetime.utcnow().isoformat())
        vals.append(submission_id)
        conn.execute(f"UPDATE submissions SET {', '.join(sets)} WHERE id=?", vals)
        conn.commit()
    conn.close()


def get_submission(submission_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM submissions WHERE id=?", (submission_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_submissions(integration_id: int | None = None, status: str | None = None,
                     date_from: str | None = None, date_to: str | None = None,
                     limit: int = 50, offset: int = 0) -> list[dict]:
    conn = get_db()
    clauses = []
    params = []
    if integration_id is not None:
        clauses.append("integration_id=?")
        params.append(integration_id)
    if status:
        clauses.append("status=?")
        params.append(status)
    if date_from:
        clauses.append("created_at >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("created_at <= ?")
        params.append(date_to)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.extend([limit, offset])
    rows = conn.execute(
        f"SELECT id, integration_id, status, created_at, updated_at FROM submissions {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
