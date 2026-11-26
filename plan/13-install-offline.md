# Step 13 — Install phase → deny-all remaining egress (D43, D63)

**Goal:** Attempt profile install with registries/git egress; preinstall assessment tooling; then **deny-all remaining guest egress** before verify (not “registries-denied” alone).

## Prerequisites

- [12-image-replace.md](12-image-replace.md)

## Read first

- [DECISIONS.md](../DECISIONS.md) D43, D63, D29, D65
- [ARCHITECTURE.md](../ARCHITECTURE.md) — network phases diagram
- [IMPLEMENTATION_TEST_VM.md](../IMPLEMENTATION_TEST_VM.md) § T2

## Vultr / msb tooling (required)

Use **`msb` CLI/SDK** (and Vultr MCP / `vultr-cli` to verify the VX1 host) per [VULTR.md](VULTR.md) and D59. Do not fake Plane 2 with Docker.

## Do

- [ ] Run `install_commands` / packages with install-phase egress
- [ ] Preinstall Playwright / MCP assessment / verify helpers in this phase (or bake into image) (D63)
- [ ] Probe control-plane denial **during install** with known-live target + positive control (D65)
- [ ] Flag failures honestly — never invent success (D29)
- [ ] Transition to **deny-all remaining egress** (loopback only) before readiness
- [ ] Log denied egress attempts as findings when observed
- [ ] Repair loop capped by `MAX_REPAIR_ATTEMPTS` (install errors only in this step)

## Do not

- Mark job `completed` after install
- Open control-plane destinations during install
- Defer Killhub assessment/browser installs until after readiness
- Treat “registries-denied” as equivalent to full offline

## Lint gate (required before Done when)

Run the full quality gate ([LINT.md](LINT.md)).

## Done when

Install attempts run under install egress; tooling is present; verify phase starts deny-all-remaining-egress; failures are flagged. Quality gate passes.

## Next

[14-readiness-verify.md](14-readiness-verify.md)
