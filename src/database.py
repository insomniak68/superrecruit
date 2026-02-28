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
    CREATE TABLE IF NOT EXISTS workspace_conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        actions_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (candidate_id) REFERENCES candidates(id)
    );
    CREATE TABLE IF NOT EXISTS skill_concepts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        canonical_name TEXT NOT NULL UNIQUE,
        description TEXT DEFAULT '',
        category TEXT DEFAULT 'other',
        subconcepts TEXT DEFAULT '[]',
        competency_signals TEXT DEFAULT '{}',
        version INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS skill_relations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_skill_id INTEGER NOT NULL,
        target_skill_id INTEGER NOT NULL,
        relation_type TEXT NOT NULL,
        strength REAL DEFAULT 1.0,
        source TEXT DEFAULT 'system',
        FOREIGN KEY (source_skill_id) REFERENCES skill_concepts(id),
        FOREIGN KEY (target_skill_id) REFERENCES skill_concepts(id)
    );
    CREATE TABLE IF NOT EXISTS role_archetypes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        canonical_name TEXT NOT NULL UNIQUE,
        description TEXT DEFAULT '',
        career_paths TEXT DEFAULT '[]',
        green_flags TEXT DEFAULT '[]',
        red_flags TEXT DEFAULT '[]',
        version INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS role_archetype_skills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role_archetype_id INTEGER NOT NULL,
        skill_concept_id INTEGER NOT NULL,
        min_confidence REAL DEFAULT 0.0,
        weight REAL DEFAULT 1.0,
        is_core INTEGER DEFAULT 1,
        FOREIGN KEY (role_archetype_id) REFERENCES role_archetypes(id),
        FOREIGN KEY (skill_concept_id) REFERENCES skill_concepts(id)
    );
    CREATE TABLE IF NOT EXISTS employer_interpretations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role_archetype_id INTEGER NOT NULL,
        employer_name TEXT DEFAULT 'anonymous',
        equivalency_prefs TEXT DEFAULT '{}',
        notes TEXT DEFAULT '',
        learned_from TEXT DEFAULT '[]',
        version INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (role_archetype_id) REFERENCES role_archetypes(id)
    );
    CREATE TABLE IF NOT EXISTS employer_skill_overrides (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employer_interpretation_id INTEGER NOT NULL,
        skill_concept_id INTEGER NOT NULL,
        priority TEXT DEFAULT 'normal',
        weight_override REAL,
        FOREIGN KEY (employer_interpretation_id) REFERENCES employer_interpretations(id),
        FOREIGN KEY (skill_concept_id) REFERENCES skill_concepts(id)
    );
    CREATE TABLE IF NOT EXISTS fit_assessments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_id INTEGER NOT NULL,
        role_archetype_id INTEGER,
        fit_score REAL NOT NULL,
        fit_level TEXT NOT NULL,
        rationale TEXT DEFAULT '',
        breakdown_json TEXT DEFAULT '{}',
        assessed_by TEXT DEFAULT 'system',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (candidate_id) REFERENCES candidates(id),
        FOREIGN KEY (role_archetype_id) REFERENCES role_archetypes(id)
    );
    CREATE TABLE IF NOT EXISTS position_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        department TEXT DEFAULT '',
        description TEXT DEFAULT '',
        required_skills TEXT DEFAULT '[]',
        preferred_skills TEXT DEFAULT '[]',
        min_experience_years INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_active INTEGER DEFAULT 0,
        created_by TEXT DEFAULT 'manual'
    );
    CREATE TABLE IF NOT EXISTS skill_overrides (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_id INTEGER NOT NULL,
        skill_id INTEGER,
        field TEXT NOT NULL,
        old_value TEXT,
        new_value TEXT,
        source TEXT DEFAULT 'human',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (candidate_id) REFERENCES candidates(id),
        FOREIGN KEY (skill_id) REFERENCES skill_assessments(id)
    );
    """)
    conn.commit()
    conn.close()
