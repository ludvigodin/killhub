# Plane 1 — Next.js (UI + Jobs API)

Implementation plan for the user-facing control plane: input · status · report windows, and the **Jobs API / SSE** owned by Next.js ([DECISIONS.md](DECISIONS.md) D28). Agent/harness workers live in `explore/` on the same host — see [IMPLEMENTATION_EXPLORE_SANDBOX.md](IMPLEMENTATION_EXPLORE_SANDBOX.md). Disposable sandboxes: [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md).

Architecture: [ARCHITECTURE.md](ARCHITECTURE.md) · Index: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)

---

## Role

| Window | Contents |
|--------|----------|
| **Input** | Public GitHub URL + start |
| **Status** | Live `status`, `progress`, `current_step`, execution log, **optional** screenshot timeline |
| **Report** | `environment_profile.json`, sandbox / readiness status, vulnerability findings, final outcome |

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

Workers in `explore/` update the job store; Next.js exposes it. Exact in-process vs localhost sidecar boundary is an open non-decision under D28.

### Client disconnect policy

Jobs are **server-owned** (Plane 1). Closing the tab does **not** cancel. Resume via `/jobs/{id}`. Cancel only via `DELETE` or timeout.

---

## Implementation phases

### N0 — Scaffold

- [ ] Next.js App Router + TypeScript in `frontend/`
- [ ] Shell pages: landing (input), `/jobs/[id]`
- [ ] Wire into `docker-compose.yml` as `frontend`
- [ ] Same-origin `/api` routes (no browser → separate Explore URL required)

**Done when:** Frontend loads; `/health` returns `200`.

### N1 — Input + Jobs API

- [ ] GitHub URL form + start
- [ ] Client-side validation hints (HTTPS, github.com)
- [ ] `POST /api/jobs` creates job (delegates to explore worker), navigate to `/jobs/{id}`
- [ ] Surface `400` in `ErrorBanner`

**Done when:** Submitting a URL creates a job and opens the job view.

### N2 — Status window

- [ ] `StatusBadge` + `ProgressBar` + `current_step` from poll and/or SSE
- [ ] `ProgressLog` chronological SSE `log` events
- [ ] `ScreenshotTimeline`: hydrate when shots exist; tolerate empty timeline (D31)
- [ ] On load: snapshot + SSE reconnect

**Done when:** Live status/progress/logs update without refresh; reconnect restores state.

### N3 — Report window

- [ ] Show `environment_profile.json` when available
- [ ] `EnvStatus`: provisioning / running / ready / destroyed (`sandbox_id` / `destroyed_at`)
- [ ] Repair attempts + containment-probe log lines
- [ ] `VulnReport` when **scan** completes (including fail path) — severity-grouped advisories; do not imply exploits were run
- [ ] Optional copy/empty state clarifying report is scan-based (not a pentest)
- [ ] Cancel control; optional retry

**Done when:** Terminal jobs show profile, readiness or clear failure, vulns, and sandbox-destroyed state.

### N4 — Hardening + public Vultr deploy

- [ ] Reconnect / event-id catch-up UX
- [ ] Empty and error states (including “no screenshots”)
- [ ] No control-plane secrets in client bundles
- [ ] E2E against golden fixtures (D32)
- [ ] Deploy control plane to **Vultr Cloud Compute** with public HTTPS (D24)

**Done when:** Leave/return restores UI; demo reachable on Vultr.

---

## Configuration (Plane 1 UI)

| Variable | Purpose |
|----------|---------|
| Server-only env for workers | Inference / MSB — never `NEXT_PUBLIC_*` for secrets |

---

## Milestones

- [ ] **N-M0:** Frontend boots in compose
- [ ] **N-M1:** Input creates job via Plane 1 API
- [ ] **N-M2:** Live status, progress, logs
- [ ] **N-M3:** Report shows profile + vulns + sandbox lifecycle
- [ ] **N-M4:** Reconnect / cancel; public Vultr demo URL live

---

## Out of scope (this doc)

- Plan-loop / harness internals → [IMPLEMENTATION_EXPLORE_SANDBOX.md](IMPLEMENTATION_EXPLORE_SANDBOX.md)
- `msb` host bootstrap → [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md)

---

## Definition of done

User can paste a GitHub URL, watch live status/progress/sandbox lifecycle, and read the report without refreshing — via Plane 1 Jobs API. Screenshots optional.
