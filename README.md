# AI Software Engineer

An autonomous AI-powered software engineer that understands natural language tasks, writes code, runs tests, self-corrects, and creates pull requests — all with human-in-the-loop approvals.

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│                      Frontend (React)                      │
│  Dashboard · Task History · Live Logs · Approval Modals    │
│       Tailwind CSS · shadcn/ui · Dark Mode · WebSocket     │
└────────────────┬───────────────────────────┬───────────────┘
                 │ REST API                  │ WebSocket
┌────────────────▼───────────────────────────▼───────────────┐
│                    Backend (FastAPI)                        │
│  Tasks API · Plugins API · WebSocket Manager               │
├────────────────────────────────────────────────────────────┤
│                 LangGraph Orchestrator                      │
│  research → analyze → plan → code → test → revise →        │
│  document → approve → create_pr                            │
├────────────────────────────────────────────────────────────┤
│                      Services                              │
│  AI (Claude + Gemini) · Git · Sandbox · Browser · Terminal │
├──────────────┬─────────────────────┬──────────────────────┤
│  PostgreSQL  │       Redis         │   Docker Sandbox     │
└──────────────┴─────────────────────┴──────────────────────┘
```

## Features

- **Multi-Agent AI** — Claude Opus for code generation & deep reasoning, Gemini Pro 2.5 for planning & documentation
- **Self-Correction Loop** — Generates code → runs tests → feeds errors back to AI for revision (up to 3 retries)
- **Sandboxed Execution** — All code runs inside Docker containers with memory limits and optional network isolation
- **Web Research** — Playwright-powered browser for searching docs and reading APIs
- **Safe Terminal** — Command execution with dangerous command detection and blocking
- **Human-in-the-Loop** — Approval modals for plans, PRs, and destructive commands
- **Real-time UI** — WebSocket streaming with live logs, progress bars, and status indicators
- **Plugin Ecosystem** — MCP (Model Context Protocol) plugin support for extensibility
- **Dark Mode** — System-preference-aware theme toggle

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI, Python 3.11, async/await |
| Database | PostgreSQL 15, SQLModel ORM |
| Queue | Redis 7, Celery |
| AI Models | Claude Opus (Anthropic), Gemini Pro 2.5 (Google) |
| Orchestration | LangGraph |
| Sandbox | Docker SDK for Python |
| Git | GitPython, PyGithub |
| Frontend | React 18, TypeScript, Vite |
| UI | Tailwind CSS, shadcn/ui, Radix UI |
| Real-time | WebSocket |

## Quick Start

### Prerequisites

- Docker & Docker Compose
- API keys for Anthropic and Google AI

### 1. Clone and configure

```bash
git clone <repo-url>
cd AI-Software-Engineer
cp .env.example .env
# Edit .env with your API keys
```

### 2. Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `ANTHROPIC_API_KEY` | Anthropic Claude API key | Yes |
| `GEMINI_API_KEY` | Google AI Studio API key | Yes |
| `GITHUB_TOKEN` | GitHub PAT with repo scope | For PRs |
| `GITHUB_OWNER` | GitHub username/org | For PRs |
| `DATABASE_URL` | PostgreSQL connection string | Auto |
| `REDIS_URL` | Redis connection string | Auto |
| `HUMAN_IN_THE_LOOP` | Enable approval workflows | Default: true |
| `MAX_RETRIES` | Max self-correction attempts | Default: 3 |
| `SANDBOX_TIMEOUT` | Container timeout (seconds) | Default: 300 |

### 3. Start with Docker Compose

```bash
docker-compose up --build
```

This starts:
- **Backend** at `http://localhost:8000` (API docs at `/docs`)
- **Frontend** at `http://localhost:3000`
- **PostgreSQL** on port 5432
- **Redis** on port 6379

### 4. Local Development (without Docker)

**Backend:**
```bash
cd backend
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

## Usage

1. Open `http://localhost:3000`
2. Type a task title and description (e.g., "Add user authentication with JWT")
3. Click **Start Task**
4. Watch the AI work through research → planning → coding → testing → documentation
5. Approve the plan and PR when prompted
6. The AI creates a GitHub PR with the implementation

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/api/tasks/` | List all tasks |
| POST | `/api/tasks/` | Create a new task |
| GET | `/api/tasks/{id}` | Get task details |
| DELETE | `/api/tasks/{id}` | Cancel a task |
| GET | `/api/tasks/{id}/logs` | Get task logs |
| GET | `/api/tasks/{id}/approvals` | Get approval requests |
| POST | `/api/tasks/{id}/approvals/{aid}/respond` | Respond to approval |
| GET | `/api/plugins/` | List plugins |
| POST | `/api/plugins/` | Register plugin |
| PATCH | `/api/plugins/{id}` | Toggle plugin |
| WS | `/ws` | Global WebSocket |
| WS | `/ws/{task_id}` | Task-specific WebSocket |

## Project Structure

```
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py              # FastAPI entry point
│       ├── config.py             # Pydantic settings
│       ├── database.py           # Async SQLModel setup
│       ├── models.py             # ORM models
│       ├── api/
│       │   ├── tasks.py          # Task CRUD endpoints
│       │   ├── plugins.py        # Plugin management
│       │   └── websocket.py      # WebSocket manager
│       ├── agents/
│       │   ├── orchestrator.py   # LangGraph workflow
│       │   ├── prompts.py        # AI role prompts
│       │   └── tools.py          # Tool definitions
│       ├── services/
│       │   ├── ai_service.py     # Claude + Gemini clients
│       │   ├── git_service.py    # Git/GitHub operations
│       │   ├── sandbox.py        # Docker sandbox
│       │   ├── web_browser.py    # Playwright browser
│       │   ├── terminal.py       # Safe command execution
│       │   ├── playwright_runner.py  # E2E test runner
│       │   └── plugin_manager.py # MCP plugin manager
│       └── workers/
│           └── celery_worker.py  # Background tasks
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── index.css
│       ├── lib/utils.ts
│       ├── hooks/
│       │   ├── useAgentWebSocket.ts
│       │   └── useLocalStorage.ts
│       └── components/
│           ├── Dashboard.tsx
│           ├── TaskHistory.tsx
│           ├── LiveLogs.tsx
│           ├── ApprovalModal.tsx
│           ├── PluginManager.tsx
│           ├── ThemeToggle.tsx
│           └── ui/ (shadcn components)
└── sandbox/
    └── Dockerfile.sandbox
```

## License

MIT
