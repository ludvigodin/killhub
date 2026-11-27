# Plane 1 workers — Agents, Host LLM Proxy, Telemetry & Harness (`explore/`)

Implementation plan for the Plane 1 Python sidecar (`explore/`): durable SQLite WAL ledger, Internal Worker API, **Host LLM Proxy** (Layer 1 circuit breaker + key isolation), **Environment/Install Planner Agent**, **Test-Planner Agent**, **Cite-Checked Vuln Reviewer & Detonation Verdict Synthesizer**, host-side **TAP/`mitmdump`/PCAP** controller, **`AF_VSOCK`/UDS NDJSON telemetry receiver**, **Layer 3 hypervisor watchdog**, `msb` harness, and optional in-guest Playwright still capture.

These workers are **Plane 1** (control plane), not a disposable VM ([DECISIONS.md](DECISIONS.md) D27–D28, D52, D69–D74). Public Jobs API/SSE and view-only `noVNC` proxying are owned by Next.js ([IMPLEMENTATION_NEXTJS.md](IMPLEMENTATION_NEXTJS.md)). Plane 2 microVM internals live in [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md).

Architecture: [ARCHITECTURE.md](ARCHITECTURE.md) · Index: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) · Contracts: [API.md](API.md) · [DATABASE.md](DATABASE.md) · `schemas/*.json`

> **Mandatory Coding Rule (`AGENTS.md` §5 — R2) & Quality Gate (`plan/LINT.md`):**
> - Every Python file edit must include concise inline comments/docstrings explaining *what* and *why* key invariants, security boundaries, or guards exist.
> - Every new `.py` module must start with a module-level triple-quoted docstring (`"""..."""`, `ruff`-compliant) documenting: (1) what the module does, (2) its plane (`Plane 1`) & trust-zone responsibility, and (3) key contracts/invariants.
> - Every step must pass the full `plan/LINT.md` gate (`ruff check .`, `ruff format --check .`, `pytest -q`, `schemas/*.json` Draft 2020-12 validation, and `frontend/` Biome/Knip/tsc/build).

---

## Baseline Fixes to Fold In Before M2/M4 (`ALIGNMENT_PLAN.md` §3)

Verified directly against `main` @ `26f49db`:

1. **Fix Live-SSE `progress` hoisting (`explore/api/routes.py:141-152`):** Initial replay (`routes.py:111-114`) hoists `progress` and `current_step` to top-level SSE JSON, whereas the live-tailing loop (`routes.py:141-152`) only hoists `status`. Add `if event.type == "progress":` field hoisting in the live-tailing loop and a regression test in `explore/tests/test_internal_api.py`.
2. **Eliminate 13–15s Live-SSE poll latency (`explore/api/routes.py:122-139`):** Replace the `sleep(max(keepalive_seconds - 2, 0))` empty-poll sleep with a short poll or `asyncio.Event` wakeup notified on `Ledger.append_event`, tracking keepalive intervals independently.
3. **Enable SQLite WAL + `busy_timeout=5000` (`explore/ledger/store.py:99-106`):** Execute `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000;` in `Ledger.__init__` so concurrent `AF_VSOCK` telemetry writers, Host LLM Proxy accounting, and FastAPI readers do not raise `database is locked`.
4. **Lock down `docker-compose.yml` port (`docker-compose.yml:7-8`):** Change `ports: ["8100:8100"]` to `127.0.0.1:8100:8100` (or compose-internal `expose: ["8100"]`) so `INTERNAL_API_TOKEN` endpoints never bind `0.0.0.0` (`D46`).
5. **Align `explore/ruff.toml` & `explore/requirements-dev.txt`:** Bump `target-version` from `"py39"` to `"py310"` (matching `.venv` and `Dockerfile` 3.12 compatibility) and add `jsonschema>=4.23.0` to `requirements-dev.txt` for schema validation in `.venv`.

---

## Role & Pipeline

