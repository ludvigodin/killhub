# Step 03 — Durable ledger core (D41)

**Goal:** Jobs and events persist in a durable store owned by `explore/` (SQLite default).

## Prerequisites

- [02-scaffold-explore.md](02-scaffold-explore.md)

## Read first

- [DATABASE.md](../DATABASE.md) — Job, JobEvent, rules
- [DECISIONS.md](../DECISIONS.md) D41, D16

## Do

- [ ] Choose SQLite path under `storage/ledger/` (record in DECISIONS if not SQLite)
- [ ] Persist Job + JobEvent with field names from DATABASE.md
- [ ] Create job / append event / load snapshot helpers
- [ ] Survive process restart (smoke: write → kill → read)

## Do not

- Build the full Internal HTTP API yet (that’s step 04)
- Wire Next.js proxy yet

## Lint gate (required before Done when)

Run Biome + Knip and fix all findings before marking this step done (see [LINT.md](LINT.md)):

```bash
cd frontend
pnpm lint:fix && pnpm lint && pnpm knip
```

Must exit **0**. Do **not** start the next step while either tool fails. Python-only changes still require a green gate.

## Done when

Restarting the explore process keeps jobs/events; schema matches DATABASE.md names. Biome + Knip lint gate passes ([LINT.md](LINT.md)).

## Next

[04-internal-worker-api.md](04-internal-worker-api.md)
