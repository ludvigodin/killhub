# Step 15 — Containment matrix, 3-layer kill switch, key isolation & ATLAS/OWASP probes (D58, D65, D70–D73)

**Goal:** Wire full `AF_VSOCK`/UDS NDJSON telemetry, `mitmdump` HTTP/S+DNS interception, `tcpdump` PCAP, `strace`/OverlayFS/cgroup v2 event sensors, **3-layer kill switch** verification, **key-isolation verification**, 4-axis containment matrix, and map all detections across **16 MITRE ATLAS tactics (`AML.TA0000`–`AML.TA0015`)** and **10 OWASP MCP Top 10 (`MCP01:2025`–`MCP10:2025`)**.

## Prerequisites

- [14-readiness-verify.md](14-readiness-verify.md)
- [08-net-policy-canaries.md](08-net-policy-canaries.md)

## Read first

- [DECISIONS.md](../DECISIONS.md) D26, D39, D44, D58, D65, D66, **D70**–**D73**
- [DATABASE.md](../DATABASE.md) § "Normative Coverage Mapping Tables"
- [IMPLEMENTATION_TEST_VM.md](../IMPLEMENTATION_TEST_VM.md) § 4, § 5, § 7, § 9
- [AGENTS.md](../AGENTS.md) § 5 (R2 inline docs + module frontmatter)

## Vultr / msb tooling (required)

Use **`msb` CLI/SDK** (and Vultr MCP / `vultr-cli` to verify the VX1 host) per [VULTR.md](VULTR.md) and `D59`. Do not fake Plane 2 with Docker.

## Do

- [ ] **4-Axis Containment Matrix (`D58`, `D65`) — Phase 2a & Phase 2b:**
  - Emit `containment` evidence for: `timeout_enforcement`, `host_access_denied`, `sibling_access_denied`, `host_liveness`
  - Use **known-live** targets + host-side **positive controls**; classify `policy_denied` | `infra_error` | `tooling_missing` | `inconclusive` (only `policy_denied` counts toward proven deny)
  - Verify CP/mgmt denial in **both** Phase 1/2a (TAP/`mitmdump` active) and Phase 2b (loopback only); verify `AF_VSOCK`/UDS exposes only Host LLM Proxy & telemetry receiver (never Jobs API / `msb` mgmt)
  - Incomplete matrix ⇒ `containment_proof.claim = "incomplete"` (`D66`)
- [ ] **Key-Isolation & Real-Time Canary Blocking Proof (`D70`, `D71`):**
  - Assert `VULTR_INFERENCE_API_KEY` & `VULTR_API_KEY` absent from guest `/proc/*/environ`, `/home/agent/.config/opencode/`, and `opencode.db` → `containment_proof.key_isolation_verified = true`
  - Verify `mitmdump` HTTP/S+DNS real-time canary blocking (`canary_blocking_verified = true`) and DoH/DoT/QUIC drops (`doh_dot_quic_dropped = true`), excluding tagged harness probes from unexpected-canary findings (`D65`)
  - Capture optional bounded `tcpdump` PCAP to `storage/artifacts/{job_id}/capture.pcap` (`MAX_PCAP_BYTES`)
- [ ] **3-Layer Kill Switch Verification (`D72`):**
  - Exercise L1 Host LLM Proxy (`max_turns=12`, `max_tokens=60000`, oscillation→`429`), L2 guest cgroup v2 (`512M`/`0`/`64` + `memory.events`/`pids.events`), and L3 watchdog telemetry flush
- [ ] **16 MITRE ATLAS + 10 OWASP MCP Sensor Mapping (`D73`):**
  - Map all runtime findings (`mitmdump_http`, `mitmdump_dns`, `tcpdump_pcap`, `strace`, `overlayfs`, `mcp_wire_tap`, `cgroup_v2`, `llm_proxy`, `canary_monitor`, `inspector_diff`, `opencode_db_audit`, `hypervisor_watchdog`) to `AML.TA0000`–`AML.TA0015` and `MCP01:2025`–`MCP10:2025` matching `schemas/detonation_verdict.v1.json`

## Do not

- Weaponize project CVEs (`D33`)
- Claim isolation from timeout alone or from a bare failed fetch (`D65`)
- Treat Phase 2b offline-mode failures as proof of Phase 1/2a control-plane denial

## Lint gate (required before Done when)

Run the **full quality gate** ([LINT.md](LINT.md) — `D68`, `D74`) including R2 compliance:

```bash
cd frontend && pnpm lint:fix && pnpm lint && pnpm knip && pnpm typecheck && pnpm build
cd ../explore && ../.venv/bin/ruff check . && ../.venv/bin/ruff format --check . && ../.venv/bin/pytest -q
cd .. && python3 -c "import json; from pathlib import Path; from jsonschema import Draft202012Validator; [Draft202012Validator.check_schema(json.loads(p.read_text())) or print('OK', p.name) for p in sorted(Path('schemas').glob('*.json'))]"
```

Must exit **0**.

## Done when

Containment matrix (4 axes + `key_isolation_verified` + `canary_blocking_verified` + `doh_dot_quic_dropped`), 3-layer kill switch probes, PCAP/telemetry streams, and 16 ATLAS / 10 OWASP MCP sensor mappings emit clean structured events; full quality gate + R2 docs pass ([LINT.md](LINT.md)).

## Next

[16-screenshots.md](16-screenshots.md)