```
IN:  Public HTTPS github.com URL or MCP registry/fixture ref (npm:/pypi:/fixture: — D15)
       │
       ▼
Plane 1 Control Loop + Plane 2 Ubuntu 24.04 MicroVM
  −1. Pre-flight (D45)               → Plane 1 only when hard-fail applies
   0. Provision Ubuntu 24.04 VM      → mounts, RO rootfs+OverlayFS, mitmproxy CA, canaries,
                                       victim OpenCode seeds, TAP+mitmdump, AF_VSOCK/UDS, L2 cgroup
   1. Inspect & Plan Environment     → persist resolved_commit (D62); Env/Install Planner emits
                                       schemas/environment_profile.v1.json + schemas/dynamic_install_spec.v1.json
                                       (replace VM only on explicit custom oci_image override — D36)
   2. Phase 1 Install                → TAP+mitmdump; record package_sha256_before / package_sha256_after
   3. Discovery → Test Planner       → @modelcontextprotocol/inspector --cli --format json
                                       (initialize, tools/list, resources/list, prompts/list + Python SDK fallback)
                                       → t0_tools_sha256 → Plane 1 Test Planner emits schemas/test_scenario_plan.v1.json
   4. Phase 2a Monitored Detonation  → launch built checkout (D62); verify readiness (D30, D37, D51, D54);
      & Readiness                      execute TestScenarioPlan via in-VM OpenCode (view-only noVNC) + Host LLM Proxy (L1)
                                       under strace, OverlayFS, MCP wire tap, cgroup v2 (L2), mitmdump canary block;
                                       record final_tools_sha256 + tool_diffs
   5. Phase 2b Strict Offline Verify → drop remaining egress (loopback only) → 4-axis containment matrix (D58, D65)
   6. Finalize                       → Plane-1 SCA (copied lockfiles) + cite-checked vuln_review (D48)
                                       + DetonationVerdict (schemas/detonation_verdict.v1.json: 16 ATLAS + 10 OWASP MCP)
                                       + JobReceipt → L3 telemetry flush → confirmed msb destroy + TAP/overlay teardown
       │
       ▼
OUT: profile revisions + DynamicInstallSpec + TestScenarioPlan + DetonationVerdict + JobReceipt → completed|failed|cancelled
```

Explore, detonation, and test share **one** Ubuntu 24.04 microVM per job (`D27`, `D69`).

---

## Repo layout (target after Steps 06–20)

```
explore/
├── main.py                       # FastAPI entrypoint + startup reconciliation (D41)
├── config.py                     # Settings (Vultr models, LLM proxy, TAP/mitmdump, IPC, cgroups, budgets)
├── models.py                     # JobStatus, EventType (+ v2 telemetry/tool_diff/kill_switch/novnc), dataclasses
├── service.py                    # Admission, job orchestration, D61 cancel finalizer
├── worker.py                     # Background job runner + Layer 3 hypervisor wall-clock watchdog
├── jobs.py                       # Ledger facade
├── preflight.py                  # Plane-1 pre-flight for GitHub URLs + npm:/pypi:/fixture: targets (D15, D45)
├── llm_proxy.py                  # Plane 1 Host LLM Proxy + Layer 1 circuit breaker (D71, D72)
├── net_tap.py                    # Host TAP bridge, mitmdump HTTP/S+DNS, DoH/DoT/QUIC drop, canary block, PCAP (D70)
├── ipc_telemetry.py              # AF_VSOCK control + NDJSON telemetry receiver (UDS/mgmt0 fallback) (D71)
├── harness.py                    # msb CLI/SDK create/replace/wait/exec/copy/destroy + D60 + L3 flush/teardown
├── novnc_bridge.py               # Authenticated view-only noVNC frame bridge (drops client RFB input — D71)
├── agents/
│   ├── __init__.py
│   ├── inference.py              # Vultr Serverless Inference client + per-role model routing (D25, D74)
│   ├── env_planner.py            # Environment/Install Planner (profile + DynamicInstallSpec)
│   ├── test_planner.py           # Discovery → Test-Planner Agent (TestScenarioPlan) (D73)
│   └── vuln_reviewer.py          # Cite-checked vuln_review + DetonationVerdict synthesizer (D48, D73)
├── profile.py                    # Schema validation for environment_profile.v1.json & dynamic_install_spec.v1.json
├── verify.py                     # Readiness probes (MCP handshake / HTTP / command) + tool_diffs
├── vulnscan.py                   # Plane-1 SCA on copied lockfiles (D43, D63)
├── screenshots.py                # Optional in-guest Playwright still capture (D31, D38)
├── api/
│   ├── auth.py                   # INTERNAL_API_TOKEN bearer check
│   └── routes.py                 # /internal/jobs*, /verdict, /telemetry, /pcap, /novnc, /internal/llm-proxy
├── ledger/
│   ├── schema.py                 # SQLite DDL (v1 → v2 migration columns)
│   └── store.py                  # WAL + busy_timeout ledger store + D67 contiguous prefix pruning
├── helpers/                      # Allowlisted copy_in scripts (D60)
│   ├── mcp_stdio_verify.py       # In-guest JSON-RPC initialize -> initialized -> tools/list (D51)
│   ├── mcp_discover.py           # Python MCP SDK fallback for large tool catalogs (D73)
│   ├── guest_sensors.sh          # strace + OverlayFS upperdir diff + MCP wire tap + cgroup v2 wrapper
│   └── pkg_hash.py               # Deterministic package_sha256_before / after tree hasher
└── fixtures/
    └── m7.json                   # Pinned SHAs/versions for 3 baseline + 6 Demo Malicious MCP Scenarios (D53)

prompts/
├── discover_environment.md       # Env/Install Planner -> environment_profile.json + DynamicInstallSpec
├── validate_environment_spec.md
├── repair_from_errors.md
├── plan_mcp_tests.md             # Discovery JSON -> TestScenarioPlan (16 ATLAS + 10 OWASP MCP)
└── vuln_review.md                # Cite-checked summary + DetonationVerdict synthesis

schemas/                          # Draft 2020-12 JSON Schemas (validated in LINT.md)
├── environment_profile.v1.json
├── dynamic_install_spec.v1.json
├── test_scenario_plan.v1.json
└── detonation_verdict.v1.json
```

