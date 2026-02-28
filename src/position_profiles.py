"""Position profiles — CRUD and job posting parser."""

import json
import logging
from typing import Optional

from .database import get_db
from .models import (
    PositionProfileCreate,
    PositionProfileUpdate,
    PositionProfileResponse,
    SkillRequirement,
)
from .llm_config import get_client

logger = logging.getLogger(__name__)


def _row_to_response(row) -> PositionProfileResponse:
    return PositionProfileResponse(
        id=row["id"],
        title=row["title"],
        department=row["department"] or "",
        description=row["description"] or "",
        required_skills=[SkillRequirement(**s) for s in json.loads(row["required_skills"] or "[]")],
        preferred_skills=[SkillRequirement(**s) for s in json.loads(row["preferred_skills"] or "[]")],
        min_experience_years=row["min_experience_years"] or 0,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        is_active=bool(row["is_active"]),
        created_by=row["created_by"] or "manual",
    )


def create_position(data: PositionProfileCreate, created_by: str = "manual") -> PositionProfileResponse:
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO position_profiles (title, department, description, required_skills, preferred_skills, min_experience_years, created_by) VALUES (?,?,?,?,?,?,?)",
        (
            data.title,
            data.department,
            data.description,
            json.dumps([s.model_dump() for s in data.required_skills]),
            json.dumps([s.model_dump() for s in data.preferred_skills]),
            data.min_experience_years,
            created_by,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM position_profiles WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return _row_to_response(row)


def get_position(position_id: int) -> Optional[PositionProfileResponse]:
    conn = get_db()
    row = conn.execute("SELECT * FROM position_profiles WHERE id=?", (position_id,)).fetchone()
    conn.close()
    return _row_to_response(row) if row else None


def list_positions() -> list[PositionProfileResponse]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM position_profiles ORDER BY created_at DESC").fetchall()
    conn.close()
    return [_row_to_response(r) for r in rows]


def update_position(position_id: int, data: PositionProfileUpdate) -> Optional[PositionProfileResponse]:
    conn = get_db()
    row = conn.execute("SELECT * FROM position_profiles WHERE id=?", (position_id,)).fetchone()
    if not row:
        conn.close()
        return None
    updates = {}
    if data.title is not None:
        updates["title"] = data.title
    if data.department is not None:
        updates["department"] = data.department
    if data.description is not None:
        updates["description"] = data.description
    if data.required_skills is not None:
        updates["required_skills"] = json.dumps([s.model_dump() for s in data.required_skills])
    if data.preferred_skills is not None:
        updates["preferred_skills"] = json.dumps([s.model_dump() for s in data.preferred_skills])
    if data.min_experience_years is not None:
        updates["min_experience_years"] = data.min_experience_years
    if updates:
        updates["updated_at"] = "CURRENT_TIMESTAMP"
        set_clause = ", ".join(
            f"{k} = CURRENT_TIMESTAMP" if v == "CURRENT_TIMESTAMP" else f"{k} = ?"
            for k, v in updates.items()
        )
        values = [v for v in updates.values() if v != "CURRENT_TIMESTAMP"]
        conn.execute(f"UPDATE position_profiles SET {set_clause} WHERE id=?", (*values, position_id))
        conn.commit()
    row = conn.execute("SELECT * FROM position_profiles WHERE id=?", (position_id,)).fetchone()
    conn.close()
    return _row_to_response(row)


def delete_position(position_id: int) -> bool:
    conn = get_db()
    cur = conn.execute("DELETE FROM position_profiles WHERE id=?", (position_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def activate_position(position_id: int) -> Optional[PositionProfileResponse]:
    conn = get_db()
    row = conn.execute("SELECT * FROM position_profiles WHERE id=?", (position_id,)).fetchone()
    if not row:
        conn.close()
        return None
    # Deactivate all others
    conn.execute("UPDATE position_profiles SET is_active=0")
    conn.execute("UPDATE position_profiles SET is_active=1, updated_at=CURRENT_TIMESTAMP WHERE id=?", (position_id,))
    conn.commit()
    row = conn.execute("SELECT * FROM position_profiles WHERE id=?", (position_id,)).fetchone()
    conn.close()
    return _row_to_response(row)


def get_active_position() -> Optional[PositionProfileResponse]:
    conn = get_db()
    row = conn.execute("SELECT * FROM position_profiles WHERE is_active=1 LIMIT 1").fetchone()
    conn.close()
    return _row_to_response(row) if row else None


def parse_job_posting(text: str) -> PositionProfileCreate:
    """Use LLM to parse job posting text into a structured position profile."""
    client = get_client("confidence_reasoning")
    prompt = f"""Parse this job posting into a structured position profile. Return valid JSON only, no markdown.

Job posting:
---
{text}
---

Return JSON with this exact structure:
{{
  "title": "Job Title",
  "department": "Department or empty string",
  "description": "Brief description of the role",
  "required_skills": [
    {{"skill_name": "Python", "min_confidence": 0.7, "weight": 1.0}},
    ...
  ],
  "preferred_skills": [
    {{"skill_name": "Docker", "min_confidence": 0.3, "weight": 0.5}},
    ...
  ],
  "min_experience_years": 3
}}

Rules:
- required_skills: skills explicitly required or strongly implied
- preferred_skills: nice-to-have skills
- min_confidence: 0.0-1.0, how confident a candidate should be (0.7 = solid, 0.5 = familiar)
- weight: importance relative to other skills (1.0 = standard, 1.5 = critical, 0.5 = minor)
- Extract specific technical skills, not vague ones
- Return ONLY the JSON object, no explanation"""

    result = client.complete(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
        system="You are a job posting parser. Return only valid JSON.",
    )

    # Clean up response
    text_clean = result.strip()
    if text_clean.startswith("```"):
        text_clean = text_clean.split("\n", 1)[1] if "\n" in text_clean else text_clean[3:]
        if text_clean.endswith("```"):
            text_clean = text_clean[:-3]
        text_clean = text_clean.strip()

    parsed = json.loads(text_clean)
    return PositionProfileCreate(**parsed)
