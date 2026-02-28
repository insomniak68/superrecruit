"""Shareable skill & role knowledge base with dual-perspective ontology.

No candidate PII — this module is safely exportable/importable between instances.
"""

import json
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from .database import get_db


# ── Pydantic Models ──

class SkillConcept(BaseModel):
    id: Optional[int] = None
    name: str
    canonical_name: str = ""
    description: str = ""
    category: str = "other"
    subconcepts: list[str] = []
    competency_signals: dict = {}
    version: int = 1
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def model_post_init(self, __context):
        if not self.canonical_name:
            self.canonical_name = self.name.lower().strip()


class SkillRelation(BaseModel):
    id: Optional[int] = None
    source_skill_id: int
    target_skill_id: int
    relation_type: str  # equivalent, adjacent, prerequisite, superset, subset
    strength: float = 1.0
    source: str = "system"  # system, human, ai


class RoleArchetypeSkill(BaseModel):
    skill_concept_id: int
    skill_name: str = ""
    min_confidence: float = 0.0
    weight: float = 1.0
    is_core: bool = True


class RoleArchetype(BaseModel):
    id: Optional[int] = None
    name: str
    canonical_name: str = ""
    description: str = ""
    core_skills: list[RoleArchetypeSkill] = []
    adjacent_skills: list[RoleArchetypeSkill] = []
    career_paths: list[str] = []
    green_flags: list[str] = []
    red_flags: list[str] = []
    version: int = 1
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def model_post_init(self, __context):
        if not self.canonical_name:
            self.canonical_name = self.name.lower().strip()


class EmployerSkillOverride(BaseModel):
    skill_concept_id: int
    skill_name: str = ""
    priority: str = "normal"  # prioritize, deprioritize, ignore
    weight_override: Optional[float] = None


class EmployerInterpretation(BaseModel):
    id: Optional[int] = None
    role_archetype_id: int
    employer_name: str = "anonymous"
    overrides: list[EmployerSkillOverride] = []
    equivalency_prefs: dict = {}
    notes: str = ""
    learned_from: list[str] = []  # session IDs, not candidate PII
    version: int = 1
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ── DB Operations: Skills ──

