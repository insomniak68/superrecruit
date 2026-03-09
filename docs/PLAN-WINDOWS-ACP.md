# Plan: SuperRecruit as Standalone Windows App with ACP

## Overview

Transform SuperRecruit from a server-deployed web app into a standalone Windows desktop application. Use ACP (Agent Communication Protocol) as the LLM integration layer — SR becomes an **ACP client** that delegates all LLM work to whatever ACP-compatible agent the user has running locally (Claude Code, Copilot CLI, or any ACP server). No API keys in SR, no vendor lock-in.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    SuperRecruit Desktop                         │
│  ┌───────────────────────┐    ┌───────────────────────────────┐│
│  │   Electron Shell      │    │   FastAPI Backend              ││
│  │   (BrowserWindow →    │───▶│   (bundled Python)             ││
│  │    localhost:8321)     │    │                                ││
│  └───────────────────────┘    │   ┌─────────────────────────┐  ││
│                               │   │ ACP Client              │  ││
│                               │   │ (replaces direct LLM    │  ││
│                               │   │  API calls)             │  ││
│                               │   └──────────┬──────────────┘  ││
│                               └──────────────┼─────────────────┘│
└──────────────────────────────────────────────┼──────────────────┘
                                               │ ACP (REST)
                    ┌──────────────────────────┼──────────────┐
                    │                          │              │
              ┌─────▼─────┐            ┌───────▼───┐   ┌─────▼──────┐
              │ Claude     │            │ Copilot   │   │ Local      │
              │ Code       │            │ CLI       │   │ Ollama     │
              │ (ACP)      │            │ (ACP)     │   │ ACP Agent  │
              └────────────┘            └───────────┘   └────────────┘
```

**Key insight:** SR doesn't need API keys or LLM provider config. It talks ACP to whatever agent is available. The user's existing Claude Code subscription, Copilot license, or local Ollama instance does the heavy lifting.

---

## Phase 0: New Repo Setup

**Goal:** Clean separation.

1. Create `insomniak68/superrecruit-desktop` (private)
2. Copy current `src/`, `tests/`, `config/`, `k8s/`, `docs/`, `templates/`, `scripts/`, `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `.env.example`
3. Verify 122 tests pass in the new repo
4. Archive the old location
5. Update MEMORY.md

**Deliverable:** Clean repo, CI green.

---

## Phase 1: ACP Client Integration

**Goal:** Replace direct LLM API calls with ACP agent calls. This is the core architectural change and should happen before Windows packaging so we validate the abstraction early.

### How It Works

SR currently calls LLMs through `LLMClient.complete()` in `llm_config.py`. Four roles use it:

| Role | What it does | ACP agent it maps to |
|---|---|---|
| `skill_extraction` | Parse resume text → structured skills | General-purpose LLM agent |
| `workspace_chat` | Interactive analysis assistant | General-purpose LLM agent |
| `bulk_processing` | Batch resume processing | General-purpose LLM agent |
| `confidence_reasoning` | Generate fit assessment rationales | General-purpose LLM agent |

All four roles just need a "complete this prompt" capability — they don't need specialized agents. SR sends structured prompts and expects text responses.

### Implementation

| # | Task | Notes |
|---|---|---|
| 1.1 | **`ACPLLMClient`** | New class implementing the existing `LLMClient` interface. Instead of calling Anthropic/OpenAI APIs, it creates an ACP run against a configured agent, sends the prompt as a message, and collects the response. |
| 1.2 | **Agent discovery** | On startup (and on-demand), SR queries configured ACP server URLs for available agents via `GET /agents`. Caches the manifest. |
| 1.3 | **Provider config** | Add `acp` as a provider type in `llm_config.py`. Config specifies ACP server URL(s) and optionally which agent name to use. |
| 1.4 | **Async run handling** | ACP runs are async (created → in-progress → completed). `ACPLLMClient.complete()` polls or uses SSE streaming to wait for completion. Timeout + cancellation support. |
| 1.5 | **Fallback chain** | Keep the existing fallback logic: try ACP agent first, fall back to direct API if configured, fall back to local Ollama. |
| 1.6 | **Settings UI** | Add ACP configuration to the settings: server URL, agent selection (dropdown populated from discovery), connection test button. |
| 1.7 | **Remove API key requirement** | When ACP is configured, no Anthropic/OpenAI key needed. First-run wizard offers two paths: "I have an ACP agent" or "I have an API key." |

