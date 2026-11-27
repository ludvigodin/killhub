# Killhub — Implementation Plan (Index)

Implementation is split by the **two** architecture planes. Use this file as the map; do the work in the plane docs and [`plan/`](plan/README.md).

**AI agents building the product:** take **one** step file from [`plan/`](plan/README.md) per session (`01`–`21`). Do not attempt the whole plan in one turn. Before marking any step done, run the full quality gate in [plan/LINT.md](plan/LINT.md) (`D68`) and comply with **`AGENTS.md` §5 (R2)** (inline comments/docstrings on every code edit + top-of-file module frontmatter on every new module). Step **21** cleans up the build ladder after M7 while preserving canonical docs and `schemas/*.json`.

Canonical docs: [PRODUCT.md](PRODUCT.md) · [AGENTS.md](AGENTS.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [DECISIONS.md](DECISIONS.md) · [DATABASE.md](DATABASE.md) · [API.md](API.md) · [ALIGNMENT_PLAN.md](ALIGNMENT_PLAN.md)

| Plane | Document | Owns |
|------:|----------|------|
| 1 | [IMPLEMENTATION_NEXTJS.md](IMPLEMENTATION_NEXTJS.md) | Next.js UI + Jobs API/SSE + authenticated view-only `noVNC` proxy + Verdict/ATLAS/OWASP UI |
| 1 | [IMPLEMENTATION_EXPLORE_SANDBOX.md](IMPLEMENTATION_EXPLORE_SANDBOX.md) | Plane 1 `explore/` sidecar: Ledger (SQLite WAL), Env/Install Planner, Test Planner, Cite-Checked Reviewer & Verdict Engine, Host LLM Proxy (`L1` breaker), TAP/`mitmdump` controller, `AF_VSOCK`/UDS telemetry receiver, `L3` watchdog, `msb` harness |
| 2 | [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md) | One disposable Ubuntu 24.04 Microsandbox per job (`D69`–`D73`): mounts/seeds/canaries, TAP/`mitmdump`/DNS/DoH-DoT-QUIC drop/PCAP, `AF_VSOCK`/UDS/`mgmt0`, in-VM OpenCode + `noVNC`, `strace`/OverlayFS/wire tap/cgroup v2 (`L2`), Discovery→Test-Planner, 6 demo scenarios |
| — | [plan/README.md](plan/README.md) | Agent-sized sequential steps (`01`–`21`) |
| — | [plan/LINT.md](plan/LINT.md) | Mandatory quality gate (Frontend Biome/Knip/tsc/build + Python Ruff/pytest + JSON Schema Draft 2020-12 + R2 docs) |
| — | [plan/VULTR.md](plan/VULTR.md) | Vultr MCP · `vultr-cli` · `msb` · Host LLM Proxy · `noVNC` · VX1 TAP/cgroup prerequisites (`D59`) |

```
┌─────────────────────────────────────────────────────────────────────────┐
│  PLANE 1 — Control plane (Next.js + explore/ on Vultr Cloud Compute)    │
│  → IMPLEMENTATION_NEXTJS.md + IMPLEMENTATION_EXPLORE_SANDBOX.md         │
│  Owns: Ledger, Planners, Verdict Engine, Host LLM Proxy (real key),     │
│        view-only noVNC proxy, TAP/mitmdump/PCAP, L3 watchdog, msb      │
└───────────────┬───────────────────────────────────▲─────────────────────┘
                │ msb create/exec/copy/destroy      │ AF_VSOCK / UDS / mgmt0
                │ + TAP bridge + view-only VNC      │ (LLM Proxy + NDJSON telemetry)
                ▼                                   │
┌───────────────────────────────────────────────────┴─────────────────────┐
│  PLANE 2 — Disposable Ubuntu 24.04 Microsandbox (one microVM on VX1)    │
│  → IMPLEMENTATION_TEST_VM.md                                            │
│  Owns: RO rootfs + OverlayFS, /workspace + canaries, victim OpenCode    │
│        (dummy token) + noVNC, Inspector/SDK, strace/wire-tap/cgroup L2  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Goal (product)

Given a public HTTPS `github.com` URL or validated MCP registry target (`npm:`, `pypi:`, pinned fixture ID — `D15`):

1. Plane 1 validates and admits the job (`D40`), runs pre-flight (`D45`), and owns job state in a durable SQLite WAL ledger (`D41`, `D52`).
2. Plane 1 provisions **one** Ubuntu 24.04 Microsandbox microVM (`D27`, `D36`, `D69`) with read-only rootfs + OverlayFS, baked `mitmproxy` CA, canary seeds (`.env`, `.ssh`, `.aws`), pre-seeded victim OpenCode (`opencode.db`, `.config/opencode/`, `.gitconfig` → Host LLM Proxy with ephemeral dummy token — `D71`), `/run/mcp-package-cache` tmpfs, TAP+`mitmdump` (DoH/DoT/QUIC drop — `D70`), `AF_VSOCK`/UDS/`mgmt0` IPC, and Layer 2 cgroup v2 caps (`D72`).
3. Environment/Install Planner emits validated `schemas/environment_profile.v1.json` + `schemas/dynamic_install_spec.v1.json` (`D51`, `D69`). Only explicit custom-OCI overrides replace the VM (re-applying sensors/CA/mounts/IPC, still one live VM — `D36`, `D64`).
4. **Phase 1 Install** uses TAP/`mitmdump` install egress and records `package_sha256_before`/`after`. For MCP targets, **Discovery** (`@modelcontextprotocol/inspector --cli --format json` + Python MCP SDK fallback) records `t0_tools_sha256` and feeds the Plane 1 **Test-Planner Agent** to produce `schemas/test_scenario_plan.v1.json` (`D73`).
5. **Phase 2a Monitored Detonation & Readiness** executes scenarios via in-VM OpenCode (viewable via authenticated **view-only `noVNC`**) under `strace`, OverlayFS `upperdir`, MCP wire tap, cgroup v2 (`512M` / `0` swap / `64` pids / `100000 100000`), `mitmdump` HTTP/S+DNS interception + **real-time canary blocking** + optional `tcpdump` PCAP, and the **3-Layer Kill Switch** (`D70`–`D72`). Captures `final_tools_sha256`, `tool_diffs`, `readiness`, and `verification.kind` (`D37`, `D54`). Optional Playwright stills run inside Plane 2 (`D31`, `D38`).
6. **Phase 2b Strict Offline Containment Verify** drops remaining egress (loopback only) to gather the 4-axis containment matrix with positive controls (`D43`, `D58`, `D65`).
7. Plane 1 runs SCA on copied lockfiles (`D43`, `D63`), cite-checked `vuln_review` (`D48`), and emits canonical **`DetonationVerdict`** (`schemas/detonation_verdict.v1.json`) mapped to all **16 MITRE ATLAS tactics (`AML.TA0000`–`AML.TA0015`)** and **10 OWASP MCP Top 10 (`MCP01:2025`–`MCP10:2025`)** into `JobReceipt` (`D73`), then executes Layer 3 telemetry flush + confirmed `msb stop/remove` + TAP/iptables/OverlayFS teardown (`D57`, `D61`, `D72`).

---

## Vulnerability vs detonation vs containment vs exploits (v1)

| Capability | In v1? | Where | Purpose |
|------------|--------|-------|---------|
| SCA / lockfile / known-advisory scan | **Yes** | E5 · `vulnscan.py` (Plane 1) | Surface known dependency risk in `VulnReport` (`source=sca`) |
| Discovery → Test-Planner → Monitored MCP Detonation | **Yes** | E2–E5 · T2–T3 (`D73`) | Enumerate MCP tools (`t0_tools_sha256`), execute scenario plans via in-VM OpenCode, detect tool drift (`tool_diffs`), prompt injection, backdoors, and canary exfil (`DetonationVerdict`) |
| AI cite-checked `vuln_review` & Verdict synthesis | **Yes** | E5 · `prompts/vuln_review.md` (`D48`) | Cite-checked summary grounded strictly in finding IDs across SCA + detonation + containment |
| Best-effort scan & partial verdict on fail path | **Yes** | E5 (controlled fail fixture — `D53`) | Emit SCA + available sensor telemetry even when readiness fails |
| 3-Layer Kill Switch + Containment probes | **Yes** | E3 · T4 · `D58`, `D65`, `D72` | Bound runaway loops (L1 proxy `429`, L2 cgroup v2, L3 watchdog), prove CP/sibling isolation & key isolation; **not** CVE exploitation |
| Auto-patch / remediate | **No** | — | Non-goal (`D11`) |
| Weaponize CVEs against non-target infra / generic web pentest suites | **No** | — | Non-goal (`D33`) |

---

## Suggested build order

Prefer [`plan/`](plan/README.md) steps **01→21** for agent sessions. Steps `01`–`05` are complete; steps `06`–`21` are reconciled with [ALIGNMENT_PLAN.md](ALIGNMENT_PLAN.md):

| Order | Work | `plan/` | Plane phases |
|------:|------|---------|--------------|
| 1 | Scaffold Next.js + `explore/` workers (`docker-compose`) | `01`–`02` `[x]` | N0 · E0 |
| 2 | Durable SQLite ledger + Internal Worker API; Next proxy + SSE cursor + admission | `03`–`05` `[x]` | N1 · E1 (`D52`, `D55`) |
| 3 | Ubuntu 24.04 microVM create/destroy + L3 watchdog; `AF_VSOCK`/UDS + exec/copy; TAP/`mitmdump` + DoH/DoT/QUIC drop + mounts/canaries | `06`–`08` | T0–T1 (`D39`, `D44`, `D69`–`D72`) |
| 4 | Pre-flight (GitHub + MCP registry); in-VM OpenCode + Host LLM Proxy (`L1` breaker + `D74` model routing); pin 3 baseline + 6 demo fixtures; Env/Install Planner (`DynamicInstallSpec`) + Discovery→Test Planner (`TestScenarioPlan`); custom-OCI replace | `09`–`12` | E2 (`D15`, `D36`, `D38`, `D51`, `D53`, `D69`–`D74`) |
| 5 | Phase 1 install (`package_sha256_before`/`after`, `L2` cgroup v2) → Phase 2a monitored detonation & Phase 2b offline; readiness + `tool_diffs` + wire tap/`strace` | `13`–`14` | E3 · T2–T3 (`D30`, `D43`, `D54`, `D62`, `D72`, `D73`) |
| 6 | Full 4-axis containment + key-isolation verification + 16 ATLAS / 10 OWASP MCP sensor matrix | `15` | E3 · T4 (`D58`, `D65`, `D70`–`D73`) |
| 7 | Optional in-guest Playwright stills + `noVNC` token gating; Status UI (`noVNC` live stream + telemetry/kill-switch SSE + `routes.py` progress bug fix) | `16`–`17` | E4 · N2 (`D18`, `D31`, `D49`, `D71`) |
| 8 | Plane-1 SCA + cite-checked `vuln_review` + `DetonationVerdict` (`schemas/detonation_verdict.v1.json`) + `JobReceipt` + L3 flush & teardown | `18` | E5 (`D48`, `D57`, `D61`, `D66`, `D72`, `D73`) |
| 9 | Report UI (`DetonationVerdict`, ATLAS 16-tactic matrix, OWASP MCP 10 classes, SHA/tool diffs, telemetry); E2E 3 baseline + 6 demo scenarios + Vultr reverse proxy deploy; doc cleanup | `19`–`21` | N3 · E6 · N4 · T4 (`D46`, `D53`, `D73`) |

---

## Cross-plane milestones

- [x] **M0:** Compose boots Plane 1 (`frontend` + `explore` workers)
- [x] **M1:** Durable ledger + Jobs API/SSE + admission from Plane 1
- [ ] **M2:** Ubuntu 24.04 microVM create/exec/copy/destroy via `msb`; `AF_VSOCK`/UDS IPC; TAP/`mitmdump` + DoH/DoT/QUIC drop; mounts/seeds/canaries; host reaper + L3 watchdog
- [ ] **M3:** Pre-flight (GitHub + MCP registry) + bootstrap + Env/Install Planner (`environment_profile.v1.json` + `DynamicInstallSpec`) + Discovery→Test Planner (`TestScenarioPlan`) + Host LLM Proxy (`L1` breaker, key isolation, `D74` models) + `10b` fixtures (3 baseline + 6 demo)
- [ ] **M4:** Phase 1 install (`package_sha256_before`/`after`, `L2` cgroup v2) → Phase 2a monitored detonation (`noVNC`, `mitmdump` canary block, `strace`, OverlayFS, wire tap) → Phase 2b offline verify + readiness gates (`t0_tools_sha256`, `final_tools_sha256`, `tool_diffs`)
- [ ] **M5:** Authenticated view-only `noVNC` live viewer + optional in-guest Playwright stills + live telemetry/kill-switch Status UI
- [ ] **M6:** Plane-1 SCA + cite-checked `vuln_review` + canonical `DetonationVerdict` (16 ATLAS + 10 OWASP MCP) + `JobReceipt` + L3 flush & confirmed destroy → `completed` (including fail/cancel paths)
- [ ] **M6b:** 4-axis containment + key-isolation + real-time canary-block + 3-layer kill-switch proof logged before destroy (`D58`, `D65`, `D70`–`D72`)
- [ ] **M7:** Pinned 3 baseline + 6 demo malicious MCP scenarios pass on real `msb`; verification kinds honest (`D54`); absolute expiry + confirm destroy across Plane 1 restart; edge bind `127.0.0.1` behind reverse proxy (`D46`)

---

## Cross-cutting

### Canonical schemas (`schemas/`, Draft 2020-12)

- `schemas/environment_profile.v1.json` — runtime executable profile (`D51`)
- `schemas/dynamic_install_spec.v1.json` — Ubuntu 24.04 microVM dynamic install, mounts/seeds, TAP/`mitmdump`, IPC, and 3-layer kill switch contract (`D69`–`D72`)
- `schemas/test_scenario_plan.v1.json` — Discovery snapshot (`t0_tools_sha256`) + Test-Planner scenarios mapped to `AML.TA*` and `MCP01:2025`–`MCP10:2025` (`D73`)
- `schemas/detonation_verdict.v1.json` — Canonical `DetonationVerdict` (`package_sha256_before`/`after`, `t0_tools_sha256`/`final_tools_sha256`/`tool_diffs`, 4-axis + key-isolation `containment_proof`, 16-tactic `atlas_coverage_matrix`, 10-class `owasp_mcp_coverage`, `telemetry`, `D73`)

### Key configuration

| Variable | Plane | Purpose |
|----------|------:|---------|
| `VULTR_API_KEY` | 1 | VX1 host ops (never injected into sandboxes) |
| `VULTR_INFERENCE_BASE_URL` / `VULTR_INFERENCE_API_KEY` | 1 | Vultr Serverless Inference (`https://api.vultrinference.com/v1`; Plane 1 + Host LLM Proxy only — `D25`, `D71`) |
| `VULTR_INFERENCE_MODEL` + `_PLANNER` / `_TESTER` / `_VICTIM` / `_REVIEW` | 1 | Per-agent model selection (`D74`; see [ALIGNMENT_PLAN.md](ALIGNMENT_PLAN.md) §6) |
| `LLM_PROXY_HOST` / `LLM_PROXY_PORT` / `LLM_PROXY_MAX_TURNS` / `LLM_PROXY_MAX_TOKENS` | 1 | Host LLM Proxy & L1 circuit breaker (`12` turns / `60000` tokens / oscillation→`429` — `D71`, `D72`) |
| `OPENCODE_*` / trusted config | 1 / 2 | Plane 1 host-locked planner config (`D38`); guest seeds `/home/agent/.config/opencode/` + `opencode.db` → Host LLM Proxy (`D71`) |
| `LEDGER_URL` | 1 | Durable SQLite WAL job/event store (`sqlite:///./storage/ledger/killhub.db`, `D41`, `D52`) |
| `INTERNAL_API_TOKEN` | 1 | Next.js → `explore/` loopback auth (`D52`) |
| `EVENT_RETENTION` / `MAX_JOB_LOG_BYTES` | 1 | SSE replay window & contiguous prefix pruning (`D55`, `D67`) |
| `MSB_HOST` / `MSB_DEFAULT_IMAGE` / `MSB_DEFAULT_CPUS` / `MSB_DEFAULT_MEMORY` | 1→2 | Ubuntu 24.04 detonation base (`ubuntu-24.04-killhub`, `2` CPUs, `2Gi`–`4Gi` headroom — `D36`, `D69`) |
| `MSB_NET_POLICY` / `TAP_BRIDGE` / `MITMDUMP_PORT` / `CAPTURE_PCAP` | 1→2 | Host TAP bridge, `mitmdump` HTTP/S+DNS interception, DoH/DoT/QUIC drop, optional PCAP (`D39`, `D70`) |
| `VM_IPC_MODE` / `VSOCK_TELEMETRY_PORT` / `NOVNC_PROXY_BIND` | 1→2 | `af_vsock` \| `uds` \| `mgmt0` IPC & `127.0.0.1` view-only `noVNC` proxy (`D46`, `D71`) |
| `CGROUP_MEM_MAX` / `CGROUP_PIDS_MAX` / `CGROUP_CPU_MAX` | 2 | Layer 2 cgroup v2 caps (`512M`, swap `0`, `64` pids, `100000 100000` — `D72`) |
| `JOB_TIMEOUT_SECONDS` / `ENV_TTL_SECONDS` | 1 / 2 | L3 hypervisor watchdog & absolute `expires_at` (`D41`, `D72`) |
| `MAX_REPAIR_ATTEMPTS` | 1 | Plan-loop retry cap (`D10`) |
| `MAX_CONCURRENT_JOBS` / `MAX_QUEUED_JOBS` / `INFERENCE_BUDGET_*` / `MAX_COPY_BYTES` / `MAX_PCAP_BYTES` | 1 | Admission & copy/disk budgets (`D40`, `D60`) |
| `VULN_SCAN_*` | 1 | SCA & verdict synthesizer settings |
| `MAX_SCREENSHOTS_PER_JOB` / `SCREENSHOT_STORAGE` | 1 | Optional Playwright still cap & storage |

### Out of scope (v1)

- Private GitHub repos / OAuth · multi-user auth / billing · long-lived customer sandboxes beyond TTL · GPU
- Auto-patching CVEs · weaponizing CVEs against non-target infrastructure / generic web pentest exploit suites (`D33`)
- Non-Vultr clouds · alternate LLM providers outside Vultr Serverless Inference (`D25`)
- Persistent full-session video recordings (live view-only `noVNC` and optional Playwright stills are in scope — `D18`, `D71`)
- Separate Explore VM vs Test VM (`D27`) · install allowlist that blocks Microsandbox-capable commands (`D29`)

### Definition of done (v1)

A user pastes a public GitHub URL or MCP registry target in Plane 1 (subject to admission) and, without refreshing, sees live status/progress, an authenticated **view-only `noVNC`** stream of in-VM OpenCode detonation, live `mitmdump`/`strace`/wire-tap/kill-switch telemetry, `environment_profile.json` + `DynamicInstallSpec` + `TestScenarioPlan`, verifiable readiness (`original_application`, `generated_demo`, or `setup_failed`), and a durable **`JobReceipt` + `DetonationVerdict`** mapped across all 16 MITRE ATLAS tactics and 10 OWASP MCP classes — while one Ubuntu 24.04 Microsandbox absorbs install, discovery, detonation, and containment probes and is destroyed cleanly on completion / fail / cancel / L3 expiry without `VULTR_*` keys ever entering Plane 2.
