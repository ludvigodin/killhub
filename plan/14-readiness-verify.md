# Step 14 — Readiness verify + verification kinds (D37, D54)

**Goal:** Set readiness evidence from real probes; label `verification.kind` honestly; do not destroy yet.

## Prerequisites

- [13-install-offline.md](13-install-offline.md)

## Read first

- [DECISIONS.md](../DECISIONS.md) D30, D37, D47, D54, D51 (MCP stdio helper if present)
- [IMPLEMENTATION_EXPLORE_SANDBOX.md](../IMPLEMENTATION_EXPLORE_SANDBOX.md) § E3 verify
- [IMPLEMENTATION_TEST_VM.md](../IMPLEMENTATION_TEST_VM.md) § T3

## Vultr / msb tooling (required)

Use **`msb` CLI/SDK** (and Vultr MCP / `vultr-cli` to verify the VX1 host) per [VULTR.md](VULTR.md) and D59. Do not fake Plane 2 with Docker.

## Do

- [ ] `verify.py`: `git_mcp` → MCP handshake that **lists tools**; `webapp`/`demo` → profile probe
- [ ] On pass: set `readiness` only — **not** `completed`, **not** destroy
- [ ] Record `verification.kind`: `original_application` \| `generated_demo` \| `setup_failed`
- [ ] If inventing `demo`, keep `verification.original_failure` visible
- [ ] Gates own success — agent cannot invent readiness (D47)

## Do not

- Destroy sandbox on readiness alone
- Collapse demo success into “app works”

## Lint gate (required before Done when)

Run Biome + Knip and fix all findings before marking this step done (see [LINT.md](LINT.md)):

```bash
cd frontend
pnpm lint:fix && pnpm lint && pnpm knip
```

Must exit **0**. Do **not** start the next step while either tool fails. Python-only changes still require a green gate.

## Done when

Pinned webapp + filesystem MCP fixtures set readiness; controlled fail fixture is `setup_failed` without demo escape; sandbox still alive. Biome + Knip lint gate passes ([LINT.md](LINT.md)).

## Next

[15-containment-probes.md](15-containment-probes.md)
