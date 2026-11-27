# Step 09 — Plane-1 pre-flight (D45)

**Goal:** Cheap checks run before bootstrap sandbox create; hard-fail skips VX1 burn.

## Prerequisites

- [05-jobs-proxy-admission.md](05-jobs-proxy-admission.md)
- [08-net-policy-canaries.md](08-net-policy-canaries.md) optional but preferred before plan loop

## Read first

- [DECISIONS.md](../DECISIONS.md) D45, D15, D40
- [ARCHITECTURE.md](../ARCHITECTURE.md) — plan loop step −1

## Do

- [x] After URL + admission: pre-flight module (metadata / cheap risk as available)
- [x] Hard-fail → terminal/failed with `finding.source=preflight`; **no** `msb create`
- [x] Soft signals → continue with findings attached
- [x] Emit `log.kind=preflight` / `finding` events

## Do not

- Run untrusted install on the control plane
- Create a sandbox “just to inspect” on hard-fail paths

## Lint gate (required before Done when)

Run Biome + Knip and fix all findings before marking this step done (see [LINT.md](LINT.md)):

```bash
cd frontend
pnpm lint:fix && pnpm lint && pnpm knip
```

Must exit **0**. Do **not** start the next step while either tool fails. Python-only changes still require a green gate.

## Done when

A deliberately invalid/hostile intake can fail before create; clean URLs proceed to bootstrap. Biome + Knip lint gate passes ([LINT.md](LINT.md)).

## Next

[10-opencode-lockdown.md](10-opencode-lockdown.md)
