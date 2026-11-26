# Step 10 — OpenCode lockdown + Vultr inference (D38, D25)

**Goal:** Environment Agent runs under trusted config; only **Vultr Serverless Inference**; no host shell.

## Prerequisites

- [04-internal-worker-api.md](04-internal-worker-api.md)

## Read first

- [VULTR.md](VULTR.md) · [DECISIONS.md](../DECISIONS.md) D38, D25, D7, D59
- [IMPLEMENTATION_EXPLORE_SANDBOX.md](../IMPLEMENTATION_EXPLORE_SANDBOX.md) § E2 (OpenCode bullets)

## Vultr tooling (required)

- [ ] Configure OpenCode provider against **`https://api.vultrinference.com/v1`** only (D25)
- [ ] Prove with a real inference call (or fail closed if `VULTR_INFERENCE_*` missing) — do not stub a fake provider
- [ ] If using Microsandbox MCP in trusted config for debug, keep it D38-gated; harness still owns job sandboxes via `msb` (D23)

## Do

- [ ] Ship host-owned trusted OpenCode system/managed config
- [ ] Deny host `shell`, arbitrary providers/plugins; allow only Vultr-compatible provider
- [ ] Expose only job-scoped harness tools (even if stubs)
- [ ] Fail closed if inference base URL is not Vultr Serverless Inference
- [ ] Treat submitted-repo `AGENTS.md` / `.opencode` as untrusted input
- [ ] Persist `inference_model` + usage toward budgets

## Do not

- Load project OpenCode config from the cloned repo as authority
- Call alternate LLM providers
- Point inference at localhost mocks in “done” criteria

## Lint gate (required before Done when)

Run Biome + Knip and fix all findings before marking this step done (see [LINT.md](LINT.md)):

```bash
cd frontend
pnpm lint:fix && pnpm lint && pnpm knip
```

Must exit **0**. Do **not** start the next step while either tool fails. Python-only changes still require a green gate.

## Done when

Agent process cannot shell the host; a test call hits **Vultr Inference** only (or fails closed without keys). Biome + Knip lint gate passes ([LINT.md](LINT.md)).

## Next

[11-bootstrap-discover.md](11-bootstrap-discover.md)
