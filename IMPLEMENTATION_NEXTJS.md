# Plane 1 — Next.js (UI + Jobs API + View-Only `noVNC` Proxy)

Implementation plan for the user-facing control plane: input · status (`noVNC` + live telemetry) · report (`DetonationVerdict` + receipt) windows, and the **Jobs API / SSE / `noVNC` proxy** owned by Next.js ([DECISIONS.md](DECISIONS.md) D28, D46, D71). Agent/harness workers, Host LLM Proxy, TAP/`mitmdump` controller, and ledger live in `explore/` on the same host — see [IMPLEMENTATION_EXPLORE_SANDBOX.md](IMPLEMENTATION_EXPLORE_SANDBOX.md). Disposable sandboxes: [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md).

Architecture: [ARCHITECTURE.md](ARCHITECTURE.md) · Index: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) · Contracts: [API.md](API.md) · [DATABASE.md](DATABASE.md) · `schemas/*.json`

> **Mandatory Coding Rule (`AGENTS.md` §5 — R2) & Quality Gate (`plan/LINT.md`):**
> - Every TypeScript/TSX file modification must include concise inline comments explaining *what* and *why* key invariants, guards, or proxy boundaries exist.
> - Every new `.ts`/`.tsx` module must start with a top-of-file JSDoc header documenting: (1) purpose, (2) plane (`Plane 1`) & trust-zone responsibility, and (3) key contracts/invariants (`biome`-compliant).
> - Every step touching `frontend/` must pass `pnpm lint:fix && pnpm lint && pnpm knip && pnpm typecheck && pnpm build` alongside Python Ruff/pytest & `schemas/*.json` checks (`plan/LINT.md`).

---

## Role

| Window | Contents |
|--------|----------|
| **Input** | Public GitHub URL (`https://github.com/org/repo`) or validated MCP registry / pinned fixture target (`npm:`, `pypi:`, `fixture:` — `D15`) + start |
| **Status** | Live `status`, `progress`, `current_step`, execution log, **authenticated view-only `noVNC` live stream** of in-VM OpenCode detonation (`D71`), live sensor telemetry (`mitmdump` HTTP/S+DNS, DoH/DoT/QUIC drop, canary block, `strace`, OverlayFS, MCP wire tap, cgroup v2, 3-layer kill switch), and optional Playwright still timeline (`D31`) |
| **Report** | Intake **receipt + `DetonationVerdict`** (`schemas/detonation_verdict.v1.json`, `D49`, `D73`): `environment_profile.json`, `DynamicInstallSpec`, `TestScenarioPlan`, sandbox lifecycle, readiness evidence, `package_sha256_before`/`after`, `t0_tools_sha256`/`final_tools_sha256`/`tool_diffs`, SCA + cite-checked `vuln_review` + active detonation findings mapped to all **16 MITRE ATLAS tactics (`AML.TA0000`–`AML.TA0015`)** and **10 OWASP MCP Top 10 (`MCP01:2025`–`MCP10:2025`)**, 4-axis + key-isolation `containment_proof`, 3-layer kill-switch status, telemetry/PCAP summary, gate outcomes |

Plane 1 **owns** job create/poll/SSE and view-only `noVNC` proxying. Browser talks only to Next.js. Control-plane secrets (`VULTR_API_KEY`, `VULTR_INFERENCE_API_KEY`, `INTERNAL_API_TOKEN`) never go to the client.

---

## Repo layout (this plane)

