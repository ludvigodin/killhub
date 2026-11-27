# Step 10 — OpenCode split, Host LLM Proxy (`L1` breaker), key isolation & `D74` models

**Goal:** Lock down Plane 1 planners/reviewers under trusted config (`D38`), implement the **Plane 1 Host LLM Proxy** serving in-VM victim OpenCode over `AF_VSOCK`/UDS/`mgmt0` with **Layer 1 circuit breaker** (`max_turns=12`, `max_tokens=60000`, oscillation→`429`) and **key isolation** (`VULTR_INFERENCE_API_KEY` never enters Plane 2 — `D71`, `D72`), and wire per-role Vultr Serverless Inference models (`D25`, `D74`).

## Prerequisites

- [04-internal-worker-api.md](04-internal-worker-api.md)
- [07-msb-exec-copy.md](07-msb-exec-copy.md) (for IPC transport)

## Read first

- [VULTR.md](VULTR.md) · [DECISIONS.md](../DECISIONS.md) D7, D25, D38, D59, **D71**, **D72**, **D74**
- [ALIGNMENT_PLAN.md](../ALIGNMENT_PLAN.md) § 6 (LLM model-selection plan)
- [IMPLEMENTATION_EXPLORE_SANDBOX.md](../IMPLEMENTATION_EXPLORE_SANDBOX.md) § "Host LLM Proxy" & "Per-Agent Model-Selection"
- [ARCHITECTURE.md](../ARCHITECTURE.md) § "Host LLM Proxy & Key Isolation Demonstration"
- [AGENTS.md](../AGENTS.md) § 5 (R2 inline docs + module frontmatter)

## Vultr tooling (required)

- [ ] Route **all** LLM calls exclusively to **`https://api.vultrinference.com/v1`** (`D25`) — prove with a real inference call (or fail closed if `VULTR_INFERENCE_API_KEY` missing); do not stub a fake provider in done criteria
- [ ] Configure per-role model env vars (`VULTR_INFERENCE_MODEL_PLANNER`, `VULTR_INFERENCE_MODEL_TESTER`, `VULTR_INFERENCE_MODEL_VICTIM`, `VULTR_INFERENCE_MODEL_REVIEW`, each falling back to `VULTR_INFERENCE_MODEL` — `D74`)

## Do

- [ ] **Plane 1 Planners/Reviewers Lockdown (`explore/agents/inference.py`):**
  - Ship host-owned trusted OpenCode/agent system config denying host `shell`, untrusted local file writes, and non-Vultr providers; treat submitted-repo `AGENTS.md` / `.opencode` and guest tool outputs as **untrusted data** (`D38`, `ALIGNMENT_PLAN.md` S6)
  - Expose only job-scoped harness tools; fail closed if `VULTR_INFERENCE_BASE_URL` is not Vultr Serverless Inference
- [ ] **Plane 1 Host LLM Proxy (`explore/llm_proxy.py`, `D71`):**
  - Serve `POST /internal/llm-proxy/v1/chat/completions` strictly on hypervisor IPC (`AF_VSOCK` / UDS / `mgmt0`) — **never** on public HTTP or Next.js `/api/*`
  - Validate per-job ephemeral dummy bearer token (`kh_proxy_<job_id>_<nonce>`) sent by Plane 2 in-VM OpenCode (`/home/agent/.config/opencode/`, `opencode.db`), strip dummy token, inject `VULTR_INFERENCE_API_KEY` exclusively on Plane 1 outbound HTTPS to Vultr Inference (`VULTR_INFERENCE_MODEL_VICTIM`)
- [ ] **Layer 1 Circuit Breaker (`D72`):**
  - Enforce `max_turns = 12` (`LLM_PROXY_MAX_TURNS`), `max_tokens = 60000` (`LLM_PROXY_MAX_TOKENS`), and repeated/oscillating tool-call detection (`>= 3` identical tool+args)
  - Return HTTP **`429`** (`code: "kill_switch_layer1"`), increment `llm_proxy_429_blocks`, and emit `kill_switch` / `log.kind=llm_proxy_429` SSE
- [ ] **Key-isolation verification test:** prove `/proc/*/environ` and OpenCode files inside Plane 2 contain zero `VULTR_*` keys while proxy logs confirm real key stays on Plane 1
- [ ] Persist `inference_model` and per-role `inference_usage` toward `INFERENCE_BUDGET_TOKENS_PER_JOB` (`200000`)

## Do not

- Inject `VULTR_INFERENCE_API_KEY` or `VULTR_API_KEY` into Plane 2 environment variables, `.config/opencode/`, or `opencode.db`
- Load project OpenCode config from the cloned repo as Plane 1 authority
- Call alternate LLM providers or point inference at localhost mocks in done criteria

## Lint gate (required before Done when)

Run the **full quality gate** ([LINT.md](LINT.md) — `D68`, `D74`) including R2 compliance:

```bash
cd frontend && pnpm lint:fix && pnpm lint && pnpm knip && pnpm typecheck && pnpm build
cd ../explore && ../.venv/bin/ruff check . && ../.venv/bin/ruff format --check . && ../.venv/bin/pytest -q
cd .. && python3 -c "import json; from pathlib import Path; from jsonschema import Draft202012Validator; [Draft202012Validator.check_schema(json.loads(p.read_text())) or print('OK', p.name) for p in sorted(Path('schemas').glob('*.json'))]"
```

Must exit **0**.

## Done when

Plane 1 planners cannot shell the host and route per-role models (`D74`) to Vultr Inference; in-VM OpenCode talks to Plane 1 Host LLM Proxy using only an ephemeral dummy token (zero `VULTR_*` keys in Plane 2); Layer 1 returns `429` at 12 turns / 60k tokens / oscillation; full quality gate + R2 docs pass ([LINT.md](LINT.md)).

## Next

[10b-pin-fixtures.md](10b-pin-fixtures.md)
