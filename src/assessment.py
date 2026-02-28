import secrets
import json
from datetime import datetime, timedelta
from .database import get_db


def create_session(candidate_id: int, test_ids: list[str], hours_valid: int = 72) -> str:
    token = secrets.token_urlsafe(32)
    conn = get_db()
    conn.execute(
        """INSERT INTO assessment_sessions (candidate_id, token, status, tests, sent_at, expires_at)
           VALUES (?, ?, 'pending', ?, ?, ?)""",
        (candidate_id, token, json.dumps(test_ids), datetime.utcnow().isoformat(),
         (datetime.utcnow() + timedelta(hours=hours_valid)).isoformat())
    )
    conn.commit()
    conn.close()
    return token


def get_session_by_token(token: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM assessment_sessions WHERE token = ?", (token,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["tests"] = json.loads(d["tests"]) if d["tests"] else []
    return d


def start_session(token: str):
    conn = get_db()
    conn.execute("UPDATE assessment_sessions SET status='in_progress', started_at=? WHERE token=?",
                 (datetime.utcnow().isoformat(), token))
    conn.commit()
    conn.close()


def complete_session(token: str):
    conn = get_db()
    conn.execute("UPDATE assessment_sessions SET status='completed', completed_at=? WHERE token=?",
                 (datetime.utcnow().isoformat(), token))
    conn.commit()
    conn.close()


def save_submission(session_id: int, test_id: str, question_id: str, answer: str,
                    is_correct: bool | None = None, score: float = 0, graded_by: str = "auto"):
    conn = get_db()
    conn.execute(
        """INSERT INTO test_submissions (session_id, test_id, question_id, answer, is_correct, score, graded_by)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (session_id, test_id, question_id, answer, is_correct, score, graded_by)
    )
    conn.commit()
    conn.close()


def get_submissions(session_id: int) -> list[dict]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM test_submissions WHERE session_id = ?", (session_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
