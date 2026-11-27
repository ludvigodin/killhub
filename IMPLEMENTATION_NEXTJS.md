# Plane 1 — Next.js (UI + Jobs API)

Implementation plan for the user-facing control plane: input · status · report windows, and the **Jobs API / SSE** owned by Next.js ([DECISIONS.md](DECISIONS.md) D28). Agent/harness workers live in `explore/` on the same host — see [IMPLEMENTATION_EXPLORE_SANDBOX.md](IMPLEMENTATION_EXPLORE_SANDBOX.md). Disposable sandboxes: [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md).

Architecture: [ARCHITECTURE.md](ARCHITECTURE.md) · Index: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)

---

## Role

| Window | Contents |
|--------|----------|
| **Input** | Public GitHub URL + start |
| **Status** | Live `status`, `progress`, `current_step`, execution log, **optional** screenshot timeline |
| **Report** | Intake **receipt**: `environment_profile.json`, sandbox lifecycle, readiness evidence, cited vulnerability findings (SCA + optional MCP / canary / containment), gate outcomes, terminal `completed` / fail |

Plane 1 **owns** job create/poll/SSE. Browser talks only to Next.js. Secrets never go to the client.

---

## Repo layout (this plane)

```
frontend/
├── app/
│   ├── page.tsx              # Input window
│   ├── jobs/[id]/page.tsx    # Status + report windows
│   ├── api/jobs/...          # Jobs API + SSE route handlers
│   └── layout.tsx
├── components/
│   ├── UrlForm.tsx
│   ├── ProgressLog.tsx
│   ├── StatusBadge.tsx
│   ├── ProgressBar.tsx
│   ├── ScreenshotTimeline.tsx
│   ├── SetupDocs.tsx
│   ├── EnvStatus.tsx
│   ├── VulnReport.tsx
│   └── ErrorBanner.tsx
└── lib/
    └── api.ts                # Browser client → same-origin /api
```

---

## Jobs API (served here)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/jobs` | Create job `{ github_url }` → `{ job_id }` |
| `GET` | `/api/jobs/{id}` | Snapshot |
| `GET` | `/api/jobs/{id}/events` | SSE |
| `GET` | `/api/jobs/{id}/screenshots` | Timeline (may be empty) |
| `GET` | `/api/jobs/{id}/screenshots/{shot_id}` | Image bytes |
| `DELETE` | `/api/jobs/{id}` | Cancel (explicit only) |
| `GET` | `/health` | Liveness |

**State owner (D52):** Python `explore/` sidecar owns the ledger. Next.js **proxies** `/api/jobs*` → `/internal/jobs*` (loopback + `INTERNAL_API_TOKEN`). Do not implement a parallel Next.js job dictionary. Freeze the Internal Worker API in [API.md](API.md) before N1.

### Client disconnect policy

Jobs are **server-owned** (Plane 1). Closing the tab does **not** cancel. Resume via `/jobs/{id}` using snapshot `event_cursor` then SSE (D55). Cancel only via `DELETE` (idempotent — D56) or timeout.

---

## Implementation phases

### N0 — Scaffold

- [x] Next.js App Router + TypeScript in `frontend/`
- [x] Shell pages: landing (input), `/jobs/[id]`
- [x] Wire into `docker-compose.yml` as `frontend`
- [x] Same-origin `/api` routes (no browser → separate Explore URL required)
- [x] **Biome + Knip** installed with `lint` / `lint:fix` / `knip` scripts; both pass ([plan/LINT.md](plan/LINT.md))

**Done when:** Frontend loads; `/health` returns `200`; Biome + Knip pass.

### N1 — Input + Jobs API proxy + admission

