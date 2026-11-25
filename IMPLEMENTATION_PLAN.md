# Killhub — Implementation Plan

Turn a public GitHub repository into an interactive Gradio demo, generated and repaired by an AI agent running inside an isolated sandbox.

## Goal

Given a GitHub URL, Killhub:

1. Clones the repo into a sandboxed container
2. Analyzes the codebase with an AI agent (OpenCode + Vultr Inference)
3. Generates a Gradio UI wired to real repository functions
4. Runs automated Playwright tests and auto-repairs failures
5. Streams progress to the frontend and serves an isolated preview URL

## Architecture overview

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

## Proposed repo structure

```
killhub/
├── frontend/                 # Next.js app
│   ├── app/
│   │   ├── page.tsx          # URL input + Generate Demo
│   │   ├── jobs/[id]/page.tsx
│   │   └── layout.tsx
│   ├── components/
│   │   ├── UrlForm.tsx
│   │   ├── ProgressLog.tsx
│   │   ├── DemoFrame.tsx
│   │   └── ErrorBanner.tsx
│   └── lib/
│       └── api.ts
├── backend/
│   ├── main.py               # FastAPI endpoints
│   ├── agent.py              # OpenCode + Vultr integration
│   ├── sandbox.py            # Docker / gVisor management
│   ├── demo.py               # Gradio template + generation helpers
│   ├── testing.py            # Playwright runner
│   ├── jobs.py               # Job state machine + storage
│   ├── config.py             # Settings (env-based)
│   ├── models.py             # Pydantic schemas
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

---

## Phase 0 — Project scaffold

**Objective:** Runnable empty shells for frontend, backend, and Docker so later phases plug in cleanly.

### Tasks

- [ ] Initialize monorepo layout above
- [ ] Scaffold Next.js (App Router, TypeScript) in `frontend/`
- [ ] Scaffold FastAPI app in `backend/` with health check `GET /health`
- [ ] Add `docker-compose.yml` services: `frontend`, `backend`, `caddy`, `sandbox-ready` base image build
- [ ] Add `.env.example` for `VULTR_API_KEY`, `OPENCODE_*`, ports, resource limits
- [ ] Add Caddyfile stub that proxies `/` → frontend, `/api/*` → backend
- [ ] Document local start: `docker compose up --build`

### Acceptance criteria

- `docker compose up` starts frontend + backend
- Frontend loads; backend `/health` returns `200`
- No secrets committed; keys only via env

---

## Phase 1 — Backend job system

**Objective:** Accept a GitHub URL, create a job, expose status/events, return a final demo URL.

### API surface

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

### Client disconnect policy

Jobs are **server-owned**. Closing the tab, navigating away, or dropping the SSE connection does **not** cancel or pause the job. The pipeline keeps running until `ready`, `failed`, `cancelled` (explicit `DELETE`), or `JOB_TIMEOUT_SECONDS`. Users resume by reopening `/jobs/{id}` (poll + reconnect SSE).

### Tasks

- [ ] Implement `jobs.py`: in-memory store first (later Redis/Postgres if needed)
- [ ] Pydantic models: `JobCreate`, `JobStatus`, `JobEvent`
- [ ] Validate GitHub URL (public HTTPS, `github.com` host only)
- [ ] Background worker / asyncio task per job (independent of any HTTP/SSE connection)
- [ ] SSE endpoint emitting structured events (`type`, `message`, `timestamp`); support reconnect / catch-up from last event id
- [ ] Persist final `demo_url` on success; `error` on failure
- [ ] Do not bind job lifetime to client presence; only `DELETE /api/jobs/{id}` or timeout cancels

### Acceptance criteria

- Creating a job returns `job_id` immediately
- Clients can poll status and subscribe to SSE logs
- Invalid URLs rejected with `400`
- Disconnecting mid-job leaves the job running; revisiting `/jobs/{id}` shows current status and logs

---

## Phase 2 — Sandbox (Docker + gVisor)

**Objective:** Isolated execution environment for clone, install, run, and cleanup — API keys never enter the container.

### Tasks

- [ ] Write `sandbox/Dockerfile` (Python base, git, common build tools, Gradio deps)
- [ ] Configure gVisor (`runsc`) runtime in Docker / compose
- [ ] `sandbox.py` APIs:
  - `create_container(job_id) → container_id`
  - `exec(container_id, cmd) → { stdout, stderr, exit_code }`
  - `clone_repo(container_id, github_url)`
  - `copy_in` / `copy_out` for generated files only (no host mounts of secrets)
  - `destroy_container(container_id)`
- [ ] Resource limits: memory, CPU shares/quota, pids, disk where possible
- [ ] Network policy: outbound only as required (e.g. pip/git); no host network
- [ ] Timeouts on all exec calls
- [ ] Automatic cleanup on job complete/fail/cancel + periodic reaper for orphans
- [ ] Confirm process environment inside container has **no** Vultr/OpenCode API keys

### Security constraints

- All agent tools that execute code/shell must target the sandbox only
- Prefer non-root user inside container
- Drop unnecessary capabilities; read-only rootfs where feasible
- No Docker socket mount into sandbox containers

### Acceptance criteria

- Repo clones inside container and `exec` captures output
- Exceeding memory/CPU/time fails safely without host impact
- Destroy removes container and associated demo network aliases
- Host env secrets are not visible via `env` inside the container

---

## Phase 3 — AI agent (OpenCode + Vultr Inference)

**Objective:** Agent understands the repo, produces Gradio code + install steps, and repairs from errors — all tool use sandboxed.

### Tasks

- [ ] Wire OpenCode client to Vultr Inference API in `agent.py`
- [ ] Prompt pack under `prompts/`:
  - **Analyze:** languages, entry points, dependencies, candidate callable functions
  - **Generate:** install commands + Gradio app from template
  - **Repair:** consume stderr / Playwright failures and patch code
- [ ] Tool interface restricted to sandbox ops (`exec`, `read_file`, `write_file`, `list_dir`)
- [ ] Structured agent output: `{ install_commands[], gradio_path, summary, functions_used[] }`
- [ ] Cap agent turns / tokens / wall-clock per job
- [ ] Stream agent step messages into job events for the UI

### Acceptance criteria

- Agent can analyze a simple public Python repo and name usable functions
- Generated install + Gradio artifacts land in the sandbox workspace
- Agent cannot invoke tools outside the sandbox API
- Failures emit actionable events and transition job to `failed` or `repairing`

---

## Phase 4 — Demo generation (Gradio)

**Objective:** Standard Gradio template bound to real repo functions, running in-sandbox with a preview URL.

### Tasks

- [ ] Define Gradio template in `demo.py` / sandbox template file:
  - Inputs: text, number, image, file
  - Outputs: text, image, file as appropriate
  - Clear title/description derived from repo metadata
- [ ] Generation rules: import real modules; avoid fake stubs when callables exist
- [ ] Start Gradio on a job-specific port inside the container
- [ ] Register demo with Caddy (or dynamic upstream) as `/demos/{job_id}`
- [ ] Health-check Gradio before marking job `ready`
- [ ] Tear down Gradio process with container cleanup

### Acceptance criteria

- Generated app imports and calls repository code (smoke-check via logs)
- Preview URL loads in iframe from frontend origin (frame ancestors / CORS as needed)
- Unsupported input types degrade gracefully or are omitted with a log event

---

## Phase 5 — Frontend (Next.js)

**Objective:** Single-flow UI: enter URL → watch live progress → view demo or error.

### Tasks

- [ ] Landing page: GitHub URL input + **Generate Demo** button
- [ ] On submit: `POST /api/jobs`, navigate to job view
- [ ] Live progress: connect to SSE, render chronological execution log
- [ ] On page load of `/jobs/{id}`, fetch current status + reconnect SSE (job may have progressed offline)
- [ ] Loading / intermediate states mapped to job status
- [ ] Embed demo in `<iframe src={demo_url}>` when `ready`
- [ ] Error banner for validation failures, agent failures, sandbox failures
- [ ] Cancel / retry controls (optional but recommended); cancel is explicit only
- [ ] Proxy or CORS config so browser talks to FastAPI cleanly in compose

### Acceptance criteria

- Happy path works end-to-end from empty input to iframe preview
- Logs update live without full page refresh
- Leaving and returning to `/jobs/{id}` resumes the live view of an in-progress or finished job
- Errors are human-readable; button disabled while a job is in flight from that session

---

## Phase 6 — Automated testing (Playwright)

**Objective:** Validate the generated Gradio UI; feed failures back to the agent for repair.

### Tasks

- [ ] `testing.py`: launch Playwright against sandbox demo URL
- [ ] Generic checks: page loads, primary inputs visible, submit/run triggers output or error
- [ ] Capture screenshots + console/network errors on failure
- [ ] Package failure report for agent repair prompt
- [ ] Limit repair loops (e.g. max 2–3 cycles) then mark `failed`
- [ ] Run Playwright from backend host or a dedicated test sidecar — **not** with elevated access into other jobs’ containers

### Acceptance criteria

- Passing demo advances job to `ready`
- Failing demo triggers at least one repair attempt with error context
- Screenshots/logs attached to job events for debugging

---

## Phase 7 — Integration & hardening

**Objective:** Full pipeline wired; Caddy routes demos; isolation and recovery verified on real public repos.

### Tasks

- [ ] Wire phases 1–6 into one job orchestration pipeline in `main.py` / `jobs.py`
- [ ] Finalize Caddyfile:
  - `/` → frontend
  - `/api/*` → backend
  - `/demos/{job_id}/*` → sandbox Gradio upstream
- [ ] End-to-end tests with several public Python repos (small ML utils, Gradio-friendly libs, pure functions)
- [ ] Chaos checks: kill container mid-job, bad URL, dependency install failure, infinite agent loop prevention
- [ ] Verify sandbox isolation (cross-job filesystem/network, no secret leakage)
- [ ] Verify automatic error recovery path (install fail → repair → retest)
- [ ] Document ops: resource sizing, cleanup intervals, rate limits

### Acceptance criteria

- At least 3 different public repos produce working demos
- Failed jobs clean up containers within the configured TTL
- Preview URLs are unreachable after cleanup
- No API keys appear in sandbox logs or `env`

---

## Cross-cutting concerns

### Configuration

| Variable | Purpose |
|----------|---------|
| `VULTR_API_KEY` | Inference API (host/backend only) |
| `OPENCODE_*` | Agent client settings |
| `SANDBOX_MEMORY` / `SANDBOX_CPUS` | Per-job limits |
| `JOB_TIMEOUT_SECONDS` | Hard wall clock |
| `MAX_REPAIR_ATTEMPTS` | Repair loop cap |
| `DEMO_BASE_URL` | Public base for preview links |
| `CADDY_*` | Routing / TLS as needed |

### Observability

- Structured logs with `job_id`
- Job event timeline as source of truth for UI
- Optional metrics later: success rate, time-to-demo, repair count

### Out of scope (v1)

- Private GitHub repos / OAuth
- Non-Python primary languages
- Multi-user auth / billing
- Persistent demo hosting beyond job TTL
- GPU workloads inside sandbox

---

## Suggested implementation order

| Order | Phase | Depends on |
|------:|-------|------------|
| 1 | Phase 0 — Scaffold | — |
| 2 | Phase 1 — Jobs API | Phase 0 |
| 3 | Phase 2 — Sandbox | Phase 0 |
| 4 | Phase 3 — Agent | Phases 1–2 |
| 5 | Phase 4 — Gradio demos | Phases 2–3 |
| 6 | Phase 5 — Frontend | Phase 1 (mock events OK early) |
| 7 | Phase 6 — Playwright | Phase 4 |
| 8 | Phase 7 — Integration | All |

Frontend (Phase 5) can start in parallel with Phase 2 using mocked SSE events.

---

## Milestone checklist

- [ ] **M0:** Compose stack boots (frontend + backend + Caddy)
- [ ] **M1:** Jobs API + SSE with stub pipeline
- [ ] **M2:** Sandbox clone/exec/cleanup with limits
- [ ] **M3:** Agent generates Gradio + install script for one fixture repo
- [ ] **M4:** Live Gradio preview via Caddy iframe
- [ ] **M5:** Playwright gate + one successful auto-repair
- [ ] **M6:** Three public repos demo successfully; isolation verified

---

## Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Agent generates broken or unsafe code | Sandbox + Playwright gate + repair cap |
| Dependency installs hang or bloat | Timeouts, memory limits, pinned base image |
| gVisor / runtime complexity on macOS | Document Linux host requirement for full isolation; local soft-sandbox mode for UI/agent iteration |
| Preview iframe blocked by headers | Configure Gradio/`X-Frame-Options` / CSP via Caddy |
| Cost of inference loops | Turn/token caps; skip repair when errors are non-actionable |

---

## Definition of done (v1)

A user can paste a public Python GitHub URL, watch live agent/sandbox logs, and interact with a Gradio demo in an iframe. The demo is generated from real repo functions, validated by Playwright, served through Caddy from a gVisor-isolated container, and torn down automatically — with API keys never entering the sandbox.
