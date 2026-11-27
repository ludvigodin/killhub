# Plane 1 workers — Environment Agent + harness (`explore/`)

Implementation plan for the Environment Agent Plan Loop, job worker orchestration, harness control of the **single disposable Microsandbox**, screenshots, and vulnerability review.

These workers are **Plane 1** (control plane), not a disposable VM ([DECISIONS.md](DECISIONS.md) D27–D28). Public Jobs API/SSE are owned by Next.js as a **proxy**; `explore/` is the **Python sidecar that owns the durable ledger** and Internal Worker API (D52).

Architecture: [ARCHITECTURE.md](ARCHITECTURE.md) · Index: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) · UI/API: [IMPLEMENTATION_NEXTJS.md](IMPLEMENTATION_NEXTJS.md) · Sandbox: [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md)

---

## Role

```
IN:  Git repo URL (job)
       │
       ▼
Environment Agent Plan Loop
  −1. Pre-flight (D45)              → Plane 1 only when hard-fail
  0. Bootstrap sandbox + canaries   → harness → Plane 2 (D36, D44)
  1. Inspect repo and docs          → via same disposable sandbox
  2. Infer required services
  3. Validate runtime profile       → replace VM if oci_image differs
  4. Provision (install egress)     → harness → Plane 2 (D43)
  5. Offline → launch + readiness   → gates own success (D47)
  6. Scan / probes / cite-checked review / receipt / destroy → completed|failed
       │
       ▼
OUT: environment_profile.json + readiness + receipt + completed|failed
```

| | |
|--|--|
| **IN** | Git repository URL |
| **Agent** | Environment Agent Plan Loop (OpenCode → Vultr Inference; trusted config D38) |
| **Decide intent** | Prefer `git_mcp` \| `webapp`; else invent `demo` (D34) |
| **OUT** | Runtime `environment_profile.json` + readiness evidence + vuln report + `completed` |

Explore and test share **one** microVM per job (bootstrap → optional replace → runtime).

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
pending → [queued] → analyzing → planning → provisioning → installing
       → verifying ⇄ repairing
       → scanning → finalizing → completed | failed | cancelled