```
frontend/
├── app/
│   ├── page.tsx                              # Input window
│   ├── jobs/[id]/page.tsx                    # Status + report windows
│   ├── api/jobs/
│   │   ├── route.ts                          # POST /api/jobs (extended intake D15 + admission D40)
│   │   └── [id]/
│   │       ├── route.ts                      # GET / DELETE snapshot & cancel
│   │       ├── events/route.ts               # SSE proxy
│   │       ├── novnc/route.ts                # [v2] Authenticated view-only noVNC WS/HTTP proxy (D71)
│   │       ├── verdict/route.ts              # [v2] GET DetonationVerdict proxy
│   │       ├── telemetry/route.ts            # [v2] GET bounded telemetry slice proxy
│   │       ├── pcap/route.ts                 # [v2] GET PCAP artifact stream proxy
│   │       └── screenshots/...               # GET timeline & PNG bytes
│   ├── health/route.ts                       # Control-plane liveness
│   └── layout.tsx
├── components/
│   ├── UrlForm.tsx                           # GitHub URL + MCP registry / fixture intake
│   ├── JobLiveView.tsx                       # SSE client + status/progress/log/telemetry
│   ├── NoVncViewer.tsx                       # [v2] View-only noVNC iframe/canvas panel (D71)
│   ├── TelemetryFeed.tsx                     # [v2] Live mitmdump/DNS/strace/wire-tap/kill-switch feed
│   ├── ScreenshotTimeline.tsx                # Optional Playwright stills (D31)
│   ├── SetupDocs.tsx                         # Profile + DynamicInstallSpec + TestScenarioPlan
│   ├── EnvStatus.tsx                         # Sandbox generation, readiness, cleanup, key-isolation
│   ├── DetonationVerdictView.tsx             # [v2] Verdict, SHA/tool diffs, 16 ATLAS + 10 OWASP MCP matrix
│   ├── VulnReport.tsx                        # Severity/source-grouped findings + cite-checked summary
│   └── ErrorBanner.tsx
└── lib/
    ├── api.ts                                # Strongly typed snapshot, verdict, profile, plan, SSE payloads
    ├── admission.ts                          # Rate limiting (edge-proxy trusted IP headers — S8)
    ├── explore.ts                            # Server-only loopback proxy helper (+ INTERNAL_API_TOKEN)
    └── github.ts                             # GitHub URL + MCP registry/fixture intake validation (D15)
```

---

## Jobs API & Proxy Routes (served here)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/jobs` | Create job (`github_url` or `{ target_type, mcp_registry_ref \| fixture_id, run_detonation? }`) → `{ job_id }` (`400`/`429`/`503`) |
| `GET` | `/api/jobs/{id}` | Full snapshot (`event_cursor`, `profile`, `install_spec`, `scenario_plan`, `detonation_verdict`, `novnc`, `receipt`) |
| `GET` | `/api/jobs/{id}/events` | SSE stream (replays contiguous window + live tail; `410 cursor_expired`; ~15s keep-alives) |
| `GET / WS` | `/api/jobs/{id}/novnc` | `[v2]` Authenticated **view-only** `noVNC` WebSocket/HTTP proxy (`view_only=true`, RFB input dropped, `127.0.0.1` bind behind reverse proxy — `D46`, `D71`) |
| `GET` | `/api/jobs/{id}/verdict` | `[v2]` Canonical `DetonationVerdict` JSON (`schemas/detonation_verdict.v1.json`) |
| `GET` | `/api/jobs/{id}/telemetry` | `[v2]` Bounded runtime sensor counters + redacted NDJSON slice |
| `GET` | `/api/jobs/{id}/pcap` | `[v2]` Captured TAP bridge PCAP (`application/vnd.tcpdump.pcap`) when enabled |
| `GET` | `/api/jobs/{id}/screenshots` | Timeline (may be `[]`) |
| `GET` | `/api/jobs/{id}/screenshots/{shot_id}` | Image bytes (`image/png`) |
| `DELETE` | `/api/jobs/{id}` | Cancel (idempotent D61 finalizer) |
| `GET` | `/health` | Control-plane liveness |

**State owner (`D52`):** Python `explore/` sidecar owns the SQLite WAL ledger (`storage/ledger/killhub.db`). Next.js **proxies** `/api/jobs*` → `/internal/jobs*` (loopback + `INTERNAL_API_TOKEN`) and must never hold a parallel job dictionary.

### Client disconnect policy

Jobs are **server-owned** (Plane 1, `D12`). Closing the tab does **not** cancel. Resume via `/jobs/{id}` using snapshot `event_cursor` then SSE (`D55`, `D67`). Cancel only via `DELETE` (idempotent — `D61`) or timeout / Layer 3 watchdog (`D72`).

---

## Implementation phases

### N0 — Scaffold `[x]`

- [x] Next.js App Router + TypeScript in `frontend/`
- [x] Shell pages: landing (input), `/jobs/[id]`
- [x] Wire into `docker-compose.yml` as `frontend`
- [x] Same-origin `/api` routes
- [x] **Biome + Knip** installed with `lint` / `lint:fix` / `knip` / `typecheck` / `build` scripts (`plan/LINT.md`)

### N1 — Input + Jobs API proxy + admission `[x]` (v2 intake extensions in step `09`/`17`)

