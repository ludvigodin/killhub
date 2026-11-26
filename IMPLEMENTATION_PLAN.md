# Killhub — Implementation Plan (Index)

Implementation is split by the **two** architecture planes. Use this file as the map; do the work in the plane docs.

Product docs: [PRODUCT.md](PRODUCT.md) · [AGENTS.md](AGENTS.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [DECISIONS.md](DECISIONS.md) · [DATABASE.md](DATABASE.md) · [API.md](API.md)

| Plane | Document | Owns |
|------:|----------|------|
| 1 | [IMPLEMENTATION_NEXTJS.md](IMPLEMENTATION_NEXTJS.md) | Next.js UI + **Jobs API/SSE** |
| 1 | [IMPLEMENTATION_EXPLORE_SANDBOX.md](IMPLEMENTATION_EXPLORE_SANDBOX.md) | Environment Agent Plan Loop · harness · screenshots · vulns (`explore/` workers) |
| 2 | [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md) | One disposable Microsandbox per job (explore + test) |

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

1. Plane 1 accepts the link, owns the job, and shows live status / report
2. Plane 1 runs the Environment Agent Plan Loop → `environment_profile.json`
3. Plane 2 is **one** disposable sandbox for that job (inspect + install + launch)
4. Readiness: MCP handshake (list tools) or HTTP healthcheck; vulns **scanned and reported**; optional MCP Inspector/SDK assessment when agent plans it (D35); screenshots optional
5. Containment probe available as isolation demo (not CVE exploitation)

---

## Vulnerability vs containment vs exploits (v1)

| Capability | In v1? | Where | Purpose |
|------------|--------|-------|---------|
| SCA / lockfile / known-advisory scan | **Yes** | E5 · `vulnscan.py` | Surface known risk in the report |
| AI `vuln_review` summary | **Yes** | E5 · prompts | Make findings readable |
| Best-effort scan on fail path | **Yes** | E5 (NodeGoat) | Vuln report even when readiness fails |
| MCP Inspector/SDK assessment | **Yes, when planned** | E5 · T3 · D35 | Agent-elected MCP protocol/tool security assessment; does not gate `ready` |
| Auto-patch / remediate | **No** | — | Non-goal (D11) |
| Weaponize CVEs / generic app/web exploit suites | **No** | — | Non-goal (D33) |
| Containment probe (adversarial cmd in sandbox) | **Yes** | E3 / D26 | Prove isolation; **not** CVE exploitation |

NodeGoat fixture: expect **readiness fail** + **vuln findings from scan** — not Killhub weaponizing OWASP flaws.

---

## Suggested build order

| Order | Work | Doc |
|------:|------|-----|
| 1 | Scaffold Next.js + explore workers (compose) | N0 · E0 |
| 2 | Jobs API + SSE on Plane 1 | N1 · E1 |
| 3 | Microsandbox create / exec / destroy | T0–T1 · harness |
| 4 | Plan loop steps 1–3 → profile | E2 |
| 5 | Provision + MCP/app readiness (no allowlist; flag failures) | E3 · T2–T3 |
| 6 | Containment probe path (isolation demo) | E3 · T4 |
| 7 | Optional screenshots + report window | E4 · N2–N3 |
| 8 | Vuln **scan + report**; optional MCP assessment when profile plans it; no CVE weaponization (incl. best-effort SCA on fail) | E5 |
| 9 | E2E on golden fixtures (D32) | E6 · T4 · N4 |

---

## Cross-plane milestones

- [ ] **M0:** Compose boots Plane 1 (frontend + explore workers)
- [ ] **M1:** Jobs API + SSE served from Plane 1
- [ ] **M2:** Harness creates / execs / destroys a Microsandbox
- [ ] **M3:** Plan loop emits valid `environment_profile.json` (`git_mcp` \| `webapp` \| `demo`)
- [ ] **M4:** Install + readiness green on sandbox (MCP handshake or HTTP)
- [ ] **M5:** Optional screenshots when useful
- [ ] **M6:** Vuln **scan report** attached (including fail path); optional MCP assessment when planned (D35); no CVE weaponization / generic exploit suites
- [ ] **M6b:** Containment probe logged then sandbox destroyed (D26)
- [ ] **M7:** Golden fixtures (D32): heroku getting-started · mcp servers · NodeGoat fail+**scan** vulns; TTL cleanup verified

---

## Cross-cutting

### Configuration

| Variable | Plane | Purpose |
|----------|------:|---------|
| `VULTR_API_KEY` | 1 | VX1 host ops (not injected into sandboxes) |
| `VULTR_INFERENCE_*` | 1 | Serverless Inference |
| `OPENCODE_*` | 1 | Agent harness |
| `MSB_HOST` / image / CPU·memory | 1→2 | Microsandbox defaults |
| `JOB_TIMEOUT_SECONDS` | 1 | Wall clock |
| `MAX_REPAIR_ATTEMPTS` | 1 | Plan-loop cap |
| `ENV_TTL_SECONDS` | 2 | Auto-destroy sandbox |
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

A user can paste a public GitHub URL in Plane 1 and, without refreshing, see live status/progress, `environment_profile.json`, and a **scan-based** vuln report (plus optional MCP assessment findings when the agent planned them) while Plane 1’s plan loop drives a single Plane 2 Microsandbox — with Killhub secrets never entering the sandbox, screenshots optional, optional containment proof, and sandboxes torn down after TTL or cancel.