```

- Steps 0–3 ≈ `analyzing` / `planning` (bootstrap create → runtime profile; image replace if needed)
- Steps 4–5 ≈ `provisioning` → `verifying` (with `repairing`); set `readiness` on probe pass
- Then `scanning` → `finalizing` (report + destroy) → `completed`
- Do **not** destroy on readiness alone (D37)

Repair capped by `MAX_REPAIR_ATTEMPTS`. Jobs server-owned on Plane 1 durable ledger (D41).

SSE types: `status` · `progress` · `log` · `screenshot` · `error` · `span` · `finding` · `containment` · `lifecycle` (+ keep-alives — D49, D50)

---

## `environment_profile.json`

Versioned executable schema (`schema_version: "1"`) — see [DATABASE.md](DATABASE.md) and [ARCHITECTURE.md](ARCHITECTURE.md). Ship `schemas/environment_profile.v1.json`. MCP requires explicit `mcp.transport` (`stdio` \| `streamable_http`); stdio readiness uses the in-guest verify helper (D51).

---

## Implementation phases

### E0 — Scaffold

- [x] Scaffold `explore/` worker with local health for compose
- [x] `docker-compose.yml` service `explore` (same network as frontend)
- [x] `.env.example`: `VULTR_API_KEY`, `VULTR_INFERENCE_*`, `OPENCODE_*`, timeouts, caps
- [x] Empty `jobs.py` / `models.py` / `config.py`

**Done when:** Worker boots; can be reached by Next.js on the same host.

### E1 — Durable job ledger + Internal Worker API

- [x] Durable job/event ledger (SQLite default; D41) **owned by this sidecar** (D52)
- [x] Implement Internal Worker API **before** N1: create / snapshot (`event_cursor`) / events / cancel / screenshots / health ([API.md](API.md))
- [x] SSE replay + `cursor_expired` (D55); keep-alives (D50); structured types (D49)
- [x] Cancel: `cancel_requested_at` → freeze ordinary writers → finalizer (receipt + destroy) → terminal `cancelled` (D61); idempotent when already cancelled
- [x] SSE cursor + contiguous prune/`gap` events (D55, D67)
- [ ] Startup reconciliation vs live Microsandbox inventory; set absolute `expires_at`
- [x] Persist profile **revisions**, sandbox **generations**, `resolved_commit`, readiness, verification, vuln_report, **receipt** (before terminal), screenshots[], `sandbox_id`, `inference_model`, `expires_at`, `cleanup`, `destroyed_at` (confirm-only — D57, D64)
- [ ] Admission hooks: concurrency / queue / rate / inference / disk budgets (D40)

**Done when:** Internal API serves create/snapshot/SSE/cancel; Next can proxy without a local store; restart keeps ledger.

### E2 — Plan loop (steps −1–3) + OpenCode lockdown

- [x] Plane-1 **pre-flight** before bootstrap create when hard-fail applies (D45); emit `log.kind=preflight` / `finding.source=preflight`
- [ ] Ship **trusted OpenCode system/managed config** (D38): deny host `shell` / arbitrary tools/providers/plugins; allow only Vultr inference + job-scoped harness tools; never load submitted-repo `.opencode` / `AGENTS.md` as authority
- [ ] Wire OpenCode → **Vultr Serverless Inference** (D25); fail closed if not Vultr
- [ ] Persist `inference_model` + usage toward budgets
- [ ] Bootstrap create via harness before inspect (D36); plant canaries (D44)
- [ ] `discover.py`: inspect → infer → validate (inspect via sandbox clone/copy/exec — not privileged host exec of untrusted install); persist **`resolved_commit`** (D62)
- [ ] On runtime `oci_image` ≠ bootstrap: `replace_environment` (log `sandbox_replace`); re-clone **same SHA**; inherit `expires_at`; still one live VM (D64)
- [ ] `profile.py` + `schemas/environment_profile.v1.json` (D51): services, CommandSpec cwd/env/timeout, processes/supervision, probes, `mcp.transport` (`stdio` \| `streamable_http`), `verification_target`, required `source.commit`; append **revisions** (D64)
- [ ] In-guest `mcp_stdio_verify` helper: launch subprocess, JSON-RPC `initialize` → `notifications/initialized` → `tools/list`; evidence via `mcp_stdio_verify`
- [ ] Prompts: discover + validate
- [ ] Intent: `git_mcp` \| `webapp` \| `demo` (agent decides; D34)
- [ ] For `git_mcp`, optionally set `mcp.security_assessment` when Inspector/SDK probes are warranted (D35); omit when not
- [ ] **No install allowlist** (D29) — runtime profile may contain any OCI/install/run Microsandbox can attempt; invalid/incomplete **runtime** profile still blocks step 4
- [ ] Cap turns / tokens / wall-clock
- [ ] Stream steps to job events

**Done when:** Golden webapp + MCP fixtures emit valid runtime profiles; image-change path replaces once; OpenCode cannot shell the host; inference hits Vultr only.

### E3 — Harness (steps 4–5)

Depends on [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md).

- [ ] `harness.py`: create / replace / wait / exec / copy / destroy (one sandbox per job); **D60** path restrictions on copy
- [ ] Map bootstrap + runtime profile → OCI image + CPU/memory + network policy + canaries
- [ ] Record sandbox **generations**, `sandbox_id` / `expires_at`; emit create/replace/destroy **lifecycle** events
- [ ] Clone + **attempt** install from runtime profile with **install-phase egress**; preinstall assessment tooling; **flag failures** (D29, D43, D63)
- [ ] Enter **deny-all remaining egress** phase; supervise processes; `verify.py` launches **built checkout** for original_application (D62):
  - `git_mcp` + `stdio` → in-guest `mcp_stdio_verify` (list tools) (D30, D51)
  - `git_mcp` + `streamable_http` → HTTP MCP handshake listing tools
  - `webapp` / `demo` → declared probe
- [ ] On probe pass: set `readiness` + `verification.kind` via **gates** (D47, D66, D54); retain `original_failure` for generated demos; **do not** destroy or mark `completed` yet (D37)
- [ ] Repair within `MAX_REPAIR_ATTEMPTS`; log attempt number; profile repairs append revisions
- [ ] **Containment matrix** (D58, D65) + **network_probe** (D39) + **canary scan** (D44) — stream `containment` / `finding`; **not** CVE exploitation (D33)

**Done when:** Getting-started webapp and pinned filesystem MCP fixture set readiness; controlled fail fixture is `setup_failed` without demo escape; containment matrix + network + canary visible; sandbox still alive after readiness until finalizing.

### E4 — Optional screenshots

- [ ] `screenshots.py`: run Playwright **inside Plane 2** when HTTP verify; copy stills out; terminal stills when useful
- [ ] **Skip** when not relevant (CLI-only MCP, early fail) — never invalidate readiness or block `completed` (D31)
- [ ] Emit SSE `screenshot` only when captured; cap `MAX_SCREENSHOTS_PER_JOB` + disk budget; redact secrets

**Done when:** HTTP webapp verify can attach a browser still captured in-guest; MCP-only jobs can complete with empty timeline; no Playwright against untrusted pages on Plane 1.

### E5 — Vulnerability scanning + optional MCP assessment + finalize

**In scope:** SCA / lockfile / known-advisory scanners + AI `vuln_review`; optional **MCP Inspector/SDK** assessment when `mcp.security_assessment.enabled` (D35).  
**Out of scope:** weaponizing CVEs or generic app/web exploit suites ([DECISIONS.md](DECISIONS.md) D11, D33).

- [ ] `vulnscan.py` on Plane 1 against lockfiles copied to artifact dir (D43, D63)
- [ ] When profile plans it: run **preinstalled** MCP Inspector and/or SDK probes in Plane 2 after readiness; stream `log.kind=mcp_assessment` / `finding`; attach `vuln_report.mcp_assessment`
- [ ] `vuln_review.md` AI summary → job `vuln_report` with **citations to finding ids** (D48); drop uncited claims
- [ ] Persist severity-grouped `VulnFinding[]` with `source` `sca` \| `mcp_assessment` \| `canary` \| `network` \| `containment` \| `preflight`; emit `finding` SSE
- [ ] Best-effort SCA on **failure** paths (controlled fail fixture must still produce **scan** findings — D53)
- [ ] Persist **JobReceipt** before terminal status (incl. cancel — D61); destroy in finally with confirm-only job-level `destroyed_at`; emit `lifecycle` (D49, D57)
- [ ] Apply gate table (D66); findings and MCP assessment do not invalidate readiness; scan tool crash → `partial` / `failed` report without erasing readiness
- [ ] **Do not** add CVE exploit PoCs or generic offensive suites against non-MCP app targets
- [ ] Separate `findings.source=sca` from `intentional_app` (D53)
- [ ] `finalizing`: persist receipt → destroy with confirm → `destroyed_at` only if confirmed else `destroy_failed` (D57) → terminal per D66

**Done when:** At least one stack produces real SCA advisories or a clean bill; MCP assessment path works when planned; controlled fail fixture has SCA without pretending original app readiness; destroy confirm-only.

### E6 — Orchestration hardening

- [ ] Single pipeline wiring E1–E5
- [ ] Chaos: bad URL, install failure, repair cap, cancel, containment, control-plane restart mid-job, image replace
- [ ] Pinned fixtures E2E (D53) + verification kinds (D54)
- [ ] No Killhub secrets in sandbox env/logs/screenshots
- [ ] Admission pressure tests (`429`/`503`)
- [ ] Deploy with frontend on Vultr Cloud Compute (D24) only after ledger + host reaper (D41)

**Done when:** D53 fixtures behave as specified; absolute expiry / cancel / completed always destroy sandbox even across Plane 1 restart.

---

## Configuration

| Variable | Purpose |
|----------|---------|
| `VULTR_API_KEY` | VX1 host ops (never in sandboxes) |
| `VULTR_INFERENCE_BASE_URL` | Default `https://api.vultrinference.com/v1` |
| `VULTR_INFERENCE_API_KEY` | Serverless Inference |
| `VULTR_INFERENCE_MODEL` | Model id |
| `OPENCODE_*` / trusted config path | Agent client → Vultr Inference; D38 lockdown |
| `LEDGER_URL` / ledger path | Durable job/event store (D41) |
| `JOB_TIMEOUT_SECONDS` | Wall clock |
| `ENV_TTL_SECONDS` | Absolute `expires_at` base (D41) |
| `MAX_REPAIR_ATTEMPTS` | Retry cap |
| `MAX_CONCURRENT_JOBS` / `MAX_QUEUED_JOBS` / rate limits | Admission (D40) |
| `INFERENCE_BUDGET_*` / `MAX_JOB_LOG_BYTES` | Budgets (D40) |
| `VULN_SCAN_*` | Scanner settings |
| `MAX_SCREENSHOTS_PER_JOB` | Cap |
| `SCREENSHOT_STORAGE` | Artifact store |
| `MSB_HOST` / `MSB_DEFAULT_IMAGE` / CPU·memory / net policy | Bootstrap + harness defaults |

