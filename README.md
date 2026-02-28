# SuperRecruit

Automated skills verification engine for hiring. Analyzes resumes, identifies claimed skills, assesses confidence in each claim, and sends candidates targeted skill tests.

## How It Works

1. **Upload** a PDF resume via web UI
2. **AI analyzes** the resume — extracts skills, evaluates evidence, assigns confidence (HIGH/MEDIUM/LOW)
3. **Test selector** picks assessments for skills needing verification
4. **One link** sent to candidate with all their tests (coding, multiple choice, short answer)
5. **Dashboard** shows results to recruiter

## Quick Start

```bash
pip install -r requirements.txt

# Generate sample resume
python scripts/seed_test_data.py

# Run the app
uvicorn src.main:app --reload

# Open http://localhost:8000
```

## Test Bank

10 pre-built assessments covering:
- Python, JavaScript, SQL, React (coding tests with real test cases)
- System Design, API Design (short answer + multiple choice)
- Git, DevOps, Agile, DSA (mixed format)

## Deploy (Kubernetes)

```bash
docker build -t superrecruit .
kubectl apply -f k8s/
# Available at 10.20.30.45
```

## Tech Stack

- **Backend:** FastAPI + SQLite
- **Frontend:** Jinja2 + Tailwind CSS + CodeMirror
- **AI:** Claude Sonnet (Anthropic) for skill extraction
- **Deployment:** Docker + Kubernetes (k3s + Longhorn + MetalLB)
