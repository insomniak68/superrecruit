# API Reference

Base URL: `http://localhost:8000`

## Health

### `GET /health`

```json
{"status": "ok"}
```

## Candidates

### `POST /api/candidates/upload`

Upload a resume and create a candidate. Triggers skill extraction and confidence scoring.

**Content-Type:** `multipart/form-data`

| Field | Type | Required |
|---|---|---|
| `file` | File (PDF) | Yes |
| `name` | string | Yes |
| `email` | string | Yes |
| `phone` | string | No |

**Response:** 303 redirect to `/candidates/{id}`

### `GET /api/candidates`

```json
[
  {"id": 1, "name": "Jane Doe", "email": "jane@example.com", "created_at": "2026-02-28T12:00:00"}
]
```

### `GET /api/candidates/{id}`

```json
{
  "candidate": {"id": 1, "name": "Jane Doe", "email": "jane@example.com", "resume_text": "...", "...": "..."},
  "skills": [
    {"id": 1, "skill_name": "Python", "category": "language", "llm_confidence": "0.9", "final_confidence": "0.85", "evidence": "5 years listed", "reasoning": "..."}
  ]
}
```

## Assessments

### `POST /api/candidates/{id}/send-assessment`

```json
// Request
{"test_ids": ["python-fundamentals", "sql-basics"], "base_url": "https://recruit.example.com"}

// Response
{"token": "abc123", "link": "https://recruit.example.com/assess/abc123"}
```

### `POST /assess/{token}/submit`

```json
// Request
{"answers": {"python-fundamentals": {"q1": "B", "q2": "A"}}}

// Response
{"status": "completed"}
```

### `GET /api/test-bank`

```json
[
  {"id": "python-fundamentals", "name": "Python Fundamentals", "category": "language", "skill_tags": ["python"], "time_limit_minutes": 30, "question_count": 10}
]
```

## Bulk Processing

### `POST /api/bulk`

**Content-Type:** `multipart/form-data` — field `file` (ZIP archive of PDFs)

```json
{"job_id": "uuid-here", "status": "processing"}
```

### `GET /api/bulk/{job_id}`

```json
{"total": 10, "processed": 7, "failed": 0, "status": "processing", "results": [...]}
```

## Workspace

### `POST /api/workspace/{cid}/chat`

```json
// Request
{"message": "I think this candidate's Python skills are stronger than shown"}

// Response
{
  "message": "I've adjusted Python confidence from 0.7 to 0.85 based on your input.",
  "actions": [{"action": "adjust_confidence", "skill_name": "Python", "confidence": 0.85}],
  "skills": [...]
}
```

### `PATCH /api/workspace/{cid}/skills/{skill_id}`

```json
// Request (any combination)
{"confidence": 0.9, "irrelevant": false, "note": "Confirmed in interview"}

// Response: updated skill object
```

### `POST /api/workspace/{cid}/skills`

```json
// Request
{"skill_name": "Kubernetes", "category": "devops", "confidence": 0.6, "evidence": "Mentioned in interview"}

// Response: created skill object
```

## Knowledge Base

### Skills CRUD

- `GET /api/kb/skills` → list of skill concepts
- `POST /api/kb/skills` → create (`{name, category, description, subconcepts, competency_signals}`)
- `GET /api/kb/skills/{id}` → skill with relations
- `PATCH /api/kb/skills/{id}` → partial update
- `DELETE /api/kb/skills/{id}` → cascading delete

### Skill Relations

- `POST /api/kb/skills/{id}/relations` → `{target_skill_id, relation_type, strength, source}`
- `DELETE /api/kb/relations/{id}`

Relation types: `equivalent`, `adjacent`, `prerequisite`, `superset`, `subset`

### Roles CRUD

- `GET /api/kb/roles` → list with core/adjacent skills
- `POST /api/kb/roles` → `{name, description, core_skills, adjacent_skills, career_paths, green_flags, red_flags}`
- `GET /api/kb/roles/{id}`
- `PATCH /api/kb/roles/{id}`
- `DELETE /api/kb/roles/{id}` → cascading delete

### Employer Interpretations

- `GET /api/kb/roles/{rid}/employers`
- `POST /api/kb/roles/{rid}/employers` → `{employer_name, overrides, equivalency_prefs, notes}`
- `GET /api/kb/roles/{rid}/employers/{eid}`
- `PATCH /api/kb/roles/{rid}/employers/{eid}`
- `DELETE /api/kb/roles/{rid}/employers/{eid}`

### Search & Export

- `GET /api/kb/search?q=python` → `{skills: [...], roles: [...]}`
- `GET /api/kb/export` → full KB JSON (PII-free)
- `POST /api/kb/import` → merge KB from JSON body → `{skills_created, skills_skipped, ...}`
