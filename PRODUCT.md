# PRODUCT.md — What we are building and why

## What

**Killhub** turns a **public GitHub repository URL or MCP registry target** into a **verified running environment** plus an **intake dossier & detonation verdict** (durable receipt of how it ran, what runtime behavior occurred, and what risk was found):

1. User pastes a public GitHub URL (`https://github.com/org/repo`) or allowed MCP registry target (`npm:<pkg>@<ver>`, `pypi:<pkg>==<ver>`, or pinned fixture ID) in a Next.js app (input · status/`noVNC` live view · report).
2. Plane 1 runs **pre-flight** (URL/registry validation, admission, cheap risk) before spending a sandbox when hard-fail applies.
3. The **control plane** (Next.js edge + Python `explore/` sidecar) runs Plane 1 planning agents (**Environment/Install Planner** and **Test Planner**) using Vultr Serverless Inference (`https://api.vultrinference.com/v1`). The Environment/Install Planner emits a **versioned executable** `environment_profile.json` (`git_mcp`, `webapp`, or `demo`) and `DynamicInstallSpec`; **deterministic gates** decide readiness, detonation verdict, and terminal outcomes from evidence. Invented demos are labeled `generated_demo` and must retain visible original setup failures.
4. A **single disposable Microsandbox** microVM (Ubuntu 24.04 detonation base) on Vultr VX1 is created with read-only rootfs + OverlayFS, baked `mitmproxy` CA, canary secrets (`.env`, `.ssh`, `.aws`), pre-seeded victim **OpenCode** pointing to the Plane 1 Host LLM Proxy (never holding `VULTR_INFERENCE_API_KEY`), host TAP/`mitmdump` network policy, and `AF_VSOCK`/UDS/`mgmt0` telemetry IPC (explore, detonation, and test share this single VM).
5. **Phase 1 Install** uses TAP/`mitmdump` install egress (registries/git allowed; CP/mgmt/siblings/DoH/DoT/QUIC denied) and records `package_sha256_before`/`after`. For MCP targets, **Discovery** (`@modelcontextprotocol/inspector --cli --format json` + Python MCP SDK fallback) captures `t0_tools_sha256` and feeds the Plane 1 **Test-Planner Agent** to generate a structured `TestScenarioPlan`.
6. **Phase 2a Monitored Detonation** executes scenarios via in-VM OpenCode (observable in real time via an authenticated, **view-only `noVNC`** stream) under the **3-Layer Kill Switch** (L1 LLM Proxy turn/token/oscillation circuit breaker; L2 guest cgroup v2 hard caps; L3 host hypervisor wall-clock watchdog) while `mitmdump` (HTTP/S + DNS interception, DoH/DoT/QUIC drop, optional `tcpdump` PCAP, real-time canary blocking) and guest sensors (`strace`, OverlayFS `upperdir`, MCP wire tap, cgroup v2) observe behavior and capture `final_tools_sha256` / `tool_diffs`. **Phase 2b Strict Offline Containment Verify** (deny-all egress, loopback only) confirms static isolation when required.
7. Known vulnerabilities are **scanned and summarized with citations** (Plane-1 SCA on copied lockfiles + cite-checked `vuln_review` + **Detonation Verdict JSON** mapped to all 16 MITRE ATLAS tactics `AML.TA0000`–`AML.TA0015` and OWASP MCP Top 10 `MCP01:2025`–`MCP10:2025`). Killhub does **not** weaponize CVEs against non-target infrastructure or run generic web pentest exploit suites.
8. After bounded report generation, probes, artifact capture, telemetry flush, and sandbox cleanup (**finally**), the job reaches **`completed`** (or `failed` / `cancelled`) with a durable **receipt** and **Detonation Verdict**. Live status/progress/evidence/telemetry stream to the UI alongside view-only `noVNC` and optional Playwright stills (never gating completion).
9. **Containment / network / canary probes** demonstrate isolation, key isolation (`VULTR_INFERENCE_API_KEY` absent from Plane 2), and that Plane 2 cannot reach Plane 1 control-plane or management surfaces.

## Why

Standing up someone else’s repo is slow, brittle, and unsafe if done on a shared laptop or production host. Killhub exists to:

- **Understand** a repo before trusting it (inspect docs, infer services, validate a spec).
- **Isolate** execution on a short-lived Microsandbox (not the operator’s machine).
- **Prove** it works (readiness) and **surface risk** (cited SCA report; optional MCP assessment; containment evidence) before humans dig in.
- **Leave a receipt** — profile, probes, findings, lifecycle — that outlives the destroyed sandbox.
- **Show work** continuously (structured events + optional stills) so operators trust the automation.

## Who it is for

Operators, security-minded engineers, and internal teams who need to quickly and safely “bring up”, detonate, and audit public GitHub repos or MCP registry packages — MCP servers, webapps, or oddball content — with a clear environment profile, runtime behavioral telemetry, and audit trail.

## Success looks like

A user submits a public GitHub URL or MCP registry target and, without refreshing, sees:

- Live status, progress, and structured evidence/telemetry events (with keep-alives on long steps)  
- An authenticated, **view-only `noVNC`** live view of the in-VM OpenCode detonation (plus optional Playwright stills for webapps)  
- A validated `environment_profile.json` and `DynamicInstallSpec` (plus `TestScenarioPlan` for MCP targets)  
- **Verifiable execution** — MCP handshake (`tools/list` + `t0_tools_sha256`) / HTTP (or other profile) readiness with an honest label: `original_application`, `generated_demo`, or `setup_failed`  
- Sandbox lifecycle signals (create → optional custom-OCI replace → install/detonate → **destroyed** only when removal is confirmed)  
- An intake **receipt & Detonation Verdict**: cited vulnerability report separating **dependency advisories (SCA)**, **active MCP detonation findings** (mapped to all 16 MITRE ATLAS tactics `AML.TA0000`–`AML.TA0015` and OWASP MCP Top 10 `MCP01:2025`–`MCP10:2025`), `package_sha256_before`/`after`, `t0_tools_sha256`/`final_tools_sha256`/`tool_diffs`, 3-layer kill-switch & containment evidence, and network/DNS interception logs — without erasing readiness evidence  

…while real Killhub secrets (`VULTR_INFERENCE_API_KEY`, `VULTR_API_KEY`) never enter the sandbox (in-VM OpenCode uses a dummy bearer token routed through the Plane 1 Host LLM Proxy, and canaries catch exfiltration in real time), Plane 1 planners cannot shell the control plane, Plane 2 cannot reach Plane 1 APIs or `msb` management endpoints, adversarial loops are bounded by the 3-layer kill switch, and the sandbox is destroyed on job completion / fail / cancel / absolute expiry (even if the control plane restarts).

Public demos run the control plane on **Vultr Cloud Compute** (app, Host LLM Proxy, and view-only `noVNC` proxy on localhost behind a reverse proxy) with agent reasoning via **Vultr Serverless Inference** and execution in Microsandbox on VX1 — behind admission limits and a durable job ledger.

## v1 golden fixtures & 6 Demo Malicious MCP Scenarios

Pinned commit SHAs and fixture configurations live in [plan/10b-pin-fixtures.md](plan/10b-pin-fixtures.md) ([DECISIONS.md](DECISIONS.md) D53, D73).

### Baseline v1 golden fixtures