---

## Core Plane 1 Subsystems (`D69`–`D74`)

### 1. Host LLM Proxy & Key Isolation (`explore/llm_proxy.py`, `D71`, `D72`)

- **Endpoint:** `POST /internal/llm-proxy/v1/chat/completions` listening strictly on hypervisor IPC (`AF_VSOCK` or UDS / `mgmt0` fallback — **never** exposed on public HTTP or Next.js `/api/*`).
- **Key isolation:** In-VM OpenCode (`/home/agent/.config/opencode/`, `/home/agent/.local/share/opencode/opencode.db`) holds only a per-job ephemeral dummy bearer token (`kh_proxy_<job_id>_<nonce>`). `llm_proxy.py` validates the dummy token, strips it, injects `VULTR_INFERENCE_API_KEY` solely on Plane 1 outbound HTTPS calls to `https://api.vultrinference.com/v1/chat/completions`, and routes using `VULTR_INFERENCE_MODEL_VICTIM`.
- **Layer 1 Circuit Breaker (`D72`):** Tracks per-session state before forwarding:
  - `max_turns = 12` (`LLM_PROXY_MAX_TURNS`)
  - `max_tokens = 60000` cumulative (`LLM_PROXY_MAX_TOKENS`)
  - Repeated / oscillating tool-call detection (e.g. identical tool name + normalized arguments repeated `>= 3` times across recent turns)
  - On trip: returns HTTP **`429`** (`code: "kill_switch_layer1"`, `reason: "max_turns" | "max_tokens" | "oscillating_tool_call"`), increments `llm_proxy_429_blocks`, and emits `kill_switch` / `finding` SSE event.

### 2. Per-Agent Vultr Serverless Inference Model-Selection Routing (`D25`, `D74`)

Every agent role resolves its dedicated env var (falling back to `VULTR_INFERENCE_MODEL`) and routes exclusively through `https://api.vultrinference.com/v1`:

| Role | Env Var | Target Tier & Caps |
|------|---------|--------------------|
| Environment / Install Planner | `VULTR_INFERENCE_MODEL_PLANNER` | Structured Reasoning/Coding (`temp=0.1`, up to `40000` tokens across retries) |
| Test-Planner Agent | `VULTR_INFERENCE_MODEL_TESTER` | Strong Security Planning (`temp=0.2`, up to `30000` tokens) |
| In-VM Victim OpenCode | `VULTR_INFERENCE_MODEL_VICTIM` | Fast Tool-Calling Agent (`temp=0.2`, L1 hard cap `max_turns=12`, `max_tokens=60000`) |
| Cite-Checked Vuln Reviewer | `VULTR_INFERENCE_MODEL_REVIEW` | High-Precision Synthesis (`temp=0.0`, up to `30000` tokens) |

Worst-case total (`160k` tokens) stays within `INFERENCE_BUDGET_TOKENS_PER_JOB=200000` (`ALIGNMENT_PLAN.md` §6).