### `ACPLLMClient` Design

```python
class ACPLLMClient(LLMClient):
    """LLM client that delegates to an ACP agent."""

    def __init__(self, server_url: str, agent_name: str, timeout: float = 120.0):
        self.server_url = server_url.rstrip("/")
        self.agent_name = agent_name
        self.timeout = timeout

    def complete(self, messages: list[dict], max_tokens: int = 4096, system: str | None = None) -> str:
        # Build ACP message from the prompt
        prompt = self._format_prompt(messages, system)
        
        # Create a run
        run = httpx.post(f"{self.server_url}/agents/{self.agent_name}/runs", json={
            "input": [{"parts": [{"content_type": "text/plain", "content": prompt}]}]
        }).json()
        
        run_id = run["id"]
        
        # Poll for completion (or use SSE if supported)
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            status = httpx.get(
                f"{self.server_url}/agents/{self.agent_name}/runs/{run_id}"
            ).json()
            
            if status["status"] == "completed":
                return self._extract_text(status["output"])
            elif status["status"] == "failed":
                raise RuntimeError(f"ACP agent failed: {status.get('error', 'unknown')}")
            
            time.sleep(1)
        
        # Cancel on timeout
        httpx.post(f"{self.server_url}/agents/{self.agent_name}/runs/{run_id}/cancel")
        raise TimeoutError(f"ACP agent did not respond within {self.timeout}s")
```

### Config Example

```yaml
# config/llm.yaml
default_provider: acp

providers:
  acp:
    type: acp
    server_url: http://localhost:3000  # Claude Code ACP endpoint
    agent_name: claude-code            # or auto-discover
    timeout: 120

  # Fallback: direct API (optional)
  anthropic:
    type: anthropic
    api_key: ${ANTHROPIC_API_KEY}
    default_model: claude-sonnet-4-20250514

roles:
  skill_extraction:
    provider: acp
    fallback: [anthropic]
  workspace_chat:
    provider: acp
    fallback: [anthropic]
  bulk_processing:
    provider: acp
    fallback: [anthropic]
  confidence_reasoning:
    provider: acp
    fallback: [anthropic]
```

---

## Phase 2: Windows Desktop Packaging

**Goal:** Single-click installable Windows app — no Python required.

### Approach: Electron + Bundled Python

| # | Task | Notes |
|---|---|---|
| 2.1 | **PyInstaller bundle** | Bundle FastAPI app + deps into `dist/superrecruit/`. Entry point: `run_server.py` (starts uvicorn on `127.0.0.1:8321`). |
| 2.2 | **Electron shell** | Minimal Electron app: spawns Python backend, opens BrowserWindow to localhost, kills backend on close. |
| 2.3 | **Data directory** | `SR_DB_PATH` → `%APPDATA%/SuperRecruit/data/superrecruit.db`. Uploads → `%APPDATA%/SuperRecruit/uploads/`. |
| 2.4 | **First-run wizard** | Two paths: (a) "Connect to ACP agent" — enter server URL, discover agents, test connection. (b) "Use API key" — enter Anthropic/OpenAI key directly. |
| 2.5 | **System tray** | Minimize to tray. Menu: Open, Settings, Agent Status, Quit. |
| 2.6 | **Agent status indicator** | Tray icon and status bar show whether ACP agent is reachable. Green dot = connected, red = disconnected (with fallback info). |
| 2.7 | **Installer** | `electron-builder` → NSIS `.exe` installer. |
| 2.8 | **Auto-update** | `electron-updater` via GitHub Releases. |
| 2.9 | **Smoke tests** | Packaged app starts, discovers ACP agent, processes a PDF, exits cleanly on Win 10/11. |

