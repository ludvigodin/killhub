# plan/ — Agent-sized build steps

Work **one step file per agent session**. Do not open every implementation doc and “finish Killhub” in one turn — that times out and drifts.

Canonical product/architecture/contracts still live at the repo root: [PRODUCT.md](../PRODUCT.md) · [AGENTS.md](../AGENTS.md) · [ARCHITECTURE.md](../ARCHITECTURE.md) · [DECISIONS.md](../DECISIONS.md) · [DATABASE.md](../DATABASE.md) · [API.md](../API.md) · [ALIGNMENT_PLAN.md](../ALIGNMENT_PLAN.md) · `schemas/*.json`.

Plane detail (when a step says “see plane doc”):  
[IMPLEMENTATION_NEXTJS.md](../IMPLEMENTATION_NEXTJS.md) · [IMPLEMENTATION_EXPLORE_SANDBOX.md](../IMPLEMENTATION_EXPLORE_SANDBOX.md) · [IMPLEMENTATION_TEST_VM.md](../IMPLEMENTATION_TEST_VM.md) · [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md)

---

## How to run a step

1. Read **only** this README + [LINT.md](LINT.md) + [VULTR.md](VULTR.md) + the **single** `NN-*.md` step you were assigned (+ any “Read first” links in that step).
2. Follow **`AGENTS.md` §5 (R2)** on every edit: add concise inline comments/docstrings explaining *what* and *why*, and start every new `.py`/`.ts`/`.tsx`/`.js`/`.sh` module with a top-of-file frontmatter/header docstring or JSDoc block (`ruff`/`biome`-compliant).
3. For Vultr / Plane 2 work, use **Vultr MCP**, **`vultr-cli`**, and/or **`msb`** as specified in [VULTR.md](VULTR.md) (`D59`) — no Docker-as-sandbox fakes.
4. Run the **full quality gate** (Biome + Knip + frontend typecheck/build + Python Ruff/pytest + `schemas/*.json` Draft 2020-12 check) and fix until all exit 0 — see [LINT.md](LINT.md) (`D68`). **No green gate ⇒ step not done.**
5. Stop when **Done when** is true (includes lint + real Vultr/`msb` where required).
6. Do **not** start the next step in the same session unless the human explicitly asks.
7. Update the step’s status checkbox in this index when finished.

---

## Order (do in sequence)

