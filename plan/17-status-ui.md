# Step 17 — Status window UI (N2)

**Goal:** Live status/progress/logs/evidence without refresh; reconnect restores state.

## Prerequisites

- [05-jobs-proxy-admission.md](05-jobs-proxy-admission.md)
- Prefer pipeline through [14-readiness-verify.md](14-readiness-verify.md) so there is real data

## Read first

- [IMPLEMENTATION_NEXTJS.md](../IMPLEMENTATION_NEXTJS.md) § N2
- [API.md](../API.md) — SSE types + keep-alives (D49, D50)

## Do

- [ ] StatusBadge + ProgressBar + `current_step`
- [ ] ProgressLog for `log` + `span` / `finding` / `containment` / `lifecycle`
- [ ] Tolerate keep-alives without UI flicker
- [ ] ScreenshotTimeline (empty OK)
- [ ] On load: snapshot + SSE reconnect with cursor

## Do not

- Build the full report dossier UI (step 19)

## Lint gate (required before Done when)

Run Biome + Knip and fix all findings before marking this step done (see [LINT.md](LINT.md)):

```bash
cd frontend
pnpm lint:fix && pnpm lint && pnpm knip
```

Must exit **0**. Do **not** start the next step while either tool fails. Python-only changes still require a green gate.

## Done when

Live updates work without refresh; leave/return restores via snapshot+SSE. Biome + Knip lint gate passes ([LINT.md](LINT.md)).

## Next

[18-vuln-receipt-finalize.md](18-vuln-receipt-finalize.md)
