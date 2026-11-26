# Killhub — Implementation Plan (Index)

Implementation is split by the three architecture planes. Use this file as the map; do the work in the plane docs.

Architecture (system design): [ARCHITECTURE.md](ARCHITECTURE.md)

| Plane | Document | Owns |
|------:|----------|------|
| 1 | [IMPLEMENTATION_NEXTJS.md](IMPLEMENTATION_NEXTJS.md) | Next.js input · status · report UI/server |
| 2 | [IMPLEMENTATION_EXPLORE_SANDBOX.md](IMPLEMENTATION_EXPLORE_SANDBOX.md) | Environment Agent Plan Loop · jobs/SSE · harness · screenshots · vulns |
| 3 | [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md) | Disposable VM from `environment_profile.json` · deps · MCP/app readiness |

```
┌─────────────────────────────────────────────────────────────────────────┐
│  PLANE 1 — Next.js                                                      │
│  → IMPLEMENTATION_NEXTJS.md                                             │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ jobs API · SSE
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  PLANE 2 — Explore Sandbox                                              │
│  → IMPLEMENTATION_EXPLORE_SANDBOX.md                                    │
│  inspect → infer → validate → provision deps → launch MCP / readiness   │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ profile · exec · destroy
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  PLANE 3 — Test VM                                                      │
│  → IMPLEMENTATION_TEST_VM.md                                            │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Goal (product)

Given a public GitHub URL:

1. Plane 1 accepts the link and shows live status / report
2. Plane 2 runs the Environment Agent Plan Loop → `environment_profile.json`
3. Plane 3 is provisioned from that profile (supported deps, MCP/webapp readiness)
4. Plane 2 streams progress, screenshots, and vuln findings back to Plane 1

---

## Suggested build order across planes

| Order | Work | Doc |
|------:|------|-----|
| 1 | Scaffold Next.js + Explore service (compose) | Plane 1 N0 · Plane 2 E0 |
| 2 | Jobs API + SSE stubs | Plane 2 E1 · Plane 1 N1–N2 (can mock) |
| 3 | Test VM create / exec / destroy | Plane 3 T0–T1 · Plane 2 harness |
| 4 | Plan loop steps 1–3 → profile | Plane 2 E2 |
| 5 | Provision deps + MCP/app readiness | Plane 2 E3 · Plane 3 T2–T3 |
| 6 | Screenshots + Plane 1 report window | Plane 2 E4 · Plane 1 N2–N3 |
| 7 | Vuln scan | Plane 2 E5 |
| 8 | E2E hardening across all planes | Plane 2 E6 · Plane 3 T4 · Plane 1 N4 |

Plane 1 UI can advance early against mocked SSE. Plane 3 has no UI of its own.

---

## Cross-plane milestones

- [ ] **M0:** Compose boots Plane 1 + Plane 2
- [ ] **M1:** Jobs API + SSE reach Plane 1
- [ ] **M2:** Harness provisions / execs / destroys a Test VM
- [ ] **M3:** Plan loop emits valid `environment_profile.json` (`git_mcp` \| `webapp`)
- [ ] **M4:** Supported deps + MCP/app readiness green on Test VM
- [ ] **M5:** Screenshots live in Plane 1
- [ ] **M6:** Vuln report in Plane 1 report window
- [ ] **M7:** Three public repos end-to-end; isolation + TTL cleanup verified

---

## Cross-cutting

### Configuration

| Variable | Plane | Purpose |
|----------|------:|---------|
| `EXPLORE_SANDBOX_URL` | 1 | Plane 1 → Plane 2 |
| `VULTR_API_KEY` | 2 (→ 3) | Inference + VM provisioning |
| `OPENCODE_*` | 2 | Agent harness |
| `VULTR_PLAN` / region / OS | 2→3 | Test VM defaults |
| `JOB_TIMEOUT_SECONDS` | 2 | Wall clock |
| `MAX_REPAIR_ATTEMPTS` | 2 | Plan-loop cap |
| `ENV_TTL_SECONDS` | 3 | Auto-destroy VM |
| `VULN_SCAN_*` | 2 | Scanners |
| `MAX_SCREENSHOTS_PER_JOB` | 2 | Screenshot cap |
| `SCREENSHOT_STORAGE` | 2 | Artifacts |

### Out of scope (v1)

- Private GitHub repos / OAuth
- Multi-user auth / billing
- Long-lived Test VMs beyond TTL
- GPU workloads
- Auto-patching vulnerabilities (report only)
- Non-Vultr Test VM providers
- Full session video (stills only)

### Definition of done (v1)

A user can paste a public GitHub URL in Plane 1 and, without refreshing, see live status/progress, screenshots, `environment_profile.json`, and a vuln report while Plane 2’s plan loop drives a Plane 3 Test VM — with Killhub secrets never entering the Test VM or screenshots, and VMs/artifacts torn down after TTL or cancel.
