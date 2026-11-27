# Step 18 — Plane-1 SCA, cite-checked `vuln_review`, `DetonationVerdict` & L3 finalize (E5, D48, D57, D61, D72, D73)

**Goal:** Run Plane-1 SCA on copied lockfiles, synthesize cite-checked `vuln_review` + schema-valid **`DetonationVerdict`** (`schemas/detonation_verdict.v1.json`) mapped across all 16 MITRE ATLAS tactics and 10 OWASP MCP classes, persist `JobReceipt` + verdict **before** terminal status, and execute Layer 3 telemetry flush + confirmed destroy + TAP/iptables/OverlayFS teardown.

## Prerequisites

- [14-readiness-verify.md](14-readiness-verify.md)
- [15-containment-probes.md](15-containment-probes.md)

## Read first

- [DECISIONS.md](../DECISIONS.md) D33, D35, D37, D43, D48, D49, D57, D61, D66, **D72**, **D73**, **D74**
- [DATABASE.md](../DATABASE.md) — `VulnReport`, `JobReceipt`, `DetonationVerdict`, 16 ATLAS & 10 OWASP MCP tables
- [API.md](../API.md) — `/verdict`, `/telemetry`, `/pcap`
- [IMPLEMENTATION_EXPLORE_SANDBOX.md](../IMPLEMENTATION_EXPLORE_SANDBOX.md) § E5
- [AGENTS.md](../AGENTS.md) § 5 (R2 inline docs + module frontmatter)

## Vultr / msb tooling (required)

Use **`msb` CLI/SDK** (and Vultr MCP / `vultr-cli` to verify the VX1 host) per [VULTR.md](VULTR.md) and `D59`. Do not fake Plane 2 with Docker.

## Do

- [ ] `explore/vulnscan.py`: SCA via **Plane 1** on lockfiles copied to `storage/artifacts/{job_id}/` (`D43`, `D63`); best-effort SCA + partial verdict on fail paths (`D53`)
- [ ] `explore/agents/vuln_reviewer.py` (using `VULTR_INFERENCE_MODEL_REVIEW`, `temp=0.0` — `D74`):
  - Cite-checked `vuln_review` (`prompts/vuln_review.md`) — every claim must cite a finding ID; drop uncited claims (`D48`)
  - Synthesize and validate **`DetonationVerdict`** against `schemas/detonation_verdict.v1.json` (`jsonschema.Draft202012Validator`):
    - `target`: `package_sha256_before`, `package_sha256_after`, `integrity_tampered`
    - `verdict`: `CLEAN` | `SUSPICIOUS` | `MALICIOUS` | `ABORTED` | `INCONCLUSIVE`, `risk_score`, `summary`, `kill_switch_triggered`
    - `containment_proof`: 4 D58 axes + `claim` + `key_isolation_verified` + `canary_blocking_verified` + `doh_dot_quic_dropped`
    - `mcp_capabilities`: `discovery_method`, `t0_tools_sha256`, `final_tools_sha256`, `tool_diffs[]`, counts
    - `findings[]` + complete 16-entry `atlas_coverage_matrix` (`AML.TA0000`–`AML.TA0015`) + complete 10-entry `owasp_mcp_coverage` (`MCP01:2025`–`MCP10:2025`) + `telemetry`
- [ ] Serve `GET /internal/jobs/{id}/verdict`, `/telemetry`, and `/pcap` from `explore/api/routes.py` (`API.md`)
- [ ] Persist `JobReceipt` (including `DetonationVerdict`, verification, probes, generations, findings) **before** terminal status (`D61`, `D66`)
- [ ] **Layer 3 Teardown in `finally` (`D57`, `D72`):** bounded graceful telemetry flush (`AF_VSOCK`/UDS) → `msb stop` + `msb remove` → TAP/iptables/OverlayFS teardown; set job-level `destroyed_at` **only** after confirmed remove of current generation else `cleanup.status=destroy_failed`
- [ ] Apply normative gate table (`D66`); separate `findings.source=sca` from `intentional_app` (`D53`); cancel path uses identical finalizer ordering (`D61`)

## Do not

- Weaponize CVEs or run generic web exploit suites (`D33`)
- Clear `readiness.passed` when detonation/SCA findings exist (`D37`, `D66`)
- Destroy on readiness alone or set terminal status before persisting `JobReceipt` + `DetonationVerdict`
- Run live in-guest `npm audit` against external registries after Phase 2b offline transition

## Lint gate (required before Done when)

Run the **full quality gate** ([LINT.md](LINT.md) — `D68`, `D74`) including R2 compliance:

```bash
cd frontend && pnpm lint:fix && pnpm lint && pnpm knip && pnpm typecheck && pnpm build
cd ../explore && ../.venv/bin/ruff check . && ../.venv/bin/ruff format --check . && ../.venv/bin/pytest -q
cd .. && python3 -c "import json; from pathlib import Path; from jsonschema import Draft202012Validator; [Draft202012Validator.check_schema(json.loads(p.read_text())) or print('OK', p.name) for p in sorted(Path('schemas').glob('*.json'))]"
```

Must exit **0**.

## Done when

Baseline and demo fixtures produce schema-valid `DetonationVerdict` (`schemas/detonation_verdict.v1.json`) + `JobReceipt` before terminal status; `/verdict`, `/telemetry`, and `/pcap` return accurate redacted payloads; L3 flush + confirmed destroy + TAP/overlay teardown complete cleanly; full quality gate + R2 docs pass ([LINT.md](LINT.md)).

## Next

[19-report-ui.md](19-report-ui.md)