- [x] GitHub URL form + start (`UrlForm.tsx`, `lib/github.ts`)
- [x] Public `/api/jobs*` **proxy** to Internal Worker API (`D52`); no local job store
- [x] Snapshot exposes `event_cursor`; status page: hydrate → SSE with `Last-Event-ID` / `?after=`; handle `cursor_expired` (`D55`)
- [x] Cancel: idempotent `DELETE` (`D61`)
- [x] Enforce / surface admission: `400` / `429` / `503` (`D40`), `ErrorBanner`
- [ ] `[v2]` Extend `UrlForm.tsx`, `lib/github.ts`, and `POST /api/jobs` for validated MCP registry targets (`npm:`, `pypi:`) and pinned fixture IDs (`D15`, `D45`)
- [ ] `[v2]` Harden `lib/admission.ts` against spoofed `x-forwarded-for` behind edge reverse proxy (`ALIGNMENT_PLAN.md` S8)

### N2 — Status window (`plan/17-status-ui.md`)

- [ ] **Prerequisite bugfix in `explore/api/routes.py:141-152`:** Ensure the live-tailing loop in `_event_stream` hoists `progress` and `current_step` (matching replay lines `111-114`) and fix the 13–15s empty-poll sleep (`routes.py:122-139`) so `JobLiveView.tsx` receives live progress and telemetry immediately.
- [ ] Strongly type `frontend/lib/api.ts` (replace `[key: string]: unknown` with typed `DetonationVerdict`, `EnvironmentProfile`, `DynamicInstallSpec`, `TestScenarioPlan`, `VulnReport`, `JobReceipt`, `NoVncInfo`).
- [ ] `StatusBadge` + `ProgressBar` + `current_step` from snapshot + live SSE.
- [ ] `JobLiveView.tsx`: register `EventSource.addEventListener` for all v1 + `[v2]` SSE types (`status`, `progress`, `log`, `screenshot`, `error`, `span`, `finding`, `containment`, `lifecycle`, `gap`, `telemetry`, `tool_diff`, `kill_switch`, `novnc`) and render structured `log.kind` payloads (`mitmdump_http`, `mitmdump_dns`, `doh_dot_quic_drop`, `canary_block`, `strace`, `overlayfs`, `mcp_wire_tap`, `cgroup_v2`, `llm_proxy_429`, `discovery`, `test_planner`).
- [ ] `NoVncViewer.tsx` + `/api/jobs/[id]/novnc`: render authenticated **view-only `noVNC`** iframe/canvas when `novnc.available === true`; enforce job-scoped auth token, `view_only=true`, and server-side RFB input-message drop; close cleanly on sandbox destroy (`D46`, `D71`).
- [ ] Tolerate SSE keep-alives without UI flicker (`D50`).
- [ ] `ScreenshotTimeline`: hydrate optional Playwright stills when present; tolerate empty timeline (`D31`).

**Done when:** Live status/progress/logs/telemetry/`noVNC` stream update without refresh; reconnect restores state; view-only `noVNC` rejects interactive guest input.

### N3 — Report window (`plan/19-report-ui.md`)

- [ ] Show `environment_profile.json`, `DynamicInstallSpec`, and `TestScenarioPlan` (`SetupDocs.tsx`).
- [ ] `EnvStatus`: provisioning / running / readiness passed / completed / destroyed / destroy_failed (`sandbox_id`, `current_sandbox_generation`, `expires_at`, `cleanup`, `destroyed_at`, `resolved_commit`) — do not equate readiness with completion (`D37`, `D57`, `D64`).
- [ ] Show `verification.kind` (`original_application` \| `generated_demo` \| `setup_failed`) and visible `original_failure` when present (`D54`).
- [ ] **`DetonationVerdictView.tsx`** (consuming `/api/jobs/{id}/verdict` or `snapshot.detonation_verdict` matching `schemas/detonation_verdict.v1.json`):
  - Verdict banner (`CLEAN` \| `SUSPICIOUS` \| `MALICIOUS` \| `ABORTED` \| `INCONCLUSIVE`, `risk_score`, `summary`)
  - Target package integrity (`package_sha256_before`, `package_sha256_after`, `integrity_tampered`)
  - MCP capability integrity (`discovery_method`, `t0_tools_sha256`, `final_tools_sha256`, `tool_diffs[]`, counts)
  - Full **16-tactic MITRE ATLAS matrix (`AML.TA0000`–`AML.TA0015`)** and **10-class OWASP MCP Top 10 (`MCP01:2025`–`MCP10:2025`)** coverage grid (monitored/triggered/sensors/finding links)
  - **4-axis + key-isolation `containment_proof`** (`timeout_enforcement`, `host_access_denied`, `sibling_access_denied`, `host_liveness`, `claim`, `key_isolation_verified`, `canary_blocking_verified`, `doh_dot_quic_dropped`)
  - **3-layer kill-switch status** (`layer1_llm_proxy` / `layer2_cgroup_v2` / `layer3_watchdog`) and runtime telemetry counters (`http_requests`, `https_intercepted`, `dns_queries`, `doh_dot_quic_blocked`, `canary_blocks`, `strace_syscalls_flagged`, `overlayfs_modified_paths`, `mcp_wire_messages`, `cgroup_events`, `llm_proxy_turns`/`tokens`/`429_blocks`, PCAP download link to `/api/jobs/{id}/pcap`)
