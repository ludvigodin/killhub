# ALIGNMENT_PLAN.md — Killhub MicroVM Detonation & MCP Security Integration

**Baseline:** `main` @ `26f49db` (`plan/` steps `01`–`05` complete; `explore/` FastAPI + SQLite ledger + 15 passing tests; `frontend/` Next.js 16 proxy/admission/SSE shell).  
**Canonical project name:** `Killhub`  
**Scope:** Reconciles the existing two-plane Microsandbox architecture (`DECISIONS.md` `D1`–`D68`) with full **Ubuntu 24.04 microVM detonation**, **host-side TAP + `mitmdump` HTTP/S & DNS interception**, **`AF_VSOCK` / UDS / `mgmt0` telemetry & Host LLM Proxy key isolation**, **in-VM victim OpenCode + view-only `noVNC`**, **3-Layer Kill Switch**, **Discovery → Test-Planner pipeline**, **16 MITRE ATLAS + 10 OWASP MCP Top 10 observability**, **Detonation Verdict JSON**, and **6 Demo Malicious MCP Scenarios** (`D69`–`D74`).

---

## 1. Executive Reconciliation Summary

| Dimension | Baseline (`main` @ `26f49db`) | Reconciled Target Architecture (`D1`–`D74`) |
|-----------|-------------------------------|--------------------------------------------|
| **Plane 1 vs Plane 2** | Next.js + `explore/` on Plane 1; one `msb` microVM per job on Plane 2 (`D27`, `D28`, `D52`) | Retained — **single** Ubuntu 24.04 microVM per job for explore, detonation, and test (`D69`) |
| **OpenCode Role Split** | OpenCode assumed only on Plane 1 (`D7`, `D38`) | **Plane 1 Planners/Reviewers** (Env/Install Planner, Test Planner, Cite-Checked Reviewer) run in `explore/`; **Plane 2 Victim OpenCode** runs inside the microVM talking over `AF_VSOCK`/UDS/`mgmt0` to the **Plane 1 Host LLM Proxy** with an ephemeral dummy token (`D71`) |
| **Inference Key Isolation** | `VULTR_INFERENCE_API_KEY` on Plane 1 only (`D25`) | Unchanged: real key stays on Plane 1 inside `explore/` & the Host LLM Proxy; guest `/proc/*/environ`, `.config/opencode/`, and `opencode.db` hold only a dummy token (`D71`) |
| **Visual Observation** | Playwright stills only; session video out of scope (`D18`, `D31`) | Authenticated **view-only `noVNC`** stream proxied via Plane 1 for live in-VM OpenCode detonation + optional Playwright stills for webapps (persistent video still out of scope) |
| **Egress Model** | Phase 1 install → Phase 2 deny-all offline (`D43`) | **Phase 1 Install** (TAP+`mitmdump`, CP/mgmt/siblings/DoH/DoT/QUIC denied) → **Phase 2a Monitored Detonation** (TAP+`mitmdump` HTTP/S+DNS, DoH/DoT/QUIC drop, **real-time canary blocking**, optional `tcpdump` PCAP) → **Phase 2b Strict Offline Containment** (loopback only) (`D43`, `D70`) |
| **Intake & Provisioning** | Public HTTPS `github.com` only (`D15`); bootstrap + `oci_image` replace (`D36`) | Public HTTPS `github.com` + validated MCP registry targets (`npm:`, `pypi:`, pinned fixtures — `D15`); unified **Ubuntu 24.04** base (`D69`) provisioned via `DynamicInstallSpec`; custom-OCI replace re-layers sensors/CA/IPC (`D36`) |
| **MCP Security Pipeline** | Optional `mcp.security_assessment` (`D35`) | First-class **Discovery** (`@modelcontextprotocol/inspector --cli --format json` + Python MCP SDK fallback) → **Test-Planner Agent** (`TestScenarioPlan`) → Monitored Detonation → **`DetonationVerdict`** (`AML.TA0000`–`AML.TA0015`, `MCP01:2025`–`MCP10:2025`, `D73`) |
| **Kill Switch** | `JOB_TIMEOUT_SECONDS` + `INFERENCE_BUDGET_TOKENS_PER_JOB=200000` | **3-Layer Kill Switch** (`D72`): L1 Host LLM Proxy (`max_turns=12`, `max_tokens=60000`, oscillation→429); L2 Guest cgroup v2 (`512M`, swap `0`, `64` pids, `100000 100000` CPU); L3 Host hypervisor watchdog (telemetry flush → hard kill → TAP/iptables/overlay teardown) |
| **Agent Code Quality** | Tree + doc rules (`AGENTS.md` §5) | **R2 binding rules:** inline comments/docstrings on every code edit + top-of-file module frontmatter/header on every new module (`ruff`/`biome` compliant) |

---

## 2. Conflict Resolution Matrix (`C1`–`C8`)