---

## Phase 3: Polish & Distribution

| # | Task | Notes |
|---|---|---|
| 3.1 | **Settings page** | Full in-app settings: ACP servers (add/remove/test), API key fallbacks, SMTP, theme. |
| 3.2 | **Offline mode** | If no ACP agent and no API key: allow browsing existing data, queue new uploads. |
| 3.3 | **Multi-agent routing** | If multiple ACP agents are discovered, let the user assign agents to roles (e.g., fast local agent for bulk processing, Claude for workspace chat). |
| 3.4 | **Import/Export** | Export DB + uploads as zip. Import on another machine. |
| 3.5 | **Documentation** | User guide for non-technical HR users. "How to connect Claude Code" walkthrough. |
| 3.6 | **CI/CD** | GitHub Actions: build Windows installer on tag, attach to Release. |
| 3.7 | **macOS build** | Electron supports it natively if demand exists. |

---

## File Structure (New Repo)

```
superrecruit-desktop/
├── electron/
│   ├── main.js                  # Spawn Python backend, manage window
│   ├── preload.js
│   ├── first-run.html           # First-run wizard (ACP or API key)
│   ├── package.json
│   └── assets/                  # Icons, tray icons
├── src/                         # Python backend (existing)
│   ├── main.py
│   ├── llm_config.py            # MODIFIED: add ACP provider type
│   ├── acp_client.py            # NEW: ACPLLMClient implementation
│   ├── acp_discovery.py         # NEW: agent discovery + caching
│   ├── fit_assessor.py
│   ├── skill_equivalencies.py
│   ├── templates/
│   └── ...
├── tests/
│   ├── test_acp_client.py       # NEW: ACP client tests (mocked)
│   └── ...
├── config/
├── docs/
├── scripts/
│   └── build_windows.py         # PyInstaller build script
├── requirements.txt
├── .github/workflows/
│   └── build-windows.yml
└── README.md
```

---

## Sequencing

```
Phase 0 (repo setup)     ████  1 hour
Phase 1 (ACP client)     ████████████  2-3 days
Phase 2 (Windows app)    ████████████  2-3 days (can start during Phase 1)
Phase 3 (polish)         ████████  1-2 days
                         ─────────────────────
                         Total: ~1 week
```

Phase 1 (ACP) should come first because:
- It's the core architectural change
- We can validate it on macOS/Linux before dealing with Windows packaging
- If ACP integration surfaces issues, better to find them before bundling

---

## What Changes vs. Current SR

| Area | Current | After |
|---|---|---|
| LLM calls | Direct Anthropic/OpenAI API | ACP agent (with API fallback) |
| API keys | Required | Optional (only for fallback) |
| Deployment | Server (Docker/k8s/bare-metal) | Desktop app (Windows installer) |
| Data | Server-side SQLite | Local `%APPDATA%` SQLite |
| Auth | Admin secret for integrations | Not needed (local app) |
| Users | Multi-user via web | Single user |
| Config | `.env` + YAML | In-app Settings UI |

---

## Open Questions

1. **ACP server availability:** Are Claude Code and Copilot CLI already exposing ACP endpoints, or do they need an adapter/wrapper? If they don't natively support ACP yet, we may need a thin adapter that wraps their CLI interfaces as ACP agents.
2. **Distribution:** GitHub Releases (private, share download links), or company website?
3. **Code signing:** Windows code-signing cert? Without one, SmartScreen warnings on install.
4. **Multi-user later?** If Jason's company wants a shared server mode, we keep the Docker/k8s deployment path alive alongside the desktop build.