- [ ] `VulnReport`: severity- and source-grouped findings (`sca` \| `mcp_assessment` \| `intentional_app` \| `canary` \| `network` \| `containment` \| `runtime_sensor` \| `kill_switch` \| `preflight`) + cite-checked `vuln_review` (`D48`, `D53`).
- [ ] Cancel control + clear copy separating SCA advisories vs active MCP detonation vs isolation proofs (never implying CVE weaponization or generic web pentest).

**Done when:** Terminal jobs render profile/spec/plan, readiness or clear failure, full `DetonationVerdict` (ATLAS/OWASP/hashes/containment/kill-switch/telemetry), cited findings, and confirmed sandbox destruction.

### N4 — Hardening + public Vultr deploy (`plan/20-e2e-fixtures-deploy.md`)

- [ ] Reconnect / event-id catch-up UX (`event_cursor`, `gap` tombstone banner — `D55`, `D67`).
- [ ] Empty and error states (empty screenshots, `429`/`503` admission, `preflight_blocked`, `destroy_failed`, `noVNC` closed).
- [ ] Zero control-plane secrets (`VULTR_*`, `INTERNAL_API_TOKEN`) in client bundles; `noVNC` proxy verified view-only and authenticated (`D71`).
- [ ] E2E against all **3 baseline fixtures + 6 Demo Malicious MCP Scenarios** (`D53`, `D73`).
- [ ] Deploy Plane 1 (`frontend`, `explore`, Host LLM Proxy, `noVNC` proxy) to **Vultr Cloud Compute** bound to `127.0.0.1` behind a reverse proxy (Caddy/nginx) configured for SSE flush, view-only `noVNC` WebSocket upgrade, and trusted `X-Real-IP` / `X-Forwarded-For` overwriting (`D24`, `D46`, `ALIGNMENT_PLAN.md` S8) only after durable SQLite WAL ledger + admission + host reaper are live.

---

## Configuration (Plane 1 UI)

| Variable | Purpose |
|----------|---------|
| `EXPLORE_BASE_URL` | Server-only loopback URL to `explore/` sidecar (e.g. `http://127.0.0.1:8100`) |
| `INTERNAL_API_TOKEN` | Server-only bearer token for Next.js → `explore/` (`D52`) |
| `NOVNC_PROXY_BIND` / `NOVNC_TOKEN_SECRET` | Server-only `127.0.0.1` bind & short-lived job-scoped `noVNC` WS token signing (`D46`, `D71`) |
| `RATE_LIMIT_*` | Admission window & per-IP/global limits (`D40`) |
| Never `NEXT_PUBLIC_*` for secrets | Browser bundles receive zero keys (`D19`) |

---

## Milestones

- [x] **N-M0:** Frontend boots in compose (`01`)
- [x] **N-M1:** Input creates job via Plane 1 proxy + SSE cursor + admission (`05`)
- [ ] **N-M2:** Live status, progress, telemetry, and authenticated view-only `noVNC` (`17`)
- [ ] **N-M3:** Report renders profile, `DetonationVerdict` (ATLAS/OWASP/hashes/containment), `VulnReport`, and sandbox lifecycle (`19`)
- [ ] **N-M4:** Reconnect / cancel / 3+6 fixtures E2E; public Vultr demo URL behind reverse proxy (`20`)

---

## Out of scope (this doc)

- Plan-loop / Host LLM Proxy / TAP-`mitmdump` / harness internals → [IMPLEMENTATION_EXPLORE_SANDBOX.md](IMPLEMENTATION_EXPLORE_SANDBOX.md)
- Ubuntu 24.04 microVM base, mounts, sensors, & `msb` host setup → [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md)