def create_skill_concept(skill: SkillConcept) -> SkillConcept:
    conn = get_db()
    now = datetime.utcnow().isoformat()
    cur = conn.execute(
        """INSERT INTO skill_concepts (name, canonical_name, description, category, subconcepts, competency_signals, version, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (skill.name, skill.canonical_name, skill.description, skill.category,
         json.dumps(skill.subconcepts), json.dumps(skill.competency_signals),
         1, now, now)
    )
    conn.commit()
    skill.id = cur.lastrowid
    skill.created_at = now
    skill.updated_at = now
    skill.version = 1
    conn.close()
    return skill


def get_skill_concept(skill_id: int) -> Optional[SkillConcept]:
    conn = get_db()
    row = conn.execute("SELECT * FROM skill_concepts WHERE id=?", (skill_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_skill(row)


def get_skill_by_canonical(canonical_name: str) -> Optional[SkillConcept]:
    conn = get_db()
    row = conn.execute("SELECT * FROM skill_concepts WHERE canonical_name=?", (canonical_name.lower().strip(),)).fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_skill(row)


def list_skill_concepts() -> list[SkillConcept]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM skill_concepts ORDER BY name").fetchall()
    conn.close()
    return [_row_to_skill(r) for r in rows]


def update_skill_concept(skill_id: int, updates: dict) -> Optional[SkillConcept]:
    conn = get_db()
    existing = conn.execute("SELECT * FROM skill_concepts WHERE id=?", (skill_id,)).fetchone()
    if not existing:
        conn.close()
        return None
    now = datetime.utcnow().isoformat()
    new_version = existing["version"] + 1
    name = updates.get("name", existing["name"])
    canonical = updates.get("canonical_name", name.lower().strip())
    conn.execute(
        """UPDATE skill_concepts SET name=?, canonical_name=?, description=?, category=?,
           subconcepts=?, competency_signals=?, version=?, updated_at=? WHERE id=?""",
        (name, canonical,
         updates.get("description", existing["description"]),
         updates.get("category", existing["category"]),
         json.dumps(updates.get("subconcepts", json.loads(existing["subconcepts"]))),
         json.dumps(updates.get("competency_signals", json.loads(existing["competency_signals"]))),
         new_version, now, skill_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM skill_concepts WHERE id=?", (skill_id,)).fetchone()
    conn.close()
    return _row_to_skill(row)


def delete_skill_concept(skill_id: int) -> bool:
    conn = get_db()
    conn.execute("DELETE FROM skill_relations WHERE source_skill_id=? OR target_skill_id=?", (skill_id, skill_id))
    conn.execute("DELETE FROM role_archetype_skills WHERE skill_concept_id=?", (skill_id,))
    conn.execute("DELETE FROM employer_skill_overrides WHERE skill_concept_id=?", (skill_id,))
    cur = conn.execute("DELETE FROM skill_concepts WHERE id=?", (skill_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def _row_to_skill(row) -> SkillConcept:
    return SkillConcept(
        id=row["id"], name=row["name"], canonical_name=row["canonical_name"],
        description=row["description"], category=row["category"],
        subconcepts=json.loads(row["subconcepts"]),
        competency_signals=json.loads(row["competency_signals"]),
        version=row["version"], created_at=row["created_at"], updated_at=row["updated_at"]
    )


# ── DB Operations: Relations ──

def create_skill_relation(rel: SkillRelation) -> SkillRelation:
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO skill_relations (source_skill_id, target_skill_id, relation_type, strength, source) VALUES (?,?,?,?,?)",
        (rel.source_skill_id, rel.target_skill_id, rel.relation_type, rel.strength, rel.source)
    )
    conn.commit()
    rel.id = cur.lastrowid
    conn.close()
    return rel


def get_skill_relations(skill_id: int) -> list[SkillRelation]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM skill_relations WHERE source_skill_id=? OR target_skill_id=?",
        (skill_id, skill_id)
    ).fetchall()
    conn.close()
    return [SkillRelation(**dict(r)) for r in rows]


def delete_skill_relation(relation_id: int) -> bool:
    conn = get_db()
    cur = conn.execute("DELETE FROM skill_relations WHERE id=?", (relation_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# ── DB Operations: Roles ──

def create_role_archetype(role: RoleArchetype) -> RoleArchetype:
    conn = get_db()
    now = datetime.utcnow().isoformat()
    cur = conn.execute(
        """INSERT INTO role_archetypes (name, canonical_name, description, career_paths, green_flags, red_flags, version, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (role.name, role.canonical_name, role.description,
         json.dumps(role.career_paths), json.dumps(role.green_flags), json.dumps(role.red_flags),
         1, now, now)
    )
    role_id = cur.lastrowid
    for s in role.core_skills:
        conn.execute(
            "INSERT INTO role_archetype_skills (role_archetype_id, skill_concept_id, min_confidence, weight, is_core) VALUES (?,?,?,?,?)",
            (role_id, s.skill_concept_id, s.min_confidence, s.weight, 1)
        )
    for s in role.adjacent_skills:
        conn.execute(
            "INSERT INTO role_archetype_skills (role_archetype_id, skill_concept_id, min_confidence, weight, is_core) VALUES (?,?,?,?,?)",
            (role_id, s.skill_concept_id, s.min_confidence, s.weight, 0)
        )
    conn.commit()
    role.id = role_id
    role.created_at = now
    role.updated_at = now
    conn.close()
    return role


def get_role_archetype(role_id: int) -> Optional[RoleArchetype]:
    conn = get_db()
    row = conn.execute("SELECT * FROM role_archetypes WHERE id=?", (role_id,)).fetchone()
    if not row:
        conn.close()
        return None
    role = _row_to_role(row, conn)
    conn.close()
    return role


def list_role_archetypes() -> list[RoleArchetype]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM role_archetypes ORDER BY name").fetchall()
    roles = [_row_to_role(r, conn) for r in rows]
    conn.close()
    return roles


def update_role_archetype(role_id: int, updates: dict) -> Optional[RoleArchetype]:
    conn = get_db()
    existing = conn.execute("SELECT * FROM role_archetypes WHERE id=?", (role_id,)).fetchone()
    if not existing:
        conn.close()
        return None
    now = datetime.utcnow().isoformat()
    new_version = existing["version"] + 1
    name = updates.get("name", existing["name"])
    canonical = updates.get("canonical_name", name.lower().strip())
    conn.execute(
        """UPDATE role_archetypes SET name=?, canonical_name=?, description=?, career_paths=?,
           green_flags=?, red_flags=?, version=?, updated_at=? WHERE id=?""",
        (name, canonical,
         updates.get("description", existing["description"]),
         json.dumps(updates.get("career_paths", json.loads(existing["career_paths"]))),
         json.dumps(updates.get("green_flags", json.loads(existing["green_flags"]))),
         json.dumps(updates.get("red_flags", json.loads(existing["red_flags"]))),
         new_version, now, role_id)
    )
    # Update skills if provided
    if "core_skills" in updates or "adjacent_skills" in updates:
        conn.execute("DELETE FROM role_archetype_skills WHERE role_archetype_id=?", (role_id,))
        for s in updates.get("core_skills", []):
            conn.execute(
                "INSERT INTO role_archetype_skills (role_archetype_id, skill_concept_id, min_confidence, weight, is_core) VALUES (?,?,?,?,?)",
                (role_id, s["skill_concept_id"], s.get("min_confidence", 0), s.get("weight", 1.0), 1)
            )
        for s in updates.get("adjacent_skills", []):
            conn.execute(
                "INSERT INTO role_archetype_skills (role_archetype_id, skill_concept_id, min_confidence, weight, is_core) VALUES (?,?,?,?,?)",
                (role_id, s["skill_concept_id"], s.get("min_confidence", 0), s.get("weight", 0.5), 0)
            )
    conn.commit()
    row = conn.execute("SELECT * FROM role_archetypes WHERE id=?", (role_id,)).fetchone()
    role = _row_to_role(row, conn)
    conn.close()
    return role


def delete_role_archetype(role_id: int) -> bool:
    conn = get_db()
    conn.execute("DELETE FROM role_archetype_skills WHERE role_archetype_id=?", (role_id,))
    conn.execute("DELETE FROM employer_interpretations WHERE role_archetype_id=?", (role_id,))
    conn.execute("DELETE FROM employer_skill_overrides WHERE employer_interpretation_id IN (SELECT id FROM employer_interpretations WHERE role_archetype_id=?)", (role_id,))
    cur = conn.execute("DELETE FROM role_archetypes WHERE id=?", (role_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def _row_to_role(row, conn) -> RoleArchetype:
    skill_rows = conn.execute(
        """SELECT ras.*, sc.name as skill_name FROM role_archetype_skills ras
           LEFT JOIN skill_concepts sc ON ras.skill_concept_id = sc.id
           WHERE ras.role_archetype_id=?""", (row["id"],)
    ).fetchall()
    core = [RoleArchetypeSkill(skill_concept_id=s["skill_concept_id"], skill_name=s["skill_name"] or "",
                                min_confidence=s["min_confidence"], weight=s["weight"], is_core=True)
            for s in skill_rows if s["is_core"]]
    adjacent = [RoleArchetypeSkill(skill_concept_id=s["skill_concept_id"], skill_name=s["skill_name"] or "",
                                    min_confidence=s["min_confidence"], weight=s["weight"], is_core=False)
                for s in skill_rows if not s["is_core"]]
    return RoleArchetype(
        id=row["id"], name=row["name"], canonical_name=row["canonical_name"],
        description=row["description"],
        core_skills=core, adjacent_skills=adjacent,
        career_paths=json.loads(row["career_paths"]),
        green_flags=json.loads(row["green_flags"]),
        red_flags=json.loads(row["red_flags"]),
        version=row["version"], created_at=row["created_at"], updated_at=row["updated_at"]
    )


# ── DB Operations: Employer Interpretations ──

def create_employer_interpretation(ei: EmployerInterpretation) -> EmployerInterpretation:
    conn = get_db()
    now = datetime.utcnow().isoformat()
    cur = conn.execute(
        """INSERT INTO employer_interpretations (role_archetype_id, employer_name, equivalency_prefs, notes, learned_from, version, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (ei.role_archetype_id, ei.employer_name,
         json.dumps(ei.equivalency_prefs), ei.notes, json.dumps(ei.learned_from),
         1, now, now)
    )
    ei_id = cur.lastrowid
    for ov in ei.overrides:
        conn.execute(
            "INSERT INTO employer_skill_overrides (employer_interpretation_id, skill_concept_id, priority, weight_override) VALUES (?,?,?,?)",
            (ei_id, ov.skill_concept_id, ov.priority, ov.weight_override)
        )
    conn.commit()
    ei.id = ei_id
    ei.created_at = now
    ei.updated_at = now
    conn.close()
    return ei


def get_employer_interpretation(ei_id: int) -> Optional[EmployerInterpretation]:
    conn = get_db()
    row = conn.execute("SELECT * FROM employer_interpretations WHERE id=?", (ei_id,)).fetchone()
    if not row:
        conn.close()
        return None
    ei = _row_to_ei(row, conn)
    conn.close()
    return ei


def list_employer_interpretations(role_id: int) -> list[EmployerInterpretation]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM employer_interpretations WHERE role_archetype_id=?", (role_id,)).fetchall()
    eis = [_row_to_ei(r, conn) for r in rows]
    conn.close()
    return eis


def update_employer_interpretation(ei_id: int, updates: dict) -> Optional[EmployerInterpretation]:
    conn = get_db()
    existing = conn.execute("SELECT * FROM employer_interpretations WHERE id=?", (ei_id,)).fetchone()
    if not existing:
        conn.close()
        return None
    now = datetime.utcnow().isoformat()
    new_version = existing["version"] + 1
    conn.execute(
        """UPDATE employer_interpretations SET employer_name=?, equivalency_prefs=?, notes=?,
           learned_from=?, version=?, updated_at=? WHERE id=?""",
        (updates.get("employer_name", existing["employer_name"]),
         json.dumps(updates.get("equivalency_prefs", json.loads(existing["equivalency_prefs"]))),
         updates.get("notes", existing["notes"]),
         json.dumps(updates.get("learned_from", json.loads(existing["learned_from"]))),
         new_version, now, ei_id)
    )
    if "overrides" in updates:
        conn.execute("DELETE FROM employer_skill_overrides WHERE employer_interpretation_id=?", (ei_id,))
        for ov in updates["overrides"]:
            conn.execute(
                "INSERT INTO employer_skill_overrides (employer_interpretation_id, skill_concept_id, priority, weight_override) VALUES (?,?,?,?)",
                (ei_id, ov["skill_concept_id"], ov.get("priority", "normal"), ov.get("weight_override"))
            )
    conn.commit()
    row = conn.execute("SELECT * FROM employer_interpretations WHERE id=?", (ei_id,)).fetchone()
    ei = _row_to_ei(row, conn)
    conn.close()
    return ei


def delete_employer_interpretation(ei_id: int) -> bool:
    conn = get_db()
    conn.execute("DELETE FROM employer_skill_overrides WHERE employer_interpretation_id=?", (ei_id,))
    cur = conn.execute("DELETE FROM employer_interpretations WHERE id=?", (ei_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def _row_to_ei(row, conn) -> EmployerInterpretation:
    override_rows = conn.execute(
        """SELECT eso.*, sc.name as skill_name FROM employer_skill_overrides eso
           LEFT JOIN skill_concepts sc ON eso.skill_concept_id = sc.id
           WHERE eso.employer_interpretation_id=?""", (row["id"],)
    ).fetchall()
    overrides = [EmployerSkillOverride(
        skill_concept_id=o["skill_concept_id"], skill_name=o["skill_name"] or "",
        priority=o["priority"], weight_override=o["weight_override"]
    ) for o in override_rows]
    return EmployerInterpretation(
        id=row["id"], role_archetype_id=row["role_archetype_id"],
        employer_name=row["employer_name"], overrides=overrides,
        equivalency_prefs=json.loads(row["equivalency_prefs"]),
        notes=row["notes"], learned_from=json.loads(row["learned_from"]),
        version=row["version"], created_at=row["created_at"], updated_at=row["updated_at"]
    )


# ── Search ──

def search_knowledge_base(query: str) -> dict:
    conn = get_db()
    q = f"%{query.lower()}%"
    skill_rows = conn.execute(
        "SELECT * FROM skill_concepts WHERE canonical_name LIKE ? OR description LIKE ? OR category LIKE ?",
        (q, q, q)
    ).fetchall()
    role_rows = conn.execute(
        "SELECT * FROM role_archetypes WHERE canonical_name LIKE ? OR description LIKE ?",
        (q, q)
    ).fetchall()
    skills = [_row_to_skill(r) for r in skill_rows]
    roles = [_row_to_role(r, conn) for r in role_rows]
    conn.close()
    return {"skills": skills, "roles": roles}


# ── Export/Import ──

def export_knowledge_base() -> dict:
    """Export entire KB as self-contained JSON (no PII)."""
    conn = get_db()
    skills = [_row_to_skill(r) for r in conn.execute("SELECT * FROM skill_concepts").fetchall()]
    relations = [SkillRelation(**dict(r)) for r in conn.execute("SELECT * FROM skill_relations").fetchall()]
    roles = [_row_to_role(r, conn) for r in conn.execute("SELECT * FROM role_archetypes").fetchall()]
    eis = []
    for role in roles:
        ei_rows = conn.execute("SELECT * FROM employer_interpretations WHERE role_archetype_id=?", (role.id,)).fetchall()
        eis.extend([_row_to_ei(r, conn) for r in ei_rows])
    conn.close()
    return {
        "version": "1.0",
        "exported_at": datetime.utcnow().isoformat(),
        "skill_concepts": [s.model_dump() for s in skills],
        "skill_relations": [r.model_dump() for r in relations],
        "role_archetypes": [r.model_dump() for r in roles],
        "employer_interpretations": [e.model_dump() for e in eis],
    }


def import_knowledge_base(data: dict) -> dict:
    """Import KB from exported JSON. Merges by canonical_name, skips existing."""
    stats = {"skills_created": 0, "skills_skipped": 0, "relations_created": 0,
             "roles_created": 0, "roles_skipped": 0, "employers_created": 0}
    skill_id_map = {}  # old_id -> new_id

    for s in data.get("skill_concepts", []):
        existing = get_skill_by_canonical(s.get("canonical_name", s["name"].lower()))
        if existing:
            skill_id_map[s.get("id")] = existing.id
            stats["skills_skipped"] += 1
        else:
            sc = SkillConcept(**{k: v for k, v in s.items() if k not in ("id", "created_at", "updated_at", "version")})
            created = create_skill_concept(sc)
            skill_id_map[s.get("id")] = created.id
            stats["skills_created"] += 1

    for r in data.get("skill_relations", []):
        src = skill_id_map.get(r.get("source_skill_id"))
        tgt = skill_id_map.get(r.get("target_skill_id"))
        if src and tgt:
            create_skill_relation(SkillRelation(
                source_skill_id=src, target_skill_id=tgt,
                relation_type=r["relation_type"], strength=r.get("strength", 1.0),
                source=r.get("source", "system")
            ))
            stats["relations_created"] += 1

    role_id_map = {}
    for r in data.get("role_archetypes", []):
        existing_roles = list_role_archetypes()
        canonical = r.get("canonical_name", r["name"].lower())
        existing = next((x for x in existing_roles if x.canonical_name == canonical), None)
        if existing:
            role_id_map[r.get("id")] = existing.id
            stats["roles_skipped"] += 1
        else:
            core = [RoleArchetypeSkill(
                skill_concept_id=skill_id_map.get(s["skill_concept_id"], s["skill_concept_id"]),
                min_confidence=s.get("min_confidence", 0), weight=s.get("weight", 1.0), is_core=True
            ) for s in r.get("core_skills", []) if skill_id_map.get(s.get("skill_concept_id"))]
            adjacent = [RoleArchetypeSkill(
                skill_concept_id=skill_id_map.get(s["skill_concept_id"], s["skill_concept_id"]),
                min_confidence=s.get("min_confidence", 0), weight=s.get("weight", 0.5), is_core=False
            ) for s in r.get("adjacent_skills", []) if skill_id_map.get(s.get("skill_concept_id"))]
            ra = RoleArchetype(
                name=r["name"], canonical_name=canonical, description=r.get("description", ""),
                core_skills=core, adjacent_skills=adjacent,
                career_paths=r.get("career_paths", []),
                green_flags=r.get("green_flags", []), red_flags=r.get("red_flags", [])
            )
            created = create_role_archetype(ra)
            role_id_map[r.get("id")] = created.id
            stats["roles_created"] += 1

    for e in data.get("employer_interpretations", []):
        role_new_id = role_id_map.get(e.get("role_archetype_id"))
        if role_new_id:
            overrides = [EmployerSkillOverride(
                skill_concept_id=skill_id_map.get(o["skill_concept_id"], o["skill_concept_id"]),
                priority=o.get("priority", "normal"), weight_override=o.get("weight_override")
            ) for o in e.get("overrides", []) if skill_id_map.get(o.get("skill_concept_id"))]
            ei = EmployerInterpretation(
                role_archetype_id=role_new_id, employer_name=e.get("employer_name", "anonymous"),
                overrides=overrides, equivalency_prefs=e.get("equivalency_prefs", {}),
                notes=e.get("notes", ""), learned_from=e.get("learned_from", [])
            )
            create_employer_interpretation(ei)
            stats["employers_created"] += 1

    return stats


# ── Enrichment (for skill_extractor integration) ──

def enrich_with_knowledge_base(skills: list) -> list:
    """Post-process extracted skills: add canonical names, related skills, competency signals."""
    conn = get_db()
    all_concepts = conn.execute("SELECT * FROM skill_concepts").fetchall()
    concept_map = {r["canonical_name"]: _row_to_skill(r) for r in all_concepts}
    conn.close()

    for skill in skills:
        skill_name = skill.skill_name if hasattr(skill, 'skill_name') else skill.get("skill_name", "")
        canonical = skill_name.lower().strip()
        concept = concept_map.get(canonical)
        if concept:
            kb_data = {
                "kb_concept_id": concept.id,
                "kb_canonical_name": concept.canonical_name,
                "kb_category": concept.category,
                "kb_competency_signals": concept.competency_signals,
                "kb_subconcepts": concept.subconcepts,
            }
            relations = get_skill_relations(concept.id)
            kb_data["kb_related"] = [{"id": r.target_skill_id if r.source_skill_id == concept.id else r.source_skill_id,
                                       "type": r.relation_type, "strength": r.strength} for r in relations]
            if hasattr(skill, '__dict__'):
                skill.__dict__.update(kb_data)
            else:
                skill.update(kb_data)
    return skills


def get_kb_context_for_role(role_name: str) -> str:
    """Get KB context string for workspace agent system prompt."""
    conn = get_db()
    q = f"%{role_name.lower()}%"
    rows = conn.execute("SELECT * FROM role_archetypes WHERE canonical_name LIKE ?", (q,)).fetchall()
    if not rows:
        conn.close()
        return ""
    role = _row_to_role(rows[0], conn)
    conn.close()
    lines = [f"\n## Role Archetype: {role.name}", role.description]
    if role.core_skills:
        lines.append("**Core skills:** " + ", ".join(f"{s.skill_name} (≥{s.min_confidence:.0%})" for s in role.core_skills))
    if role.adjacent_skills:
        lines.append("**Nice-to-have:** " + ", ".join(s.skill_name for s in role.adjacent_skills))
    if role.green_flags:
        lines.append("**Green flags:** " + ", ".join(role.green_flags))
    if role.red_flags:
        lines.append("**Red flags:** " + ", ".join(role.red_flags))
    return "\n".join(lines)


def get_skills_context() -> str:
    """Get summary of all skill concepts for workspace agent."""
    skills = list_skill_concepts()
    if not skills:
        return ""
    lines = ["\n## Knowledge Base Skills"]
    for s in skills[:30]:  # cap to avoid token bloat
        lines.append(f"- **{s.name}** ({s.category}): {s.description[:100]}")
    return "\n".join(lines)
