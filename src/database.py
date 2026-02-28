import sqlite3
import json
import os

DB_PATH = os.environ.get("SR_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "superrecruit.db"))


def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        phone TEXT,
        resume_path TEXT,
        resume_text TEXT,
        parsed_data TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS skill_assessments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_id INTEGER NOT NULL,
        skill_name TEXT NOT NULL,
        category TEXT,
        evidence TEXT,
        llm_confidence TEXT,
        final_confidence TEXT,
        reasoning TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (candidate_id) REFERENCES candidates(id)
    );
    CREATE TABLE IF NOT EXISTS assessment_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_id INTEGER NOT NULL,
        token TEXT UNIQUE NOT NULL,
        status TEXT DEFAULT 'pending',
        tests TEXT,
        sent_at TIMESTAMP,
        started_at TIMESTAMP,
        completed_at TIMESTAMP,
        expires_at TIMESTAMP,
        FOREIGN KEY (candidate_id) REFERENCES candidates(id)
    );
    CREATE TABLE IF NOT EXISTS test_submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        test_id TEXT NOT NULL,
        question_id TEXT NOT NULL,
        answer TEXT,
        is_correct INTEGER,
        score REAL,
        graded_by TEXT DEFAULT 'auto',
        submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES assessment_sessions(id)
    );
    CREATE TABLE IF NOT EXISTS test_bank_meta (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        test_id TEXT UNIQUE NOT NULL,
        name TEXT,
        category TEXT,
        skill_tags TEXT,
        times_administered INTEGER DEFAULT 0,
        avg_score REAL DEFAULT 0,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    conn.close()
