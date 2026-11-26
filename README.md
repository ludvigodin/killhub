# Killhub

Turn a public GitHub repository into a **verified running environment** — Environment Agent plan, one disposable Microsandbox, readiness checks, and a vulnerability report — without running untrusted code on your laptop.

**Vultr-native agent runtime:** control plane on Vultr Cloud Compute, agent reasoning via [Vultr Serverless Inference](https://docs.vultr.com/products/serverless/inference/provisioning), untrusted execution in [Microsandbox](https://docs.vultr.com/how-to-set-up-agent-sandboxing-on-vultr-cloud-compute) on VX1.

## What it does

Given a public GitHub URL, Killhub:

1. Accepts the link in a Next.js app (input · status · report)
2. Runs an **Environment Agent Plan Loop** on the control plane (OpenCode → Vultr Inference)
3. Writes a structured **`environment_profile.json`** (intent: `git_mcp` or `webapp`)
4. Creates **one disposable Microsandbox** per job (explore + test are the same VM)
5. Attempts install/run from the profile (**no allowlist** — failures are flagged), launches MCP or webapp, verifies **readiness** (MCP handshake listing tools, or HTTP healthcheck)
6. Scans known vulnerabilities (including best-effort on fail paths) and summarizes findings
7. Streams status and progress (screenshots **when useful**, optional)
8. Destroys the sandbox (and can demonstrate a **containment** probe absorbing unsafe commands inside it)

Jobs are **server-owned** by Plane 1. Closing the tab does not cancel. Reopen `/jobs/{id}` to resume. Only explicit cancel or timeout stops a job.

## Architecture

Two planes ([DECISIONS.md](DECISIONS.md) D27–D28):

```
┌─────────────────────────────────────────────────────────────────────────┐
│  PLANE 1 — Control plane (Next.js + explore/ workers)                   │
│  UI · Jobs API/SSE · Environment Agent · harness · vuln review          │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ msb create / exec / destroy
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  PLANE 2 — Disposable Microsandbox (per job on Vultr VX1)               │
│  Same VM for explore + test · clone · install · launch · readiness      │
└─────────────────────────────────────────────────────────────────────────┘
```

**Data flow:** User submits URL → Plane 1 creates job → plan loop emits profile → harness provisions one sandbox → readiness + vuln scan → UI shows profile and report → sandbox destroyed. Killhub secrets never enter the sandbox.

### Golden fixtures (M7)

| Outcome | Repo |
|---------|------|
| `webapp` success | [heroku/node-js-getting-started](https://github.com/heroku/node-js-getting-started) |
| `git_mcp` success | [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) |
| Fail + vulns | [OWASP/NodeGoat](https://github.com/OWASP/NodeGoat) |

## Docs

| Doc | Purpose |
|-----|---------|
| [PRODUCT.md](PRODUCT.md) | What and why |
| [AGENTS.md](AGENTS.md) | Rules every AI agent must follow |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Two planes and boundaries |
| [DECISIONS.md](DECISIONS.md) | Agreed technical decisions |
| [DATABASE.md](DATABASE.md) | Data model and rules |
| [API.md](API.md) | How components communicate |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | Implementation index |
| [IMPLEMENTATION_NEXTJS.md](IMPLEMENTATION_NEXTJS.md) | Plane 1 UI + Jobs API |
| [IMPLEMENTATION_EXPLORE_SANDBOX.md](IMPLEMENTATION_EXPLORE_SANDBOX.md) | Plane 1 agent/harness workers |
| [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md) | Plane 2 disposable Microsandbox |

## Repo structure (planned)

```
killhub/
├── frontend/                 # Plane 1 — Next.js (UI + Jobs API)
├── explore/                  # Plane 1 — agent / harness workers
├── prompts/                  # Agent prompts
├── storage/                  # profiles/ + screenshots/ (dev)
├── PRODUCT.md … API.md       # Canonical product docs
└── README.md
```

Plane 2 is not a checked-in app folder — it is an ephemeral Microsandbox microVM per job on a Vultr VX1 host.

## Quick start

1. Read [PRODUCT.md](PRODUCT.md) and [ARCHITECTURE.md](ARCHITECTURE.md)
2. Follow [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)
3. When compose lands: Plane 1 boots locally; Plane 2 is harness-provisioned at job time on VX1

## Demo / deploy (Vultr)

| Piece | Requirement |
|-------|-------------|
| Plane 1 | Deploy on **Vultr Cloud Compute**; public HTTPS demo URL |
| Inference | `https://api.vultrinference.com/v1` via `VULTR_INFERENCE_*` |
| Plane 2 | Microsandbox on Vultr VX1 (`MSB_HOST`); one sandbox per job |
| Containment | Record a moment where the sandbox absorbs something unsafe, then destroy |
| Local | `docker-compose` for Plane 1 during development |

## API

Jobs API is **owned by Plane 1** (Next.js). Full contracts: [API.md](API.md).

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/jobs` | Create job `{ github_url }` → `{ job_id }` |
| `GET` | `/api/jobs/{id}` | Snapshot |
| `GET` | `/api/jobs/{id}/events` | SSE |
| `GET` | `/api/jobs/{id}/screenshots` | Timeline (may be empty) |
| `DELETE` | `/api/jobs/{id}` | Cancel + destroy sandbox |
| `GET` | `/health` | Control-plane liveness |

### Job states

```
pending → analyzing → planning → provisioning → installing
       → verifying ⇄ repairing
       → scanning → ready | failed | cancelled
```

Repair loop capped by `MAX_REPAIR_ATTEMPTS`, then `failed`.

## Configuration

| Variable | Plane | Purpose |
|----------|------:|---------|
| `VULTR_API_KEY` | 1 | VX1 host ops (never injected into sandboxes) |
| `VULTR_INFERENCE_BASE_URL` | 1 | Default `https://api.vultrinference.com/v1` |
| `VULTR_INFERENCE_API_KEY` | 1 | Serverless Inference |
| `VULTR_INFERENCE_MODEL` | 1 | Model id |
| `OPENCODE_*` | 1 | Agent harness (must use Vultr Inference) |
| `MSB_HOST` / image / CPU·memory | 1→2 | Microsandbox defaults |
| `JOB_TIMEOUT_SECONDS` | 1 | Wall clock |
| `MAX_REPAIR_ATTEMPTS` | 1 | Plan-loop / readiness cap |
| `ENV_TTL_SECONDS` | 2 | Auto-destroy sandbox |
| `VULN_SCAN_*` / `MAX_SCREENSHOTS_PER_JOB` | 1 | Scan + screenshot caps |

## Security

- Untrusted repo code runs only on **Plane 2**, never as privileged control-plane host processes
- `VULTR_API_KEY` / `VULTR_INFERENCE_*` / `OPENCODE_*` stay on Plane 1 server; not injected into the sandbox by default
- Public HTTPS `github.com` URLs only in v1
- Destroy sandboxes on `ready` / cancel / failure / `ENV_TTL_SECONDS`
- Containment probes run only inside Plane 2 and must be visible in the job log before destroy

## Out of scope (v1)

- Private GitHub repos / OAuth · multi-user auth / billing
- Long-lived customer sandboxes beyond TTL · GPU · auto-patch CVEs
- Non-Vultr clouds · alternate agent LLM providers · session video
- Separate Explore VM vs Test VM · install allowlist

## Roadmap

| Milestone | Goal |
|-----------|------|
| **M0** | Compose boots Plane 1 |
| **M1** | Jobs API + SSE on Plane 1 |
| **M2** | Harness create / exec / destroy Microsandbox |
| **M3** | Plan loop → valid `environment_profile.json` |
| **M4** | Install + MCP/HTTP readiness on sandbox |
| **M5** | Optional screenshots when useful |
| **M6** | Vuln report (incl. fail path) |
| **M7** | Golden fixtures (D32) + isolation + TTL cleanup |

## Definition of done (v1)

A user can paste a public GitHub URL in Plane 1 and, without refreshing, see live status/progress, `environment_profile.json`, and a vuln report while the plan loop drives a single Plane 2 Microsandbox — with Killhub secrets never entering the sandbox, screenshots optional, containment absorbed in Plane 2, and sandboxes torn down after TTL or cancel.