| ID | Conflict / Tension Identified | Resolution & Canonical Decisions | Primary Updated Docs & Schemas |
|----|-------------------------------|----------------------------------|--------------------------------|
| **C1** | **Egress:** `D43` verify phase required blanket deny-all offline, blocking observation of outbound exfil in Scenarios 1, 3, 4, 5 | Split Phase 2 into **Phase 2a (Monitored Detonation Egress)** via host TAP + `mitmdump` (HTTP/S + DNS interception, DoH/DoT/QUIC drop, real-time canary blocking, optional PCAP) and **Phase 2b (Strict Offline Containment Verify)** (`D43`, `D44`, `D70`). | `DECISIONS.md`, `ARCHITECTURE.md`, `IMPLEMENTATION_TEST_VM.md`, `plan/08`, `plan/13`, `plan/15` |
| **C2** | **IPC:** "Plane 2 never calls Plane 1" (`D39`) vs guest telemetry & in-VM OpenCode → Host LLM Proxy | Keep general IP traffic from Plane 2 to Plane 1 Jobs API, `msb` mgmt, and sibling VMs **denied**; permit only hypervisor-constrained **`AF_VSOCK`** (control + NDJSON telemetry) or **UDS/`mgmt0`** fallback for Host LLM Proxy & telemetry (`D39`, `D42`, `D71`). | `AGENTS.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `API.md`, `IMPLEMENTATION_TEST_VM.md` |
| **C3** | **OpenCode & `noVNC`:** Plane 1 OpenCode + stills-only (`D7`, `D18`, `D38`) vs in-VM OpenCode + `noVNC` | Split roles: Plane 1 planners/reviewers remain host-locked (`D38`); Plane 2 runs **victim OpenCode** inside Ubuntu 24.04 microVM with dummy token → Plane 1 Host LLM Proxy, exposed via authenticated **view-only `noVNC`** WS proxy (`D7`, `D18`, `D71`). Persistent full-session video stays out of scope. | `AGENTS.md`, `PRODUCT.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `API.md`, `plan/10`, `plan/16`, `plan/17` |
| **C4** | **Base Image & Intake:** Bootstrap/custom OCI replace (`D36`) + GitHub-only (`D15`) vs unified Ubuntu 24.04 image + MCP registry intake | Standardize on pre-baked **Ubuntu 24.04** detonation image (`D69`) provisioned via `DynamicInstallSpec`; custom-OCI replace (`D36`) must re-layer sensors/CA/IPC. Extend `D15` to allow validated MCP registry specifiers (`npm:`, `pypi:`, pinned fixtures) alongside public HTTPS `github.com`. | `PRODUCT.md`, `DECISIONS.md`, `DATABASE.md`, `API.md`, `schemas/dynamic_install_spec.v1.json`, `plan/09`, `plan/11`, `plan/12` |
| **C5** | **Budgets & Caps:** `4Gi` VM RAM / `200k` job tokens vs `512M` cgroup / `60k` proxy tokens & missing kill switch | MicroVM boots with `2Gi`–`4Gi` headroom for Ubuntu OS + `noVNC` + OpenCode + Inspector, while **Layer 2 cgroup v2** caps the untrusted target workload slice at `512M` / `0` swap / `64` pids / `100000 100000` CPU; **Layer 1 LLM Proxy** enforces `12` turns / `60000` tokens / oscillation→429 within the `200000` total job token budget; **Layer 3** flushes telemetry before hard kill + teardown (`D72`). | `ARCHITECTURE.md`, `DECISIONS.md`, `plan/06`, `plan/10`, `plan/13`, `plan/15`, `plan/18` |
| **C6** | **Discovery, ATLAS/OWASP & 6 Scenarios:** `D33`/`D35` treated MCP assessment as optional; `D53` had only 3 fixtures | Elevate **Discovery (`@modelcontextprotocol/inspector` + SDK fallback) → Test Planner (`TestScenarioPlan`) → Monitored Detonation (`DetonationVerdict`)** to first-class MCP pipeline (`D33`, `D35`, `D73`); add all 16 MITRE ATLAS tactics + 10 OWASP MCP classes + 6 Demo Scenarios (`D53`, `D66`). | `PRODUCT.md`, `DECISIONS.md`, `DATABASE.md`, `API.md`, `schemas/*.json`, `plan/10b`, `plan/11`, `plan/14`, `plan/18`, `plan/19`, `plan/20` |
| **C7** | **`AGENTS.md` R2 Documentation Rule:** Missing inline doc & module frontmatter mandates | Add binding **R2** rules to `AGENTS.md` §5 requiring inline comments/docstrings on every code edit and top-of-file module headers (Python docstrings / TS JSDoc) on every new module, compliant with `ruff` & `biome`. | `AGENTS.md`, `DECISIONS.md` (`D74`), `plan/LINT.md`, `plan/06`–`20` |
| **C8** | **Model Selection & Handoffs:** Single `VULTR_INFERENCE_MODEL` & no teammate execution split | Define per-role Vultr Serverless Inference model plan (`D74`) and detailed handoff plans for **Teammate A** (VM/Observability) and **Teammate B** (Control-Plane/Agents/Frontend). | `DECISIONS.md` (`D74`), `ARCHITECTURE.md`, `ALIGNMENT_PLAN.md` §7–§8 |

---

## 3. Architectural Improvements (Reconciling Baseline Code & Infra Gaps)

Verified directly against `main` @ `26f49db` (`explore/`, `frontend/`, `docker-compose.yml`, `plan/LINT.md`):

