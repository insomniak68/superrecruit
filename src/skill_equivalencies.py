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
    {
        "name": "ML/AI Frameworks",
        "description": "Machine learning and deep learning frameworks",
        "skills": [
            {"skill_name": "pytorch", "weight": 1.0},
            {"skill_name": "tensorflow", "weight": 0.95},
            {"skill_name": "keras", "weight": 0.8},
            {"skill_name": "jax", "weight": 0.75},
            {"skill_name": "scikit-learn", "weight": 0.7},
        ],
    },
    {
        "name": "Mobile Development",
        "description": "Mobile app development frameworks and platforms",
        "skills": [
            {"skill_name": "swift", "weight": 1.0},
            {"skill_name": "kotlin", "weight": 0.95},
            {"skill_name": "react native", "weight": 0.8},
            {"skill_name": "flutter", "weight": 0.8},
            {"skill_name": "objective-c", "weight": 0.7},
            {"skill_name": "java (android)", "weight": 0.7},
        ],
    },
    {
        "name": "Infrastructure as Code",
        "description": "IaC and configuration management tools",
        "skills": [
            {"skill_name": "terraform", "weight": 1.0},
            {"skill_name": "pulumi", "weight": 0.9},
            {"skill_name": "cloudformation", "weight": 0.8},
            {"skill_name": "ansible", "weight": 0.75},
            {"skill_name": "chef", "weight": 0.6},
            {"skill_name": "puppet", "weight": 0.6},
        ],
    },
    {
        "name": "Monitoring & Observability",
        "description": "Monitoring, logging, and observability platforms",
        "skills": [
            {"skill_name": "datadog", "weight": 1.0},
            {"skill_name": "prometheus", "weight": 0.95},
            {"skill_name": "grafana", "weight": 0.85},
            {"skill_name": "new relic", "weight": 0.9},
            {"skill_name": "splunk", "weight": 0.8},
            {"skill_name": "elastic stack", "weight": 0.8},
        ],
    },
    {
        "name": "Message Queues & Streaming",
        "description": "Messaging and event streaming platforms",
        "skills": [
            {"skill_name": "kafka", "weight": 1.0},
            {"skill_name": "rabbitmq", "weight": 0.85},
            {"skill_name": "aws sqs", "weight": 0.75},
            {"skill_name": "redis streams", "weight": 0.7},
            {"skill_name": "pulsar", "weight": 0.7},
            {"skill_name": "nats", "weight": 0.65},
        ],
    },
    {
        "name": "Data Engineering",
        "description": "Data pipeline and processing frameworks",
        "skills": [
            {"skill_name": "apache spark", "weight": 1.0},
            {"skill_name": "apache flink", "weight": 0.9},
            {"skill_name": "apache airflow", "weight": 0.85},
            {"skill_name": "dbt", "weight": 0.8},
            {"skill_name": "luigi", "weight": 0.6},
            {"skill_name": "prefect", "weight": 0.7},
            {"skill_name": "dagster", "weight": 0.7},
        ],
    },
    {
        "name": "Data Warehouses",
        "description": "Cloud data warehouse platforms",
        "skills": [
            {"skill_name": "snowflake", "weight": 1.0},
            {"skill_name": "bigquery", "weight": 0.95},
            {"skill_name": "redshift", "weight": 0.9},
            {"skill_name": "databricks", "weight": 0.85},
            {"skill_name": "synapse", "weight": 0.75},
        ],
    },
    {
        "name": "Search Engines",
        "description": "Full-text search and analytics engines",
        "skills": [
            {"skill_name": "elasticsearch", "weight": 1.0},
            {"skill_name": "opensearch", "weight": 0.95},
            {"skill_name": "solr", "weight": 0.8},
            {"skill_name": "meilisearch", "weight": 0.65},
            {"skill_name": "typesense", "weight": 0.6},
        ],
    },
    {
        "name": "Version Control",
        "description": "Source code version control systems",
        "skills": [
            {"skill_name": "git", "weight": 1.0},
            {"skill_name": "github", "weight": 0.95},
            {"skill_name": "gitlab", "weight": 0.9},
            {"skill_name": "bitbucket", "weight": 0.85},
            {"skill_name": "svn", "weight": 0.5},
        ],
    },
    {
        "name": "API Styles",
        "description": "API design and communication patterns",
        "skills": [
            {"skill_name": "rest", "weight": 1.0},
            {"skill_name": "graphql", "weight": 0.85},
            {"skill_name": "grpc", "weight": 0.8},
            {"skill_name": "websockets", "weight": 0.6},
        ],
    },
    {
        "name": "Testing Frameworks",
        "description": "Software testing tools and frameworks",
        "skills": [
            {"skill_name": "pytest", "weight": 1.0},
            {"skill_name": "jest", "weight": 0.95},
            {"skill_name": "junit", "weight": 0.9},
            {"skill_name": "cypress", "weight": 0.8},
            {"skill_name": "selenium", "weight": 0.75},
            {"skill_name": "playwright", "weight": 0.8},
        ],
    },
    {
        "name": "CSS Frameworks",
        "description": "CSS and UI component frameworks",
        "skills": [
            {"skill_name": "tailwind css", "weight": 1.0},
            {"skill_name": "bootstrap", "weight": 0.85},
            {"skill_name": "material ui", "weight": 0.8},
            {"skill_name": "styled-components", "weight": 0.7},
            {"skill_name": "sass", "weight": 0.65},
        ],
    },
    {
        "name": "Identity & Auth",
        "description": "Authentication and identity management",
        "skills": [
            {"skill_name": "oauth2", "weight": 1.0},
            {"skill_name": "openid connect", "weight": 0.95},
            {"skill_name": "saml", "weight": 0.8},
            {"skill_name": "auth0", "weight": 0.75},
            {"skill_name": "okta", "weight": 0.75},
            {"skill_name": "keycloak", "weight": 0.7},
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

def record_cooccurrences(skill_names: list[str]) -> None:
    """Record pairwise skill co-occurrences from a single resume."""
    if len(skill_names) < 2:
        return
    names = sorted(set(s.lower().strip() for s in skill_names if s))
    if len(names) < 2:
        return
    conn = get_db()
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            conn.execute(
                """INSERT INTO skill_cooccurrences (skill_a, skill_b, count)
                   VALUES (?, ?, 1)
                   ON CONFLICT(skill_a, skill_b) DO UPDATE SET count = count + 1""",
                (names[i], names[j]),
            )
    conn.commit()
    conn.close()


def suggest_equivalency_groups(min_cooccurrences: int = 5, min_skills: int = 3) -> list[dict]:
    """Suggest potential equivalency groups based on skill co-occurrence patterns.

    Returns groups of skills that frequently appear together on resumes
    but aren't already in an equivalency group.
    """
    conn = get_db()

    # Get existing equivalency skill names
    existing = set()
    rows = conn.execute("SELECT LOWER(skill_name) as sn FROM skill_equivalencies").fetchall()
    for r in rows:
        existing.add(r["sn"])

    # Get frequent co-occurrences not already in groups
    pairs = conn.execute(
        "SELECT skill_a, skill_b, count FROM skill_cooccurrences WHERE count >= ? ORDER BY count DESC",
        (min_cooccurrences,),
    ).fetchall()
    conn.close()

    # Build clusters from co-occurring pairs
    # Simple approach: group skills that share frequent co-occurrences
    from collections import defaultdict
    adjacency = defaultdict(set)
    pair_counts = {}
    for p in pairs:
        a, b = p["skill_a"], p["skill_b"]
        # Skip if both already in equivalency groups
        if a in existing and b in existing:
            continue
        adjacency[a].add(b)
        adjacency[b].add(a)
        pair_counts[(a, b)] = p["count"]

    # Find connected components (simple BFS)
    visited = set()
    suggestions = []
    for skill in adjacency:
        if skill in visited:
            continue
        cluster = set()
        queue = [skill]
        while queue:
            s = queue.pop(0)
            if s in visited:
                continue
            visited.add(s)
            cluster.add(s)
            for neighbor in adjacency[s]:
                if neighbor not in visited:
                    queue.append(neighbor)
        if len(cluster) >= min_skills:
            # Calculate average co-occurrence for the cluster
            total_cooc = sum(
                pair_counts.get(tuple(sorted([a, b])), 0)
                for a in cluster for b in cluster if a < b
            )
            num_pairs = len(cluster) * (len(cluster) - 1) / 2
            avg_cooc = total_cooc / num_pairs if num_pairs > 0 else 0
            suggestions.append({
                "skills": sorted(cluster),
                "avg_cooccurrences": round(avg_cooc, 1),
                "size": len(cluster),
            })

    suggestions.sort(key=lambda x: x["avg_cooccurrences"], reverse=True)
    return suggestions


def record_equivalency_feedback(
    required_skill: str,
    candidate_skill: str,
    original_weight: float,
    screener_action: str,
    group_id: int = None,
    adjusted_score: float = None,
    context: dict = None,
) -> None:
    """Record screener feedback on an equivalency match."""
    conn = get_db()
    conn.execute(
        """INSERT INTO equivalency_feedback
           (group_id, required_skill, candidate_skill, original_weight, adjusted_score, screener_action, context)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (group_id, required_skill.lower().strip(), candidate_skill.lower().strip(),
         original_weight, adjusted_score, screener_action, json.dumps(context or {})),
    )
    conn.commit()
    conn.close()


def get_weight_suggestions(min_feedback: int = 3) -> list[dict]:
    """Analyze equivalency feedback to suggest weight adjustments.

    Returns suggestions where screeners consistently override equivalency scores.
    """
    conn = get_db()
    rows = conn.execute(
        """SELECT required_skill, candidate_skill, original_weight,
                  AVG(adjusted_score) as avg_adjusted, COUNT(*) as feedback_count,
                  group_id
           FROM equivalency_feedback
           WHERE adjusted_score IS NOT NULL
           GROUP BY required_skill, candidate_skill
           HAVING COUNT(*) >= ?
           ORDER BY feedback_count DESC""",
        (min_feedback,),
    ).fetchall()
    conn.close()

    suggestions = []
    for r in rows:
        suggested_weight = round(r["avg_adjusted"] / r["original_weight"], 3) if r["original_weight"] > 0 else None
        if suggested_weight and abs(suggested_weight - 1.0) > 0.05:  # Only suggest if meaningful change
            suggestions.append({
                "required_skill": r["required_skill"],
                "candidate_skill": r["candidate_skill"],
                "current_weight": r["original_weight"],
                "suggested_weight": min(suggested_weight, 1.0),
                "feedback_count": r["feedback_count"],
                "group_id": r["group_id"],
            })
    return suggestions


def find_equivalents(skill_name: str, position_id: int = None, employer_prefs: dict = None) -> list[dict]:
    """Find equivalent skills + weights for a given skill.

    Returns list of {"skill_name": str, "weight": float} for all skills
    in the same equivalency group(s), excluding the input skill itself.

    Precedence: position-level overrides > employer prefs > global groups.
    """
    skill_lower = skill_name.lower().strip()

    # Check position-level overrides first (highest precedence)
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

    # Check employer-level prefs (middle precedence)
    if employer_prefs:
        groups = employer_prefs if isinstance(employer_prefs, list) else employer_prefs.get("groups", [])
        for group in groups:
            group_skills = {s["skill_name"].lower().strip(): s["weight"] for s in group.get("skills", [])}
            if skill_lower in group_skills:
                return [
                    {"skill_name": s_name, "weight": s_weight}
                    for s_name, s_weight in group_skills.items()
                    if s_name != skill_lower
                ]

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
        # Get the required skill's own weight in this group
        required_row = conn.execute(
            "SELECT weight FROM skill_equivalencies WHERE group_id=? AND LOWER(skill_name) = ?",
            (gid, skill_lower),
        ).fetchone()
        required_weight = required_row["weight"] if required_row else 1.0

        skills = conn.execute(
            "SELECT skill_name, weight FROM skill_equivalencies WHERE group_id=? AND LOWER(skill_name) != ?",
            (gid, skill_lower),
        ).fetchall()
        for s in skills:
            # Relative weight: how well does this skill substitute for the required one
            # If required=0.9 and candidate=1.0, relative = min(1.0/0.9, 1.0) = 1.0 (capped)
            # If required=1.0 and candidate=0.8, relative = 0.8/1.0 = 0.8
            relative = min(s["weight"] / required_weight, 1.0) if required_weight > 0 else s["weight"]
            equivalents.append({"skill_name": s["skill_name"], "weight": round(relative, 3)})

    conn.close()
    return equivalents


def adjusted_skill_score(
    candidate_skill: str,
    required_skill: str,
    base_score: float = 1.0,
    position_id: int = None,
    employer_prefs: dict = None,
) -> tuple[float, str]:
    """Return (adjusted_score, explanation) factoring in equivalency weight.

    If candidate_skill == required_skill, returns (base_score, "exact match").
    Otherwise checks equivalency groups for the required_skill.
    """
    if candidate_skill.lower().strip() == required_skill.lower().strip():
        return base_score, "exact match"

    equivalents = find_equivalents(required_skill, position_id=position_id, employer_prefs=employer_prefs)
    candidate_lower = candidate_skill.lower().strip()

    for eq in equivalents:
        if eq["skill_name"] == candidate_lower:
            weight = eq["weight"]
            adjusted = round(base_score * weight, 3)
            pct = int(weight * 100)
            explanation = f"{required_skill} required → has {candidate_skill} ({pct}% equivalent) → adjusted score: {adjusted}"
            return adjusted, explanation

    return 0.0, f"no equivalency found between {candidate_skill} and {required_skill}"
