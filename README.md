# SuperRecruit

**AI-powered technical recruiting platform** — parse resumes, extract and score skills with LLMs, administer targeted assessments, and build a shared knowledge base of skills and role archetypes.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Browser / Client                       │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP
┌──────────────────────────▼──────────────────────────────────┐
│                    FastAPI Application                       │
│                                                             │
│  ┌─────────────┐ ┌──────────────┐ ┌───────────────────┐    │
│  │ Resume      │ │ Skill        │ │ Assessment        │    │
│  │ Parser      │ │ Extractor    │ │ Engine            │    │
│  │ (pdfplumber)│ │ (Claude LLM) │ │ (YAML test bank)  │    │
│  └──────┬──────┘ └──────┬───────┘ └────────┬──────────┘    │
│         │               │                   │               │
│  ┌──────▼───────────────▼───────────────────▼──────────┐    │
│  │              Confidence Scorer                       │    │
│  │         (heuristic + LLM hybrid)                     │    │
│  └──────────────────────┬──────────────────────────────┘    │
│                         │                                   │
│  ┌──────────────────────▼──────────────────────────────┐    │
│  │           Workspace Agent (Claude)                   │    │
│  │     Interactive skill review & KB learning           │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─────────────────┐  ┌────────────────────────────────┐    │
│  │ Bulk Processor  │  │ Knowledge Base                 │    │
│  │ (ZIP upload)    │  │ (skills, roles, employers)     │    │
│  └─────────────────┘  └────────────────────────────────┘    │
└──────────────────────────┬──────────────────────────────────┘
                           │
                    ┌──────▼──────┐
                    │   SQLite    │
                    │  (WAL mode) │
                    └─────────────┘
```

## Features

- **Resume Parsing** — Upload PDFs, extract text and structured sections
- **AI Skill Extraction** — Claude-powered skill identification with confidence scoring
- **Confidence Scoring** — Hybrid heuristic + LLM pipeline with manual override support
- **Assessment Portal** — Send candidates targeted tests from a YAML-based test bank; auto-grade multiple choice
- **Bulk Processing** — Upload a ZIP of resumes for batch analysis
- **Interactive Workspace** — Chat with an AI agent to review and adjust candidate skills in real-time
- **Candidate-Role Fit Assessment** — Automatic scoring of how well a candidate matches a role archetype, with LLM-generated rationale and manual override support
- **Knowledge Base** — Maintain a shared ontology of skills, role archetypes, and employer-specific interpretations; fully exportable/importable

## Quick Start (Local Development)

```bash
# Clone and set up
git clone https://github.com/insomniak68/superrecruit.git
cd superrecruit
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env — at minimum set ANTHROPIC_API_KEY

# (Optional) Seed knowledge base
python scripts/seed_knowledge_base.py

# (Optional) Seed test data
python scripts/seed_test_data.py

# Run
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

Open http://localhost:8000

## Docker Deployment

```bash
# Build
docker build -t superrecruit:latest .

# Configure
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY

# Run with docker-compose
docker compose up -d

# Or run directly
docker run -d \
  --name superrecruit \
  -p 8000:8000 \
  --env-file .env \
  -v superrecruit-data:/app/data \
  superrecruit:latest
```

## Kubernetes Deployment

```bash
# Create namespace and storage
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/pvc.yaml

# Create secrets (replace values)
kubectl -n superrecruit create secret generic superrecruit-secrets \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-api03-your-key \
  --from-literal=SR_SMTP_PASSWORD=your-smtp-password

# Deploy
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml

# (Optional) Configure ingress
# Edit k8s/ingress.yaml with your domain, then:
# kubectl apply -f k8s/ingress.yaml
```

## Configuration Reference

| Variable | Description | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key (required) | — |
| `SR_LLM_MODEL` | Claude model name | `claude-sonnet-4-20250514` |
| `SR_DB_PATH` | SQLite database path | `data/superrecruit.db` |
| `SR_HOST` | Server bind address | `0.0.0.0` |
| `SR_PORT` | Server port | `8000` |
| `SR_BASE_URL` | Public-facing URL | `http://localhost:8000` |
| `SR_SMTP_HOST` | SMTP server hostname | — |
| `SR_SMTP_PORT` | SMTP server port | `587` |
| `SR_SMTP_USER` | SMTP username | — |
| `SR_SMTP_PASSWORD` | SMTP password | — |
| `SR_SMTP_FROM` | Sender email address | `assessments@superrecruit.dev` |
| `SR_UPLOAD_DIR` | Resume upload directory | `data/uploads` |

## API Reference

### Health

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check → `{"status": "ok"}` |