- [ ] GitHub URL form + start
- [ ] Client-side validation hints (HTTPS, github.com)
- [ ] Public `/api/jobs*` **proxy** to Internal Worker API (D52); no local job store
- [ ] Snapshot exposes `event_cursor`; status page: hydrate → SSE with `Last-Event-ID` / `?after=`; handle `cursor_expired` (D55)
- [ ] Cancel: idempotent `DELETE`; surface already-cancelled cleanly (D56)
- [ ] Enforce / surface admission: `400` / `429` / `503` (D40)
- [ ] Surface errors in `ErrorBanner`

**Done when:** Submitting a URL creates a job via sidecar; hydrate+SSE has no silent gaps; overload returns explicit rejection codes.

### N2 — Status window

- [x] `StatusBadge` + `ProgressBar` + `current_step` from poll and/or SSE
- [x] `ProgressLog` chronological SSE `log` + evidence events (`span` / `finding` / `containment` / `lifecycle`)
- [x] Tolerate SSE keep-alives without UI flicker (D50)
- [x] `ScreenshotTimeline`: hydrate when shots exist; tolerate empty timeline (D31)
- [x] On load: snapshot + SSE reconnect

**Done when:** Live status/progress/logs/evidence update without refresh; reconnect restores state.

### N3 — Report window

- [ ] Show `environment_profile.json` when available
- [ ] `EnvStatus`: provisioning / running / readiness passed / completed / destroyed / destroy_failed (`sandbox_id` / `expires_at` / `cleanup` / `destroyed_at`) — do not equate readiness with completion (D37, D57)
- [ ] Show `verification.kind` (`original_application` \| `generated_demo` \| `setup_failed`) and visible `original_failure` when present (D54)
- [ ] Repair attempts + containment / network / canary evidence
- [ ] Render **receipt** dossier when present (D49): gates, probes, lifecycle, cited findings
- [ ] `VulnReport` when **scan** completes (including fail path) — severity-grouped advisories by `source` (`sca` \| `mcp_assessment` \| `canary` \| `network` \| `containment` \| `preflight`)
- [ ] When present, show `vuln_report.mcp_assessment` (Inspector/SDK) separately from SCA; clarify assessment was agent-planned (D35)
- [ ] Optional copy clarifying default report is scan-based; MCP assessment appears only when planned — not a generic app pentest; findings do not erase readiness
- [ ] Cancel control; optional retry

**Done when:** Terminal jobs show profile, readiness evidence or clear failure, receipt/vulns (and MCP assessment when planned), and sandbox-destroyed / `completed` state.

### N4 — Hardening + public Vultr deploy

- [ ] Reconnect / event-id catch-up UX (durable event ids — D41)
- [ ] Empty and error states (including “no screenshots”, admission rejections, pre-flight hard-fail)
- [ ] No control-plane secrets in client bundles
- [ ] E2E against pinned fixtures (D53)
- [ ] Deploy control plane to **Vultr Cloud Compute** with public HTTPS via reverse proxy; app binds `127.0.0.1` (D24, D46) only after ledger + admission + host reaper are live

**Done when:** Leave/return restores UI; demo reachable on Vultr behind admission controls and edge proxy.

---

## Configuration (Plane 1 UI)

| Variable | Purpose |
|----------|---------|
| Server-only env for workers | Inference / MSB — never `NEXT_PUBLIC_*` for secrets |

---

## Milestones

- [x] **N-M0:** Frontend boots in compose
- [ ] **N-M1:** Input creates job via Plane 1 API
- [x] **N-M2:** Live status, progress, logs
- [ ] **N-M3:** Report shows profile + vulns + sandbox lifecycle
- [ ] **N-M4:** Reconnect / cancel; public Vultr demo URL live

---

## Out of scope (this doc)

- Plan-loop / harness internals → [IMPLEMENTATION_EXPLORE_SANDBOX.md](IMPLEMENTATION_EXPLORE_SANDBOX.md)
- `msb` host bootstrap → [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md)

---

## Definition of done

User can paste a GitHub URL, watch live status/progress/sandbox lifecycle, and read the report without refreshing — via Plane 1 Jobs API. Screenshots optional.
