# Step 20 — E2E fixtures + demo deploy (M7)

**Goal:** Pinned fixtures behave as specified; public demo is on **Vultr Cloud Compute** behind edge bind + admission + durable ledger.

## Prerequisites

- [18-vuln-receipt-finalize.md](18-vuln-receipt-finalize.md)
- [19-report-ui.md](19-report-ui.md)

## Read first

- [VULTR.md](VULTR.md) · [DECISIONS.md](../DECISIONS.md) D53, D54, D46, D40, D41, D24, **D59**
- [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md) — M7
- [IMPLEMENTATION_NEXTJS.md](../IMPLEMENTATION_NEXTJS.md) § N4
- [IMPLEMENTATION_EXPLORE_SANDBOX.md](../IMPLEMENTATION_EXPLORE_SANDBOX.md) § E6

## Vultr tooling (required)

- [ ] Inspect/confirm demo + VX1 hosts with **Vultr MCP** (read-only)
- [ ] Provision/mutate demo control-plane VM with **`vultr-cli`** (or Vultr API) — not a non-Vultr host (D24)
- [ ] Fixture sandboxes run via harness → **`msb`** on VX1
- [ ] If MCP/`vultr-cli`/`msb` unavailable: stop and report — do not declare M7 done on localhost-only

## Do

- [ ] **Assert** (do not first-time pin) fixtures from [10b-pin-fixtures.md](10b-pin-fixtures.md) still match D53
- [ ] Assert webapp → `original_application`; MCP filesystem → original readiness from **built checkout**; controlled fail → `setup_failed`
- [ ] Absolute expiry + cancel + completed always reclaim sandbox across Plane 1 restart
- [ ] Demo deploy: reverse proxy faces internet; app binds `127.0.0.1` (D46)
- [ ] Admission + ledger + host reaper live before public URL

## Do not

- Deploy without ledger/reaper/admission
- Deploy demo off Vultr
- Use NodeGoat as the deterministic fail fixture (D53)
- Fake fixture greens without `msb`
- Treat this step as the owner of first-time SHA pinning (that is 10b)

## Lint gate (required before Done when)

Run Biome + Knip and fix all findings before marking this step done (see [LINT.md](LINT.md)):

```bash
cd frontend
pnpm lint:fix && pnpm lint && pnpm knip
```

Must exit **0**. Do **not** start the next step while either tool fails. Python-only changes still require a green gate.

## Done when

Pinned fixtures pass on real **`msb`** sandboxes; demo URL is on Vultr behind edge proxy (verified via Vultr MCP/`vultr-cli`); sandboxes die on expiry even if control plane restarts. Biome + Knip lint gate passes ([LINT.md](LINT.md)).

## Next

[21-cleanup-docs.md](21-cleanup-docs.md) — remove build scaffolding docs once M7 is green.
