# Plane 2 — Explore Sandbox

Implementation plan for the Environment Agent Plan Loop, job orchestration, harness control of the Test VM, screenshots, and vulnerability review. Plane 2 is the only plane that talks to Plane 3. It reports status to Plane 1.

Architecture: [ARCHITECTURE.md](ARCHITECTURE.md) · Index: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) · Plane 1: [IMPLEMENTATION_NEXTJS.md](IMPLEMENTATION_NEXTJS.md) · Plane 3: [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md)

---

## Role

```
IN:  Git repo
       │
       ▼
Environment Agent Plan Loop
  1. Inspect repo and docs
  2. Infer required services
  3. Validate environment and spec
  4. Provision supported deps          → via harness on Plane 3
  5. Launch MCP and verify readiness   → via harness on Plane 3
       │
       ▼
OUT: environment_profile.json + readiness
     (+ status / progress / screenshots / vuln report → Plane 1)
```

| | |
|--|--|
| **IN** | Git repository or package |
| **Agent** | Environment Agent Plan Loop |
| **Classify intent** | `git_mcp` \| `webapp` |
| **OUT** | `environment_profile.json` + readiness |

---

## Repo layout (this plane)

```
explore/
├── main.py                 # API / worker entry
├── discover.py             # Environment Agent Plan Loop
├── agent.py                # OpenCode + Vultr Inference
├── harness.py              # Control surface → Plane 3 (see Test VM doc)
├── profile.py              # environment_profile.json schema + IO
├── verify.py               # Readiness probes (MCP / HTTP)
├── vulnscan.py
├── screenshots.py
├── jobs.py                 # Job store + SSE events
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

## Job system (API offered to Plane 1)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/jobs` | Create job `{ github_url }` → `{ job_id }` |
| `GET` | `/api/jobs/{id}` | Full snapshot |
| `GET` | `/api/jobs/{id}/events` | SSE |
| `GET` | `/api/jobs/{id}/screenshots` | Timeline |
| `GET` | `/api/jobs/{id}/screenshots/{shot_id}` | Image |
| `DELETE` | `/api/jobs/{id}` | Cancel + destroy Test VM |
| `GET` | `/health` | Liveness |

### Job states

```
pending → analyzing → planning → provisioning → installing
       → verifying ⇄ repairing
       → scanning → ready | failed | cancelled
```

- Steps 1–3 of the plan loop ≈ `analyzing` / `planning`
- Steps 4–5 ≈ `provisioning` → `verifying` (with `repairing` loop)
- Then `scanning` → `ready`

Repair / plan-loop retry capped by `MAX_REPAIR_ATTEMPTS`. Jobs are server-owned; only `DELETE` or `JOB_TIMEOUT_SECONDS` cancels.

### SSE event types

`status` · `progress` · `log` · `screenshot` · `error`

---

## `environment_profile.json`

Illustrative shape (validated in step 3 before steps 4–5):

```json
{
  "intent": "git_mcp",
  "source": {
    "type": "git",
    "url": "https://github.com/org/repo",
    "ref": "main"
  },
  "runtime": "python",
  "os_image": "ubuntu-24.04",
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

- [ ] Scaffold `explore/` service with `GET /health`
- [ ] `docker-compose.yml` service `explore`
- [ ] `.env.example`: `VULTR_API_KEY`, `VULTR_INFERENCE_*`, `OPENCODE_*`, timeouts, caps
- [ ] Empty `jobs.py` / `models.py` / `config.py`

**Done when:** `explore` boots; `/health` returns `200`.

### E1 — Job store + SSE

- [ ] In-memory job store; background worker per job
- [ ] Validate GitHub URL (public HTTPS, `github.com` only)
- [ ] Implement API surface above; SSE with reconnect / event-id catch-up
- [ ] On every state change: update `status` + `progress` + `current_step`; emit events
- [ ] Persist profile, readiness, vuln_report, screenshots[], `sandbox_id`, `inference_model`, `destroyed_at` on the job

**Done when:** Plane 1 can create a job, poll status, and subscribe to stub SSE events.

### E2 — Environment Agent Plan Loop (steps 1–3)

- [ ] Wire OpenCode → **Vultr Serverless Inference** in `agent.py` (`VULTR_INFERENCE_BASE_URL` default `https://api.vultrinference.com/v1`, API key, model) — [DECISIONS.md](DECISIONS.md) D25
- [ ] Refuse / fail closed if inference is not configured for Vultr (no silent alternate provider)
- [ ] Persist `inference_model` on the job for Plane 1 / demo evidence
- [ ] `discover.py` state machine: inspect → infer → validate
- [ ] `profile.py` schema validation + `storage/profiles/{job_id}/`
- [ ] Prompts: `discover_environment.md`, `validate_environment_spec.md`
- [ ] Intent: `git_mcp` \| `webapp` only in v1 (hackathon slice may ship one intent first)
- [ ] Supported-deps allowlist; unsupported services recorded, not invented
- [ ] Cap turns / tokens / wall-clock for discovery
- [ ] Stream each step to SSE; attach profile to job for Plane 1 report window
- [ ] Invalid profile blocks step 4 with clear `error` event

**Done when:** Fixture webapp and MCP repos emit valid `environment_profile.json` with correct intent; inference calls hit Vultr only.

### E3 — Harness integration (steps 4–5)

Depends on Plane 3 APIs documented in [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md).

