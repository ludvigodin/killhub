# Step 12 — Same-job image replace (D36)

**Goal:** If runtime `oci_image` ≠ bootstrap, replace VM once; still one live sandbox.

## Prerequisites

- [11-bootstrap-discover.md](11-bootstrap-discover.md)

## Read first

- [DECISIONS.md](../DECISIONS.md) D36, D27
- [IMPLEMENTATION_TEST_VM.md](../IMPLEMENTATION_TEST_VM.md) § T2 replace path

## Vultr / msb tooling (required)

Use **`msb` CLI/SDK** (and Vultr MCP / `vultr-cli` to verify the VX1 host) per [VULTR.md](VULTR.md) and D59. Do not fake Plane 2 with Docker.

## Do

- [x] `replace_environment`: stop+remove prior **generation** → create new image → re-clone at **`resolved_commit`**
- [x] Inherit original job `expires_at` (do not extend); do not set job-level `destroyed_at` while replacement is alive (D64)
- [x] Re-plant canaries; re-apply net policy
- [x] Emit `lifecycle` / `log.kind=sandbox_replace`
- [x] Assert never two concurrent microVMs for one job
- [x] Same-image path continues in place (no replace)

## Do not

- Split explore/test into two VMs
- Leave bootstrap VM running after replace
- Re-clone at a floating ref that can drift from the inspected SHA

## Lint gate (required before Done when)

Run Biome + Knip and fix all findings before marking this step done (see [LINT.md](LINT.md)):

```bash
cd frontend
pnpm lint:fix && pnpm lint && pnpm knip
```

Must exit **0**. Do **not** start the next step while either tool fails. Python-only changes still require a green gate.

## Done when

Image-change fixture replaces exactly once; same-image path does not replace. Biome + Knip lint gate passes ([LINT.md](LINT.md)).

## Next

[13-install-offline.md](13-install-offline.md)
