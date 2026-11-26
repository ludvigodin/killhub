# Step 13 — Install phase → offline (D43)

**Goal:** Attempt profile install with registries/git egress; then detach/deny egress before verify.

## Prerequisites

- [12-image-replace.md](12-image-replace.md)

## Read first

- [DECISIONS.md](../DECISIONS.md) D43, D29
- [ARCHITECTURE.md](../ARCHITECTURE.md) — network phases diagram
- [IMPLEMENTATION_TEST_VM.md](../IMPLEMENTATION_TEST_VM.md) § T2

## Vultr / msb tooling (required)

Use **`msb` CLI/SDK** (and Vultr MCP / `vultr-cli` to verify the VX1 host) per [VULTR.md](VULTR.md) and D59. Do not fake Plane 2 with Docker.

## Do

- [ ] Run `install_commands` / packages with install-phase egress
- [ ] Flag failures honestly — never invent success (D29)
- [ ] Transition to offline/deny-egress before readiness
- [ ] Log denied egress attempts as findings when observed
- [ ] Repair loop capped by `MAX_REPAIR_ATTEMPTS` (install errors only in this step)

## Do not

- Mark job `completed` after install
- Open control-plane destinations during install

## Lint gate (required before Done when)

Run Biome + Knip and fix all findings before marking this step done (see [LINT.md](LINT.md)):

```bash
cd frontend
pnpm lint:fix && pnpm lint && pnpm knip
```

Must exit **0**. Do **not** start the next step while either tool fails. Python-only changes still require a green gate.

## Done when

Install attempts run under install egress; verify phase starts offline/deny; failures are flagged. Biome + Knip lint gate passes ([LINT.md](LINT.md)).

## Next

[14-readiness-verify.md](14-readiness-verify.md)
