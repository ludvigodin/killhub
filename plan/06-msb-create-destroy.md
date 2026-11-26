# Step 06 — Microsandbox create / destroy + reaper (T0)

**Goal:** Harness can create and destroy a named microVM via **`msb` CLI/SDK**; host reaper enforces absolute `expires_at`.

## Prerequisites

- [04-internal-worker-api.md](04-internal-worker-api.md) (harness lives in explore)
- Vultr VX1 host exists and `msb doctor` is green (block if unavailable — do not fake)

## Read first

- [VULTR.md](VULTR.md) · [DECISIONS.md](../DECISIONS.md) D22, D23, D41, D57, **D59**
- [IMPLEMENTATION_TEST_VM.md](../IMPLEMENTATION_TEST_VM.md) § T0, Host vs sandbox

## Vultr / msb tooling (required)

- [ ] Locate/verify the VX1 instance with **Vultr MCP** or `vultr-cli instance list` (D59)
- [ ] On the host: `msb doctor` (or Microsandbox MCP `runtime_check`) must pass
- [ ] Harness implements create/destroy by calling **`msb` CLI or official SDK** — not Docker, not a mock

## Do

- [ ] `harness.py`: `create_environment` / `wait_until_ready` / `destroy_environment` wrapping `msb create` / status / `msb stop` + `msb remove`
- [ ] Set absolute `expires_at` at create; `msb touch` must not extend it
- [ ] Emit lifecycle create/destroy events to the ledger
- [ ] Confirm destroy only sets `destroyed_at` after successful remove (D57)
- [ ] Host-side reaper for past `expires_at` + Plane 1 orphan reconcile stub

## Do not

- Install repo deps or readiness probes yet
- Skip real `msb` with a pretend success
- Use Docker/Podman as Plane 2

## Lint gate (required before Done when)

Run Biome + Knip and fix all findings before marking this step done (see [LINT.md](LINT.md)):

```bash
cd frontend
pnpm lint:fix && pnpm lint && pnpm knip
```

Must exit **0**. Do **not** start the next step while either tool fails. Python-only changes still require a green gate.

## Done when

Harness creates and destroys a microsandbox for a job id **via `msb`**; host reaper kills past `expires_at` without Plane 1; VX1 verified via Vultr MCP/`vultr-cli`. Biome + Knip lint gate passes ([LINT.md](LINT.md)).

## Next

[07-msb-exec-copy.md](07-msb-exec-copy.md)
