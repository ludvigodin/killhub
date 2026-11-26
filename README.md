# Killhub

Turn a public GitHub repository into a **verified running environment** — Environment Agent plan, disposable Test VM, readiness checks, and a vulnerability report — without running untrusted code on your laptop.

## What it does

Given a public GitHub URL, Killhub:

1. Accepts the link in a Next.js app (input · status · report)
2. Runs an **Environment Agent Plan Loop** in the Explore Sandbox
3. Writes a structured **`environment_profile.json`** (intent: `git_mcp` or `webapp`)
4. Creates a disposable **Test VM** (Microsandbox microVM on Vultr VX1) from that profile
5. Installs supported deps, launches MCP or webapp, and verifies **readiness** (capped repair loop)
6. Scans known vulnerabilities and summarizes findings
7. Streams status, progress, screenshots, profile, and reports back to the UI

Jobs are **server-owned**. Closing the tab or dropping the SSE connection does not cancel the pipeline. Reopen `/jobs/{id}` to resume status and logs. Only an explicit cancel or timeout stops a job.

## Architecture

Three planes with hard boundaries:

```
┌─────────────────────────────────────────────────────────────────────────┐
│  PLANE 1 — Frontend + Server (Next.js)                                  │
│  Input window · status · progress · screenshots · setup docs · report   │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ jobs API · SSE (status / progress / shots)
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  PLANE 2 — Explore Sandbox                                              │
│  Environment Agent Plan Loop → environment_profile.json                 │
│  inspect → infer → validate → provision deps → launch / readiness       │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ profile + harness → provision · exec
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  PLANE 3 — Test VM (Microsandbox microVM on Vultr VX1)                  │
│  Created from environment_profile.json · deps · MCP / app readiness     │
└─────────────────────────────────────────────────────────────────────────┘
```

**Data flow:** User submits URL → job created → plan loop emits profile → harness provisions Test VM → readiness + vuln scan → UI shows profile, screenshots, and report. Killhub secrets never enter the Test VM.

## Docs

| Doc | Purpose |
|-----|---------|
| [PRODUCT.md](PRODUCT.md) | What and why |
| [AGENTS.md](AGENTS.md) | Rules every AI agent must follow |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Three planes and boundaries |
| [DECISIONS.md](DECISIONS.md) | Agreed technical decisions |
| [DATABASE.md](DATABASE.md) | Data model and rules |
| [API.md](API.md) | How components communicate |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | Implementation index by plane |
| [IMPLEMENTATION_NEXTJS.md](IMPLEMENTATION_NEXTJS.md) | Plane 1 |
| [IMPLEMENTATION_EXPLORE_SANDBOX.md](IMPLEMENTATION_EXPLORE_SANDBOX.md) | Plane 2 |
| [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md) | Plane 3 |

## Repo structure (planned)

```
killhub/
├── frontend/                 # Plane 1 — Next.js
├── explore/                  # Plane 2 — jobs API, agent, harness
├── prompts/                  # Agent prompts
├── storage/                  # profiles/ + screenshots/ (dev)
├── PRODUCT.md … API.md       # Canonical product docs
└── README.md
```

Plane 3 is not a checked-in app folder — it is an ephemeral Microsandbox microVM created per job on a Vultr VX1 host.

## Quick start

Docs-first for now: product and plane docs are the source of truth while code is scaffolded.

1. Read [PRODUCT.md](PRODUCT.md) and [ARCHITECTURE.md](ARCHITECTURE.md)
2. Follow plane work in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)
3. When compose lands: Plane 1 + Plane 2 boot together; Plane 3 is harness-provisioned at job time

## API

Jobs API is offered by Plane 2; Plane 1 proxies/consumes it. Full contracts: [API.md](API.md).

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/jobs` | Create job `{ github_url }` → `{ job_id }` |
| `GET` | `/api/jobs/{id}` | Snapshot (status, profile, readiness, vulns, screenshots) |
| `GET` | `/api/jobs/{id}/events` | SSE: `status` · `progress` · `log` · `screenshot` · `error` |
| `GET` | `/api/jobs/{id}/screenshots` | Screenshot timeline |
| `DELETE` | `/api/jobs/{id}` | Cancel + destroy Test VM |
| `GET` | `/health` | Plane 2 liveness |

### Job states

```
pending → analyzing → planning → provisioning → installing
       → verifying ⇄ repairing
       → scanning → ready | failed | cancelled
```

Repair loop: `verifying → repairing → verifying`, capped by `MAX_REPAIR_ATTEMPTS`, then `failed`.

## Configuration

Cross-cutting env (details in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)):

| Variable | Plane | Purpose |
|----------|------:|---------|
| `EXPLORE_SANDBOX_URL` | 1 | Plane 1 → Plane 2 |
| `VULTR_API_KEY` | 2 | Inference + VX1 host ops (never injected into sandboxes) |
| `OPENCODE_*` | 2 | Agent harness |
| `MSB_HOST` / image / CPU·memory | 2→3 | Microsandbox defaults |
| `JOB_TIMEOUT_SECONDS` | 2 | Wall clock |
| `MAX_REPAIR_ATTEMPTS` | 2 | Plan-loop / readiness cap |
| `ENV_TTL_SECONDS` | 3 | Auto-destroy sandbox |
| `VULN_SCAN_*` / `MAX_SCREENSHOTS_PER_JOB` | 2 | Scan + screenshot caps |

## Security

- Untrusted repo code runs on **Plane 3** (or tightly scoped Explore discovery), never as privileged Plane 1 server code
- `VULTR_API_KEY` / `OPENCODE_*` stay on Plane 2; they are not injected into the Test VM by default
- Public HTTPS `github.com` URLs only in v1; others rejected with `400`
- Destroy sandboxes when the agent finishes instructions and all tests (`ready`), or on cancel, failure, or `ENV_TTL_SECONDS`
- Prefer non-root in the sandbox; no Docker socket mount from the control plane

## Out of scope (v1)

- Private GitHub repos / OAuth
- Multi-user auth / billing
- Long-lived Test VMs beyond TTL
- GPU workloads
- Auto-patching vulnerabilities (report only)
- Non-Vultr Test VM providers
- Full session video (stills only)

## Roadmap

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for phased tasks and plane docs.

| Milestone | Goal |
|-----------|------|
| **M0** | Compose boots Plane 1 + Plane 2 |
| **M1** | Jobs API + SSE reach Plane 1 |
| **M2** | Harness provisions / execs / destroys a Test VM |
| **M3** | Plan loop emits valid `environment_profile.json` (`git_mcp` \| `webapp`) |
| **M4** | Supported deps + MCP/app readiness green on Test VM |
| **M5** | Screenshots live in Plane 1 |
| **M6** | Vuln report in Plane 1 report window |
| **M7** | Three public repos end-to-end; isolation + TTL cleanup verified |

## Definition of done (v1)

A user can paste a public GitHub URL in Plane 1 and, without refreshing, see live status/progress, screenshots, `environment_profile.json`, and a vuln report while Plane 2’s plan loop drives a Plane 3 Microsandbox microVM — with Killhub secrets never entering the sandbox or screenshots, and sandboxes/artifacts torn down after TTL or cancel.
