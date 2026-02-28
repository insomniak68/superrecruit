#!/usr/bin/env python3
"""Seed the knowledge base with common skills and role archetypes. Idempotent."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.database import init_db
from src.knowledge_base import (
    SkillConcept, SkillRelation, RoleArchetype, RoleArchetypeSkill,
    create_skill_concept, get_skill_by_canonical, create_skill_relation,
    create_role_archetype, list_role_archetypes,
)

SKILLS = [
    {"name": "Python", "category": "programming", "description": "General-purpose programming language",
     "subconcepts": ["data science Python", "web Python", "scripting Python", "ML Python"],
     "competency_signals": {"strong": ["multiple Python projects", "library authorship"], "moderate": ["used in work"], "weak": ["listed in skills section"]}},
    {"name": "JavaScript", "category": "programming", "description": "Web programming language",
     "subconcepts": ["frontend JS", "Node.js", "TypeScript"],
     "competency_signals": {"strong": ["SPA development", "npm packages"], "moderate": ["used at work"], "weak": ["skills list only"]}},
    {"name": "TypeScript", "category": "programming", "description": "Typed superset of JavaScript",
     "subconcepts": ["React TypeScript", "Node TypeScript"]},
    {"name": "Java", "category": "programming", "description": "Enterprise programming language",
     "subconcepts": ["Spring Java", "Android Java"]},
    {"name": "Go", "category": "programming", "description": "Systems programming language by Google"},
    {"name": "Rust", "category": "programming", "description": "Memory-safe systems language"},
    {"name": "SQL", "category": "database", "description": "Structured Query Language for databases",
     "subconcepts": ["PostgreSQL", "MySQL", "SQLite", "query optimization"]},
    {"name": "PostgreSQL", "category": "database", "description": "Advanced open-source relational database"},
    {"name": "MongoDB", "category": "database", "description": "Document-oriented NoSQL database"},
    {"name": "React", "category": "framework", "description": "JavaScript UI library by Meta",
     "subconcepts": ["React hooks", "React Native", "Next.js"]},
    {"name": "Django", "category": "framework", "description": "Python web framework"},
    {"name": "FastAPI", "category": "framework", "description": "Modern Python async web framework"},
    {"name": "AWS", "category": "cloud", "description": "Amazon Web Services cloud platform",
     "subconcepts": ["EC2", "S3", "Lambda", "RDS", "ECS", "CloudFormation"],
     "competency_signals": {"strong": ["AWS certifications", "architecture decisions"], "moderate": ["deployed to AWS"], "weak": ["mentioned"]}},
    {"name": "Docker", "category": "devops", "description": "Container platform",
     "subconcepts": ["Dockerfile authoring", "Docker Compose", "multi-stage builds"]},
    {"name": "Kubernetes", "category": "devops", "description": "Container orchestration platform",
     "subconcepts": ["Helm", "kubectl", "cluster administration"]},
    {"name": "Git", "category": "devops", "description": "Version control system"},
    {"name": "CI/CD", "category": "devops", "description": "Continuous Integration and Deployment",
     "subconcepts": ["GitHub Actions", "Jenkins", "GitLab CI"]},
    {"name": "Machine Learning", "category": "data", "description": "Building predictive models",
     "subconcepts": ["supervised learning", "deep learning", "NLP", "computer vision"]},
    {"name": "Data Engineering", "category": "data", "description": "Building data pipelines and infrastructure",
     "subconcepts": ["ETL", "Spark", "Airflow", "data warehousing"]},
    {"name": "Terraform", "category": "devops", "description": "Infrastructure as Code tool"},
]

RELATIONS = [
    ("typescript", "javascript", "subset", 0.9),
    ("react", "javascript", "prerequisite", 0.8),
    ("django", "python", "prerequisite", 0.9),
    ("fastapi", "python", "prerequisite", 0.9),
    ("django", "fastapi", "adjacent", 0.7),
    ("postgresql", "sql", "subset", 0.8),
    ("kubernetes", "docker", "prerequisite", 0.7),
    ("terraform", "aws", "adjacent", 0.6),
    ("machine learning", "python", "prerequisite", 0.7),
    ("data engineering", "sql", "prerequisite", 0.8),
    ("ci/cd", "git", "prerequisite", 0.6),
]

ROLES = [
    {"name": "Python Developer", "description": "Backend developer specializing in Python web services and APIs",
     "core": [("python", 0.7), ("sql", 0.5), ("git", 0.4)],
     "adjacent": [("django", 0.5), ("fastapi", 0.5), ("docker", 0.4), ("aws", 0.3), ("postgresql", 0.4)],
     "career_paths": ["CS degree", "bootcamp graduate", "self-taught with portfolio", "data science transition"],
     "green_flags": ["open source contributions", "API design experience", "testing culture"],
     "red_flags": ["no version control experience", "only tutorial projects"]},
    {"name": "Full Stack Engineer", "description": "Developer comfortable across frontend and backend",
     "core": [("javascript", 0.6), ("python", 0.5), ("sql", 0.5), ("react", 0.5), ("git", 0.4)],
     "adjacent": [("typescript", 0.4), ("docker", 0.3), ("aws", 0.3), ("ci/cd", 0.3)],
     "career_paths": ["CS degree", "bootcamp", "frontend-to-fullstack", "backend-to-fullstack"],
     "green_flags": ["shipped production apps end-to-end", "responsive design", "API + UI"],
     "red_flags": ["only backend or only frontend", "no deployment experience"]},
    {"name": "DevOps Engineer", "description": "Infrastructure, CI/CD, and platform engineering",
     "core": [("docker", 0.7), ("kubernetes", 0.6), ("aws", 0.6), ("ci/cd", 0.6), ("terraform", 0.5), ("git", 0.5)],
     "adjacent": [("python", 0.4), ("go", 0.3)],
     "career_paths": ["sysadmin transition", "developer transition", "CS degree + ops interest"],
     "green_flags": ["infrastructure as code", "monitoring setup", "incident response"],
     "red_flags": ["no scripting ability", "manual deployment only"]},
    {"name": "Data Scientist", "description": "Statistical analysis, ML models, and data-driven insights",
     "core": [("python", 0.7), ("machine learning", 0.7), ("sql", 0.6)],
     "adjacent": [("data engineering", 0.4), ("aws", 0.3), ("docker", 0.3)],
     "career_paths": ["statistics/math degree", "physics PhD", "analytics transition", "CS + ML specialization"],
     "green_flags": ["published research", "production ML models", "A/B testing experience"],
     "red_flags": ["no statistical foundation", "only Kaggle competitions"]},
]


def seed():
    init_db()
    skill_map = {}  # canonical -> id

    print("Seeding skills...")
    for s in SKILLS:
        canonical = s["name"].lower().strip()
        existing = get_skill_by_canonical(canonical)
        if existing:
            print(f"  ✓ {s['name']} (exists)")
            skill_map[canonical] = existing.id
            continue
        sc = SkillConcept(**s)
        created = create_skill_concept(sc)
        skill_map[canonical] = created.id
        print(f"  + {s['name']}")

    print("\nSeeding relations...")
    from src.database import get_db
    conn = get_db()
    existing_rels = conn.execute("SELECT source_skill_id, target_skill_id FROM skill_relations").fetchall()
    existing_set = {(r["source_skill_id"], r["target_skill_id"]) for r in existing_rels}
    conn.close()
    for src, tgt, rtype, strength in RELATIONS:
        src_id = skill_map.get(src)
        tgt_id = skill_map.get(tgt)
        if not src_id or not tgt_id:
            print(f"  ⚠ Skipping {src} -> {tgt} (missing)")
            continue
        if (src_id, tgt_id) in existing_set:
            print(f"  ✓ {src} -> {tgt} (exists)")
            continue
        create_skill_relation(SkillRelation(source_skill_id=src_id, target_skill_id=tgt_id, relation_type=rtype, strength=strength))
        print(f"  + {src} -[{rtype}]-> {tgt}")

    print("\nSeeding roles...")
    existing_roles = {r.canonical_name for r in list_role_archetypes()}
    for r in ROLES:
        canonical = r["name"].lower().strip()
        if canonical in existing_roles:
            print(f"  ✓ {r['name']} (exists)")
            continue
        core = [RoleArchetypeSkill(skill_concept_id=skill_map[s], min_confidence=c, weight=1.0, is_core=True)
                for s, c in r["core"] if s in skill_map]
        adjacent = [RoleArchetypeSkill(skill_concept_id=skill_map[s], min_confidence=0, weight=w, is_core=False)
                    for s, w in r["adjacent"] if s in skill_map]
        ra = RoleArchetype(name=r["name"], description=r["description"],
                           core_skills=core, adjacent_skills=adjacent,
                           career_paths=r["career_paths"], green_flags=r["green_flags"], red_flags=r["red_flags"])
        create_role_archetype(ra)
        print(f"  + {r['name']}")

    print("\nDone!")


if __name__ == "__main__":
    seed()
