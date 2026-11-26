# Killhub — Implementation Plan (Index)

Implementation is split by the **two** architecture planes. Use this file as the map; do the work in the plane docs.

**AI agents building the product:** prefer one file from [`plan/`](plan/README.md) per session (steps 01–21). Do not attempt the whole plan in one turn. Step **21** deletes the build ladder (and optionally these `IMPLEMENTATION_*.md` files) after M7.

Product docs: [PRODUCT.md](PRODUCT.md) · [AGENTS.md](AGENTS.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [DECISIONS.md](DECISIONS.md) · [DATABASE.md](DATABASE.md) · [API.md](API.md)

| Plane | Document | Owns |
|------:|----------|------|
| 1 | [IMPLEMENTATION_NEXTJS.md](IMPLEMENTATION_NEXTJS.md) | Next.js UI + **Jobs API/SSE** |
| 1 | [IMPLEMENTATION_EXPLORE_SANDBOX.md](IMPLEMENTATION_EXPLORE_SANDBOX.md) | Environment Agent Plan Loop · harness · screenshots · vulns (`explore/` workers) |
| 2 | [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md) | One disposable Microsandbox per job (explore + test) |
| — | [plan/README.md](plan/README.md) | Agent-sized sequential steps (01–20) |
| — | [plan/VULTR.md](plan/VULTR.md) | Vultr MCP · `vultr-cli` · `msb` (D59) |

```
┌─────────────────────────────────────────────────────────────────────────┐
│  PLANE 1 — Control plane                                                │
│  → IMPLEMENTATION_NEXTJS.md + IMPLEMENTATION_EXPLORE_SANDBOX.md         │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ msb / SDK
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  PLANE 2 — Disposable Microsandbox (Vultr VX1)                          │
│  → IMPLEMENTATION_TEST_VM.md                                            │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Goal (product)

Given a public GitHub URL:

1. Plane 1 admits the link (D40), owns the job in a durable ledger (D41), and shows live status / report
2. Plane 1 bootstraps one sandbox, runs the Environment Agent Plan Loop → runtime `environment_profile.json` (replace VM if image differs — D36)
3. Plane 2 is **one** disposable sandbox for that job (inspect + install + launch) under Killhub network policy (D39)
4. Readiness evidence ≠ completion (D37): MCP handshake or HTTP probe; then bounded scan/report/finalize → `completed`; optional MCP assessment (D35); screenshots optional via in-guest Playwright (D38)
5. Containment + network probes available as isolation demos (not CVE exploitation)

---

## Vulnerability vs containment vs exploits (v1)

| Capability | In v1? | Where | Purpose |
|------------|--------|-------|---------|
| SCA / lockfile / known-advisory scan | **Yes** | E5 · `vulnscan.py` | Surface known risk in the report |
| AI `vuln_review` summary | **Yes** | E5 · prompts | Make findings readable |
| Best-effort scan on fail path | **Yes** | E5 (controlled fail fixture — D53) | Vuln report even when readiness fails |
| MCP Inspector/SDK assessment | **Yes, when planned** | E5 · T3 · D35 | Agent-elected MCP protocol/tool security assessment; does not invalidate readiness or gate `completed` |
| Auto-patch / remediate | **No** | — | Non-goal (D11) |
| Weaponize CVEs / generic app/web exploit suites | **No** | — | Non-goal (D33) |
| Containment probe (adversarial cmd in sandbox) | **Yes** | E3 / D26 | Prove isolation; **not** CVE exploitation |

Controlled fail fixture (D53): expect **`setup_failed`** + **SCA findings from lockfile** — not Killhub weaponizing app vulns; intentional-app findings stay a separate class.

---

## Suggested build order

Prefer [`plan/`](plan/README.md) steps **01→20** for agent sessions. Mapping to plane phases:

| Order | Work | plan/ | Plane phases |
|------:|------|-------|--------------|
| 1 | Scaffold Next.js + explore workers (compose) | 01–02 | N0 · E0 |
| 2 | Durable ledger + Internal Worker API; Next proxy + SSE cursor + admission | 03–05 | N1 · E1 (D52, D55) |
| 3 | Microsandbox create / exec / destroy + reaper + net policy + canaries | 06–08 | T0–T1 |
| 4 | Pre-flight + OpenCode lockdown + bootstrap + discover + image replace | 09–12 | E2 (D51) |
| 5 | Install egress → deny-all remaining egress + readiness/verification gates | 13–14 | E3 · T2–T3 |
| 6 | Containment matrix + network + canary probes | 15 | E3 · T4 (D58) |
| 7 | Optional screenshots + status UI | 16–17 | E4 · N2 |
| 8 | Vuln scan + cite-checked report + receipt + destroy → `completed` | 18 | E5 (D57) |
| 9 | Report UI + E2E fixtures + public deploy | 19–20 | N3 · E6 · N4 · T4 |

---

## Cross-plane milestones

- [ ] **M0:** Compose boots Plane 1 (frontend + explore workers)
- [ ] **M1:** Durable ledger + Jobs API/SSE + admission from Plane 1
- [ ] **M2:** Harness creates / execs / destroys a Microsandbox; host reaper; net policy; canaries
- [ ] **M3:** Pre-flight + bootstrap + plan loop emits valid runtime `environment_profile.json` (`git_mcp` \| `webapp` \| `demo`); OpenCode lockdown
- [ ] **M4:** Install-phase egress → deny-all remaining egress + readiness gates (MCP handshake or HTTP); image replace reuses resolved commit
- [ ] **M5:** Optional in-guest screenshots when useful
- [ ] **M6:** Vuln **scan + cite-checked report** + **receipt** + `finalizing` → `completed` (including fail path); optional MCP assessment when planned (D35); no CVE weaponization / generic exploit suites
- [ ] **M6b:** Containment + network + canary probes logged then sandbox destroyed (D26, D39, D44)
- [ ] **M7:** Pinned fixtures (D53); verification kinds honest (D54); absolute expiry + confirm destroy across Plane 1 restart; demo edge bind (D46)

---

## Cross-cutting

### Configuration

| Variable | Plane | Purpose |
|----------|------:|---------|
| `VULTR_API_KEY` | 1 | VX1 host ops (not injected into sandboxes) |
| `VULTR_INFERENCE_*` | 1 | Serverless Inference |
| `OPENCODE_*` / trusted config | 1 | Agent lockdown (D38) |
| `LEDGER_URL` | 1 | Durable job/event store (D41; Python sidecar) |
| `INTERNAL_API_TOKEN` | 1 | Next.js → explore loopback auth (D52) |
| `EVENT_RETENTION` | 1 | SSE replay window (D55) |
| `MSB_HOST` / `MSB_DEFAULT_IMAGE` / CPU·memory / net policy | 1→2 | Bootstrap + Microsandbox |
| `JOB_TIMEOUT_SECONDS` | 1 | Wall clock |
| `MAX_REPAIR_ATTEMPTS` | 1 | Plan-loop cap |
| `MAX_CONCURRENT_JOBS` / `MAX_QUEUED_JOBS` / rate / inference / disk caps | 1 | Admission (D40) |
| `ENV_TTL_SECONDS` | 2 | Absolute `expires_at` (D41) |
| `VULN_SCAN_*` | 1 | Scanners |
| `MAX_SCREENSHOTS_PER_JOB` | 1 | Screenshot cap |
| `SCREENSHOT_STORAGE` | 1 | Artifacts |

### Out of scope (v1)

- Private GitHub repos / OAuth
- Multi-user auth / billing
- Long-lived customer sandboxes beyond TTL
- GPU · auto-patch CVEs · weaponizing CVEs / generic app/web exploit suites · non-Vultr clouds · session video
- Separate Explore VM vs Test VM · install allowlist
- MCP Inspector on every job (only when `mcp.security_assessment` is planned — D35)

### Definition of done (v1)

A user can paste a public GitHub URL in Plane 1 (subject to admission) and, without refreshing, see live status/progress, `environment_profile.json`, readiness evidence, and a **scan-based** vuln report ending in `completed` (plus optional MCP assessment findings) while Plane 1’s locked-down plan loop drives a single Plane 2 Microsandbox under network policy — with durable ledger recovery, absolute expiry that survives control-plane failure, Killhub secrets never entering the sandbox, screenshots optional in-guest, and sandboxes torn down after completion / cancel / expiry.
