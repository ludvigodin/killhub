# Killhub — Implementation Plan (Index)

Implementation is split by the three architecture planes. Use this file as the map; do the work in the plane docs.

Product docs: [PRODUCT.md](PRODUCT.md) · [AGENTS.md](AGENTS.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [DECISIONS.md](DECISIONS.md) · [DATABASE.md](DATABASE.md) · [API.md](API.md)

| Plane | Document | Owns |
|------:|----------|------|
| 1 | [IMPLEMENTATION_NEXTJS.md](IMPLEMENTATION_NEXTJS.md) | Next.js input · status · report UI/server |
| 2 | [IMPLEMENTATION_EXPLORE_SANDBOX.md](IMPLEMENTATION_EXPLORE_SANDBOX.md) | Environment Agent Plan Loop · jobs/SSE · harness · screenshots · vulns |
| 3 | [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md) | Microsandbox microVM from `environment_profile.json` · deps · MCP/app readiness |

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
│  PLANE 3 — Test VM (Microsandbox on Vultr VX1)                          │
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
| 3 | Microsandbox create / exec / destroy | Plane 3 T0–T1 · Plane 2 harness |
| 4 | Plan loop steps 1–3 → profile (Vultr Inference) | Plane 2 E2 |
| 5 | Provision deps + MCP/app readiness | Plane 2 E3 · Plane 3 T2–T3 |
| 6 | Screenshots + Plane 1 report window | Plane 2 E4 · Plane 1 N2–N3 |
| 7 | Containment probe + destroy visibility | Plane 2 E3/E6 · Plane 3 T4 · Plane 1 N3 |
| 8 | Deploy Plane 1+2 public URL on Vultr VM | Plane 1 N4 · D24 |
| 9 | Vuln scan (after demo path is green) | Plane 2 E5 |
| 10 | E2E hardening / multi-repo | Plane 2 E6 · Plane 3 T4 · Plane 1 N4 |

Plane 1 UI can advance early against mocked SSE. Plane 3 has no UI of its own.

---

## Hackathon / demo slice (priority)

Ship a **verifiable** path before breadth. Deep vuln polish and multi-repo coverage come after the demo loop is solid ([DECISIONS.md](DECISIONS.md) D24–D26).

| Priority | Work | Cut if needed |
|----------|------|---------------|
| P0 | Compose + jobs/SSE + Microsandbox create/exec/destroy | — |
| P0 | OpenCode → Vultr Serverless Inference only | Alternate providers |
| P0 | One intent (`webapp` *or* `git_mcp`) end-to-end with readiness | Dual-intent polish |
| P0 | Screenshot timeline + sandbox lifecycle in UI | Fancy report chrome |
| P0 | Containment probe moment + sandbox destroyed signal | Ad-hoc live improvisation |
| P0 | Public HTTPS demo on Vultr Cloud Compute | Non-Vultr hosting |
| P1 | Vuln report in report window | Multi-scanner depth |
| P2 | Three-repo matrix + chaos suite | — |

**Demo definition of done:** public Vultr URL → paste known-good GitHub URL → live plan/dispatch/sandbox → readiness (or clear failure) + screenshots → containment clip → sandbox destroyed; inference traffic via `api.vultrinference.com`.

---

## Cross-plane milestones

- [ ] **M0:** Compose boots Plane 1 + Plane 2
- [ ] **M1:** Jobs API + SSE reach Plane 1
- [ ] **M2:** Harness creates / execs / destroys a Microsandbox
- [ ] **M3:** Plan loop emits valid `environment_profile.json` (`git_mcp` \| `webapp`) via Vultr Inference
- [ ] **M4:** Supported deps + MCP/app readiness green on Microsandbox
- [ ] **M5:** Screenshots live in Plane 1
- [ ] **M-demo:** Public Vultr control-plane URL + containment probe visible in UI/logs + destroy confirmed ([D24](DECISIONS.md) / [D26](DECISIONS.md))
- [ ] **M6:** Vuln report in Plane 1 report window
- [ ] **M7:** Three public repos end-to-end; isolation + TTL cleanup verified

---

## Cross-cutting

### Configuration

| Variable | Plane | Purpose |
|----------|------:|---------|
| `EXPLORE_SANDBOX_URL` | 1 | Plane 1 → Plane 2 |
| `VULTR_API_KEY` | 2 | VX1 host ops (not injected into sandboxes) |
| `VULTR_INFERENCE_BASE_URL` | 2 | Default `https://api.vultrinference.com/v1` |
| `VULTR_INFERENCE_API_KEY` | 2 | Serverless Inference (Plane 2 only) |
| `VULTR_INFERENCE_MODEL` | 2 | Model id |
| `OPENCODE_*` | 2 | Agent harness (must use Vultr Inference) |
| `MSB_HOST` / image / CPU·memory | 2→3 | Microsandbox defaults |
| `JOB_TIMEOUT_SECONDS` | 2 | Wall clock |
| `MAX_REPAIR_ATTEMPTS` | 2 | Plan-loop cap |
| `ENV_TTL_SECONDS` | 3 | Auto-destroy sandbox |
| `VULN_SCAN_*` | 2 | Scanners |
| `MAX_SCREENSHOTS_PER_JOB` | 2 | Screenshot cap |
| `SCREENSHOT_STORAGE` | 2 | Artifacts |

### Out of scope (v1)

- Private GitHub repos / OAuth
- Multi-user auth / billing
- Long-lived customer Test VMs beyond TTL (public control-plane demo on Vultr is in scope)
- GPU workloads
- Auto-patching vulnerabilities (report only)
- Non-Vultr clouds for demo control plane or Test VMs
- Alternate LLM providers for the Environment Agent
- Full session video (stills only)

### Definition of done (v1)

A user can paste a public GitHub URL in Plane 1 (publicly on Vultr for demo) and, without refreshing, see live status/progress, screenshots, `environment_profile.json`, and a vuln report while Plane 2’s plan loop (Vultr Inference) drives a Plane 3 Microsandbox microVM — with Killhub secrets never entering the sandbox or screenshots, containment probes absorbed in Plane 3, and sandboxes/artifacts torn down after TTL or cancel.
