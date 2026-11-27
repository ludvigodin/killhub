# Step 01 — Scaffold frontend (N0)

**Goal:** Next.js App Router app boots in compose; `/health` returns 200; **Biome + Knip + typecheck/build** scripts are installed and green (D68).

## Prerequisites

- None (first step).

## Read first

- [IMPLEMENTATION_NEXTJS.md](../IMPLEMENTATION_NEXTJS.md) § N0
- [ARCHITECTURE.md](../ARCHITECTURE.md) — proposed repo layout (skim)
- [LINT.md](LINT.md)

## Do

- [x] Create `frontend/` Next.js App Router + TypeScript
- [x] Landing shell (input placeholder) + `/jobs/[id]` placeholder
- [x] `GET /health` → `200`
- [x] Wire `frontend` into `docker-compose.yml`
- [x] Same-origin `/api` route stubs (no real jobs yet)
- [x] Add **Biome** (`@biomejs/biome`) with `biome.json` (or `biome.jsonc`) covering `frontend/`
- [x] Add **Knip** with `knip` config; wire unused-export/dep checks for the Next app
- [x] Add package scripts: `lint` → `biome check .`, `lint:fix` → `biome check --write .`, `knip` → `knip`, `typecheck` → `tsc --noEmit`, `build` → `next build`
- [x] Document commands in [LINT.md](LINT.md) if the package manager differs from `pnpm`

## Do not

- Implement full Jobs API, SSE, or agent logic
- Add inference keys to `NEXT_PUBLIC_*`
- Leave Biome/Knip/typecheck/build failing or unconfigured

## Lint gate (required before Done when)

```bash
cd frontend
pnpm lint:fix && pnpm lint && pnpm knip && pnpm typecheck && pnpm build
```

Must exit 0. See [LINT.md](LINT.md).

## Done when

Frontend loads locally via compose; `/health` returns `200`; Biome + Knip + typecheck + build are configured and pass.

## Next

[02-scaffold-explore.md](02-scaffold-explore.md)
