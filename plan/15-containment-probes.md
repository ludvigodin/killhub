# Step 15 — Containment matrix + probes (D58)

**Goal:** Record multi-axis isolation evidence (timeout, host deny, sibling deny, host liveness) plus network/canary scans.

## Prerequisites

- [14-readiness-verify.md](14-readiness-verify.md)
- [08-net-policy-canaries.md](08-net-policy-canaries.md)

## Read first

- [DECISIONS.md](../DECISIONS.md) D26, D58, D65, D39, D44, D66
- [IMPLEMENTATION_TEST_VM.md](../IMPLEMENTATION_TEST_VM.md) § T4 / containment

## Vultr / msb tooling (required)

Use **`msb` CLI/SDK** (and Vultr MCP / `vultr-cli` to verify the VX1 host) per [VULTR.md](VULTR.md) and D59. Do not fake Plane 2 with Docker.

## Do

- [x] Emit `containment` evidence for: timeout_enforcement, host_access_denied, sibling_access_denied, host_liveness
- [x] Use **known-live** targets + host-side **positive controls**; classify `policy_denied` \| `infra_error` \| `tooling_missing` \| `inconclusive` (D65)
- [x] Also probe CP denial during **install** phase (already attempted in step 13 — retain evidence here)
- [x] `network_probe` to Plane 1 + management targets: only `policy_denied` counts as proven deny
- [x] Canary scan → high-severity `finding.source=canary` on **unexpected** hit; exclude deliberate probe sessions (D65)
- [x] Incomplete matrix ⇒ `containment.claim=incomplete` (not “proven”) — D66
- [x] **Not** CVE exploitation of the submitted app (D33)

## Do not

- Weaponize project CVEs
- Claim isolation from timeout alone or from a bare failed fetch
- Treat offline-mode failures as proof of control-plane denial

## Lint gate (required before Done when)

Run Biome + Knip and fix all findings before marking this step done (see [LINT.md](LINT.md)):

```bash
cd frontend
pnpm lint:fix && pnpm lint && pnpm knip
```

Must exit **0**. Do **not** start the next step while either tool fails. Python-only changes still require a green gate.

## Done when

Containment/network/canary results appear on the job stream/receipt fields; Plane 2 cannot call Plane 1 in the probe. Biome + Knip lint gate passes ([LINT.md](LINT.md)).

## Next

[16-screenshots.md](16-screenshots.md)
