# Deployment Guide

## Prerequisites

- Python 3.12+ (local) or Docker
- Anthropic API key

## Bare Metal / VM

```bash
git clone https://github.com/insomniak68/superrecruit.git
cd superrecruit
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Set ANTHROPIC_API_KEY in .env

# Optional: seed data
python scripts/seed_knowledge_base.py
python scripts/seed_test_data.py

# Run (production)
uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 1

# Or with systemd (create /etc/systemd/system/superrecruit.service):
# [Unit]
# Description=SuperRecruit
# After=network.target
#
# [Service]
# Type=simple
# User=superrecruit
# WorkingDirectory=/opt/superrecruit
# EnvironmentFile=/opt/superrecruit/.env
# ExecStart=/opt/superrecruit/.venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000
# Restart=always
#
# [Install]
# WantedBy=multi-user.target
```

> **Note:** Use `--workers 1` — SQLite does not support concurrent writers well. For multi-worker setups, migrate to PostgreSQL.

## Docker

```bash
docker build -t superrecruit:latest .
cp .env.example .env
# Edit .env

# With docker-compose (recommended)
docker compose up -d

# Or standalone
docker run -d \
  --name superrecruit \
  -p 8000:8000 \
  --env-file .env \
  -v superrecruit-data:/app/data \
  --restart unless-stopped \
  superrecruit:latest
```

### Health Check

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

## Kubernetes

### 1. Namespace & Storage

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/pvc.yaml
```

### 2. Secrets

```bash
kubectl -n superrecruit create secret generic superrecruit-secrets \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-api03-your-key \
  --from-literal=SR_SMTP_PASSWORD=your-smtp-password
```

### 3. Config & Deploy

```bash
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```

### 4. Verify

```bash
kubectl -n superrecruit get pods
kubectl -n superrecruit logs -f deployment/superrecruit
```

### 5. Ingress (Optional)

Edit `k8s/ingress.yaml` with your domain and TLS issuer, then:

```bash
kubectl apply -f k8s/ingress.yaml
```

### Building for k8s

If your cluster can't pull from a registry, build and import directly:

```bash
docker build -t superrecruit:latest .
docker save superrecruit:latest | ssh node "sudo k3s ctr images import -"
```

## Data Backup

```bash
# SQLite backup (while running — WAL mode is safe for this)
cp data/superrecruit.db data/superrecruit.db.bak

# Knowledge base export
curl http://localhost:8000/api/kb/export > kb-backup.json
```
