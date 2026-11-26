# Plane 1 — Next.js (Frontend + Server)

Implementation plan for the user-facing plane: input window, status window, and report window. Plane 1 talks **only** to the Explore Sandbox (Plane 2). It does not provision VMs or run the Environment Agent.

Architecture: [ARCHITECTURE.md](ARCHITECTURE.md) · Index: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) · Plane 2: [IMPLEMENTATION_EXPLORE_SANDBOX.md](IMPLEMENTATION_EXPLORE_SANDBOX.md) · Plane 3: [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md)

---

## Role

| Window | Contents |
|--------|----------|
| **Input** | Public GitHub URL + start |
| **Status** | Live `status`, `progress`, `current_step`, execution log, screenshot timeline |
| **Report** | `environment_profile.json`, Test VM / readiness status, vulnerability findings, final outcome |

---

## Repo layout (this plane)

```
frontend/
├── app/
│   ├── page.tsx              # Input window
│   ├── jobs/[id]/page.tsx    # Status + report windows
│   └── layout.tsx
├── components/
│   ├── UrlForm.tsx
│   ├── ProgressLog.tsx
│   ├── StatusBadge.tsx
│   ├── ProgressBar.tsx
│   ├── ScreenshotTimeline.tsx
│   ├── SetupDocs.tsx           # / profile view
│   ├── EnvStatus.tsx
│   ├── VulnReport.tsx
│   └── ErrorBanner.tsx
└── lib/
    └── api.ts                  # Client for EXPLORE_SANDBOX_URL
```

---

## API consumed from Plane 2

Plane 1 is the client of these Explore Sandbox endpoints (may be proxied via Next.js route handlers):

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/jobs` | Create job `{ github_url }` → `{ job_id }` |
| `GET` | `/api/jobs/{id}` | Snapshot: status, progress, profile, vuln, screenshot ids |
| `GET` | `/api/jobs/{id}/events` | SSE: status, progress, logs, screenshots, errors |
| `GET` | `/api/jobs/{id}/screenshots` | Ordered timeline |
| `GET` | `/api/jobs/{id}/screenshots/{shot_id}` | Image bytes |
| `DELETE` | `/api/jobs/{id}` | Cancel (explicit only) |

### Status payload (always pollable)

```json
{
  "job_id": "...",
  "status": "installing",
  "progress": 55,
  "current_step": "pip install -r requirements.txt",
  "steps_completed": ["analyzing", "planning", "provisioning"],
  "updated_at": "...",
  "error": null
}
```

Poll and SSE must stay consistent. Reconnect restores status, logs, and screenshots.

### SSE event types

| `type` | Purpose |
|--------|---------|
| `status` | State machine transition |
| `progress` | Numeric progress + `current_step` |
| `log` | Execution / agent message |
| `screenshot` | New process still |
| `error` | Failure detail |

### Client disconnect policy

Jobs are **server-owned** (Plane 2). Closing the tab or dropping SSE does **not** cancel. Resume via `/jobs/{id}`. Cancel only via explicit `DELETE` or Plane 2 timeout.

---

## Implementation phases

### N0 — Scaffold

- [ ] Next.js App Router + TypeScript in `frontend/`
- [ ] Shell pages: landing (input), `/jobs/[id]` (status + report placeholders)
- [ ] `lib/api.ts` reading `EXPLORE_SANDBOX_URL`
- [ ] Wire into `docker-compose.yml` as `frontend`
- [ ] Proxy or CORS so browser reaches Explore Sandbox cleanly

**Done when:** Frontend loads; can hit explore `/health` through configured base URL.

### N1 — Input window

- [ ] GitHub URL form + start button
- [ ] Client-side validation hints (HTTPS, github.com)
- [ ] On submit: `POST /api/jobs`, navigate to `/jobs/{id}`
- [ ] Disable start while a job is in flight from that session
- [ ] Surface `400` validation errors in `ErrorBanner`

**Done when:** Submitting a URL creates a job and opens the job view.

### N2 — Status window

- [ ] `StatusBadge` + `ProgressBar` + `current_step` from poll and/or SSE
- [ ] `ProgressLog` chronological SSE `log` events
- [ ] `ScreenshotTimeline`: hydrate from `GET .../screenshots`; append on `screenshot` events
- [ ] On `/jobs/{id}` load: fetch snapshot + reconnect SSE + load screenshots so far
- [ ] Map intermediate job states to loading UI

**Done when:** Live status/progress/logs/screenshots update without full page refresh; reconnect restores timeline.

### N3 — Report window

- [ ] Show `environment_profile.json` / setup docs when available
- [ ] `EnvStatus`: provisioning / running / ready / destroyed
- [ ] `VulnReport`: severity-grouped findings when scan completes
- [ ] Error banner for agent / provision / install failures
- [ ] Cancel control (explicit); optional retry

**Done when:** Ready job shows profile, readiness, vuln report, and full screenshot timeline.

### N4 — Hardening

- [ ] Reconnect / event-id catch-up UX
- [ ] Empty and error states for each window
- [ ] No control-plane secrets in client bundles
- [ ] E2E happy path against mocked or real Explore Sandbox

**Done when:** Leave/return to `/jobs/{id}` restores full UI; errors are human-readable.

---

## Configuration (Plane 1)

| Variable | Purpose |
|----------|---------|
| `EXPLORE_SANDBOX_URL` | Base URL for Plane 2 |
| Next.js public/proxy settings | Browser → Explore Sandbox |

---

## Milestones (Plane 1)

- [ ] **N-M0:** Frontend boots in compose
- [ ] **N-M1:** Input creates job and opens status view
- [ ] **N-M2:** Live status, progress, logs, screenshots
- [ ] **N-M3:** Report window shows profile + vulns + timeline
- [ ] **N-M4:** Reconnect / cancel UX verified

---

## Out of scope (this plane)

- Environment Agent Plan Loop
- Provisioning or destroying Test VMs
- Running scanners or Playwright capture (Plane 2 produces screenshots; Plane 1 only displays them)

---

## Definition of done (Plane 1)

User can paste a GitHub URL, watch live status/progress/screenshots, and read the report (profile, readiness, vulns) without refreshing — entirely via Explore Sandbox APIs.
