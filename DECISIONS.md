# DECISIONS.md — Agreed technical decisions

Record lasting choices here. Newest first within each section. Link related docs when behavior changes.

Product intent: [PRODUCT.md](PRODUCT.md) · Structure: [ARCHITECTURE.md](ARCHITECTURE.md)

---

## Platform shape

| ID | Decision | Rationale |
|----|----------|-----------|
| D27 | **Two planes:** (1) durable **control plane** (Next.js + agent/harness workers) · (2) **one disposable Microsandbox microVM per job**. There is no separate Explore VM vs Test VM — explore and test share that same sandbox. | Operator choice: same disposable compute for discovery and runtime; avoids dual-VM cost and drift |
| D28 | **Plane 1 owns Jobs API + SSE** (Next.js). It starts the plan loop and launches/destroys the disposable sandbox via the harness. `explore/` is a same-host worker/library under Plane 1, not a disposable VM and not a separate plane. | Durable job state cannot live in an ephemeral sandbox |
| D1 | ~~Three planes: Next.js · Explore Sandbox · Test VM~~ → **superseded by D27** | — |
| D2 | ~~Plane 1 does not run the agent or provision VMs~~ → **superseded by D28** (Plane 1 owns orchestration; browser still must not hold secrets) | — |
| D3 | ~~Plane 2 owns plan loop and harness~~ → **superseded by D28** (plan loop + harness run on the control plane) | — |
| D4 | Disposable Microsandbox per job on Vultr VX1 — **retained**; clarified by D27 that this single sandbox is both explore and test | Ephemeral KVM isolation; destroy on `ready` / cancel / fail / TTL |
| D5 | ~~Primary v1 intents: **`git_mcp` \| `webapp`**; unknown intents blocked/flagged~~ → **superseded by D34** | — |
| D34 | Environment Agent **decides** how to demonstrate the repo. Prefer **`git_mcp`** or **`webapp`** when those fit; otherwise invent a minimal **`demo`** (e.g. serve a lone `.txt` / puzzle as a tiny HTTP page or scripted verify) and put that plan in `environment_profile.json`. Hard-fail only when no verifiable demo can be launched within caps — not merely because the repo is not MCP/webapp. Readiness for `demo` = the profile’s declared probe (typically HTTP 200 or a command exit 0 with logged evidence); still **verifiable execution**, not a chat description. | Operator wants agent judgment: “bring it up somehow” including edge repos |
| D6 | Canonical artifact: **`environment_profile.json`** | Clear handoff from discovery to sandbox provisioning |
| D22 | Plane 2 runtime = **[Microsandbox on Vultr Cloud Compute](https://docs.vultr.com/how-to-set-up-agent-sandboxing-on-vultr-cloud-compute)** (`msb` / SDK over KVM+libkrun) | Official Vultr agent-sandboxing path |
| D24 | **Public / demo control plane** runs on **Vultr Cloud Compute**; local `docker-compose` remains for development only | Vultr is the orchestration fabric, not only sandboxes |

---

## Agent and AI

| ID | Decision | Rationale |
|----|----------|-----------|
| D7 | Agent stack: **OpenCode + Vultr Inference** | Align compute/inference with Vultr footprint |
| D25 | All Environment Agent LLM calls go through **[Vultr Serverless Inference](https://docs.vultr.com/products/serverless/inference/provisioning)** OpenAI-compatible API (`https://api.vultrinference.com/v1`); configure via `VULTR_INFERENCE_BASE_URL` / `VULTR_INFERENCE_API_KEY` / `VULTR_INFERENCE_MODEL` (control plane only) | Mandatory single inference path |
| D8 | Plan loop may draft/validate profile before mutating the sandbox; install/launch require harness + sandbox | Spec first, then mutate remote state |
| D9 | ~~Only supported deps allowlist~~ → **superseded by D29** | — |
| D29 | **No install allowlist in v1.** Any OCI image Microsandbox can boot + any install/run commands from the profile may be attempted; **failures are flagged** (job error / unsupported outcome), not silently invented into success. Still never inject Killhub secrets into the sandbox. | Match “everything Vultr/Microsandbox can run”; honesty over false green |
| D10 | Repair/readiness retries capped by **`MAX_REPAIR_ATTEMPTS`** | Bound cost and infinite loops |
| D11 | Vuln findings are **reported**, not auto-patched; do not hard-fail `ready` by default | Visibility without blocking exploration |
| D33 | **Vulnerability posture in v1:** run **SCA / lockfile / known-advisory scans** and AI `vuln_review` only. **Do not** run active exploits, weaponize CVEs, or pentest the target app. **Containment probes (D26)** prove sandbox isolation and are **not** vuln exploitation of the submitted repo. | Scan + report risk; separate isolation demo from offensive testing |
| D30 | **`git_mcp` readiness** = real **MCP handshake** that can list tools (not merely process-alive or HTTP ping) | Proves the MCP server speaks the protocol |
| D31 | **Screenshots are optional.** Capture when useful (e.g. HTTP webapp verify); skip for CLI-only MCP or early fail. Missing screenshots must **not** block `ready` / terminal states. | Not every job has a meaningful still |

---

## API and realtime

| ID | Decision | Rationale |
|----|----------|-----------|
| D12 | Jobs are **server-owned**; disconnect ≠ cancel | Long pipelines survive tab close; cancel is explicit `DELETE` or timeout |
| D13 | Dual channel: **poll `GET /jobs/{id}` + SSE `/events`** must stay consistent | Robust UI + live updates |
| D14 | SSE types: `status`, `progress`, `log`, `screenshot`, `error` | Uniform event model |
| D15 | Public **HTTPS github.com** URLs only in v1 | Reduce auth and SSRF surface |

---

## Data and storage

| ID | Decision | Rationale |
|----|----------|-----------|
| D16 | v1 job store: **in-memory first**; Redis/Postgres later if needed | Speed to scaffold; schema in [DATABASE.md](DATABASE.md) |
| D17 | Profiles under `storage/profiles/{job_id}/`; screenshots under `storage/screenshots/{job_id}/` | Simple local/dev layout; object storage later via `SCREENSHOT_STORAGE` |
| D18 | Screenshot **stills only** when captured (Playwright browser when HTTP; else terminal stills) — see D31 | Enough audit trail without video cost |

---

## Security

| ID | Decision | Rationale |
|----|----------|-----------|
| D19 | Killhub control-plane secrets **never** injected into sandbox `env` by default | Prevent key exfiltration via untrusted repos |
| D20 | Agent tools may only target harness / sandbox APIs — **never** execute untrusted repo install/run on the control-plane host | Discovery reads via clone/`msb` copy/exec inside the sandbox |
| D21 | Prefer non-root in sandbox; no Docker socket mount from control plane | Reduce breakout risk |
| D23 | Harness drives Plane 2 via **`msb` CLI / Microsandbox SDK** (create / exec / copy / stop / remove); OpenCode may optionally use `microsandbox-mcp` for agent-side tools | Job-owned lifecycle stays in harness; MCP is additive |
| D26 | **Containment proof** is a first-class path: harness (or a demo job mode) must run an adversarial probe inside the sandbox, show absorption via timeout/kill without host impact, stream to logs/SSE, then destroy. This is **not** exploiting the submitted project’s vulns (see D33). | Isolation is only demonstrable if unsafe execution is visible and contained |

---

## v1 golden fixtures (M7)

| ID | Decision | Rationale |
|----|----------|-----------|
| D32 | M7 fixtures (public HTTPS github.com): **(1)** webapp success — [`heroku/node-js-getting-started`](https://github.com/heroku/node-js-getting-started); **(2)** `git_mcp` success — [`modelcontextprotocol/servers`](https://github.com/modelcontextprotocol/servers) (filesystem or everything server via documented launch); **(3)** expected **fail + vulns** — [`OWASP/NodeGoat`](https://github.com/OWASP/NodeGoat) (Mongo-backed; expect readiness fail without durable DB within caps, still emit SCA/vuln findings on best-effort scan) | One green webapp, one green MCP handshake, one honest failure with a vulnerability report |

---

## Explicit non-decisions (open)

- Production DB choice (Postgres vs Redis+blob) when leaving in-memory  
- Object storage vendor for screenshots in prod  
- Exact Next.js ↔ `explore/` process boundary (in-process vs sidecar on same Vultr host) — both allowed under D28  

When these close, add a dated row above and update [DATABASE.md](DATABASE.md) / [API.md](API.md) as needed.
