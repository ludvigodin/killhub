# Plane 1 workers — Environment Agent + harness (`explore/`)

Implementation plan for the Environment Agent Plan Loop, job worker orchestration, harness control of the **single disposable Microsandbox**, screenshots, and vulnerability review.

These workers are **Plane 1** (control plane), not a disposable VM ([DECISIONS.md](DECISIONS.md) D27–D28). Public Jobs API/SSE are owned by Next.js; `explore/` updates job state as a same-host worker/library.

Architecture: [ARCHITECTURE.md](ARCHITECTURE.md) · Index: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) · UI/API: [IMPLEMENTATION_NEXTJS.md](IMPLEMENTATION_NEXTJS.md) · Sandbox: [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md)

---

## Role

```
IN:  Git repo URL (job)
       │
       ▼
Environment Agent Plan Loop
  1. Inspect repo and docs          → via same disposable sandbox
  2. Infer required services
  3. Validate environment and spec
  4. Provision deps                 → harness → Plane 2
  5. Launch chosen target + ready   → harness → Plane 2
       │
       ▼
OUT: environment_profile.json + readiness/failure + vuln report
```

| | |
|--|--|
| **IN** | Git repository URL |
| **Agent** | Environment Agent Plan Loop (OpenCode → Vultr Inference) |
| **Decide intent** | Prefer `git_mcp` \| `webapp`; else invent `demo` (D34) |
| **OUT** | `environment_profile.json` + readiness (or flagged failure) |

Explore and test share **one** microVM per job.

---

## Repo layout

```
explore/
├── main.py                 # Worker entry (optional local /health for compose)
├── discover.py             # Environment Agent Plan Loop
├── agent.py                # OpenCode + Vultr Inference
├── harness.py              # Control surface → Plane 2
├── profile.py              # environment_profile.json schema + IO
├── verify.py               # Readiness probes (MCP handshake / HTTP)
├── vulnscan.py
├── screenshots.py          # Optional captures
├── jobs.py                 # Job store + events (consumed by Next.js API)
├── config.py
├── models.py
└── requirements.txt

prompts/
├── discover_environment.md
├── validate_environment_spec.md
├── repair_from_errors.md
└── vuln_review.md

storage/
├── screenshots/{job_id}/
└── profiles/{job_id}/environment_profile.json
```

---

## Job states

```
pending → analyzing → planning → provisioning → installing
       → verifying ⇄ repairing
       → scanning → ready | failed | cancelled
```

- Steps 1–3 ≈ `analyzing` / `planning`
- Steps 4–5 ≈ `provisioning` → `verifying` (with `repairing`)
- Then `scanning` → terminal

Repair capped by `MAX_REPAIR_ATTEMPTS`. Jobs server-owned on Plane 1.

SSE types: `status` · `progress` · `log` · `screenshot` · `error`

---

## `environment_profile.json`

```json
{
  "intent": "git_mcp",
  "source": {
    "type": "git",
    "url": "https://github.com/org/repo",
    "ref": "main"
  },
  "runtime": "node",
  "os_image": "ubuntu-24.04",
  "oci_image": "node:22-bookworm",
  "services": [],
  "packages": [],
  "install_commands": [],
  "run_commands": [],
  "mcp": {
    "launch_command": "",
    "readiness": { "type": "mcp_handshake", "timeout_seconds": 60 }
  },
  "healthcheck": { "type": "http", "path": "/", "port": 8000 },
  "ports": [8000],
  "summary": "..."
}
```

---

## Implementation phases

### E0 — Scaffold

- [ ] Scaffold `explore/` worker with local health for compose
- [ ] `docker-compose.yml` service `explore` (same network as frontend)
- [ ] `.env.example`: `VULTR_API_KEY`, `VULTR_INFERENCE_*`, `OPENCODE_*`, timeouts, caps
- [ ] Empty `jobs.py` / `models.py` / `config.py`

**Done when:** Worker boots; can be reached by Next.js on the same host.

### E1 — Job store + events

- [ ] In-memory job store; background worker per job
- [ ] Validate GitHub URL (public HTTPS, `github.com` only)
- [ ] Wire store so Next.js Jobs API can create/poll/SSE/cancel
- [ ] Persist profile, readiness, vuln_report, screenshots[], `sandbox_id`, `inference_model`, `destroyed_at`

**Done when:** Plane 1 API can create a job and stream stub events.

### E2 — Plan loop (steps 1–3)

- [ ] Wire OpenCode → **Vultr Serverless Inference** (D25); fail closed if not Vultr
- [ ] Persist `inference_model` on the job
- [ ] `discover.py`: inspect → infer → validate (inspect via sandbox clone/copy/exec — not privileged host exec of untrusted install)
- [ ] `profile.py` schema + `storage/profiles/{job_id}/`
- [ ] Prompts: discover + validate
- [ ] Intent: `git_mcp` \| `webapp` \| `demo` (agent decides; D34)
- [ ] **No install allowlist** (D29) — profile may contain any OCI/install/run Microsandbox can attempt; invalid/incomplete profile still blocks step 4
- [ ] Cap turns / tokens / wall-clock
- [ ] Stream steps to job events

**Done when:** Golden webapp + MCP fixtures emit valid profiles; inference hits Vultr only.

### E3 — Harness (steps 4–5)

Depends on [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md).

