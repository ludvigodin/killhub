# Step 14 — Readiness verify + verification kinds (D37, D54)

**Goal:** Set readiness evidence from real probes; label `verification.kind` honestly; do not destroy yet.

## Prerequisites

- [13-install-offline.md](13-install-offline.md)
- [10b-pin-fixtures.md](10b-pin-fixtures.md)

## Read first

- [DECISIONS.md](../DECISIONS.md) D30, D37, D47, D54, D51, D62, D66
- [IMPLEMENTATION_EXPLORE_SANDBOX.md](../IMPLEMENTATION_EXPLORE_SANDBOX.md) § E3 verify
- [IMPLEMENTATION_TEST_VM.md](../IMPLEMENTATION_TEST_VM.md) § T3

## Vultr / msb tooling (required)

Use **`msb` CLI/SDK** (and Vultr MCP / `vultr-cli` to verify the VX1 host) per [VULTR.md](VULTR.md) and D59. Do not fake Plane 2 with Docker.

## Do

- [x] `verify.py`: `git_mcp` → MCP handshake that **lists tools**; `webapp`/`demo` → profile probe
- [x] For `original_application`: launch **built checkout** at `resolved_commit` — no unpinned `npx -y` (D62)
- [x] On pass: set `readiness` only — **not** `completed`, **not** destroy
- [x] Record `verification.kind`: `original_application` \| `generated_demo` \| `setup_failed`
- [x] If inventing `demo`, keep `verification.original_failure` visible
- [x] Gates own success — agent cannot invent readiness (D47, D66)
- [x] Use pinned fixtures from step 10b

## Do not

- Destroy sandbox on readiness alone
- Collapse demo success into “app works”
- Satisfy original-application readiness via unversioned registry package launch

## Lint gate (required before Done when)

Run the full quality gate ([LINT.md](LINT.md)).

## Done when

Pinned webapp + filesystem MCP fixtures set readiness against their SHAs; controlled fail fixture is `setup_failed` without demo escape; sandbox still alive. Quality gate passes.

## Next

[15-containment-probes.md](15-containment-probes.md)
