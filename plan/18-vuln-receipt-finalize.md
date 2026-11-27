# Step 18 — Vuln scan + receipt + finalize (E5)

**Goal:** SCA + cite-checked review + durable receipt; confirm destroy; terminal `completed`/`failed`.

## Prerequisites

- [14-readiness-verify.md](14-readiness-verify.md)
- [15-containment-probes.md](15-containment-probes.md)

## Read first

- [DECISIONS.md](../DECISIONS.md) D33, D48, D49, D57, D35, D37, D43, D61, D66
- [DATABASE.md](../DATABASE.md) — VulnReport, JobReceipt
- [IMPLEMENTATION_EXPLORE_SANDBOX.md](../IMPLEMENTATION_EXPLORE_SANDBOX.md) § E5

## Vultr / msb tooling (required)

Use **`msb` CLI/SDK** (and Vultr MCP / `vultr-cli` to verify the VX1 host) per [VULTR.md](VULTR.md) and D59. Do not fake Plane 2 with Docker.

## Do

- [x] `vulnscan.py` SCA via **Plane 1** on lockfiles copied to artifact dir (D43); best-effort on fail paths
- [x] Optional MCP assessment only when profile plans it — tooling already present (D35, D63)
- [x] Cite-checked `vuln_review` — drop uncited claims (D48)
- [x] Persist JobReceipt (verification, gates, probes, generations, findings) **before** terminal status
- [x] Destroy in finally; job-level `destroyed_at` only after confirmed remove of current generation (D57, D64)
- [x] Apply gate table (D66); mark `completed`/`failed` only after report + cleanup path (D37)
- [x] Cancel path uses same finalizer ordering (D61)

## Do not

- Weaponize CVEs / generic app exploit suites
- Clear readiness when findings exist
- Destroy on readiness alone
- Run live in-guest `npm audit` against the registry after offline
- Set terminal status before receipt

## Lint gate (required before Done when)

Run Biome + Knip and fix all findings before marking this step done (see [LINT.md](LINT.md)):

```bash
cd frontend
pnpm lint:fix && pnpm lint && pnpm knip
```

Must exit **0**. Do **not** start the next step while either tool fails. Python-only changes still require a green gate.

## Done when

At least one fixture yields SCA findings or clean bill; fail path still scans; receipt exists; destroy confirmed or `destroy_failed` visible. Biome + Knip lint gate passes ([LINT.md](LINT.md)).

## Next

[19-report-ui.md](19-report-ui.md)
