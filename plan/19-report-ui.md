# Step 19 — Report / `DetonationVerdict` & receipt window (N3, D73)

**Goal:** Terminal jobs render the full `DetonationVerdict`, profile/install-spec/scenario-plan, SHA/tool diffs, 16 MITRE ATLAS + 10 OWASP MCP coverage matrices, 4-axis + key-isolation containment proof, 3-layer kill-switch status, telemetry/PCAP links, and sandbox lifecycle honestly.

## Prerequisites

- [17-status-ui.md](17-status-ui.md)
- [18-vuln-receipt-finalize.md](18-vuln-receipt-finalize.md)

## Read first

- [IMPLEMENTATION_NEXTJS.md](../IMPLEMENTATION_NEXTJS.md) § N3
- [PRODUCT.md](../PRODUCT.md) — success / intake dossier
- [API.md](../API.md) — `/verdict`, `/telemetry`, `/pcap`
- [DATABASE.md](../DATABASE.md) — `DetonationVerdict`, `VulnReport`, `JobReceipt`
- [AGENTS.md](../AGENTS.md) § 5 (R2 inline docs + module frontmatter)

## Do

- [ ] `SetupDocs.tsx`: render `environment_profile.json`, `DynamicInstallSpec`, and `TestScenarioPlan`
- [ ] `EnvStatus.tsx`: show `readiness` (never equated to completion), `verification.kind` (`original_application` | `generated_demo` | `setup_failed`) + `original_failure`, `resolved_commit`, `current_sandbox_generation`, `cleanup.status` / `destroyed_at`
- [ ] `DetonationVerdictView.tsx` (consuming `/api/jobs/{id}/verdict` or `snapshot.detonation_verdict` matching `schemas/detonation_verdict.v1.json`):
  - Verdict header (`CLEAN` | `SUSPICIOUS` | `MALICIOUS` | `ABORTED` | `INCONCLUSIVE`, `risk_score`, `summary`)
  - Target integrity (`package_sha256_before`, `package_sha256_after`, `integrity_tampered`)
  - MCP capability integrity (`discovery_method`, `t0_tools_sha256`, `final_tools_sha256`, `tool_diffs[]`, tool/resource/prompt counts)
  - Complete **16-tactic MITRE ATLAS (`AML.TA0000`–`AML.TA0015`)** and **10-class OWASP MCP Top 10 (`MCP01:2025`–`MCP10:2025`)** coverage grids
  - **4-axis + key-isolation `containment_proof`** (`timeout_enforcement`, `host_access_denied`, `sibling_access_denied`, `host_liveness`, `claim`, `key_isolation_verified`, `canary_blocking_verified`, `doh_dot_quic_dropped`)
  - **3-layer kill-switch status** (`layer1_llm_proxy` / `layer2_cgroup_v2` / `layer3_watchdog`) and runtime telemetry summary + `/api/jobs/{id}/pcap` download link
- [ ] `VulnReport.tsx`: severity- & source-grouped findings (`sca`, `mcp_assessment`, `intentional_app`, `canary`, `network`, `containment`, `runtime_sensor`, `kill_switch`, `preflight`) + cite-checked `vuln_review` (`D48`, `D53`)
- [ ] Cancel control + clear copy explaining SCA vs active MCP detonation vs isolation proofs (no CVE weaponization)

## Do not

- Imply `generated_demo` means original application works (`D54`)
- Hide `destroy_failed` or incomplete containment claims (`D57`, `D58`, `D66`)

## Lint gate (required before Done when)

Run the **full quality gate** ([LINT.md](LINT.md) — `D68`, `D74`) including R2 compliance:

```bash
cd frontend && pnpm lint:fix && pnpm lint && pnpm knip && pnpm typecheck && pnpm build
cd ../explore && ../.venv/bin/ruff check . && ../.venv/bin/ruff format --check . && ../.venv/bin/pytest -q
cd .. && python3 -c "import json; from pathlib import Path; from jsonschema import Draft202012Validator; [Draft202012Validator.check_schema(json.loads(p.read_text())) or print('OK', p.name) for p in sorted(Path('schemas').glob('*.json'))]"
```

Must exit **0**.

## Done when

Terminal jobs display profile/spec/plan, readiness or clear failure, full `DetonationVerdict` (ATLAS/OWASP/SHA/tool diffs/containment/kill-switch/telemetry), cited findings, and destroyed/`completed` state; full quality gate + R2 docs pass ([LINT.md](LINT.md)).

## Next

[20-e2e-fixtures-deploy.md](20-e2e-fixtures-deploy.md)
