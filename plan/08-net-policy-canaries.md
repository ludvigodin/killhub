# Step 08 — Network policy + canaries (D39, D44)

**Goal:** Every create/replace applies Killhub net policy through **`msb` create flags/SDK** and plants randomized canaries.

## Prerequisites

- [07-msb-exec-copy.md](07-msb-exec-copy.md)

## Read first

- [VULTR.md](VULTR.md) · [IMPLEMENTATION_TEST_VM.md](../IMPLEMENTATION_TEST_VM.md) § Network policy + Canaries
- [DECISIONS.md](../DECISIONS.md) D39, D44, D19, D59
- [ARCHITECTURE.md](../ARCHITECTURE.md) — trust-zone matrix (D42)

## Vultr / msb tooling (required)

- [x] Encode network policy using Microsandbox **`msb` / SDK** `--net*` (or equivalent) on create — document exact flags in IMPLEMENTATION_TEST_VM.md
- [x] Verify VX1 / policy assumptions with Vultr MCP or `vultr-cli` if host networking/firewall is involved

## Do

- [x] Apply egress policy on create: deny control-plane + management; sibling isolation
- [x] Document concrete `--net*` / SDK flags in IMPLEMENTATION_TEST_VM.md
- [x] Plant randomized canaries (env/files); never real Killhub secrets
- [x] Do not log canary plaintext in SSE
- [x] Stub hooks for later `network_probe` / canary scan (step 15)

## Do not

- Implement full containment matrix yet
- Reintroduce a command allowlist (D29)
- Fake network isolation without `msb` policy

## Lint gate (required before Done when)

Run Biome + Knip and fix all findings before marking this step done (see [LINT.md](LINT.md)):

```bash
cd frontend
pnpm lint:fix && pnpm lint && pnpm knip
```

Must exit **0**. Do **not** start the next step while either tool fails. Python-only changes still require a green gate.

## Done when

New sandboxes have **`msb`-enforced** policy + canaries; guest cannot be created without the Killhub net policy path. Biome + Knip lint gate passes ([LINT.md](LINT.md)).

## Next

[09-preflight.md](09-preflight.md)
