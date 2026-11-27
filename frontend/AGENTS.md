<!-- BEGIN:nextjs-agent-rules -->

## This is NOT the Next.js you know

This version has breaking changes - APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` - verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

## Killhub frontend (Plane 1 edge)

Root rules: [AGENTS.md](../AGENTS.md). Module map: [docs/CODEMAP.md](../docs/CODEMAP.md). Contracts: [API.md](../API.md).

- **Public `/api/*` and `/mcp` are proxies** to the explore sidecar (`EXPLORE_BASE_URL` + `INTERNAL_API_TOKEN`). Do **not** put ledger, job pipeline, or harness logic in Next — that lives in `explore/` (D52).
- **SSE:** hydrate snapshot (`event_cursor`) then subscribe with `Last-Event-ID` / `?after=` (D55). Client: `components/JobLiveView.tsx`, `lib/api.ts`.
- **Admission:** edge rate limits on `POST /api/jobs` in `lib/admission.ts`; concurrency/queue/inference budgets are in explore. Multi-instance needs `ADMISSION_STORE=valkey` on **both** sides (D71).
- **Deep link:** `app/[owner]/[repo]/page.tsx` is GitHub-only client-side create (D82) — not a server GET that burns admission for crawlers.
- Quality gate: root [AGENTS.md](../AGENTS.md) §8 (`pnpm lint` / knip / typecheck / build).
