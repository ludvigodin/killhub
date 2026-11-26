# Step 19 — Report / receipt window (N3)

**Goal:** Terminal jobs show profile, readiness, receipt/vulns, and sandbox lifecycle honestly.

## Prerequisites

- [17-status-ui.md](17-status-ui.md)
- [18-vuln-receipt-finalize.md](18-vuln-receipt-finalize.md)

## Read first

- [IMPLEMENTATION_NEXTJS.md](../IMPLEMENTATION_NEXTJS.md) § N3
- [PRODUCT.md](../PRODUCT.md) — success / intake dossier

## Do

- [ ] Show `environment_profile.json`
- [ ] EnvStatus: readiness ≠ completion; show destroy/cleanup state
- [ ] Render receipt: gates, probes, lifecycle, `verification.kind`
- [ ] VulnReport by source (`sca`, `mcp_assessment`, `canary`, `network`, …)
- [ ] Cancel control; clear copy that scan ≠ pentest

## Do not

- Imply `generated_demo` means original app works

## Lint gate (required before Done when)

Run Biome + Knip and fix all findings before marking this step done (see [LINT.md](LINT.md)):

```bash
cd frontend
pnpm lint:fix && pnpm lint && pnpm knip
```

Must exit **0**. Do **not** start the next step while either tool fails. Python-only changes still require a green gate.

## Done when

Terminal jobs show profile, readiness or clear failure, receipt/vulns, and destroyed/`completed` state. Biome + Knip lint gate passes ([LINT.md](LINT.md)).

## Next

[20-e2e-fixtures-deploy.md](20-e2e-fixtures-deploy.md)