| Intent / outcome | Public repo |
|------------------|-------------|
| `webapp` → `original_application` | [heroku/node-js-getting-started](https://github.com/heroku/node-js-getting-started) @ pin |
| `git_mcp` → filesystem server (stdio) | [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) @ pin + fixed filesystem entrypoint |
| Controlled `setup_failed` + SCA | Deliberately broken fixture (not NodeGoat); dependency advisories via lockfile SCA, separate from intentional app vulns |

### 6 Demo Malicious MCP Scenarios (DVMCP + targeted fixtures)

| # | Scenario | Target / Fixture | Key Catching Sensors & Tactics |
|---|----------|------------------|--------------------------------|
| **1** | **Indirect prompt injection via GitHub issue** | DVMCP / issue-reading MCP server | `mcp_wire_tap` + `mitmdump_http` + `mitmdump_dns` + `canary_monitor` (`AML.TA0004`, `AML.TA0010`; `MCP06:2025`) |
| **2** | **Delayed tool obfuscation / rug pull** | Time/call-count stateful MCP server | `inspector_diff` (`t0_tools_sha256` vs `final_tools_sha256`, `tool_diffs`) + `mcp_wire_tap` (`AML.TA0001`, `AML.TA0008`; `MCP03:2025`) |
| **3** | **Post-install modified package backdoor** | Registry/tarball install hook fixture | `overlayfs` (`package_sha256_before` vs `after`, `upperdir`) + `strace` (`execve`) + `mitmdump_http` (`AML.TA0003`, `AML.TA0006`; `MCP04:2025`, `MCP09:2025`) |
| **4** | **Host microVM credential exfiltration via OpenCode tools & `opencode.db`** | Exfil-seeking MCP tool probing `/workspace/.env`, `.ssh`, `.aws`, `opencode.db` | `strace` (`openat`) + `opencode_db_audit` + `canary_monitor` + `mitmdump_http` + `mitmdump_dns` + `llm_proxy` dummy-token check (`AML.TA0009`, `AML.TA0010`, `AML.TA0013`; `MCP01:2025`, `MCP05:2025`) |
| **5** | **External manipulation of a clean MCP server via tool drift / shadowing** | Clean MCP server paired with untrusted external metadata / sibling tool | `inspector_diff` (`tool_diffs`) + `mcp_wire_tap` + `mitmdump_http` + `mitmdump_dns` + `strace` (`AML.TA0008`, `AML.TA0014`, `AML.TA0015`; `MCP03:2025`, `MCP06:2025`) |
| **6** | **Resource exhaustion via infinite agent loop** | Recursive/oscillating MCP tool response | 3-Layer Kill Switch: `llm_proxy` (`max_turns=12`, `max_tokens=60000`, oscillation→429), `cgroup_v2` (`512M`/`64` pids/`memory.events`), `hypervisor_watchdog` (`AML.TA0011`; `MCP08:2025`, `MCP10:2025`) |

## Non-goals (v1)

- Private repos / OAuth  
- Multi-user auth / billing  
- Long-lived **customer** environments / production hosting beyond job TTL (a publicly reachable control-plane demo on Vultr is in scope)  
- GPU workloads  
- Auto-remediating vulnerabilities  
- Weaponizing CVEs against non-target infrastructure or running generic app/web pentest exploit suites (SCA + report always; Discovery → Test-Planner → Monitored MCP Detonation for MCP targets; containment probes are isolation-only — D33, D35, D73)  
- Clouds other than Vultr for the demo control plane or sandboxes  
- Alternate LLM providers outside Vultr Serverless Inference  
- Persistent full-session video recordings (live **view-only `noVNC`** stream during execution and optional Playwright stills are in scope)  
- Separate Explore VM vs Test VM  
- Install allowlist that blocks commands Microsandbox can run (attempt + flag failures instead)

## Doc map

| Doc | Purpose |
|-----|---------|
| [AGENTS.md](AGENTS.md) | Rules every AI agent must follow (incl. R2 inline code & module frontmatter rules) |
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the platform is structured (planes, IPC, TAP/`mitmdump`, `noVNC`, Host LLM Proxy, 3-layer kill switch) |
| [DECISIONS.md](DECISIONS.md) | Agreed technical decisions (`D1`–`D74`) |
| [DATABASE.md](DATABASE.md) | Data model, schemas (`schemas/*.json`), and rules |
| [API.md](API.md) | How components communicate |
| [ALIGNMENT_PLAN.md](ALIGNMENT_PLAN.md) | Reconciliation plan, model-selection plan, mitigations, and teammate handoffs |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | Implementation index by plane |
| [plan/README.md](plan/README.md) | Agent-sized build steps (one per session; removed after step 21) |
| [plan/VULTR.md](plan/VULTR.md) | Vultr MCP / `vultr-cli` / `msb` tooling rules (fold into AGENTS/ARCHITECTURE at step 21) |
| [plan/21-cleanup-docs.md](plan/21-cleanup-docs.md) | Post-M7 doc cleanup (delete scaffolding) |
