# Plan: SuperRecruit as Standalone Windows App with ACP

## Overview

Transform SuperRecruit from a server-deployed web app into a standalone Windows desktop application that HR screeners install and run locally. Add ACP (Agent Communication Protocol) support so SR's screening agents can interoperate with other AI systems.

---

## Phase 0: New Repo Setup

**Goal:** Clean separation from the monorepo.

1. Create `insomniak68/superrecruit-desktop` (private)
2. Copy current `src/`, `tests/`, `config/`, `k8s/`, `docs/`, `templates/`, `scripts/`, `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `.env.example` 
3. Add `.gitignore` for Python, Windows build artifacts, `.env`, `data/`
4. Verify 122 tests pass in the new repo
5. Archive or mark the old repo as "see superrecruit-desktop"
6. Update MEMORY.md with new repo location

**Deliverable:** Clean repo, CI green, old repo archived.

---

## Phase 1: Windows Desktop Packaging

**Goal:** Single-click installable Windows app — no Python required on the user's machine.

### Approach: Electron + FastAPI Backend (recommended)

```
┌──────────────────────────────────────────┐
│           Electron Shell (UI)            │
│  ┌────────────────────────────────────┐  │
│  │   Chromium (existing HTML/Jinja2   │  │
│  │   templates served from local      │  │
│  │   FastAPI backend)                 │  │
│  └──────────────┬─────────────────────┘  │
│                 │ localhost:8321          │
│  ┌──────────────▼─────────────────────┐  │
│  │   FastAPI Backend (bundled Python) │  │
│  │   SQLite DB in %APPDATA%/SR/       │  │
│  └────────────────────────────────────┘  │
└──────────────────────────────────────────┘
```

**Why Electron + embedded Python:**
- Reuses 100% of existing Jinja2 templates and FastAPI routes
- No frontend rewrite needed
- Electron handles native window, system tray, auto-update
- PyInstaller/cx_Freeze bundles Python + deps into a single directory
- SQLite stays as-is (perfect for single-user desktop)

**Alternative considered:** Tauri (Rust shell) — lighter but still needs a Python sidecar process. Same complexity, less ecosystem support for auto-update on Windows.

### Tasks

| # | Task | Notes |
|---|---|---|
| 1.1 | **PyInstaller bundle** | Bundle FastAPI app + all deps into `dist/superrecruit/`. Entry point: `run_server.py` that starts uvicorn on `127.0.0.1:8321`. |
| 1.2 | **Electron shell** | Minimal Electron app: spawns the Python backend on startup, opens `http://127.0.0.1:8321` in a BrowserWindow, kills backend on close. |
| 1.3 | **Data directory** | Move default `SR_DB_PATH` to `%APPDATA%/SuperRecruit/data/superrecruit.db`. Uploads to `%APPDATA%/SuperRecruit/uploads/`. |
| 1.4 | **First-run wizard** | On first launch: prompt for LLM API key (Anthropic/OpenAI), save to `%APPDATA%/SuperRecruit/.env`. Offer to seed equivalency groups. |
| 1.5 | **System tray** | Minimize to tray. Tray menu: Open, Settings, Quit. |
| 1.6 | **Installer** | Use `electron-builder` to produce `.exe` installer (NSIS) and `.msi`. Sign with code-signing cert if available. |
| 1.7 | **Auto-update** | `electron-updater` pointing at GitHub Releases (or S3). Check on startup, prompt user. |
| 1.8 | **Smoke tests** | Verify the packaged app starts, serves the UI, processes a test PDF, and exits cleanly on Windows 10/11. |

### Key Decisions