### 3. Environment/Install Planner & Discovery → Test-Planner (`D69`, `D73`)

- **`env_planner.py`:** Validates intake (`github_repo` | `npm_package` | `pypi_package` | `fixture`), inspects inside Plane 2, persists `resolved_commit` (`D62`), and outputs schema-valid `schemas/environment_profile.v1.json` + `schemas/dynamic_install_spec.v1.json` (saved to `storage/profiles/{job_id}/` and `storage/specs/{job_id}/`).
- **`test_planner.py`:** After Phase 1 install (`package_sha256_before`/`after`), runs `@modelcontextprotocol/inspector --cli --format json` (`initialize`, `tools/list`, `resources/list`, `prompts/list`, falling back to `explore/helpers/mcp_discover.py` for large tool catalogs > threshold), records `t0_tools_sha256`, wraps untrusted discovery output in strict untrusted-data delimiters (`ALIGNMENT_PLAN.md` S6), and emits schema-valid `schemas/test_scenario_plan.v1.json` (`storage/plans/{job_id}/scenario_plan.json`).

### 4. Host TAP/`mitmdump`, `AF_VSOCK`/UDS Telemetry & Layer 3 Watchdog (`D70`–`D72`)

- **`net_tap.py`:** Configures per-job TAP bridge + `iptables`/`nftables` denying Plane 1 CP, `msb` mgmt, sibling VMs, and **DoH/DoT/QUIC** (UDP/443, TCP/853, known DoH resolvers); runs transparent `mitmdump` (HTTP/S + DNS interception) with **real-time canary blocking** addon and optional bounded `tcpdump` PCAP (`storage/artifacts/{job_id}/capture.pcap`, capped by `MAX_PCAP_BYTES`). Switches cleanly across **Phase 1 (Install)** → **Phase 2a (Monitored Detonation)** → **Phase 2b (Strict Offline Containment, loopback only)**.
- **`ipc_telemetry.py`:** Receives bounded NDJSON lines (<= 64 KiB/line, `ALIGNMENT_PLAN.md` S4) over `AF_VSOCK` (or UDS/`mgmt0` fallback) from `strace`, OverlayFS `upperdir`, MCP wire tap, and cgroup v2 (`memory.events`/`pids.events`), redacts canary plaintext, and persists events/counters to `Ledger` + `storage/artifacts/{job_id}/telemetry.ndjson`.
- **Layer 3 Watchdog (`worker.py` / `harness.py`):** On `JOB_TIMEOUT_SECONDS` or detonation wall-clock expiry, signals a bounded graceful telemetry flush (`flush_grace_seconds`, default `5s`) over `AF_VSOCK`/UDS before `msb stop` + `msb remove` and deterministic **TAP/iptables/OverlayFS teardown**.

### 5. Cite-Checked `vuln_review` & `DetonationVerdict` Synthesizer (`D48`, `D73`)

- Runs Plane-1 SCA (`vulnscan.py`) on lockfiles copied via `D60` `copy_out`.
- Aggregates SCA, `inspector_diff` (`t0_tools_sha256` vs `final_tools_sha256`, `tool_diffs`), `package_sha256_before`/`after`, `mitmdump`/DNS/canary-block events, `strace`/`overlayfs`/`mcp_wire_tap`/`cgroup_v2`, 3-layer kill-switch triggers, 4-axis + key-isolation `containment_proof`, and `vuln_review` citations (`D48`).
- Emits and validates **`schemas/detonation_verdict.v1.json`** (covering all 16 `AML.TA0000`–`AML.TA0015` tactics and all 10 `MCP01:2025`–`MCP10:2025` classes) into `JobReceipt` **before** setting terminal status (`D61`, `D66`).

---

## Implementation phases

### E0 — Scaffold `[x]` (`02-scaffold-explore.md`)

- [x] FastAPI worker shell, `config.py`, `models.py`, `ruff.toml`, `Dockerfile`, `.env.example`

### E1 — Durable SQLite ledger + Internal Worker API `[x]` (`03`–`04`, fixes before `09`)

