# plan/ — Agent-sized build steps

Work **one step file per agent session**. Do not open every implementation doc and “finish Killhub” in one turn — that times out and drifts.

Canonical product/architecture still live at the repo root. These steps **sequence** the work; they do not replace [PRODUCT.md](../PRODUCT.md) · [ARCHITECTURE.md](../ARCHITECTURE.md) · [DECISIONS.md](../DECISIONS.md) · [DATABASE.md](../DATABASE.md) · [API.md](../API.md).

Plane detail (when a step says “see plane doc”):  
[IMPLEMENTATION_NEXTJS.md](../IMPLEMENTATION_NEXTJS.md) · [IMPLEMENTATION_EXPLORE_SANDBOX.md](../IMPLEMENTATION_EXPLORE_SANDBOX.md) · [IMPLEMENTATION_TEST_VM.md](../IMPLEMENTATION_TEST_VM.md) · [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md)

---

## How to run a step

1. Read **only** this README + [LINT.md](LINT.md) + [VULTR.md](VULTR.md) + the **single** `NN-*.md` step you were assigned (+ any “Read first” links in that step).
2. Complete the checklist. For Vultr / Plane 2 work, use **Vultr MCP**, **`vultr-cli`**, and/or **`msb`** as specified in [VULTR.md](VULTR.md) (D59) — no Docker-as-sandbox fakes.
3. Run the **Lint gate** (Biome + Knip) and fix until both exit 0 — see [LINT.md](LINT.md). **No green lint ⇒ step not done.**
4. Stop when **Done when** is true (includes lint + real Vultr/`msb` where required).
5. Do **not** start the next step in the same session unless the human explicitly asks.
6. Update the step’s status checkbox in this index when finished.

---

## Order (do in sequence)

| Status | Step | Focus |
|:------:|------|--------|
| [ ] | [01-scaffold-frontend](01-scaffold-frontend.md) | Next.js compose shell (N0) |
| [ ] | [02-scaffold-explore](02-scaffold-explore.md) | Explore worker shell (E0) |
| [ ] | [03-ledger-core](03-ledger-core.md) | Durable job/event store (D41) |
| [ ] | [04-internal-worker-api](04-internal-worker-api.md) | Python Internal Worker API (D52) |
| [ ] | [05-jobs-proxy-admission](05-jobs-proxy-admission.md) | Next proxy + admission + SSE cursor (N1) |
| [ ] | [06-msb-create-destroy](06-msb-create-destroy.md) | Microsandbox create/destroy + reaper (T0) |
| [ ] | [07-msb-exec-copy](07-msb-exec-copy.md) | Exec + copy in/out (T1) |
| [ ] | [08-net-policy-canaries](08-net-policy-canaries.md) | Network policy + canaries on create (D39, D44) |
| [ ] | [09-preflight](09-preflight.md) | Plane-1 pre-flight before create (D45) |
| [ ] | [10-opencode-lockdown](10-opencode-lockdown.md) | Trusted OpenCode + Vultr inference only (D38, D25) |
| [ ] | [11-bootstrap-discover](11-bootstrap-discover.md) | Bootstrap sandbox + discover runtime profile (D36) |
| [ ] | [12-image-replace](12-image-replace.md) | Same-job image replace (still one VM) |
| [ ] | [13-install-offline](13-install-offline.md) | Install egress → offline phase (D43) |
| [ ] | [14-readiness-verify](14-readiness-verify.md) | MCP/HTTP readiness + verification kinds (D37, D54) |
| [ ] | [15-containment-probes](15-containment-probes.md) | Containment matrix + network + canary scan (D58) |
| [ ] | [16-screenshots](16-screenshots.md) | Optional in-guest Playwright stills (E4) |
| [ ] | [17-status-ui](17-status-ui.md) | Live status / SSE UI (N2) |
| [ ] | [18-vuln-receipt-finalize](18-vuln-receipt-finalize.md) | SCA + cite-checked review + receipt + destroy (E5) |
| [ ] | [19-report-ui](19-report-ui.md) | Report / receipt window (N3) |
| [ ] | [20-e2e-fixtures-deploy](20-e2e-fixtures-deploy.md) | Pinned fixtures + demo edge deploy (M7) |
| [ ] | [21-cleanup-docs](21-cleanup-docs.md) | Remove build-step / scaffolding docs after M7 |

After **21**, the `plan/` ladder (and optionally `IMPLEMENTATION_*.md`) should be gone; durable docs remain at the repo root. See the keep/remove matrix in step 21.

---

## Rules of thumb

- **One plane touch preferred** per step (frontend *or* explore *or* harness/msb). Cross-plane steps say so explicitly.
- **Lint gate every step:** Biome + Knip must pass before continuing ([LINT.md](LINT.md)). Step 01 installs them; later steps keep them green even if only Python changed.
- **Vultr gate:** Plane 2 and Vultr host work via MCP/`vultr-cli`/`msb` only ([VULTR.md](VULTR.md), D59).
- **No secrets** in commits or sandbox env (canaries only).
- **Do not** invent readiness success or skip destroy (D29, D47, D57).
- If blocked on Vultr MCP, `vultr-cli`, or `msb` credentials/runtime, **stop and report** — do not fake Plane 2.