---

## Milestones

- [x] **E-M0:** Worker boots
- [x] **E-M1:** Durable ledger drives Plane 1 API/SSE; restart reconciliation
- [ ] **E-M2:** Bootstrap + plan loop → valid runtime profile via Vultr Inference; OpenCode lockdown
- [ ] **E-M3:** Readiness via harness + containment/network probes; image replace path
- [ ] **E-M4:** Optional in-guest screenshots when useful
- [ ] **E-M5:** Vuln **scan** report (incl. fail path); optional MCP assessment; `finalizing` → `completed`
- [ ] **E-M5b:** Containment + network probes logged
- [ ] **E-M6:** D53 fixtures + admission + absolute expiry cleanup; Vultr demo deploy

---

## Security

- Secrets stay on Plane 1 server — **not** injected into Plane 2 by default
- OpenCode trusted config: harness tools only; repo instructions untrusted (D38)
- Attempt any Microsandbox-bootable OCI + install commands; flag failures (D29)
- Containment + network probes only inside Plane 2 (D26, D39)
- Vuln path is SCA + report always (D33); MCP Inspector/SDK only when profile plans it (D35)
- Playwright for untrusted HTTP verify runs in Plane 2 only

---

## Out of scope

- Next.js UI components
- VX1 `msb` install details beyond harness contract
- Non-Vultr inference providers
- Weaponizing CVEs / generic app/web exploit suites
- Running MCP Inspector on every job without `mcp.security_assessment` (D35)

---

## Definition of done

Given a GitHub URL job, the plan loop (locked-down OpenCode → Vultr Inference) bootstraps **one** Plane 2 sandbox, produces a validated runtime profile (replacing the VM if the OCI image changes), drives install + MCP/HTTP readiness evidence, streams status (optional in-guest screenshots), attaches a **scan-based** vuln report, finalizes without clearing readiness on findings, and destroys the sandbox on `completed` / fail / cancel / absolute expiry — without leaking Killhub secrets, host shell from the agent, Plane 2→Plane 1 calls, or CVE weaponization.
