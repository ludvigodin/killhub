# Step 07 — Microsandbox exec + copy (T1)

**Goal:** Plane 1 runs commands and moves files via **`msb exec` / `msb copy`** (or SDK equivalents).

## Prerequisites

- [06-msb-create-destroy.md](06-msb-create-destroy.md)

## Read first

- [VULTR.md](VULTR.md) · [IMPLEMENTATION_TEST_VM.md](../IMPLEMENTATION_TEST_VM.md) § T1
- [API.md](../API.md) — harness contract · D59

## Vultr / msb tooling (required)

- [ ] Implement `exec` / `copy_in` / `copy_out` with **`msb exec`** and **`msb copy`** (or official SDK) only
- [ ] Optional debug: Microsandbox MCP sandbox tools — product path remains harness → `msb` (D23)

## Do

- [ ] `exec(environment_id, cmd)` → stdout/stderr/exit_code + per-call timeout
- [ ] `copy_in` / `copy_out`
- [ ] Assert Killhub API/inference keys are **absent** from guest env
- [ ] Stream exec failures as job `log` events (no secrets)

## Do not

- Clone/install untrusted repos yet (next steps)
- Mount Docker socket
- Shell into the guest with ad-hoc SSH instead of `msb exec` for the harness path

## Lint gate (required before Done when)

Run Biome + Knip and fix all findings before marking this step done (see [LINT.md](LINT.md)):

```bash
cd frontend
pnpm lint:fix && pnpm lint && pnpm knip
```

Must exit **0**. Do **not** start the next step while either tool fails. Python-only changes still require a green gate.

## Done when

A remote command runs via **`msb exec`** and output returns to Plane 1; keys not visible in guest env. Biome + Knip lint gate passes ([LINT.md](LINT.md)).

## Next

[08-net-policy-canaries.md](08-net-policy-canaries.md)