1. **Fix Live-SSE `progress` Field Hoisting (`explore/api/routes.py:141-152`):**
   - *Gap:* Replay loop (`routes.py:111-114`) hoists `progress` and `current_step` to top-level SSE JSON (expected by `frontend/components/JobLiveView.tsx:92-95`), whereas the live-tailing loop (`routes.py:141-152`) only hoists `status`.
   - *Improvement:* Hoist `progress` and `current_step` in the live-tailing loop too, and add a focused regression test in `explore/tests/test_internal_api.py`.
2. **Eliminate 13–15s Live-SSE Poll Latency (`explore/api/routes.py:122-139`):**
   - *Gap:* `_event_stream` sleeps 2s, emits `: keepalive`, and then sleeps `max(keepalive_seconds - 2, 0)` (13s) before checking for new events, delaying live status/telemetry updates by up to 15s.
   - *Improvement:* Poll on a short interval (e.g. 0.5–1.0s) or wake on an in-process `asyncio.Event` / condition notified by `Ledger.append_event`, emitting `: keepalive` only when `elapsed >= keepalive_seconds`.
3. **Enable SQLite WAL Mode & `busy_timeout` (`explore/ledger/store.py:99-106`):**
   - *Gap:* `sqlite3.connect(...)` uses default rollback journal and default busy timeout; adding concurrent `AF_VSOCK` telemetry writers, Host LLM Proxy accounting, and FastAPI readers will trigger `database is locked`.
   - *Improvement:* Execute `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000;` in `Ledger.__init__`, alongside an asyncio/thread write lock or retry wrapper.
4. **Lock Down `docker-compose.yml` Internal Port (`docker-compose.yml:7-8`):**
   - *Gap:* `ports: ["8100:8100"]` exposes the Internal Worker API on `0.0.0.0:8100` on the host.
   - *Improvement:* Change to `127.0.0.1:8100:8100` (or compose-internal `expose: ["8100"]` only) so `INTERNAL_API_TOKEN` endpoints are never reachable off-host.
5. **Standardize `plan/LINT.md`, `.venv`, `ruff.toml`, and `jsonschema` Validation:**
   - *Gap:* `plan/LINT.md` references `explore/.venv` while the repo venv is `.venv/`; `.venv/` lacks `jsonschema` (installed in system `python3` at `4.23.0`); `explore/ruff.toml` sets `target-version = "py39"` while `.venv` is Python 3.10 and `Dockerfile` is 3.12; several `plan/06`–`20` inline lint snippets omit `typecheck`, `build`, `ruff`, and `pytest`.
   - *Improvement:* Align `plan/LINT.md` to `.venv/` (or explicit `python3 -m venv`), add `jsonschema` to `explore/requirements-dev.txt`, validate `schemas/*.json` in the quality gate, bump `ruff.toml` `target-version` to `"py310"` (or `"py312"` matching container), and standardize all `plan/` lint gates on the full Rule 1/3 check.
6. **Replace `[key: string]: unknown` in `frontend/lib/api.ts` & Extend Intake Contract:**
   - *Gap:* `JobSnapshot` leaves nested fields untyped (`[key: string]: unknown`), and `CreateJobBody` / `validate_github_url` / `frontend/lib/github.ts` reject MCP registry specifiers.
   - *Improvement:* Strongly type `DetonationVerdict`, `EnvironmentProfile`, `TestScenarioPlan`, `VulnReport`, `JobReceipt`, and `novnc` metadata in `frontend/lib/api.ts` matching `schemas/*.json`, and extend intake validation (`CreateJobBody`, `UrlForm.tsx`) for validated `npm:` / `pypi:` / fixture references per `D15`.

---

## 4. Potential Technical & Security Issues with Concrete Mitigations

