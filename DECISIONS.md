# DECISIONS.md — Agreed technical decisions

Record lasting choices here. Newest first within each section. Link related docs when behavior changes.

Product intent: [PRODUCT.md](PRODUCT.md) · Structure: [ARCHITECTURE.md](ARCHITECTURE.md)

---

## Platform shape

| ID | Decision | Rationale |
|----|----------|-----------|
| D1 | **Three planes:** Next.js · Explore Sandbox · Test VM | Hard isolation between UI, agent/orchestration, and untrusted runtime |
| D2 | Plane 1 is **Next.js (UI + server)**; it does not run the agent or provision VMs | Keeps browser/server UX thin; all intelligence in Plane 2 |
| D3 | Plane 2 owns the **Environment Agent Plan Loop** and harness | Single place for inspect → infer → validate → provision → launch/readiness |
| D4 | Plane 3 is a **disposable Microsandbox microVM per job** on a Vultr VX1 host, not a checked-in app | Ephemeral KVM isolation; destroy when the agent finishes instructions + all tests (`ready`), or on cancel/fail/TTL (host may be pooled) |
| D5 | Primary v1 intents: **`git_mcp` \| `webapp`** | Focused classification; unknown intents blocked/flagged |
| D6 | Canonical artifact: **`environment_profile.json`** | Clear handoff from discovery to Test VM provisioning |
| D22 | Plane 3 runtime = **[Microsandbox on Vultr Cloud Compute](https://docs.vultr.com/how-to-set-up-agent-sandboxing-on-vultr-cloud-compute)** (`msb` / SDK over KVM+libkrun) | Official Vultr agent-sandboxing path; separate kernel per sandbox, CPU/memory caps, inter-sandbox network deny-by-default — stronger than shared-kernel containers |

---

## Agent and AI

| ID | Decision | Rationale |
|----|----------|-----------|
| D7 | Agent stack: **OpenCode + Vultr Inference** | Align compute/inference with Vultr footprint |
| D8 | Plan loop steps 1–3 can run before Plane 3 exists; steps 4–5 require harness + VM | Spec first, then mutate remote state |
| D9 | Only **supported** deps are provisioned; unsupported are recorded | Prevents silent invention of unsafe/unknown services |
| D10 | Repair/readiness retries capped by **`MAX_REPAIR_ATTEMPTS`** | Bound cost and infinite loops |
| D11 | Vuln findings are **reported**, not auto-patched; do not hard-fail `ready` by default | Visibility without blocking exploration |

---

## API and realtime

| ID | Decision | Rationale |
|----|----------|-----------|
| D12 | Jobs are **server-owned**; disconnect ≠ cancel | Long pipelines survive tab close; cancel is explicit `DELETE` or timeout |
| D13 | Dual channel: **poll `GET /jobs/{id}` + SSE `/events`** must stay consistent | Robust UI + live updates |
| D14 | SSE types: `status`, `progress`, `log`, `screenshot`, `error` | Uniform event model for Plane 1 |
| D15 | Public **HTTPS github.com** URLs only in v1 | Reduce auth and SSRF surface |

---

## Data and storage

| ID | Decision | Rationale |
|----|----------|-----------|
| D16 | v1 job store: **in-memory first**; Redis/Postgres later if needed | Speed to scaffold; schema documented in [DATABASE.md](DATABASE.md) |
| D17 | Profiles under `storage/profiles/{job_id}/`; screenshots under `storage/screenshots/{job_id}/` | Simple local/dev layout; object storage later via `SCREENSHOT_STORAGE` |
| D18 | Screenshot **stills only** (Playwright browser when HTTP; else terminal stills) | Enough audit trail without video cost |

---

## Security

| ID | Decision | Rationale |
|----|----------|-----------|
| D19 | Killhub control-plane secrets **never** injected into Test VM `env` by default | Prevent key exfiltration via untrusted repos |
| D20 | Agent tools may only target Explore Sandbox + Test VM harness APIs | No privileged exec of untrusted code on Plane 1 |
| D21 | Prefer non-root on Test VM; no Docker socket mount from control plane | Reduce breakout risk |
| D23 | Harness drives Plane 3 via **`msb` CLI / Microsandbox SDK** (create / exec / copy / stop / remove); OpenCode may optionally use `microsandbox-mcp` for agent-side tools | Job-owned lifecycle stays in `harness.py`; MCP is additive, not a substitute for ready/cancel/fail/TTL destroy |

---

## Explicit non-decisions (open)

- Production DB choice (Postgres vs Redis+blob) when leaving in-memory  
- Exact supported-deps allowlist contents  
- Object storage vendor for screenshots in prod  

When these close, add a dated row above and update [DATABASE.md](DATABASE.md) / [API.md](API.md) as needed.
