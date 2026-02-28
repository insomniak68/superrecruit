"""Skill equivalencies — CRUD, matching logic, and seed data."""

import json
import logging
from typing import Optional

from .database import get_db
from .models import (
    EquivalencyGroupCreate,
    EquivalencyGroupUpdate,
    EquivalencyGroupResponse,
    EquivalencySkill,
)

logger = logging.getLogger(__name__)


# ── CRUD ──

def _row_to_response(row, skills: list[dict]) -> EquivalencyGroupResponse:
    return EquivalencyGroupResponse(
        id=row["id"],
        name=row["name"],
        description=row["description"] or "",
        skills=[EquivalencySkill(skill_name=s["skill_name"], weight=s["weight"]) for s in skills],
        created_at=str(row["created_at"]),
    )


def create_equivalency_group(data: EquivalencyGroupCreate) -> EquivalencyGroupResponse:
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO skill_equivalency_groups (name, description) VALUES (?, ?)",
        (data.name, data.description),
    )
    group_id = cur.lastrowid
    for s in data.skills:
        conn.execute(
            "INSERT INTO skill_equivalencies (group_id, skill_name, weight) VALUES (?, ?, ?)",
            (group_id, s.skill_name.lower().strip(), s.weight),
        )
    conn.commit()
    row = conn.execute("SELECT * FROM skill_equivalency_groups WHERE id=?", (group_id,)).fetchone()
    skills = conn.execute("SELECT * FROM skill_equivalencies WHERE group_id=?", (group_id,)).fetchall()
    conn.close()
    return _row_to_response(row, [dict(s) for s in skills])


def get_equivalency_group(group_id: int) -> Optional[EquivalencyGroupResponse]:
    conn = get_db()
    row = conn.execute("SELECT * FROM skill_equivalency_groups WHERE id=?", (group_id,)).fetchone()
    if not row:
        conn.close()
        return None
    skills = conn.execute("SELECT * FROM skill_equivalencies WHERE group_id=?", (group_id,)).fetchall()
    conn.close()
    return _row_to_response(row, [dict(s) for s in skills])


def list_equivalency_groups() -> list[EquivalencyGroupResponse]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM skill_equivalency_groups ORDER BY created_at DESC").fetchall()
    result = []
    for row in rows:
        skills = conn.execute("SELECT * FROM skill_equivalencies WHERE group_id=?", (row["id"],)).fetchall()
        result.append(_row_to_response(row, [dict(s) for s in skills]))
    conn.close()
    return result


def update_equivalency_group(group_id: int, data: EquivalencyGroupUpdate) -> Optional[EquivalencyGroupResponse]:
    conn = get_db()
    row = conn.execute("SELECT * FROM skill_equivalency_groups WHERE id=?", (group_id,)).fetchone()
    if not row:
        conn.close()
        return None
    if data.name is not None:
        conn.execute("UPDATE skill_equivalency_groups SET name=? WHERE id=?", (data.name, group_id))
    if data.description is not None:
        conn.execute("UPDATE skill_equivalency_groups SET description=? WHERE id=?", (data.description, group_id))
    if data.skills is not None:
        conn.execute("DELETE FROM skill_equivalencies WHERE group_id=?", (group_id,))
        for s in data.skills:
            conn.execute(
                "INSERT INTO skill_equivalencies (group_id, skill_name, weight) VALUES (?, ?, ?)",
                (group_id, s.skill_name.lower().strip(), s.weight),
            )
    conn.commit()
    row = conn.execute("SELECT * FROM skill_equivalency_groups WHERE id=?", (group_id,)).fetchone()
    skills = conn.execute("SELECT * FROM skill_equivalencies WHERE group_id=?", (group_id,)).fetchall()
    conn.close()
    return _row_to_response(row, [dict(s) for s in skills])