| # | Risk / Technical Issue | Concrete Mitigation |
|---|------------------------|---------------------|
| **S1** | **`noVNC` Session Hijack or Interactive Guest Escape:** An unauthenticated or interactive `noVNC` WebSocket could let public internet users type into the victim OpenCode terminal or view another job's VM. | (1) Authenticate `/api/jobs/{id}/novnc` with a short-lived, `job_id`-scoped signed token issued on Plane 1; (2) enforce **strict view-only mode** (`view_only=true` at VNC server **and** drop all client→server RFB pointer/key/clipboard messages at the Plane 1 WS proxy); (3) bind internal VNC/websockify bridge to `127.0.0.1` (or UDS); (4) close proxy immediately on terminal status / VM destroy. |
| **S2** | **DoH / DoT / QUIC / Raw-Socket Evasion of `mitmdump`:** A malicious MCP server can hardcode `1.1.1.1:443` DoH, `8.8.8.8:853` DoT, UDP/443 QUIC, or raw ICMP/DNS tunneling to bypass HTTP/S interception. | Host TAP firewall (`iptables`/`nftables`) enforces default-deny outbound except: TCP/80 & TCP/443 redirected transparently to host `mitmdump`, and UDP/53 + TCP/53 redirected to host DNS interceptor (`mitmdump` DNS / dnsmasq hook). Explicitly **DROP** UDP/443 (QUIC), TCP/853 (DoT), known DoH IPs/ASNs, non-53 DNS, and raw IP-literal egress outside proxy, logging drops as `network` findings. |
| **S3** | **Static TLS Pinning / Ignored `SSL_CERT_FILE` (Go/Rust/custom OpenSSL):** Compiled MCP binaries that bundle roots or pin certs will fail TLS handshake with `mitmdump` rather than accepting `mitmproxy` CA. | Keep TLS-inspection bypass visible: log `mitmdump` TLS handshake errors (`tls_client_alert` / SNI) alongside DNS interceptor logs, `tcpdump` PCAP metadata, and `strace` `connect(2)` destination IPs so pinned exfil attempts are still caught, blocked (if canary/disallowed), and attributed without weakening TLS verification. |
| **S4** | **`AF_VSOCK` / UDS Telemetry Flood & PCAP Parser Bounds:** A noisy `strace` loop or malformed binary MCP payload could overflow NDJSON buffers, exhaust Plane 1 disk/SQLite, or crash host parsers. | (1) Cap guest→host NDJSON line size (e.g. 64 KiB/line) and stream rate with bounded ring buffers; (2) enforce `MAX_COPY_BYTES`, `MAX_PCAP_BYTES`, and `MAX_JOB_LOG_BYTES` with contiguous prefix pruning + `gap` tombstones (`D67`); (3) parse PCAP/telemetry strictly via non-evaluating JSON/struct parsers (`tshark`/`dpkt` bounded slices, never `eval`/pickle). |
| **S5** | **OverlayFS / `/workspace` / `tmpfs` Disk Exhaustion:** A malicious package install or MCP tool writing `/tmp` or `/workspace` could fill guest memory/disk or crash the VX1 host sparse file. | Mount `/run/mcp-package-cache` as a size-capped `tmpfs` (e.g. `256M`), cap `/workspace` OverlayFS backing file (e.g. `2G`), enforce Layer 2 cgroup v2 `memory.max=512M` + `memory.swap.max=0` on the target slice, and clean up `upperdir` + backing sparse image deterministically in Layer 3 teardown (`D69`, `D72`). |
| **S6** | **Indirect Prompt Injection Crossing Plane 2 → Plane 1 Planners/Reviewers:** Malicious MCP tool descriptions, `tools/list` output, or `strace`/PCAP strings could inject instructions into Plane 1 `Test Planner` or `vuln_review`. | (1) Wrap all guest-derived data in explicit untrusted-data XML/JSON delimiters in Plane 1 prompts; (2) give Plane 1 planners/reviewers **zero** shell/filesystem mutation tools (`D38`); (3) validate `TestScenarioPlan` and `DetonationVerdict` against strict JSON Schemas (`schemas/*.json`); (4) enforce `D48` cite-checking and `D66` deterministic gates so LLM text cannot alter verdict or terminal status. |
| **S7** | **`explore/` Concurrency & SSE Bugs:** Missing live `progress` hoisting (`routes.py:141-152`), 13–15s SSE sleep (`routes.py:122-139`), and SQLite lock contention (`store.py:99-106`). | Apply §3 improvements #1–#3 before M4/M5 telemetry integration (`plan/15`, `plan/17`). |
| **S8** | **Next.js `X-Forwarded-For` Spoofing & Process-Local Rate Limiter (`frontend/lib/admission.ts`, `route.ts`):** Clients can spoof `x-forwarded-for` unless stripped by edge proxy, and `perIp` map resets across worker replicas. | Configure Caddy/nginx reverse proxy (`D46`) to overwrite `X-Real-IP` / `X-Forwarded-For` from actual socket peer IP; move authoritative sliding-window rate limits into `explore/` SQLite ledger (or single Next.js instance on `127.0.0.1`) before public demo (`plan/20`). |

---

## 5. Discovery → Test-Planner Pipeline, ATLAS / OWASP MCP Mapping & 6 Demo Scenarios (`D73`)

### 5.1 Discovery → Test-Planner Flow

1. **Discovery (`@modelcontextprotocol/inspector --cli --format json` + Python MCP SDK fallback):**
   - Execute `initialize`, `tools/list`, `resources/list`, and `prompts/list` against the built checkout (`stdio` or `streamable_http`).
   - If `@modelcontextprotocol/inspector` truncates or times out on large tool catalogs (e.g. >50 tools or deep schemas), fall back transparently to a Killhub Python MCP SDK helper (`explore/helpers/mcp_discover.py`).
   - Normalize discovered capability manifest and compute SHA-256 **`t0_tools_sha256`**.
2. **Test-Planner Agent (Plane 1):**
   - Consumes the Discovery JSON, `environment_profile.json`, and `DynamicInstallSpec`.
   - Emits a schema-valid **`TestScenarioPlan`** (`schemas/test_scenario_plan.v1.json`) with root-level `target_atlas_tactics` (`AML.TA*`) and `target_owasp_mcp` (`MCP01:2025`–`MCP10:2025`), plus ordered `scenarios[]`, each specifying: `scenario_id`, `title`, `demo_fixture_id`, `category`, `atlas_tactics`, `owasp_mcp`, `trigger_steps[]`, `expected_invariants[]`, `catching_sensors[]`, and `max_turns`.
