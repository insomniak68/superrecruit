# Deployment Guide

SuperRecruit is a FastAPI application backed by SQLite. It can run bare-metal, in Docker, or on Kubernetes.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| **Python 3.12+** | For bare-metal only |
| **LLM API key** | Anthropic recommended; OpenAI or local Ollama also supported |
| **~512 MB RAM** | Baseline; more for bulk processing |
| **Disk** | Minimal — SQLite DB + uploaded PDFs |

## Quick Start (Docker)

```bash
git clone https://github.com/insomniak68/superrecruit.git
cd superrecruit

# Configure
cp .env.example .env
# Edit .env — at minimum set ANTHROPIC_API_KEY

# Run
docker compose up -d

# Verify
curl http://localhost:8000/health
# {"status":"ok"}

# Open browser
open http://localhost:8000
```

That's it. The app auto-creates the database, seeds equivalency groups, and syncs the test bank on startup.

---

## Configuration

### Environment Variables

Core settings in `.env`:

```bash
# Required: at least one LLM provider key
ANTHROPIC_API_KEY=sk-ant-api03-...

# Model selection (defaults to claude-sonnet-4-20250514)
SR_LLM_MODEL=claude-sonnet-4-20250514

# Database (SQLite path — relative to working directory)
SR_DB_PATH=data/superrecruit.db

# Server
SR_HOST=0.0.0.0
SR_PORT=8000
SR_BASE_URL=http://localhost:8000  # Used in assessment email links

# SMTP (optional — for sending assessment invitations)
SR_SMTP_HOST=smtp.gmail.com
SR_SMTP_PORT=587
SR_SMTP_USER=you@example.com
SR_SMTP_PASSWORD=app-specific-password
SR_SMTP_FROM=assessments@yourcompany.com

# Admin API (for integration management)
SR_ADMIN_SECRET=superrecruit-admin-secret  # Change this in production!
```

### LLM Configuration

For advanced multi-provider setups, copy and edit the LLM config:

```bash
cp config/config.example.yaml config/llm.yaml
```

This lets you:
- Use different models per task (e.g., cheaper model for bulk processing)
- Set up fallback chains (Anthropic → OpenAI → local Ollama)
- Route specific roles to specific providers

See `config/config.example.yaml` for the full schema. Environment variables (`SR_LLM_*`) override the YAML config.

**LLM Roles:**
| Role | Used For |
|---|---|
| `skill_extraction` | Parsing skills from resumes |
| `workspace_chat` | AI assistant in the analysis workspace |
| `bulk_processing` | Batch resume processing |
| `confidence_reasoning` | Fit assessment rationale generation |

---

## Deployment Options

### Bare Metal / VM

```bash
git clone https://github.com/insomniak68/superrecruit.git
cd superrecruit

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env

# Optional: seed the knowledge base with common skills/roles
python scripts/seed_knowledge_base.py

# Run
uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 1
```

> **Important:** Use `--workers 1`. SQLite doesn't handle concurrent writers well. For multi-worker deployments, you'd need to migrate to PostgreSQL (not yet supported but scaffolded in docker-compose.yml).

#### systemd Service

```ini
# /etc/systemd/system/superrecruit.service
[Unit]
Description=SuperRecruit
After=network.target

[Service]
Type=simple
User=superrecruit
WorkingDirectory=/opt/superrecruit
EnvironmentFile=/opt/superrecruit/.env
ExecStart=/opt/superrecruit/.venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now superrecruit
```

### Docker

```bash
# Build
docker build -t superrecruit:latest .

# Run standalone
docker run -d \
  --name superrecruit \
  -p 8000:8000 \
  --env-file .env \
  -v superrecruit-data:/app/data \
  --restart unless-stopped \
  superrecruit:latest

# Or with docker-compose (recommended)
docker compose up -d
```

The Docker image:
- Multi-stage build (slim runtime image)
- Runs as non-root user `superrecruit`
- Built-in health check (30s interval)
- Data persisted to `/app/data` volume

### Kubernetes

Manifests are in `k8s/`. Adjust for your cluster.

```bash
# 1. Create namespace and storage
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/pvc.yaml

# 2. Create secrets
kubectl -n superrecruit create secret generic superrecruit-secrets \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-api03-... \
  --from-literal=SR_ADMIN_SECRET=your-admin-secret \
  --from-literal=SR_SMTP_PASSWORD=your-smtp-password

# 3. Deploy
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml

# 4. Verify
kubectl -n superrecruit get pods
kubectl -n superrecruit logs -f deployment/superrecruit
curl http://<service-ip>:8000/health

# 5. Ingress (optional — edit k8s/ingress.yaml with your domain first)
kubectl apply -f k8s/ingress.yaml
```