| Status | Step | Focus |
|:------:|------|--------|
| [x] | [01-scaffold-frontend](01-scaffold-frontend.md) | Next.js compose shell (N0) |
| [x] | [02-scaffold-explore](02-scaffold-explore.md) | Explore worker shell (E0) |
| [x] | [03-ledger-core](03-ledger-core.md) | Durable job/event store (D41) |
| [x] | [04-internal-worker-api](04-internal-worker-api.md) | Python Internal Worker API (D52) |
| [x] | [05-jobs-proxy-admission](05-jobs-proxy-admission.md) | Next proxy + admission + SSE cursor (N1) |
| [ ] | [06-msb-create-destroy](06-msb-create-destroy.md) | Ubuntu 24.04 microVM create/destroy + RO rootfs/OverlayFS + TAP/noVNC bind + L3 watchdog (T0, D69, D72) |
| [ ] | [07-msb-exec-copy](07-msb-exec-copy.md) | `msb exec`/`copy` (D60) + `AF_VSOCK`/UDS/`mgmt0` control & NDJSON telemetry IPC (T1, D71) |
| [ ] | [08-net-policy-canaries](08-net-policy-canaries.md) | Host TAP + `mitmdump` (HTTP/S+DNS, DoH/DoT/QUIC drop, PCAP) + baked CA/TLS env + mounts & canary seeds (D39, D44, D69, D70) |
| [ ] | [09-preflight](09-preflight.md) | Plane-1 pre-flight for GitHub URLs & MCP registry/fixture intake + baseline `explore/` fixes (D15, D45) |
| [ ] | [10-opencode-lockdown](10-opencode-lockdown.md) | Plane 1 OpenCode lockdown + Plane 1 Host LLM Proxy (`L1` breaker, key isolation) + per-role Vultr models (D25, D38, D71, D72, D74) |
| [ ] | [10b-pin-fixtures](10b-pin-fixtures.md) | Pin 3 baseline fixtures + 6 Demo Malicious MCP Scenarios (D53, D73) |
| [ ] | [11-bootstrap-discover](11-bootstrap-discover.md) | Bootstrap Ubuntu 24.04 + Env/Install Planner (`DynamicInstallSpec`) + Discovery (`@modelcontextprotocol/inspector`/SDK) → Test Planner (`TestScenarioPlan`) (D36, D69, D73) |
| [ ] | [12-image-replace](12-image-replace.md) | Same-job custom-OCI image replace re-layering sensors/CA/mounts/canaries/IPC/cgroup v2 (D36, D64, D69) |
| [ ] | [13-install-offline](13-install-offline.md) | Phase 1 install (`package_sha256_before`/`after`, `L2` cgroup v2 `512M`/`64` pids) → Phase 2a monitored detonation & Phase 2b offline verify (D43, D70, D72) |
| [ ] | [14-readiness-verify](14-readiness-verify.md) | Readiness + in-VM OpenCode executes `TestScenarioPlan` (`t0_tools_sha256`→`final_tools_sha256`, `tool_diffs`, wire tap/`strace`) (D30, D37, D54, D73) |
| [ ] | [15-containment-probes](15-containment-probes.md) | 4-axis containment + key-isolation + 3-layer kill switch + 16 MITRE ATLAS & 10 OWASP MCP sensor matrix (D58, D65, D70–D73) |
| [ ] | [16-screenshots](16-screenshots.md) | Authenticated view-only `noVNC` bridge + optional in-guest Playwright stills (E4, D18, D31, D71) |
| [ ] | [17-status-ui](17-status-ui.md) | Live status / SSE UI + `noVNC` live stream + telemetry/kill-switch feed + `routes.py` progress fix (N2, D49, D71) |
| [ ] | [18-vuln-receipt-finalize](18-vuln-receipt-finalize.md) | Plane-1 SCA + cite-checked `vuln_review` + `DetonationVerdict` (`schemas/detonation_verdict.v1.json`) + `JobReceipt` + L3 flush & teardown (E5, D48, D57, D61, D72, D73) |
| [ ] | [19-report-ui](19-report-ui.md) | Report UI: `DetonationVerdict`, SHA/tool diffs, 16 ATLAS + 10 OWASP MCP coverage, containment/kill-switch proof, telemetry/PCAP (N3, D73) |
| [ ] | [20-e2e-fixtures-deploy](20-e2e-fixtures-deploy.md) | Assert 3 baseline + 6 demo MCP scenarios, key isolation, 3-layer kill switch + Vultr reverse proxy deploy (M7, D46, D53, D73) |
| [ ] | [21-cleanup-docs](21-cleanup-docs.md) | Remove build-step / scaffolding docs after M7 (keeping canonical docs + `schemas/*.json`) |

After **21**, the `plan/` ladder should be gone; durable docs and `schemas/*.json` remain at the repo root. See the keep/remove matrix in step 21.

---

## Rules of thumb

- **One plane touch preferred** per step (frontend *or* explore *or* harness/msb). Cross-plane steps say so explicitly.
- **Quality gate every step:** Biome + Knip + typecheck/build + Ruff + pytest + `schemas/*.json` validation + R2 inline/module docs must pass ([LINT.md](LINT.md), `D68`, `D74`).
- **Vultr gate:** Plane 2 and Vultr host work via MCP/`vultr-cli`/`msb` only ([VULTR.md](VULTR.md), `D59`).
- **No secrets** in commits or sandbox env (`VULTR_*` never enters Plane 2 — dummy proxy token + canaries only).
- **Do not** invent readiness success or skip destroy (`D29`, `D47`, `D57`).
- If blocked on Vultr MCP, `vultr-cli`, or `msb` credentials/runtime, **stop and report** — do not fake Plane 2.