3. **Monitored Detonation & Diff:**
   - In-VM victim OpenCode executes the planned scenarios under `noVNC`, `mitmdump`, `strace`, OverlayFS, MCP wire tap, cgroup v2, and 3-layer kill switch.
   - Re-query `tools/list` post-detonation to compute **`final_tools_sha256`** and **`tool_diffs`** (`added`, `removed`, `modified_schema`, `modified_description`).
   - Synthesize **`DetonationVerdict`** (`schemas/detonation_verdict.v1.json`) with full `atlas_coverage_matrix` and `owasp_mcp_coverage`.

### 5.2 Complete 16 MITRE ATLAS Tactics (`AML.TA0000`–`AML.TA0015`) Sensor Mapping

| Tactic ID | MITRE ATLAS Tactic | Primary Killhub Sensors & Triggers |
|-----------|--------------------|------------------------------------|
| `AML.TA0000` | AI Model Access | `llm_proxy`, `opencode_db_audit`, `mcp_wire_tap`: unauthorized model proxy probe, token extraction attempt from `opencode.db`, or non-proxy LLM API endpoint dial blocked at TAP |
| `AML.TA0001` | AI Attack Adaptation | `mcp_wire_tap`, `inspector_diff`, `llm_proxy`: dynamic prompt/tool-description mutation mid-session or adversarial payload shaping detected across turns (Scenario 2) |
| `AML.TA0002` | Reconnaissance | `strace`, `mcp_wire_tap`, `mitmdump_dns`: enumeration of `/etc/passwd`, `~/.ssh`, `~/.aws`, network interfaces, or MCP host metadata probing |
| `AML.TA0003` | Resource Development | `mitmdump_http`, `mitmdump_dns`, `overlayfs`: fetching external second-stage scripts/packages or staging binaries in `/tmp` or `/workspace` post-install (Scenario 3) |
| `AML.TA0004` | Initial Access | `mcp_wire_tap`, `inspector_diff`, `opencode_db_audit`: malicious MCP server returning indirect prompt injection payload (e.g., Scenario 1 GitHub issue) or poisoned tool schema |
| `AML.TA0005` | Execution | `strace`, `mcp_wire_tap`, `cgroup_v2`: unexpected `execve`/`fork`/`clone` from MCP or OpenCode tool calls, shell metacharacter injection, or rogue subprocess spawn |
| `AML.TA0006` | Persistence | `overlayfs`, `strace`: post-install modification of installed package files (`package_sha256_after != package_sha256_before`, Scenario 3), `~/.bashrc`, cron, or `opencode.db` tampering |
| `AML.TA0007` | Defense Evasion | `mitmdump_dns`, `mitmdump_http`, `strace`: attempted DoH/DoT/QUIC bypass (`tcp/853`, `udp/443`, known DoH endpoints dropped), cert-pinning bypass, or clearing logs/`upperdir` artifacts |
| `AML.TA0008` | Discovery | `strace`, `inspector_diff`, `mcp_wire_tap`: tool-list drift/shadowing (`final_tools_sha256 != t0_tools_sha256`, Scenarios 2 & 5), internal port scanning, or `env` dumping |
| `AML.TA0009` | Collection | `strace`, `opencode_db_audit`, `canary_monitor`: `openat`/`read` of canary files (`/workspace/.env`, `/home/agent/.ssh/*`, `/home/agent/.aws/*`, `opencode.db`) by untrusted process (Scenario 4) |
| `AML.TA0010` | Exfiltration | `mitmdump_http`, `mitmdump_dns`, `canary_monitor`, `tcpdump_pcap`: canary token matched in outbound HTTP/S headers/body or DNS subdomain query; **blocked in real time** by `mitmdump` (Scenarios 1, 4) |
| `AML.TA0011` | Impact | `cgroup_v2`, `llm_proxy`, `hypervisor_watchdog`: resource exhaustion / infinite agent loop (Scenario 6) tripping L1 `429` (`max_turns=12` / `max_tokens=60000` / oscillation), L2 cgroup (`512M` / `64` pids), or L3 watchdog |
| `AML.TA0012` | Privilege Escalation | `strace`, `cgroup_v2`: `setuid`/`sudo`/capability elevation attempts, `/proc`/cgroup escape probes, or host filesystem access outside `/workspace` |
| `AML.TA0013` | Credential Access | `canary_monitor`, `strace`, `opencode_db_audit`: reading `.env`, `.ssh`, `.aws`, `.gitconfig`, or `opencode.db` tokens; verifying `VULTR_INFERENCE_API_KEY` absence (`key_isolation_verified`, Scenario 4) |
| `AML.TA0014` | Lateral Movement | `mitmdump_http`, `tcpdump_pcap`, `strace`: attempted connection from Plane 2 to Plane 1 control plane, `msb` management endpoints, or sibling sandboxes (`host_access_denied` / `sibling_access_denied`, Scenario 5) |
| `AML.TA0015` | Command and Control | `mitmdump_http`, `mitmdump_dns`, `tcpdump_pcap`, `mcp_wire_tap`: repeated beaconing, reverse-shell socket `connect()` in `strace`, or unauthorized C2 channel over HTTP/S/DNS (Scenario 5) |

### 5.3 OWASP MCP Top 10 (`MCP01:2025`–`MCP10:2025`) Sensor Mapping