- [ ] `harness.py`: create / wait / exec / copy / destroy (one sandbox per job)
- [ ] Map profile → OCI image + CPU/memory
- [ ] Record `sandbox_id`; emit create/destroy logs
- [ ] Clone + **attempt** install/run from profile; **flag failures** (do not invent success)
- [ ] Launch chosen target; `verify.py`:
  - `git_mcp` → MCP handshake that **lists tools** (D30)
  - `webapp` / `demo` → profile probe (typically HTTP)
- [ ] Repair within `MAX_REPAIR_ATTEMPTS`; log attempt number
- [ ] **Containment probe** (D26) inside Plane 2 only — adversarial cmd / loop absorbed by timeout/kill; stream `log.kind=containment_probe`; **not** exploiting the submitted repo (D33)
- [ ] Set `destroyed_at` on remove; do not mark `ready` until readiness passes (scan still E5)

**Done when:** Getting-started webapp and MCP servers fixture pass readiness; NodeGoat path fails honestly with logged errors; containment probe visible as isolation proof only.

### E4 — Optional screenshots

- [ ] `screenshots.py`: browser (Playwright) when HTTP verify; terminal stills when useful
- [ ] **Skip** when not relevant (CLI-only MCP, early fail) — never block `ready` (D31)
- [ ] Emit SSE `screenshot` only when captured; cap `MAX_SCREENSHOTS_PER_JOB`; redact secrets

**Done when:** HTTP webapp verify can attach a browser still; MCP-only jobs can complete with empty timeline.

### E5 — Vulnerability scanning (scan + report only)

**In scope:** SCA / lockfile / known-advisory scanners + AI `vuln_review`.  
**Out of scope:** active exploits, weaponizing CVEs, or pentesting the submitted app ([DECISIONS.md](DECISIONS.md) D11, D33).

- [ ] `vulnscan.py` against sandbox / lockfiles / detected stack (advisory databases only)
- [ ] `vuln_review.md` AI summary → job `vuln_report` for Plane 1 report UI
- [ ] Persist severity-grouped `VulnFinding[]`; emit progress via SSE
- [ ] Best-effort scan on **failure** paths (NodeGoat must still produce **scan** findings)
- [ ] Findings do not hard-fail `ready` by default (D11); scan tool crash → `partial` / `failed` report without erasing readiness
- [ ] **Do not** add exploit PoCs, payload runners, or offensive probe suites against the target app
- [ ] On `ready` (and on terminal fail after scan policy): destroy sandbox; artifacts stay on Plane 1

**Done when:** At least one stack produces real advisories or a clean bill; NodeGoat fail path still has a scan-based vuln report; no exploit tooling in the pipeline; sandbox gone after terminal state.

### E6 — Orchestration hardening

- [ ] Single pipeline wiring E1–E5
- [ ] Chaos: bad URL, install failure, repair cap, cancel, containment
- [ ] Golden fixtures E2E (D32)
- [ ] No Killhub secrets in sandbox env/logs/screenshots
- [ ] Deploy with frontend on Vultr Cloud Compute (D24)

**Done when:** D32 fixtures behave as specified; TTL/cancel always destroy sandbox.

---

## Configuration

| Variable | Purpose |
|----------|---------|
| `VULTR_API_KEY` | VX1 host ops (never in sandboxes) |
| `VULTR_INFERENCE_BASE_URL` | Default `https://api.vultrinference.com/v1` |
| `VULTR_INFERENCE_API_KEY` | Serverless Inference |
| `VULTR_INFERENCE_MODEL` | Model id |
| `OPENCODE_*` | Agent client → Vultr Inference |
| `JOB_TIMEOUT_SECONDS` | Wall clock |
| `MAX_REPAIR_ATTEMPTS` | Retry cap |
| `VULN_SCAN_*` | Scanner settings |
| `MAX_SCREENSHOTS_PER_JOB` | Cap |
| `SCREENSHOT_STORAGE` | Artifact store |
| `MSB_HOST` / image / CPU·memory | Harness defaults |

---

## Milestones

- [ ] **E-M0:** Worker boots
- [ ] **E-M1:** Job store drives Plane 1 API/SSE
- [ ] **E-M2:** Plan loop → valid profile via Vultr Inference
- [ ] **E-M3:** Readiness via harness + containment probe logged
- [ ] **E-M4:** Optional screenshots when useful
- [ ] **E-M5:** Vuln **scan** report (incl. fail path); no exploits
- [ ] **E-M5b:** Containment probe logged (isolation only)
- [ ] **E-M6:** D32 fixtures + cleanup; Vultr demo deploy

---

## Security

- Secrets stay on Plane 1 server — **not** injected into Plane 2 by default
- Agent tools only use harness / sandbox APIs
- Attempt any Microsandbox-bootable OCI + install commands; flag failures (D29)
- Containment probes only inside Plane 2 (D26) — isolation proof, not app pentest
- Vuln path is **scan + report only** (D33)

---

## Out of scope

- Next.js UI components
- VX1 `msb` install details beyond harness contract
- Non-Vultr inference providers
- Active exploits / pentest of submitted projects

---

## Definition of done

Given a GitHub URL job, the plan loop (Vultr Inference) produces a validated profile, drives **one** Plane 2 sandbox through install + MCP/HTTP readiness, streams status (optional screenshots), attaches a **scan-based** vuln report (including fail paths), optionally proves containment, and destroys the sandbox on terminal states — without leaking Killhub secrets or running exploits against the target app.
