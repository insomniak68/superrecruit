# Architecture

## Module Overview

| Module | Purpose |
|---|---|
| `main.py` | FastAPI application, all route definitions, startup initialization |
| `models.py` | Pydantic data models for candidates, skills, assessments |
| `database.py` | SQLite connection management, schema initialization (WAL mode) |
| `resume_parser.py` | PDF text extraction via pdfplumber, section parsing |
| `skill_extractor.py` | Sends resume text to Claude for structured skill extraction |
| `confidence_scorer.py` | Hybrid scoring: LLM confidence + heuristic evidence signals |
| `test_selector.py` | Matches candidate skills to YAML test bank entries |
| `assessment.py` | Assessment session lifecycle (create → start → complete) |
| `auth.py` | Authentication utilities |
| `email_service.py` | SMTP integration for assessment invitation emails |
| `bulk_processor.py` | Processes ZIP archives of resumes in background tasks |
| `workspace_agent.py` | Claude-powered chat agent for interactive skill review |
| `fit_assessor.py` | Overall candidate-role fit scoring with LLM rationale |
| `knowledge_base.py` | Skill ontology, role archetypes, employer interpretations |

## Data Flow

```
Resume (PDF) → resume_parser → raw text + sections
                                    │
                              skill_extractor (Claude API)
                                    │
                              confidence_scorer
                                    │
                              ┌─────▼─────┐
                              │  SQLite DB │
                              └─────┬──────┘
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
              test_selector    workspace_agent   knowledge_base
                    │               │               │
              assessment       fit_assessor      ontology CRUD
                                    │
                              fit_assessments
              (email → portal → auto-grade)
```

## Database Schema

### Core Tables

- **candidates** — id, name, email, phone, resume_path, resume_text, parsed_data, created_at
- **skill_assessments** — id, candidate_id (FK), skill_name, category, evidence, llm_confidence, final_confidence, reasoning, created_at
- **assessment_sessions** — id, candidate_id (FK), token (unique), status, tests (JSON), sent_at, started_at, completed_at, expires_at
- **test_submissions** — id, session_id (FK), test_id, question_id, answer, is_correct, score, graded_by, submitted_at
- **test_bank_meta** — id, test_id (unique), name, category, skill_tags (JSON), times_administered, avg_score
- **workspace_conversations** — id, candidate_id (FK), role, content, actions_json, created_at
- **fit_assessments** — id, candidate_id (FK), role_archetype_id (FK, nullable), fit_score (REAL), fit_level (TEXT), rationale (TEXT), breakdown_json (JSON), assessed_by (system/human/ai), created_at
- **skill_overrides** — id, candidate_id (FK), skill_id (FK), field, old_value, new_value, source, created_at

### Knowledge Base Tables

- **skill_concepts** — id, name, canonical_name (unique), description, category, subconcepts (JSON), competency_signals (JSON), version, timestamps
- **skill_relations** — id, source_skill_id (FK), target_skill_id (FK), relation_type, strength, source
- **role_archetypes** — id, name, canonical_name (unique), description, career_paths (JSON), green_flags (JSON), red_flags (JSON), version, timestamps
- **role_archetype_skills** — id, role_archetype_id (FK), skill_concept_id (FK), min_confidence, weight, is_core
- **employer_interpretations** — id, role_archetype_id (FK), employer_name, equivalency_prefs (JSON), notes, learned_from (JSON), version, timestamps
- **employer_skill_overrides** — id, employer_interpretation_id (FK), skill_concept_id (FK), priority, weight_override

## LLM Configuration

SuperRecruit supports multiple LLM providers via a unified interface (`src/llm_config.py`).

### Providers
- **Anthropic** — Uses the `anthropic` Python library
- **OpenAI-compatible** — Any provider with a `/v1/chat/completions` endpoint (OpenAI, Azure, Ollama, vLLM, local models). Uses `httpx` directly — no `openai` dependency.

### Roles
Each LLM task maps to a "role" that resolves to a provider + model:
- `skill_extraction` — Resume skill analysis
- `workspace_chat` — Interactive candidate review agent
- `bulk_processing` — Batch resume pipeline
- `confidence_reasoning` — Confidence score justification

### Configuration Hierarchy
1. `config/llm.yaml` — Primary config (copy from `config/llm.example.yaml`)
2. `SR_LLM_*` env vars — Override provider/model per role
3. `ANTHROPIC_API_KEY` + `ANTHROPIC_MODEL` — Backward-compatible fallback

### Fallback Chains
Each role can define a `fallback` list of providers. If the primary fails (network error, API down), the next provider is tried automatically.

### Unified Interface
All LLM calls go through `get_client(role) -> LLMClient` with a single `.complete()` method:
```python
from src.llm_config import get_client
client = get_client("skill_extraction")
result = client.complete(messages=[...], max_tokens=4096, system="...")
```

## Key Design Decisions

- **SQLite with WAL** — Simple deployment, sufficient for single-instance. Postgres migration path planned.
- **In-memory bulk job tracking** — `_bulk_jobs` dict in `main.py`; jobs lost on restart (acceptable for batch processing).
- **Knowledge Base is PII-free** — Safely exportable between instances. Skill ontology is separate from candidate data.
- **Workspace agent actions** — Chat responses can include structured actions (adjust_confidence, add_skill, remove_skill, learn_skill_concept, learn_equivalency, set_note, override_fit) that are executed server-side.
- **Fit assessment** — Automatic scoring of candidates against role archetypes or ad-hoc position profiles. Uses weighted skill matching with KB equivalencies and LLM-generated rationale. Supports manual override via API or workspace chat.