- [ ] `harness.py` calls: create / wait / exec / copy / destroy Microsandbox (Plane 3)
- [ ] Map profile → OCI image + CPU/memory (`msb` / SDK on Vultr VX1)
- [ ] Record `sandbox_id` / environment ref on the job; emit SSE `log` on create and destroy
- [ ] Clone + install **supported** deps only from profile
- [ ] Launch MCP or webapp; readiness via `verify.py`
- [ ] On failure: `repair_from_errors.md`; re-enter plan loop within `MAX_REPAIR_ATTEMPTS`; log attempt number in SSE
- [ ] **Containment probe** ([D26](DECISIONS.md)): run adversarial command/loop inside Plane 3, capture timeout/kill, stream to Plane 1, then continue or destroy — never on Plane 1/2 host
- [ ] Record `verify_result` / `readiness` on the job; set `destroyed_at` when sandbox is removed
- [ ] Do not mark `ready` until readiness passes (scan still required — E5)

**Done when:** Deps → launch → readiness green for one fixture; failed readiness retries once; containment probe visible in logs; sandbox destroy recorded.

### E4 — Process screenshots

- [ ] `screenshots.py`: `capture_browser` (Playwright), `capture_terminal`
- [ ] Capture on plan-loop transitions, provision, launch, readiness pass/fail, scan
- [ ] Emit SSE `screenshot` events; store under `storage/screenshots/{job_id}/`
- [ ] Cap `MAX_SCREENSHOTS_PER_JOB`; redact secrets; TTL cleanup with job

**Done when:** Successful job has ≥1 screenshot per major stage; HTTP verify yields browser shot.

### E5 — Vulnerability scanning

- [ ] `vulnscan.py` against detected stack on Test VM / lockfiles
- [ ] `vuln_review.md` for AI summary → Plane 1 report
- [ ] Persist `VulnFinding[]`; emit progress via SSE
- [ ] Scan tool crash → `partial` / `failed` report without erasing readiness
- [ ] Job → `ready` when readiness passed and scan finished (findings do not hard-fail by default)
- [ ] On `ready`: harness destroys the Test VM immediately (report artifacts stay on Plane 2)

**Done when:** At least one stack produces real advisories or a clean bill; UI can show severity groups; sandbox is gone after `ready`.

### E6 — Orchestration hardening

- [ ] Single pipeline in `main.py` / `jobs.py` wiring E1–E5
- [ ] Chaos: bad URL, install failure, agent loop prevention, mid-job cancel, containment probe
- [ ] Assert SSE order for happy path (including create → probe/retry → destroy)
- [ ] No Killhub secrets in Test VM env, logs, or screenshots
- [ ] Cleanup profiles/screenshots with job TTL
- [ ] Deploy Explore with Plane 1 on Vultr Cloud Compute for public demo (D24)

**Done when:** Three public repos reach `ready` with profile, readiness, vulns, and screenshot timeline; demo deploy uses Vultr Inference + Microsandbox only.

---

## Configuration (Plane 2)

| Variable | Purpose |
|----------|---------|
| `VULTR_API_KEY` | VX1 host ops (never injected into sandboxes) |
| `VULTR_INFERENCE_BASE_URL` | Default `https://api.vultrinference.com/v1` |
| `VULTR_INFERENCE_API_KEY` | Serverless Inference (Plane 2 only) |
| `VULTR_INFERENCE_MODEL` | Model id from Vultr model list |
| `OPENCODE_*` | Agent client (must target Vultr Inference) |
| `JOB_TIMEOUT_SECONDS` | Hard wall clock |
| `MAX_REPAIR_ATTEMPTS` | Plan-loop / readiness retry cap |
| `VULN_SCAN_*` | Scanner settings |
| `MAX_SCREENSHOTS_PER_JOB` | Screenshot cap |
| `SCREENSHOT_STORAGE` | Artifact store |
| `MSB_HOST` / `MSB_DEFAULT_IMAGE` / CPU·memory | Harness → Microsandbox defaults |

---

## Milestones (Plane 2)

- [ ] **E-M0:** Explore service boots
- [ ] **E-M1:** Jobs API + SSE stubs
- [ ] **E-M2:** Plan loop steps 1–3 → valid profile via Vultr Inference
- [ ] **E-M3:** Steps 4–5 readiness green via harness + containment probe logged
- [ ] **E-M4:** Screenshots streamed to Plane 1
- [ ] **E-M5:** Vuln report attached
- [ ] **E-M6:** Three-repo E2E + cleanup; Vultr public control-plane deploy

---

## Security

- Inference / API secrets stay in Plane 2 — **not** injected into Test VM by default
- Agent tools only use Explore Sandbox + harness APIs (never Plane 1 host shell)
- Only **supported** deps provisioned on Plane 3
- All agent LLM calls via Vultr Serverless Inference (D25); containment probes only inside Plane 3 (D26)

---

## Out of scope (this plane)

- Next.js UI components (Plane 1)
- VX1 host bootstrap / `msb` install details beyond harness contract (Plane 3 doc)
- Non-Vultr inference providers for the Environment Agent

---

## Definition of done (Plane 2)

Given a GitHub URL job from Plane 1, the Environment Agent Plan Loop (Vultr Inference) produces a validated `environment_profile.json`, drives Plane 3 through supported deps + MCP/app readiness, streams status/screenshots/sandbox lifecycle (including a containment probe when enabled), attaches a vuln report, and destroys the Test VM when instructions and all tests complete (`ready`) — or on cancel/fail/TTL — without leaking Killhub secrets.
