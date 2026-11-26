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

- [ ] `replace_environment`: stop+remove → create new image → re-clone
- [ ] Re-plant canaries; re-apply net policy
- [ ] Emit `lifecycle` / `log.kind=sandbox_replace`
- [ ] Assert never two concurrent microVMs for one job
- [ ] Same-image path continues in place (no replace)

## Do not

- Split explore/test into two VMs
- Leave bootstrap VM running after replace

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