- [x] Durable SQLite ledger (`explore/ledger/`) owning job/event/revision/generation/receipt state (`D41`, `D52`)
- [x] Internal Worker API (`/internal/jobs*`, SSE replay + `cursor_expired` + contiguous `gap` pruning, D61 cancel finalizer)
- [ ] Fold in baseline fixes: `routes.py:141-152` live `progress` hoisting, `routes.py:122-139` poll latency, `store.py` SQLite WAL + `busy_timeout=5000`, `docker-compose.yml` `127.0.0.1:8100:8100`, `ruff.toml` `py310` + `jsonschema` in `requirements-dev.txt`
- [ ] Startup reconciliation vs live `msb` + orphaned TAP/OverlayFS cleanup (`D41`)
- [ ] Admission hooks + `[v2]` ledger columns/API routes (`/verdict`, `/telemetry`, `/pcap`, `/novnc`, `target_type`, `schemas/*.json` validation)

### E2 — Pre-flight, Host LLM Proxy, Planners & Discovery (`plan/09`–`12`)

- [ ] `preflight.py`: validate public `github.com` URLs and MCP registry/fixture targets (`npm:`, `pypi:`, `fixture:`) before create (`D15`, `D45`)
- [ ] Trusted Plane 1 OpenCode config (`D38`) + `llm_proxy.py` (`AF_VSOCK`/UDS/`mgmt0`, dummy token → `VULTR_INFERENCE_API_KEY`, Layer 1 circuit breaker `max_turns=12`/`max_tokens=60000`/oscillation→`429`, per-role model routing `D74`)
- [ ] Pin 3 baseline + 6 demo scenarios in `explore/fixtures/m7.json` (`plan/10b-pin-fixtures.md`, `D53`)
- [ ] Bootstrap Ubuntu 24.04 create (`D36`, `D69`) → clone + `resolved_commit` (`D62`) → `env_planner.py` (`environment_profile.v1.json` + `dynamic_install_spec.v1.json`) → custom-OCI `replace_environment` re-layering sensors/CA/mounts/IPC if needed (`D36`, `D64`)
- [ ] Discovery (`@modelcontextprotocol/inspector --cli --format json` + `mcp_discover.py` fallback → `t0_tools_sha256`) → `test_planner.py` (`test_scenario_plan.v1.json`, `D73`)

### E3 — Harness, TAP/`mitmdump`, Monitored Detonation & Containment (`plan/06`–`08`, `13`–`15`)

Depends on [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md).

- [ ] `harness.py`, `net_tap.py`, `ipc_telemetry.py`: `msb` lifecycle, `AF_VSOCK`/UDS control+telemetry, `D60` copy restrictions, TAP/`mitmdump`/DoH-DoT-QUIC drop/PCAP, mounts/canaries, Layer 2 cgroup v2 (`512M`/`0`/`64`/`100000 100000`), Layer 3 watchdog flush + teardown
- [ ] Phase 1 Install (`package_sha256_before`/`after`) → Phase 2a Monitored Detonation (in-VM OpenCode via `noVNC` + real-time canary blocking + `strace`/OverlayFS/wire tap; `final_tools_sha256` & `tool_diffs`; `readiness` + `verification.kind` — `D30`, `D37`, `D54`, `D62`) → Phase 2b Strict Offline Containment Verify (`D43`, `D58`, `D65`)
- [ ] Verify key isolation (`VULTR_INFERENCE_API_KEY` absent from guest) & 3-Layer Kill Switch triggers (`D71`, `D72`)

### E4 — Optional screenshots & `noVNC` Bridge (`plan/16`)

- [ ] `novnc_bridge.py`: job-scoped token check, strict `view_only=true`, RFB client-input frame drop, auto-close on destroy (`D71`)
- [ ] `screenshots.py`: in-guest Playwright stills for HTTP webapps only (`D31`, `D38`, `D60`)

### E5 — SCA + Cite-Checked `vuln_review` + `DetonationVerdict` + Finalize (`plan/18`)

- [ ] `vulnscan.py` on Plane 1 against copied lockfiles (`D43`, `D63`); best-effort on fail paths (`D53`)
- [ ] `vuln_reviewer.py`: cite-checked summary (`D48`) + schema-valid `DetonationVerdict` (`schemas/detonation_verdict.v1.json`) mapping all 16 ATLAS tactics and 10 OWASP MCP classes
- [ ] Persist `JobReceipt` + `DetonationVerdict` **before** terminal status (`D61`); Layer 3 telemetry flush + confirmed `msb` destroy + TAP/iptables/OverlayFS teardown (`D57`, `D66`, `D72`)

