# Step 01 — Scaffold frontend (N0)

**Goal:** Next.js App Router app boots in compose; `/health` returns 200; **Biome + Knip** are installed and green.

## Prerequisites

- None (first step).

## Read first

- [IMPLEMENTATION_NEXTJS.md](../IMPLEMENTATION_NEXTJS.md) § N0
- [ARCHITECTURE.md](../ARCHITECTURE.md) — proposed repo layout (skim)
- [LINT.md](LINT.md)

## Do

- [ ] Create `frontend/` Next.js App Router + TypeScript
- [ ] Landing shell (input placeholder) + `/jobs/[id]` placeholder
- [ ] `GET /health` → `200`
- [ ] Wire `frontend` into `docker-compose.yml`
- [ ] Same-origin `/api` route stubs (no real jobs yet)
- [ ] Add **Biome** (`@biomejs/biome`) with `biome.json` (or `biome.jsonc`) covering `frontend/`
- [ ] Add **Knip** with `knip` config; wire unused-export/dep checks for the Next app
- [ ] Add package scripts: `lint` → `biome check .`, `lint:fix` → `biome check --write .`, `knip` → `knip`
- [ ] Document commands in [LINT.md](LINT.md) if the package manager differs from `pnpm`

## Do not

- Implement full Jobs API, SSE, or agent logic
- Add inference keys to `NEXT_PUBLIC_*`
- Leave Biome/Knip failing or unconfigured

## Lint gate (required before Done when)

```bash
cd frontend
pnpm lint:fix && pnpm lint && pnpm knip
```

Must exit 0. See [LINT.md](LINT.md).

## Done when

Frontend loads locally via compose; `/health` returns `200`; Biome + Knip are configured and pass.

## Next

[02-scaffold-explore.md](02-scaffold-explore.md)