def delete_equivalency_group(group_id: int) -> bool:
    conn = get_db()
    conn.execute("DELETE FROM skill_equivalencies WHERE group_id=?", (group_id,))
    cur = conn.execute("DELETE FROM skill_equivalency_groups WHERE id=?", (group_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# ── Seed Data ──

SEED_GROUPS = [
    {
        "name": "Cloud Platforms",
        "description": "Major cloud providers",
        "skills": [
            {"skill_name": "aws", "weight": 1.0},
            {"skill_name": "azure", "weight": 0.9},
            {"skill_name": "gcp", "weight": 0.85},
        ],
    },
    {
        "name": "Frontend Frameworks",
        "description": "JavaScript frontend frameworks",
        "skills": [
            {"skill_name": "react", "weight": 1.0},
            {"skill_name": "vue", "weight": 0.85},
            {"skill_name": "angular", "weight": 0.8},
            {"skill_name": "svelte", "weight": 0.75},
        ],
    },
    {
        "name": "Backend Languages",
        "description": "Server-side programming languages",
        "skills": [
            {"skill_name": "python", "weight": 1.0},
            {"skill_name": "java", "weight": 0.9},
            {"skill_name": "go", "weight": 0.85},
            {"skill_name": "c#", "weight": 0.85},
            {"skill_name": "node.js", "weight": 0.8},
        ],
    },
    {
        "name": "Databases",
        "description": "Database technologies",
        "skills": [
            {"skill_name": "postgresql", "weight": 1.0},
            {"skill_name": "mysql", "weight": 0.9},
            {"skill_name": "mongodb", "weight": 0.7},
            {"skill_name": "redis", "weight": 0.6},
        ],
    },
    {
        "name": "Container Orchestration",
        "description": "Container and orchestration tools",
        "skills": [
            {"skill_name": "kubernetes", "weight": 1.0},
            {"skill_name": "docker", "weight": 0.8},
            {"skill_name": "docker swarm", "weight": 0.6},
        ],
    },
    {
        "name": "CI/CD",
        "description": "Continuous integration and deployment",
        "skills": [
            {"skill_name": "github actions", "weight": 1.0},
            {"skill_name": "jenkins", "weight": 0.85},
            {"skill_name": "gitlab ci", "weight": 0.9},
            {"skill_name": "circleci", "weight": 0.8},
        ],
    },
]


def seed_equivalency_groups() -> list[EquivalencyGroupResponse]:
    """Seed common equivalency groups. Skips groups whose names already exist."""
    conn = get_db()
    existing = {row["name"] for row in conn.execute("SELECT name FROM skill_equivalency_groups").fetchall()}
    conn.close()

    created = []
    for group_data in SEED_GROUPS:
        if group_data["name"] in existing:
            continue
        data = EquivalencyGroupCreate(
            name=group_data["name"],
            description=group_data["description"],
            skills=[EquivalencySkill(**s) for s in group_data["skills"]],
        )
        created.append(create_equivalency_group(data))
    return created


# ── Matching Logic ──

def find_equivalents(skill_name: str, position_id: int = None) -> list[dict]:
    """Find equivalent skills + weights for a given skill.

    Returns list of {"skill_name": str, "weight": float} for all skills
    in the same equivalency group(s), excluding the input skill itself.

    Position-level overrides take precedence if position_id is provided.
    """
    skill_lower = skill_name.lower().strip()

    # Check position-level overrides first
    if position_id is not None:
        conn = get_db()
        row = conn.execute(
            "SELECT equivalency_overrides FROM position_profiles WHERE id=?", (position_id,)
        ).fetchone()
        conn.close()
        if row and row["equivalency_overrides"]:
            try:
                overrides = json.loads(row["equivalency_overrides"])
                # overrides format: list of groups, same as EquivalencyGroupCreate
                for group in overrides:
                    group_skills = {s["skill_name"].lower().strip(): s["weight"] for s in group.get("skills", [])}
                    if skill_lower in group_skills:
                        return [
                            {"skill_name": s_name, "weight": s_weight}
                            for s_name, s_weight in group_skills.items()
                            if s_name != skill_lower
                        ]
            except (json.JSONDecodeError, TypeError):
                pass

    # Global equivalencies
    conn = get_db()
    rows = conn.execute(
        """SELECT g.id as group_id FROM skill_equivalency_groups g
           JOIN skill_equivalencies e ON e.group_id = g.id
           WHERE LOWER(e.skill_name) = ?""",
        (skill_lower,),
    ).fetchall()

    if not rows:
        conn.close()
        return []

    group_ids = list({r["group_id"] for r in rows})
    equivalents = []
    for gid in group_ids:
        skills = conn.execute(
            "SELECT skill_name, weight FROM skill_equivalencies WHERE group_id=? AND LOWER(skill_name) != ?",
            (gid, skill_lower),
        ).fetchall()
        for s in skills:
            equivalents.append({"skill_name": s["skill_name"], "weight": s["weight"]})

    conn.close()
    return equivalents


def adjusted_skill_score(
    candidate_skill: str,
    required_skill: str,
    base_score: float = 1.0,
    position_id: int = None,
) -> tuple[float, str]:
    """Return (adjusted_score, explanation) factoring in equivalency weight.

    If candidate_skill == required_skill, returns (base_score, "exact match").
    Otherwise checks equivalency groups for the required_skill.
    """
    if candidate_skill.lower().strip() == required_skill.lower().strip():
        return base_score, "exact match"

    equivalents = find_equivalents(required_skill, position_id=position_id)
    candidate_lower = candidate_skill.lower().strip()

    for eq in equivalents:
        if eq["skill_name"] == candidate_lower:
            weight = eq["weight"]
            adjusted = round(base_score * weight, 3)
            pct = int(weight * 100)
            explanation = f"{required_skill} required → has {candidate_skill} ({pct}% equivalent) → adjusted score: {adjusted}"
            return adjusted, explanation

    return 0.0, f"no equivalency found between {candidate_skill} and {required_skill}"