If your cluster can't pull from a registry:
```bash
docker build -t superrecruit:latest .
docker save superrecruit:latest | ssh node "sudo k3s ctr images import -"
```

---

## Post-Deployment Setup

### 1. Seed Equivalency Groups

On first startup, the app auto-seeds 18 skill equivalency groups (Cloud, Frontend, Backend, Databases, CI/CD, ML/AI, Mobile, IaC, Monitoring, Queues, Data Engineering, Warehouses, Search, VCS, APIs, Testing, CSS, Auth).

To re-seed manually (idempotent):
```bash
curl -X POST http://localhost:8000/api/equivalencies/seed
```

Or click **🌱 Seed Common Groups** on the `/equivalencies` page.

### 2. Create a Position Profile

Before processing resumes, create a position profile so candidates get scored against it:

1. Go to `/positions`
2. Click **Create Position**
3. Add required and preferred skills with weights
4. **Activate** the position (only one active at a time)

Or paste a job posting URL — SR will auto-extract requirements.

### 3. Set Up Integrations (Optional)

For ATS/external system integration:

```bash
# Create an API key for a partner
curl -X POST http://localhost:8000/api/admin/integrations \
  -H "Authorization: Bearer $SR_ADMIN_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"name": "AcmeATS", "webhook_url": "https://acme.com/webhooks/sr"}'
```

See [INTEGRATION_SPEC.md](INTEGRATION_SPEC.md) for the full submission API.

### 4. Customize Equivalency Groups

Go to `/equivalencies` to:
- **Edit** default group weights (e.g., your org values GCP more than Azure)
- **Create** domain-specific groups (e.g., your internal frameworks)
- **Review suggestions** — after processing resumes, click 💡 Suggestions to see co-occurrence-based group recommendations
- **Review weight feedback** — after screeners use the workspace, click ⚖️ Weight Feedback to see suggested weight adjustments

Position-level and employer-level overrides are also supported — see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Key URLs

| Path | Description |
|---|---|
| `/` | Dashboard — upload resumes |
| `/candidates` | All candidates |
| `/candidates/<id>` | Candidate detail |
| `/workspace/<id>` | Interactive analysis workspace |
| `/positions` | Position profiles |
| `/equivalencies` | Skill equivalency group management |
| `/knowledge-base` | Skills & role archetype KB |
| `/health` | Health check endpoint |

---

## Data & Backup

### SQLite Backup

```bash
# Safe to copy while running (WAL mode)
cp data/superrecruit.db data/superrecruit.db.bak
```

### Knowledge Base Export/Import

```bash
# Export
curl http://localhost:8000/api/kb/export > kb-backup.json

# Import (into a fresh instance)
curl -X POST http://localhost:8000/api/kb/import \
  -H "Content-Type: application/json" \
  -d @kb-backup.json
```

### Docker Volume Backup

```bash
docker run --rm -v superrecruit-data:/data -v $(pwd):/backup \
  alpine tar czf /backup/sr-data-$(date +%Y%m%d).tar.gz /data
```

---

## Security Notes

- **Change `SR_ADMIN_SECRET`** in production — it gates the integration management API.
- The app has no built-in authentication for the web UI. Put it behind a reverse proxy with auth (nginx + OAuth2 Proxy, Cloudflare Access, Tailscale, etc.).
- API keys for integrations are SHA-256 hashed at rest — the raw key is only shown once at creation.
- Uploaded resumes are stored on disk at `data/uploads/`. Secure this directory.
- SQLite WAL mode is enabled for safe concurrent reads, but limit to 1 write worker.

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `ModuleNotFoundError: pdfplumber` | `pip install -r requirements.txt` in your venv |
| 500 on resume upload | Check `ANTHROPIC_API_KEY` is set and valid |
| Fit scores all 0.0 | No active position profile — create and activate one at `/positions` |
| Equivalency matches not showing | Run seed (`POST /api/equivalencies/seed`) or create groups at `/equivalencies` |
| Health check failing in Docker | Wait 10s for startup; check `docker logs superrecruit` |
| Tests failing | `pip install pytest && python -m pytest tests/` — all 122 should pass |

---

## Running Tests

```bash
pip install pytest
python -m pytest tests/ -v
# Expected: 122 passed
```
