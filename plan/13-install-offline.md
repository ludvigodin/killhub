# Step 13 — Phase 1 install (`package_sha256`, `L2` cgroup v2) → Phase 2a / 2b egress (D43, D70, D72)

**Goal:** Execute Phase 1 `DynamicInstallSpec` install under TAP/`mitmdump`, capture `package_sha256_before` and `package_sha256_after`, enforce **Layer 2 cgroup v2 hard caps** (`512M` / `0` swap / `64` pids / `100000 100000`), and reconcile Phase 2 egress into **Phase 2a (Monitored Detonation via TAP/`mitmdump` + real-time canary blocking)** and **Phase 2b (Strict Offline Containment Verify)**.

## Prerequisites

- [12-image-replace.md](12-image-replace.md)

## Read first

- [DECISIONS.md](../DECISIONS.md) D29, D43, D63, D65, **D69**, **D70**, **D72**
- [ARCHITECTURE.md](../ARCHITECTURE.md) — network phases diagram (`Phase 1` / `Phase 2a` / `Phase 2b`)
- [IMPLEMENTATION_TEST_VM.md](../IMPLEMENTATION_TEST_VM.md) § 3, § 4, § 5
- [AGENTS.md](../AGENTS.md) § 5 (R2 inline docs + module frontmatter)

## Vultr / msb tooling (required)

Use **`msb` CLI/SDK** (and Vultr MCP / `vultr-cli` to verify the VX1 host) per [VULTR.md](VULTR.md) and `D59`. Do not fake Plane 2 with Docker.

## Do

- [ ] **Phase 1 Install (`mode="install"`):**
  - Capture **`package_sha256_before`** via `explore/helpers/pkg_hash.py` (pre-install resolved artifact/manifest hash)
  - Execute `DynamicInstallSpec.install_commands` using `/run/mcp-package-cache` tmpfs and `mitmproxy` CA TLS env (`SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `NODE_EXTRA_CA_CERTS`) under TAP/`mitmdump` (CP/mgmt/siblings/DoH/DoT/QUIC denied)
  - Capture **`package_sha256_after`** and OverlayFS `upperdir` baseline (detects Scenario 3 post-install backdoor tamper); verify assessment/Playwright/verify tooling present (`D63`)
  - Probe control-plane denial **during Phase 1** with known-live target + positive control (`D65`)
  - Flag install failures honestly (`D29`); repair loop capped by `MAX_REPAIR_ATTEMPTS`
- [ ] **Layer 2 Guest cgroup v2 Hard Caps (`D72`):**
  - Wrap target MCP server / workload slice under `memory.max=512M`, `memory.swap.max=0`, `pids.max=64`, `cpu.max=100000 100000` (`explore/helpers/guest_sensors.sh`)
  - Monitor `memory.events` (`oom`, `oom_kill`) and `pids.events` (`max`), streaming hits over `AF_VSOCK`/UDS as `telemetry` / `kill_switch` (`layer2_cgroup_v2`)
- [ ] **Reconciled Phase 2 Network Transitions (`D43`, `D70`):**
  - **Phase 2a (`mode="monitored_detonation"`, default for MCP detonation):** Keep guest outbound HTTP/S + DNS routed through host TAP + `mitmdump` with **real-time canary blocking** (`block_http=true`, `block_dns=true`), **DoH/DoT/QUIC drop**, and optional `tcpdump` PCAP — while CP/mgmt/siblings stay denied
  - **Phase 2b (`mode="offline_verify"`):** Drop all remaining guest egress (loopback only) when transitioning into static offline containment checks

## Do not

- Mark job `completed` after install (`D37`)
- Blindly apply loopback-only offline mode during Phase 2a monitored detonation (would blind Scenarios 1, 3, 4, 5)
- Open control-plane, `msb` management, or sibling destinations in any phase

## Lint gate (required before Done when)

Run the **full quality gate** ([LINT.md](LINT.md) — `D68`, `D74`) including R2 compliance:

```bash
cd frontend && pnpm lint:fix && pnpm lint && pnpm knip && pnpm typecheck && pnpm build
cd ../explore && ../.venv/bin/ruff check . && ../.venv/bin/ruff format --check . && ../.venv/bin/pytest -q
cd .. && python3 -c "import json; from pathlib import Path; from jsonschema import Draft202012Validator; [Draft202012Validator.check_schema(json.loads(p.read_text())) or print('OK', p.name) for p in sorted(Path('schemas').glob('*.json'))]"
```

Must exit **0**.

## Done when

Phase 1 records `package_sha256_before`/`after`, cgroup v2 enforces `512M`/`0`/`64`/`100000 100000` with event streaming, Phase 2a (`mitmdump` + canary block + DoH/DoT/QUIC drop) and Phase 2b (loopback only) transitions work deterministically, and full quality gate + R2 docs pass ([LINT.md](LINT.md)).

## Next

[14-readiness-verify.md](14-readiness-verify.md)
