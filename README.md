# Killhub

Turn a public GitHub repository into an interactive Gradio demo — generated and repaired by an AI agent running inside an isolated sandbox.

## What it does

Given a GitHub URL, Killhub:

1. Clones the repo into a sandboxed container
2. Analyzes the codebase with an AI agent (OpenCode + Vultr Inference)
3. Generates a Gradio UI wired to real repository functions
4. Runs automated Playwright tests and auto-repairs failures
5. Streams progress to the frontend and serves an isolated preview URL

## Architecture

```
┌─────────────┐     SSE (progress)     ┌──────────────┐
│  Next.js UI │ ◄────────────────────► │   FastAPI    │
│  (frontend) │   POST /jobs           │   (backend)  │
└──────┬──────┘                        └──────┬───────┘
       │ iframe preview                       │
       ▼                                      ▼
┌─────────────┐                        ┌──────────────┐
│   Caddy     │ ─── /demos/{id} ─────► │   Sandbox    │
│  (routing)  │                        │ Docker+gVisor│
└─────────────┘                        └──────┬───────┘
                                              │
                       ┌──────────────────────┼──────────────────────┐
                       ▼                      ▼                      ▼
                 ┌───────────┐         ┌────────────┐         ┌────────────┐
                 │ OpenCode  │         │   Gradio   │         │ Playwright │
                 │ + Vultr   │         │   demo     │         │   tests    │
                 └───────────┘         └────────────┘         └────────────┘
```

**Data flow:** User submits URL → job created → agent analyzes repo in sandbox → Gradio app generated → Playwright validates → demo URL returned → Caddy routes preview traffic.

Jobs are **server-owned**. Closing the tab or dropping the SSE connection does not cancel the pipeline. Reopen `/jobs/{id}` to resume status and logs. Only an explicit cancel or timeout stops a job.

## Repo structure

```
killhub/
├── frontend/                 # Next.js app
│   ├── app/
│   ├── components/
│   └── lib/
├── backend/
│   ├── main.py               # FastAPI endpoints
│   ├── agent.py              # OpenCode + Vultr integration
│   ├── sandbox.py            # Docker / gVisor management
│   ├── demo.py               # Gradio template + generation helpers
│   ├── testing.py            # Playwright runner
│   ├── jobs.py               # Job state machine + storage
│   ├── config.py
│   ├── models.py
│   └── requirements.txt
├── sandbox/
│   └── Dockerfile            # Agent/demo runtime image
├── prompts/
│   ├── analyze_repo.md
│   ├── generate_gradio.md
│   └── repair_from_errors.md
├── docker-compose.yml
├── Caddyfile
├── .env.example
└── README.md
```

## Quick start

```bash
cp .env.example .env   # fill in VULTR_API_KEY and related settings
docker compose up --build
```

- Frontend: proxied via Caddy at `/`
- Backend health: `GET /health` (via `/api` as configured)
- Demo previews: `/demos/{job_id}`

> Full gVisor isolation targets a Linux host. On macOS, use a soft-sandbox mode for UI/agent iteration when documented.

## API

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/jobs` | Create job `{ github_url }` → `{ job_id }` |
| `GET` | `/api/jobs/{id}` | Job status + demo URL when ready |
| `GET` | `/api/jobs/{id}/events` | SSE stream of progress / logs |
| `DELETE` | `/api/jobs/{id}` | Cancel job + trigger cleanup |

### Job states

```
pending → provisioning → cloning → analyzing → generating
       → installing → starting → testing ⇄ repairing
       → ready | failed | cancelled
```

Repair loop: `testing → repairing → testing`, capped by `MAX_REPAIR_ATTEMPTS`, then `failed`.

## Configuration

Copy `.env.example` and set:

| Variable | Purpose |
|----------|---------|
| `VULTR_API_KEY` | Inference API (host/backend only — never injected into the sandbox) |
| `OPENCODE_*` | Agent client settings |
| `SANDBOX_MEMORY` / `SANDBOX_CPUS` | Per-job resource limits |
| `JOB_TIMEOUT_SECONDS` | Hard wall-clock timeout |
| `MAX_REPAIR_ATTEMPTS` | Repair loop cap |
| `DEMO_BASE_URL` | Public base for preview links |
| `CADDY_*` | Routing / TLS as needed |

## Security

- Agent tool use (`exec`, file IO) runs only inside the sandbox
- API keys stay on the host/backend; they never enter the container env
- Resource limits (memory, CPU, pids, timeouts) and no Docker socket mount into sandboxes
- Prefer non-root, dropped capabilities, and no host network

## Out of scope (v1)

- Private GitHub repos / OAuth
- Non-Python primary languages
- Multi-user auth / billing
- Persistent demo hosting beyond job TTL
- GPU workloads inside the sandbox

## Roadmap

See [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md) for phased tasks, acceptance criteria, and milestones.

| Milestone | Goal |
|-----------|------|
| **M0** | Compose stack boots (frontend + backend + Caddy) |
| **M1** | Jobs API + SSE with stub pipeline |
| **M2** | Sandbox clone/exec/cleanup with limits |
| **M3** | Agent generates Gradio + install script for one fixture repo |
| **M4** | Live Gradio preview via Caddy iframe |
| **M5** | Playwright gate + one successful auto-repair |
| **M6** | Three public repos demo successfully; isolation verified |

## Definition of done (v1)

A user can paste a public Python GitHub URL, watch live agent/sandbox logs, and interact with a Gradio demo in an iframe. The demo is generated from real repo functions, validated by Playwright, served through Caddy from a gVisor-isolated container, and torn down automatically — with API keys never entering the sandbox.
