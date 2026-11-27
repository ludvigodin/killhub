# Step 20b — Video-site feed UI (many GitHub entries)

**Goal:** Make the public frontend feel like a **video site**: a browsable grid of GitHub jobs as “entries,” with a create flow that encourages submitting **as many public repos as admission allows**.

## Prerequisites

- [17-status-ui.md](17-status-ui.md)
- [19-report-ui.md](19-report-ui.md)
- Prefer [16-screenshots.md](16-screenshots.md) so cards can use real thumbnails when present
- Prefer [20-e2e-fixtures-deploy.md](20-e2e-fixtures-deploy.md) so the feed can show real fixture jobs

## Read first

- [IMPLEMENTATION_NEXTJS.md](../IMPLEMENTATION_NEXTJS.md) — Input window + layout
- [API.md](../API.md) — Jobs API (extend with list)
- [PRODUCT.md](../PRODUCT.md) — input · status · report
- [DECISIONS.md](../DECISIONS.md) D40 (admission — do not bypass)

## Product shape

Treat each job as a **video-like entry** on a feed:

| Metaphor | Killhub meaning |
|----------|-----------------|
| Thumbnail | Latest screenshot when present; otherwise a branded placeholder (repo initial / status color) |
| Title | `owner/repo` from the GitHub URL |
| Subtitle / meta | `status`, `current_step`, short time since create |
| Watch / open | Navigate to `/jobs/[id]` (status/report already from steps 17 / 19) |
| Upload / New | Create one or many jobs from public GitHub URLs |

Home should read as **one composition**: brand, short line, create control, and a dense entry grid — not a single-field form in the middle of empty space.

## Do

### API (minimal — feed needs a list)

- [ ] Add **`GET /internal/jobs`** → recent jobs (newest first), capped (e.g. last `N`, query `limit`) — summary fields only: `job_id`, `github_url`, `status`, `progress`, `current_step`, `created_at`, optional screenshot id
- [ ] Proxy **`GET /api/jobs`** the same way (public list for the demo feed)
- [ ] Document the contract in [API.md](../API.md) (+ [DATABASE.md](../DATABASE.md) only if a new index/query is required)
- [ ] Record a short decision in [DECISIONS.md](../DECISIONS.md) if the feed/list is a lasting public surface

### Create many entries

- [ ] Landing create UX supports **rapid successive** creates (stay on the feed after each start; do not force-navigate away every time)
- [ ] Prefer a **multi-URL** create path (textarea / one-URL-per-line, or “add another” rows) that posts jobs **sequentially**, showing per-URL success / `429` / `503` / `400` without aborting the whole batch on the first failure
- [ ] Surface admission honestly (D40): queue full / rate limit copy; never fake creates or bypass concurrency
- [ ] Optional: local “draft queue” of URLs waiting to retry when `503`/`429` clears — still server-owned jobs once accepted

### Video-site UI

- [ ] Replace the sparse single-form landing with a **feed grid** of job entry cards
- [ ] Card: thumbnail (screenshot or placeholder), `owner/repo`, status badge, progress hint
- [ ] Empty state: brand-forward CTA to paste the first GitHub URL(s)
- [ ] Loading / polling: refresh the list on an interval or after create so new entries appear without a full page reload
- [ ] Keep `/jobs/[id]` as the detail route; do **not** rework status/report chrome beyond linking into it
- [ ] Update [IMPLEMENTATION_NEXTJS.md](../IMPLEMENTATION_NEXTJS.md) Input window + component list to match
- [ ] Light touch on [PRODUCT.md](../PRODUCT.md) success copy if the first viewport is now a feed, not a lone paste field

## Do not

- Bypass or weaken D40 admission / rate limits to “create unlimited” jobs
- Re-open Plane 2 pipeline steps (14–18) unless a feed bug forces a tiny fix
- Add auth, private repos, or non-`github.com` hosts
- Start [21-cleanup-docs.md](21-cleanup-docs.md) in the same session

## Lint gate (required before Done when)

Run the full quality gate ([LINT.md](LINT.md)):

```bash
cd frontend
pnpm lint:fix && pnpm lint && pnpm knip && pnpm typecheck && pnpm build

cd ../explore
ruff check . && ruff format --check .
# focused tests for list + create batch client helpers as added
```

Must exit **0**.

## Done when

- Home looks and behaves like a video-site feed of GitHub job entries
- Users can submit **many** public GitHub URLs in one sitting (batch or rapid create) up to admission caps, with clear per-entry errors
- `GET /api/jobs` (and internal twin) returns a recent-job list the feed uses
- Detail still lives at `/jobs/[id]`; quality gate is green

## Next

[21-cleanup-docs.md](21-cleanup-docs.md)