| ID | OWASP MCP Top 10 Class | Primary Sensors & Verification Signals |
|----|------------------------|----------------------------------------|
| `MCP01:2025` | Token Mismanagement & Secret Exposure | `canary_monitor`, `mitmdump_http`, `mitmdump_dns`, `opencode_db_audit`, `strace`: reading or exfiltrating `.env`/`.ssh`/`.aws` canaries or `opencode.db` proxy tokens; `mitmdump` real-time block (Scenario 4) |
| `MCP02:2025` | Privilege Escalation via Scope Creep | `inspector_diff`, `mcp_wire_tap`, `strace`: tool gains undeclared filesystem/network capabilities after `t0`, or accesses paths outside declared `/workspace` scope |
| `MCP03:2025` | Tool Poisoning | `inspector_diff`, `mcp_wire_tap`, `llm_proxy`: hidden instructions in tool `description`/`inputSchema`, delayed rug-pull mutation (`t0_tools_sha256 != final_tools_sha256`), or shadowing (Scenarios 2 & 5) |
| `MCP04:2025` | Software Supply Chain Attacks & Dependency Tampering | `overlayfs`, `sca_scanner`, `mitmdump_http`: post-install package modification (`package_sha256_before != package_sha256_after`, Scenario 3), install-hook network calls, or vulnerable lockfile dependencies |
| `MCP05:2025` | Command Injection & Execution | `strace`, `mcp_wire_tap`: unsanitized tool arguments spawning `sh -c`/`bash`/subprocesses observed via `strace` `execve` (Scenario 4) |
| `MCP06:2025` | Prompt Injection via Contextual Payloads | `mcp_wire_tap`, `llm_proxy`, `canary_monitor`: external resource/tool output (e.g., GitHub issue body, Scenarios 1 & 5) hijacking victim OpenCode into unauthorized tool calls |
| `MCP07:2025` | Insufficient Authentication & Authorization | `inspector_diff`, `mcp_wire_tap`, `mitmdump_http`: Streamable HTTP MCP endpoint accepting unauthenticated calls or missing origin/session validation |
| `MCP08:2025` | Lack of Audit and Telemetry | `mcp_wire_tap`, `llm_proxy`, `cgroup_v2`, `hypervisor_watchdog`: missing telemetry stream, runaway resource exhaustion, or tamper attempt against `/dev/vsock` / NDJSON logging / `opencode.db` audit (Scenario 6) |
| `MCP09:2025` | Shadow MCP Servers | `strace`, `mitmdump_http`, `mcp_wire_tap`: target spawns an undeclared background MCP listener/subprocess not declared in `DynamicInstallSpec.launch` (Scenario 3) |
| `MCP10:2025` | Context Injection & Over-Sharing | `opencode_db_audit`, `mcp_wire_tap`, `llm_proxy`: cross-tool context contamination, infinite agent loop correlation, or leaking prior prompt/session context across tool boundaries (Scenario 6) |

### 5.4 The 6 Demo Malicious MCP Scenarios (`D53`, `D73`)

| # | Scenario | Fixture / Source | Trigger Steps | Expected Invariant | Catching Sensors |
|---|----------|------------------|---------------|--------------------|------------------|
| **1** | **Indirect prompt injection via GitHub issue** (`scenario-1-indirect-prompt-injection`) | DVMCP / issue-reader MCP fixture | Test Planner directs OpenCode to summarize a crafted issue containing hidden exfil instructions | Issue text must not cause unauthorized tool execution or outbound exfiltration | `mcp_wire_tap`, `mitmdump_http`, `mitmdump_dns`, `canary_monitor` (`AML.TA0004`, `AML.TA0010`; `MCP06:2025`) |
| **2** | **Delayed tool obfuscation / rug pull** (`scenario-2-tool-rug-pull`) | Stateful MCP fixture mutating tool schema/doc after N calls | Discovery records `t0_tools_sha256`; Test Planner invokes tool repeatedly across turns; re-runs `tools/list` | Tool definitions & descriptions remain immutable between `t0` and final state | `inspector_diff` (`t0_tools_sha256` ≠ `final_tools_sha256`, `tool_diffs`), `mcp_wire_tap` (`AML.TA0001`, `AML.TA0008`; `MCP03:2025`) |
| **3** | **Post-install modified package backdoor** (`scenario-3-post-install-backdoor`) | Registry/tarball fixture w/ install-time or runtime payload mutation | Capture `package_sha256_before` → Phase 1 install → capture `package_sha256_after` + launch | Installed tree matches declared manifest without post-install file tamper or unexpected spawns | `overlayfs` (`package_sha256_before` ≠ `after`, `upperdir`), `strace` (`execve`), `mitmdump_http` (`AML.TA0003`, `AML.TA0006`; `MCP04:2025`, `MCP09:2025`) |
| **4** | **Host microVM credential exfiltration via OpenCode tools & `opencode.db`** (`scenario-4-credential-exfiltration`) | Exfil-seeking MCP fixture | Tool prompts OpenCode / reads `/workspace/.env`, `.ssh`, `.aws`, `opencode.db` and attempts HTTP/DNS exfil | Guest has zero real `VULTR_*` keys; canary reads & exfil are blocked in real time | `strace` (`openat`), `opencode_db_audit`, `canary_monitor`, `mitmdump_http`, `mitmdump_dns`, `llm_proxy` (`AML.TA0009`, `AML.TA0010`, `AML.TA0013`; `MCP01:2025`, `MCP05:2025`) |
| **5** | **External manipulation of a clean MCP server via tool drift / shadowing** (`scenario-5-tool-drift-shadowing`) | Clean MCP server + malicious companion/external metadata source | Clean server runs alongside untrusted external feed/sibling tool attempting shadowing | Clean server's `tools/list` and invocation routing are not shadowed or hijacked | `inspector_diff` (`tool_diffs`), `mcp_wire_tap`, `mitmdump_http`, `mitmdump_dns`, `strace` (`AML.TA0008`, `AML.TA0014`, `AML.TA0015`; `MCP03:2025`, `MCP06:2025`) |
| **6** | **Resource exhaustion via infinite agent loop** (`scenario-6-infinite-loop-exhaustion`) | Recursive/oscillating MCP tool fixture | MCP tool repeatedly returns self-referential tasks or spawns processes/allocates RAM | Runaway agent & processes bounded cleanly without crashing VX1 host | **3-Layer Kill Switch:** `llm_proxy` (`max_turns=12`, `max_tokens=60000`, oscillation→429), `cgroup_v2` (`512M`/`64` pids/`memory.events`), `hypervisor_watchdog` flush (`AML.TA0011`; `MCP08:2025`, `MCP10:2025`) |

