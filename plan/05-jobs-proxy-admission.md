# Step 05 — Jobs proxy + admission (N1)

**Goal:** Public `/api/jobs` proxies to explore; admission + SSE cursor contract work from the browser path.

## Prerequisites

- [04-internal-worker-api.md](04-internal-worker-api.md)

## Read first

- [IMPLEMENTATION_NEXTJS.md](../IMPLEMENTATION_NEXTJS.md) § N1
- [DECISIONS.md](../DECISIONS.md) D40, D15, D55
- [API.md](../API.md)

## Do

- [ ] URL form + `POST /api/jobs` → Internal API (server-side token only)
- [ ] `GET /api/jobs/{id}` + `/events` proxy; hydrate snapshot then SSE with cursor
- [ ] Cursor expired → client re-snapshots (D55)
- [ ] Admission: `400` bad URL; `429` rate/inference; `503` queue/concurrency (D40)
- [ ] Navigate to `/jobs/{id}` after create

## Do not

- Build full status/report UI polish (steps 17 / 19)
- Call Microsandbox from Next.js

## Lint gate (required before Done when)

Run Biome + Knip and fix all findings before marking this step done (see [LINT.md](LINT.md)):

```bash
cd frontend
pnpm lint:fix && pnpm lint && pnpm knip
```

Must exit **0**. Do **not** start the next step while either tool fails. Python-only changes still require a green gate.

## Done when

Submitting a public GitHub URL creates a job via sidecar; hydrate+SSE has no silent gaps; overload returns explicit codes. Biome + Knip lint gate passes ([LINT.md](LINT.md)).

## Next

[06-msb-create-destroy.md](06-msb-create-destroy.md)
