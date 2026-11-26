# Step 02 — Scaffold explore worker (E0)

**Goal:** Python `explore/` worker boots and is reachable on the compose network.

## Prerequisites

- [01-scaffold-frontend.md](01-scaffold-frontend.md)

## Read first

- [IMPLEMENTATION_EXPLORE_SANDBOX.md](../IMPLEMENTATION_EXPLORE_SANDBOX.md) § E0
- [DECISIONS.md](../DECISIONS.md) D28, D52 (sidecar owns state later)

## Do

- [ ] Scaffold `explore/` (`main.py`, `config.py`, `models.py`, empty `jobs.py`, `requirements.txt`)
- [ ] Add **Ruff** to the explore toolchain (`ruff check` / `ruff format`) per [LINT.md](LINT.md) / D68
- [ ] Local health endpoint for compose
- [ ] Compose service `explore` on same network as frontend
- [ ] `.env.example` with `VULTR_*`, `OPENCODE_*`, `MSB_*`, timeouts (no real secrets committed)

## Do not

- Implement ledger, harness, or OpenCode plan loop yet

## Lint gate (required before Done when)

Run Biome + Knip and fix all findings before marking this step done (see [LINT.md](LINT.md)):

```bash
cd frontend
pnpm lint:fix && pnpm lint && pnpm knip
```

Must exit **0**. Do **not** start the next step while either tool fails. Python-only changes still require a green gate.

## Done when

Worker boots; frontend can reach explore health on the same host/network. Biome + Knip lint gate passes ([LINT.md](LINT.md)).

## Next

[03-ledger-core.md](03-ledger-core.md)
