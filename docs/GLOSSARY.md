# GLOSSARY.md — Killhub terms

Short definitions used across PRODUCT, ARCHITECTURE, DATABASE, and API. Code anchors: [CODEMAP.md](CODEMAP.md).

| Term | Meaning |
|------|---------|
| **Pattern A** | Plan → sandboxed execution → verifiable output → destroy. Killhub’s product loop. |
| **Plane 1** | Durable **control plane**: Next.js edge + Python `explore/` sidecar. Owns UI, Jobs API/SSE proxy, ledger, worker, harness, secrets. |
| **Plane 2** | One **disposable Microsandbox** microVM per job. Untrusted clone/install/run. Explore and test share that same VM (D27). |
| **Environment Agent** | Normative plan-loop role on Plane 1 that proposes how to demo a repo and writes a runtime profile. Live code is mostly an imperative worker pipeline with heuristic discover — see ARCHITECTURE implementation note. |
| **Harness** | Plane 1 code that drives Plane 2 via `msb` (`explore/harness.py`). Not the operator MCP. |
| **Operator MCP (D81)** | MCP tools that call the **public** Jobs API (`create_job`, `get_receipt`, …). Entry: `explore/operator_mcp.py` / public `/mcp`. |
| **Harness MCP** | In-sandbox / agent-tool MCP surface for OpenCode-shaped configs (`harness_mcp.py`). Distinct from Operator MCP. |
| **Bootstrap profile** | Trusted Killhub-owned profile used for first sandbox create before discovery (D36). |
| **Runtime profile** | Versioned executable `environment_profile.json` produced after inspect/infer/validate (D51). Drives install/run/probes. |
| **Profile revision** | Append-only accepted profile snapshot for a job (`EnvironmentProfileRevision` — D64). |
| **Sandbox generation** | One create/replace cycle of a microVM for a job (`SandboxGeneration` — D64). Job-level `sandbox_id` describes the **current** generation. |
| **Readiness** | Probe evidence that the target answered (`readiness.passed`, probe detail). **Not** job completion and **not** a destroy trigger (D37). |
| **`completed` / `failed` / `cancelled`** | Terminal job statuses after receipt + cleanup path. |
| **Receipt** | Durable dossier on Plane 1 that outlives the sandbox (profile, readiness, findings, containment, lifecycle — D49). |
| **`verification.kind`** | Honesty label: `original_application` \| `generated_demo` \| `setup_failed` (D54). |
| **Canary** | Fake secret planted in Plane 2; real Killhub keys never injected (D19, D44). |
| **Admission** | Global concurrency, queue, rate limits, inference/disk budgets on the public demo (D40). Split: edge in frontend, concurrency in explore. |
| **`git_url`** | Wire/DB field name for the public git HTTPS URL. Hosts are allowlisted (D78); user-facing copy says “public git URL.” |
| **SSE `event_cursor`** | Last durable `event_id` on the snapshot; clients subscribe with `Last-Event-ID` / `?after=` (D55, D67). |
| **Install phase vs verify phase** | Install: package/git egress allowed, CP/management denied. Verify/containment: **deny-all remaining guest egress** (D43). |
| **Host reaper vs in-process reaper** | In-process: `reaper_loop` in explore. Host: `python -m reaper --host` on VX1 for absolute `expires_at` if Plane 1 is down (D41). Stall/timeout terminalization: D83. |
| **Self-heal** | Re-run pipeline on a fresh generation if the live microVM vanishes mid-flight (D80). |
| **Quality gate** | Frontend Biome/knip/typecheck/build + explore ruff/pytest before substantive merge (D68 / AGENTS §8). |

---

## Related

[ARCHITECTURE.md](../ARCHITECTURE.md) · [DATABASE.md](../DATABASE.md) · [DECISIONS.md](../DECISIONS.md) · [CODEMAP.md](CODEMAP.md)