### Candidates

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/candidates/upload` | Upload resume (multipart: file, name, email, phone) |
| `GET` | `/api/candidates` | List all candidates |
| `GET` | `/api/candidates/{id}` | Get candidate with skills |

### Assessments

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/candidates/{id}/send-assessment` | Send assessment email (`{test_ids, base_url}`) |
| `GET` | `/assess/{token}` | Candidate assessment portal |
| `POST` | `/assess/{token}/submit` | Submit assessment answers |
| `GET` | `/api/test-bank` | List available tests |

### Bulk Processing

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/bulk` | Upload ZIP of resumes → `{job_id}` |
| `GET` | `/api/bulk/{job_id}` | Poll bulk job status |

### Workspace

| Method | Path | Description |
|---|---|---|
| `GET` | `/workspace/{cid}` | Interactive workspace UI |
| `POST` | `/api/workspace/{cid}/chat` | Chat with AI agent (`{message}`) |
| `PATCH` | `/api/workspace/{cid}/skills/{sid}` | Update skill (`{confidence, irrelevant, note}`) |
| `POST` | `/api/workspace/{cid}/skills` | Add skill manually |
| `PATCH` | `/api/workspace/{cid}/fit` | Override fit assessment (`{fit_level, rationale}`) |

### Knowledge Base

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/kb/skills` | List skill concepts |
| `POST` | `/api/kb/skills` | Create skill concept |
| `GET` | `/api/kb/skills/{id}` | Get skill with relations |
| `PATCH` | `/api/kb/skills/{id}` | Update skill concept |
| `DELETE` | `/api/kb/skills/{id}` | Delete skill concept |
| `POST` | `/api/kb/skills/{id}/relations` | Create skill relation |
| `DELETE` | `/api/kb/relations/{id}` | Delete skill relation |
| `GET` | `/api/kb/roles` | List role archetypes |
| `POST` | `/api/kb/roles` | Create role archetype |
| `GET` | `/api/kb/roles/{id}` | Get role with skills |
| `PATCH` | `/api/kb/roles/{id}` | Update role archetype |
| `DELETE` | `/api/kb/roles/{id}` | Delete role archetype |
| `GET` | `/api/kb/roles/{id}/employers` | List employer interpretations |
| `POST` | `/api/kb/roles/{id}/employers` | Create employer interpretation |
| `GET` | `/api/kb/roles/{id}/employers/{eid}` | Get employer interpretation |
| `PATCH` | `/api/kb/roles/{id}/employers/{eid}` | Update employer interpretation |
| `DELETE` | `/api/kb/roles/{id}/employers/{eid}` | Delete employer interpretation |
| `GET` | `/api/kb/search?q=` | Search skills and roles |
| `GET` | `/api/kb/export` | Export entire KB as JSON |
| `POST` | `/api/kb/import` | Import KB from JSON |

### Web Pages

| Path | Description |
|---|---|
| `/` | Home page |
| `/candidates` | Candidates list |
| `/candidates/{id}` | Candidate detail |
| `/candidates/{id}/assessment` | Assessment setup |
| `/bulk` | Bulk upload page |
| `/knowledge-base` | Knowledge base management |

## Knowledge Base Export/Import

```bash
# Export
curl http://localhost:8000/api/kb/export > kb-backup.json

# Import (merges by canonical name, skips existing)
curl -X POST http://localhost:8000/api/kb/import \
  -H "Content-Type: application/json" \
  -d @kb-backup.json

# Seed from script
python scripts/seed_knowledge_base.py
```

## Testing

```bash
source .venv/bin/activate
pytest tests/ -v
```

## Project Structure

```
superrecruit/
├── src/
│   ├── main.py              # FastAPI app and routes
│   ├── models.py            # Pydantic models
│   ├── database.py          # SQLite init and connection
│   ├── resume_parser.py     # PDF parsing (pdfplumber)
│   ├── skill_extractor.py   # LLM-based skill extraction
│   ├── confidence_scorer.py # Hybrid confidence scoring
│   ├── test_selector.py     # Assessment test selection
│   ├── assessment.py        # Assessment session management
│   ├── auth.py              # Authentication utilities
│   ├── email_service.py     # SMTP email sending
│   ├── bulk_processor.py    # ZIP bulk resume processing
│   ├── workspace_agent.py   # AI workspace chat agent
│   ├── fit_assessor.py      # Candidate-role fit assessment
│   ├── knowledge_base.py    # Skill/role ontology CRUD
│   ├── templates/           # Jinja2 HTML templates
│   └── test_bank/           # YAML assessment questions
├── scripts/
│   ├── seed_test_data.py
│   └── seed_knowledge_base.py
├── config/
│   └── config.example.yaml
├── k8s/                     # Kubernetes manifests
├── tests/                   # pytest test suite
├── docs/                    # Extended documentation
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Write tests for new functionality
4. Ensure `pytest tests/ -v` passes
5. Submit a pull request

## License

Proprietary — internal use only.