- **No cloud dependency:** Everything runs locally. LLM calls go directly to provider APIs from the user's machine.
- **Single-user:** No auth needed (it's their desktop). Remove `SR_ADMIN_SECRET` gate from integration management — or simplify to a local settings page.
- **Port conflict:** If 8321 is taken, auto-increment. Store chosen port in a lockfile.

---

## Phase 2: ACP Integration

**Goal:** SR exposes its screening capabilities as ACP agents, and can invoke external ACP agents.

### SR as ACP Server

SR will host multiple ACP agents behind its FastAPI server:

```
ACP Server (SuperRecruit)
├── resume-screener      — accepts PDF, returns skill assessment + fit score
├── skill-extractor      — accepts text, returns structured skill list
├── fit-assessor         — accepts skills + position profile, returns fit result
└── equivalency-advisor  — accepts skill name, returns equivalents + weights
```

### Implementation

| # | Task | Notes |
|---|---|---|
| 2.1 | **Add `acp-sdk` dependency** | `pip install acp-sdk` — the Python SDK for ACP server/client. |
| 2.2 | **Agent manifests** | Define manifests for each agent: name, description, input/output content types (application/json, application/pdf). |
| 2.3 | **Resume Screener agent** | Wraps the existing upload→parse→extract→score flow. Input: PDF (application/pdf) + optional position profile (application/json). Output: structured assessment JSON. Supports async runs (LLM calls take time). |
| 2.4 | **Skill Extractor agent** | Wraps skill extraction only. Input: text/plain (resume text). Output: application/json (skills array). Stateless. |
| 2.5 | **Fit Assessor agent** | Input: skills + position profile (JSON). Output: fit result JSON. Stateless, fast. |
| 2.6 | **Equivalency Advisor agent** | Input: skill name. Output: equivalents with weights. Stateless. |
| 2.7 | **ACP discovery endpoint** | `GET /agents` returns agent manifests per ACP spec. Mount alongside existing FastAPI routes. |
| 2.8 | **Run lifecycle** | Implement `POST /agents/{name}/runs`, `GET /agents/{name}/runs/{id}` with proper state machine (created → in-progress → completed/failed). Use background tasks for async LLM work. |
| 2.9 | **Streaming** | For resume-screener: stream progress updates (parsing... extracting... scoring...) via ACP's SSE streaming. |
| 2.10 | **SR as ACP client** | Add ability to call external ACP agents. Use case: plug in a third-party reference-checker agent, salary-benchmarking agent, etc. Settings page to register external ACP server URLs. |

### ACP Route Structure

```
/agents                          GET  — list all agents (ACP discovery)
/agents/{name}                   GET  — agent manifest
/agents/{name}/runs              POST — create a run
/agents/{name}/runs/{id}         GET  — get run status/result
/agents/{name}/runs/{id}/cancel  POST — cancel a run
```

These mount alongside existing `/api/*` routes. No conflicts.

### Agent Input/Output Schemas

**resume-screener:**
```json
// Input message
{
  "parts": [
    {"content_type": "application/pdf", "content": "<base64>"},
    {"content_type": "application/json", "content": {"position_title": "Senior Python Dev", "core_skills": ["python", "aws"]}}
  ]
}

// Output message  
{
  "parts": [
    {"content_type": "application/json", "content": {
      "candidate_name": "Jane Doe",
      "skills": [...],
      "fit_score": 0.82,
      "fit_level": "strong",
      "rationale": "...",
      "equivalency_matches": [...]
    }}
  ]
}
```

---

## Phase 3: Polish & Distribution

| # | Task | Notes |
|---|---|---|
| 3.1 | **Settings UI** | Replace `.env` file with a Settings page in the app: API keys, LLM provider selection, SMTP config, ACP external agents. |
| 3.2 | **Offline mode** | Detect when LLM API is unreachable. Allow browsing existing candidates/data. Queue uploads for processing when connection returns. |
| 3.3 | **Import/Export** | Export all data (DB + uploads) as a zip for backup or migration. Import on another machine. |
| 3.4 | **Theming** | Windows-native look: dark mode support, proper DPI scaling. |
| 3.5 | **Documentation** | User-facing README, "Getting Started" guide for non-technical HR users. |
| 3.6 | **GitHub Releases** | CI pipeline (GitHub Actions) to build Windows installer on tag push. |
| 3.7 | **macOS build** | If demand exists — Electron supports it with minimal changes. |

---

## File Structure (New Repo)

```
superrecruit-desktop/
├── electron/                    # Electron shell
│   ├── main.js                  # Main process: spawn Python, open window
│   ├── preload.js
│   ├── package.json
│   └── assets/                  # Icons, tray icon
├── src/                         # Python backend (existing, moved as-is)
│   ├── main.py
│   ├── fit_assessor.py
│   ├── skill_equivalencies.py
│   ├── acp/                     # NEW: ACP agent definitions
│   │   ├── __init__.py
│   │   ├── server.py            # ACP server setup, agent registry
│   │   ├── resume_screener.py   # Resume screener agent
│   │   ├── skill_extractor.py   # Skill extraction agent
│   │   ├── fit_assessor_agent.py
│   │   └── equivalency_advisor.py
│   ├── templates/               # Existing Jinja2 templates
│   └── ...
├── tests/                       # Existing + new ACP tests
├── config/
├── docs/
├── scripts/
│   └── build_windows.py         # PyInstaller build script
├── requirements.txt
├── pyproject.toml
├── .github/
│   └── workflows/
│       └── build-windows.yml    # CI: build installer on tag
└── README.md
```

---

## Sequencing

| Phase | Effort | Dependency |
|---|---|---|
| Phase 0: New repo | 1 hour | None |
| Phase 1: Windows app | 2-3 days | Phase 0 |
| Phase 2: ACP | 2-3 days | Phase 0 (can parallel with Phase 1) |
| Phase 3: Polish | 1-2 days | Phases 1 + 2 |

**Total: ~1 week to a distributable Windows app with ACP support.**

---

## Open Questions for Jason

1. **Code signing:** Do you have a Windows code-signing certificate? Without one, users get SmartScreen warnings.
2. **Distribution:** GitHub Releases (private, share links), or something more formal (company website download)?
3. **LLM default:** Should the app default to a specific model, or force the user to choose on first run?
4. **ACP scope:** Do you want SR to only *serve* agents, or also *consume* external ACP agents from day one?
5. **Multi-user:** Any need for a shared/server mode later, or is single-user desktop the target?