### E6 — Orchestration Hardening & E2E (`plan/20`)

- [ ] End-to-end verification of all **3 baseline fixtures + 6 Demo Malicious MCP Scenarios** (`D53`, `D73`), chaos/restart/cancel recovery, key-isolation proof, 3-layer kill-switch proof, and Vultr Cloud Compute deployment behind `127.0.0.1` + reverse proxy (`D24`, `D46`).

---

## Configuration

| Variable | Purpose |
|----------|---------|
| `VULTR_API_KEY` | VX1 host ops (Plane 1 only; never in Plane 2) |
| `VULTR_INFERENCE_BASE_URL` / `VULTR_INFERENCE_API_KEY` | `https://api.vultrinference.com/v1` (Plane 1 + Host LLM Proxy only — `D25`, `D71`) |
| `VULTR_INFERENCE_MODEL` + `_PLANNER` / `_TESTER` / `_VICTIM` / `_REVIEW` | Per-role Vultr model selection (`D74`) |
| `LLM_PROXY_HOST` / `LLM_PROXY_PORT` / `LLM_PROXY_MAX_TURNS` / `LLM_PROXY_MAX_TOKENS` | Host LLM Proxy + Layer 1 circuit breaker (`12` turns / `60000` tokens — `D71`, `D72`) |
| `OPENCODE_*` | Plane 1 host-locked config (`D38`) |
| `LEDGER_URL` | `sqlite:///./storage/ledger/killhub.db` (SQLite WAL + `busy_timeout=5000` — `D41`) |
| `MSB_HOST` / `MSB_DEFAULT_IMAGE` / `MSB_DEFAULT_CPUS` / `MSB_DEFAULT_MEMORY` | VX1 `msb` host & Ubuntu 24.04 base (`ubuntu-24.04-killhub`, `2` CPUs, `2Gi`–`4Gi`) |
| `MSB_NET_POLICY` / `TAP_BRIDGE` / `MITMDUMP_PORT` / `CAPTURE_PCAP` | Host TAP bridge, `mitmdump`, DoH/DoT/QUIC drop, optional PCAP (`D70`) |
| `VM_IPC_MODE` / `VSOCK_TELEMETRY_PORT` / `NOVNC_PROXY_BIND` | `af_vsock` \| `uds` \| `mgmt0` & `127.0.0.1` view-only `noVNC` bridge (`D71`) |
| `CGROUP_MEM_MAX` / `CGROUP_PIDS_MAX` / `CGROUP_CPU_MAX` | Layer 2 target caps (`512M`, `0` swap, `64` pids, `100000 100000` — `D72`) |
| `JOB_TIMEOUT_SECONDS` / `ENV_TTL_SECONDS` / `MAX_REPAIR_ATTEMPTS` | L3 watchdog, absolute `expires_at` (`D41`), retry cap |
| `MAX_CONCURRENT_JOBS` / `MAX_QUEUED_JOBS` / `INFERENCE_BUDGET_*` / `MAX_JOB_LOG_BYTES` / `MAX_COPY_BYTES` / `MAX_PCAP_BYTES` | Admission & artifact budgets (`D40`, `D60`, `D67`) |
| `VULN_SCAN_*` / `MAX_SCREENSHOTS_PER_JOB` / `SCREENSHOT_STORAGE` | SCA & still caps |

---

## Milestones

- [x] **E-M0:** Worker boots (`02`)
- [x] **E-M1:** Durable ledger drives Plane 1 API/SSE (`03`–`04`)
- [ ] **E-M2:** Pre-flight, Host LLM Proxy (`L1` breaker + key isolation), Env/Install Planner, Discovery→Test Planner (`09`–`12`)
- [ ] **E-M3:** Readiness + Phase 2a monitored detonation (`noVNC`, TAP/`mitmdump`, `strace`/OverlayFS/wire tap/`L2` cgroup) + Phase 2b containment (`06`–`08`, `13`–`15`)
- [ ] **E-M4:** View-only `noVNC` bridge + optional in-guest Playwright stills (`16`)
- [ ] **E-M5:** Plane-1 SCA + cite-checked `vuln_review` + `DetonationVerdict` (16 ATLAS + 10 OWASP MCP) + `JobReceipt` + L3 flush & destroy (`18`)
- [ ] **E-M6:** 3 baseline + 6 demo scenarios E2E + admission + Vultr demo deploy (`20`)