---

## 6. LLM Model-Selection Plan (`D25`, `D74`)

All inference calls route exclusively through **Vultr Serverless Inference** (`https://api.vultrinference.com/v1`) using `VULTR_INFERENCE_API_KEY` on Plane 1. Each role reads its dedicated env var and falls back to `VULTR_INFERENCE_MODEL`:

| Agent / Task | Plane | Env Var (Fallback: `VULTR_INFERENCE_MODEL`) | Recommended Vultr Model Tier | Temp | Token / Turn Caps | Rationale |
|--------------|-------|---------------------------------------------|------------------------------|------|-------------------|-----------|
| **Environment / Install Planner** (`discover_environment`, `validate_environment_spec`, `repair_from_errors`) | Plane 1 (`explore/`) | `VULTR_INFERENCE_MODEL_PLANNER` | **Structured Reasoning / Coding Tier** (e.g., `qwen2.5-coder-32b-instruct` or `llama-3.3-70b-instruct` on Vultr Serverless) | `0.1` | Up to `40000` tokens across `MAX_REPAIR_ATTEMPTS` | High JSON Schema adherence for `environment_profile.json` and `DynamicInstallSpec`, plus accurate build-error diagnosis |
| **Test-Planner Agent** (`plan_mcp_tests`) | Plane 1 (`explore/`) | `VULTR_INFERENCE_MODEL_TESTER` | **Strong Reasoning / Security Planning Tier** (e.g., `llama-3.3-70b-instruct` or `deepseek-r1-distill-llama-70b`) | `0.2` | Up to `30000` tokens/job | Must map arbitrary Discovery `tools/list` schemas into targeted `TestScenarioPlan` probes across 16 ATLAS tactics & 10 OWASP MCP classes |
| **In-VM Victim OpenCode Agent** (executes scenarios via Host LLM Proxy) | Plane 2 (via Plane 1 Proxy) | `VULTR_INFERENCE_MODEL_VICTIM` | **Fast Tool-Calling Agent Tier** (e.g., `qwen2.5-coder-32b-instruct` or `llama-3.1-8b-instruct` / `llama-3.3-70b-instruct` w/ native OpenAI tool calling) | `0.2` | **L1 Hard Cap:** `max_turns=12`, `max_tokens=60000`, oscillation→429 | Needs reliable OpenAI-compatible MCP tool calling under low latency for live `noVNC` demos while staying bounded by L1 proxy caps |
| **Cite-Checked Vuln Reviewer & Verdict Synthesizer** (`vuln_review`) | Plane 1 (`explore/`) | `VULTR_INFERENCE_MODEL_REVIEW` | **High-Precision Synthesis Tier** (e.g., `llama-3.3-70b-instruct`) | `0.0` | Up to `30000` tokens/job | Deterministic zero-temperature summarization grounded strictly in finding IDs (`D48`) without hallucinating uncited risks |

*Budget math (`D40`, `D72`):* Worst-case sum across Planner (`40k`) + Test Planner (`30k`) + Victim Proxy (`60k`) + Reviewer (`30k`) = `160k` tokens, leaving `40k` headroom inside `INFERENCE_BUDGET_TOKENS_PER_JOB=200000`.

---

## 7. Multi-Agent Teammate Handoff Notes (`plan/06`–`plan/21`)

All teammates **must follow `AGENTS.md` §5 (R2)**: add concise inline comments/docstrings on every code edit and a top-of-file module docstring / JSDoc header on every new module, and pass the full `plan/LINT.md` quality gate on both `explore/` and `frontend/` before marking any step complete.

### 7.1 Teammate A — VM-Provisioning & Runtime Observability (`Plane 2` & VX1 Harness)

