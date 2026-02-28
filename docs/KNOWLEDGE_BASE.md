# Knowledge Base

The Knowledge Base (KB) is SuperRecruit's shared ontology of skills, role archetypes, and employer-specific interpretations. It contains **no candidate PII** and is safely exportable between instances.

## Concepts

### Skill Concepts

A canonical definition of a skill (e.g., "Python", "Kubernetes", "Project Management").

Fields:
- **name** / **canonical_name** — display name and lowercase key
- **category** — language, framework, devops, soft_skill, etc.
- **description** — what this skill entails
- **subconcepts** — e.g., Python → [asyncio, type hints, FastAPI]
- **competency_signals** — evidence patterns that indicate proficiency

### Skill Relations

Typed edges between skill concepts:
- **equivalent** — "React.js" ↔ "React" (strength 1.0)
- **adjacent** — "Python" → "FastAPI" (strength 0.7)
- **prerequisite** — "JavaScript" → "TypeScript"
- **superset/subset** — "Machine Learning" ⊃ "Deep Learning"

### Role Archetypes

Template definitions for job roles with:
- **Core skills** — required, with minimum confidence thresholds and weights
- **Adjacent skills** — nice-to-have
- **Career paths** — typical progression
- **Green/red flags** — signals in resumes

### Employer Interpretations

Per-employer customization layered on role archetypes:
- Skill priority overrides (prioritize/deprioritize/ignore)
- Weight overrides
- Equivalency preferences
- Notes and learning history

## Export & Import

```bash
# Export entire KB
curl http://localhost:8000/api/kb/export > kb.json

# Import into another instance (merges by canonical_name)
curl -X POST http://localhost:8000/api/kb/import \
  -H "Content-Type: application/json" \
  -d @kb.json
```

Import behavior:
- Skills matched by `canonical_name` — existing are skipped, new are created
- Relations recreated with remapped IDs
- Roles matched by `canonical_name`
- Employer interpretations attached to remapped role IDs

## Seeding

```bash
python scripts/seed_knowledge_base.py
```

This populates the KB with common skill concepts, relations, and role archetypes.

## Integration

The KB enriches the pipeline in two ways:

1. **Skill Extractor** — `enrich_with_knowledge_base()` adds canonical names, subconcepts, and competency signals to extracted skills
2. **Workspace Agent** — `get_kb_context_for_role()` and `get_skills_context()` inject KB context into the agent's system prompt, enabling informed skill discussions

## Workspace Agent Actions

The workspace chat agent can learn from conversations:
- **learn_skill_concept** — create a new skill concept from discussion
- **learn_equivalency** — record that two skills are equivalent
