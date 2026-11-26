# Step 16 — Optional in-guest screenshots (E4, D38)

**Goal:** Capture useful stills inside Plane 2; never gate completion; never run Playwright on Plane 1 against untrusted pages.

## Prerequisites

- [14-readiness-verify.md](14-readiness-verify.md)

## Read first

- [DECISIONS.md](../DECISIONS.md) D31, D38, D18
- [IMPLEMENTATION_EXPLORE_SANDBOX.md](../IMPLEMENTATION_EXPLORE_SANDBOX.md) § E4

## Vultr / msb tooling (required)

Use **`msb` CLI/SDK** (and Vultr MCP / `vultr-cli` to verify the VX1 host) per [VULTR.md](VULTR.md) and D59. Do not fake Plane 2 with Docker.

## Do

- [ ] Run Playwright **in guest** for HTTP verify when useful; `copy_out` stills
- [ ] Skip for CLI-only MCP / early fail
- [ ] Cap `MAX_SCREENSHOTS_PER_JOB` + disk budget; redact secrets
- [ ] Emit SSE `screenshot` only when captured

## Do not

- Block `completed` when timeline is empty
- Run untrusted page JS on the control plane

## Lint gate (required before Done when)

Run Biome + Knip and fix all findings before marking this step done (see [LINT.md](LINT.md)):

```bash
cd frontend
pnpm lint:fix && pnpm lint && pnpm knip
```

Must exit **0**. Do **not** start the next step while either tool fails. Python-only changes still require a green gate.

## Done when

HTTP webapp verify can attach an in-guest still; MCP-only jobs can finish with empty timeline. Biome + Knip lint gate passes ([LINT.md](LINT.md)).

## Next

[17-status-ui.md](17-status-ui.md)