- **Owns `plan/` steps:** `06-msb-create-destroy.md`, `07-msb-exec-copy.md`, `08-net-policy-canaries.md`, `10b-pin-fixtures.md`, `12-image-replace.md`, `13-install-offline.md`, `14-readiness-verify.md`, `15-containment-probes.md`, `16-screenshots.md`, and the VX1/`msb`/fixture portion of `20-e2e-fixtures-deploy.md`.
- **Key modules to build (in `explore/` & `explore/helpers/`):**
  - `explore/harness.py` (`msb` CLI/SDK wrapper, `DynamicInstallSpec` execution, custom-OCI `replace_environment` re-layering, Layer 3 hypervisor wall-clock watchdog with graceful telemetry flush + hard kill + TAP/iptables/OverlayFS teardown).
  - `explore/net_tap.py` (host TAP bridge, `mitmdump` HTTP/S + DNS interception launcher, `iptables`/`nftables` DoH/DoT/QUIC drop rules, real-time canary blocking addon, optional `tcpdump` bounded PCAP capture, Phase 1 / Phase 2a / Phase 2b transitions).
  - `explore/ipc_telemetry.py` (`AF_VSOCK` control + NDJSON telemetry receiver with UDS/`mgmt0` fallback, bounded line/byte ingestion, `D67` budget awareness).
  - `explore/helpers/` (allowlisted `copy_in` scripts per `D60`: guest `mcp_stdio_verify.py`, `mcp_discover.py` Python SDK fallback, `strace` wrapper, OverlayFS `upperdir` differ, `package_sha256` & `tools/list` hasher, Layer 2 cgroup v2 launcher enforcing `memory.max=512M`, `memory.swap.max=0`, `pids.max=64`, `cpu.max=100000 100000`).
  - `explore/fixtures/` (`plan/10b`: pinned SHAs for the 3 baseline fixtures + 6 Demo Malicious MCP Scenarios).
- **Acceptance checks:**
  - Verify real `msb` microVM boots Ubuntu 24.04 with all required tools (`python`, `pip`, `uv`, Node 22+, `git`, `strace`, `OpenCode`, `@modelcontextprotocol/inspector`, `noVNC`), mounts, and canaries (`.env`, `.ssh`, `.aws`, `opencode.db`, `.config/opencode/`).
  - Prove key isolation (`/proc/*/environ` audit + `opencode.db` dummy token + `mitmdump` log trace).
  - Prove Layer 2 cgroup v2 (`memory.events`/`pids.events`) and Layer 3 teardown leave zero orphaned VMs, TAP devices, or iptables rules.

### 7.2 Teammate B — Control-Plane, Agents & Frontend (`Plane 1`)

- **Owns `plan/` steps:** `09-preflight.md`, `10-opencode-lockdown.md`, `11-bootstrap-discover.md`, `17-status-ui.md`, `18-vuln-receipt-finalize.md`, `19-report-ui.md`, `21-cleanup-docs.md`, plus Plane 1 API/UI/deployment in `20-e2e-fixtures-deploy.md`.
- **Immediate baseline fixes before step `09`:**
  - Fix `explore/api/routes.py:141-152` live-SSE `progress`/`current_step` hoisting bug and `routes.py:122-139` 13–15s poll sleep.
  - Enable SQLite WAL + `busy_timeout=5000` in `explore/ledger/store.py`.
  - Bind `explore` to `127.0.0.1:8100:8100` in `docker-compose.yml`.
- **Key modules to build:**
  - `explore/llm_proxy.py` (Plane 1 Host LLM Proxy: validates ephemeral dummy bearer token, swaps in `VULTR_INFERENCE_API_KEY` outbound only, enforces Layer 1 circuit breaker `max_turns=12`, `max_tokens=60000`, oscillation→429, per-role model routing `D74`).
  - `explore/agents/` (`env_planner.py` producing `environment_profile.json` + `DynamicInstallSpec`, `test_planner.py` consuming Discovery JSON to emit `TestScenarioPlan`, `vuln_reviewer.py` producing cite-checked `vuln_review` + `DetonationVerdict` mapped to all 16 ATLAS tactics & 10 OWASP MCP classes).
  - `explore/api/routes.py` & `explore/ledger/` extensions (`verdict`, `telemetry`, `novnc` token/session routes, MCP registry intake `D15`, `DetonationVerdict` persistence in `JobReceipt` / `VulnReport`).
  - `frontend/` (`UrlForm.tsx` supporting GitHub URL + MCP registry intake, authenticated view-only `noVNC` WS proxy `/api/jobs/[id]/novnc` + `NoVncViewer.tsx`, `JobLiveView.tsx` telemetry/kill-switch stream, Report UI rendering `DetonationVerdict`, `package_sha256_before`/`after`, `t0_tools_sha256`/`final_tools_sha256`/`tool_diffs`, 16-tactic ATLAS matrix, OWASP MCP Top 10 badges, and typed `lib/api.ts`).
- **Acceptance checks:**
  - Every `schemas/*.json` schema validates generated payloads via `jsonschema 4.23.0`.
  - View-only `noVNC` drops all client RFB input frames and requires job-scoped auth.
  - Full E2E run of baseline fixtures + all 6 Demo Scenarios on Vultr Cloud Compute / VX1 behind reverse proxy (`127.0.0.1` binding — `D46`), followed by `plan/21-cleanup-docs.md`.
