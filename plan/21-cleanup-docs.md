# Step 21 — Cleanup build docs (post-implementation)

**Goal:** After steps 01–20 are done and M7 is green, remove scaffolding/build-step docs that no longer earn their keep, and leave a slim durable doc set.

## Prerequisites

- [20-e2e-fixtures-deploy.md](20-e2e-fixtures-deploy.md) **Done when** is true (fixtures + Vultr demo)
- Human confirms it is time to retire the build ladder (do not run mid-build)

## Read first

- [PRODUCT.md](../PRODUCT.md) doc map
- [AGENTS.md](../AGENTS.md) § Read before you change
- This file’s keep/remove matrix (below)

## Keep (durable — do not delete)

| Doc | Why |
|-----|-----|
| `PRODUCT.md` | What / why |
| `ARCHITECTURE.md` | Planes, zones, flows |
| `DECISIONS.md` | Binding choices |
| `DATABASE.md` | Schema / ledger rules |
| `API.md` | Contracts |
| `AGENTS.md` | Agent rules |
| `README.md` | Repo entry |
| `plan/LINT.md` **or** fold into `AGENTS.md` / `frontend` README | Lint gate remains useful in CI |
| `plan/VULTR.md` **or** fold into `AGENTS.md` / `ARCHITECTURE.md` | Vultr MCP/`vultr-cli`/`msb` rules (D59) |

Prefer **folding** `LINT.md` / `VULTR.md` into canonical docs, then delete the `plan/` copies — avoid duplicating forever.

## Remove (build scaffolding — delete when this step runs)

| Path | Why remove |
|------|------------|
| `plan/01-*.md` … `plan/20-*.md` | One-shot build steps; done |
| `plan/README.md` | Index for the ladder; obsolete after cleanup |
| `plan/21-cleanup-docs.md` | This step — delete **last** after checklist |
| Empty `plan/` directory | Remove if nothing remains |

## Collapse or rewrite (not blind-delete)

| Doc | Action |
|-----|--------|
| `IMPLEMENTATION_PLAN.md` | Replace with a short pointer to PRODUCT/ARCHITECTURE/API **or** delete if redundant |
| `IMPLEMENTATION_NEXTJS.md` | Delete **or** trim to a short “frontend layout” note if still useful for onboarding |
| `IMPLEMENTATION_EXPLORE_SANDBOX.md` | Same — delete or trim; code + API/DATABASE are source of truth |
| `IMPLEMENTATION_TEST_VM.md` | Same — keep only if operators need a living VX1/`msb` runbook; otherwise fold essentials into `ARCHITECTURE.md` + `plan/VULTR.md` content, then delete |

**Rule:** Do not delete an implementation doc until its unique operator facts (env vars, `msb` flags, Internal API paths) live in `ARCHITECTURE.md`, `API.md`, `DATABASE.md`, or `AGENTS.md`.

## Do

- [ ] Confirm steps 01–20 checkboxes are done in the old `plan/README.md` (or equivalent)
- [ ] Move any still-needed bits from `LINT.md` / `VULTR.md` / `IMPLEMENTATION_*.md` into canonical docs
- [ ] Update all links: `PRODUCT.md` doc map, `AGENTS.md`, `ARCHITECTURE.md`, `README.md` — remove references to deleted paths
- [ ] Delete `plan/01`–`plan/20` step files
- [ ] Delete or rewrite `IMPLEMENTATION_PLAN.md` + plane `IMPLEMENTATION_*.md` per matrix above
- [ ] Delete `plan/README.md`, then `plan/LINT.md` / `plan/VULTR.md` if folded, then **this file**
- [ ] Remove empty `plan/` if applicable
- [ ] Grep the repo for `plan/0`, `IMPLEMENTATION_`, `LINT.md`, `VULTR.md` broken links and fix

## Do not

- Delete `PRODUCT` / `ARCHITECTURE` / `DECISIONS` / `DATABASE` / `API` / `AGENTS`
- Run this step before M7 / step 20 is actually done
- Leave dangling markdown links

## Lint gate (required before Done when)

```bash
cd frontend
pnpm lint:fix && pnpm lint && pnpm knip
```

Must exit **0**. See [LINT.md](LINT.md) while it still exists.

## Done when

Build-step docs are gone; canonical docs still describe the running system; no broken doc links; Biome + Knip pass.

## Next

None — documentation cleanup complete.
