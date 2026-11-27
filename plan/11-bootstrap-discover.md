# Step 11 — Bootstrap, Env/Install Planner & Discovery → Test Planner (D36, D69, D73)

**Goal:** Provision the Ubuntu 24.04 bootstrap VM, inspect the cloned repo/registry target, run the **Environment/Install Planner** (`schemas/environment_profile.v1.json` + `schemas/dynamic_install_spec.v1.json`), and wire the **Discovery (`@modelcontextprotocol/inspector` + Python MCP SDK fallback) → Test-Planner Agent** pipeline (`schemas/test_scenario_plan.v1.json`).

## Prerequisites

- [09-preflight.md](09-preflight.md)
- [10-opencode-lockdown.md](10-opencode-lockdown.md)
- [10b-pin-fixtures.md](10b-pin-fixtures.md)
- [08-net-policy-canaries.md](08-net-policy-canaries.md)

## Read first

- [DECISIONS.md](../DECISIONS.md) D6, D34, D35, D36, D51, D62, D64, **D69**, **D73**
- [DATABASE.md](../DATABASE.md) — `EnvironmentProfileRevision`, `DynamicInstallSpec`, `TestScenarioPlan`
- [IMPLEMENTATION_EXPLORE_SANDBOX.md](../IMPLEMENTATION_EXPLORE_SANDBOX.md) § "Environment/Install Planner & Discovery → Test-Planner"
- [IMPLEMENTATION_TEST_VM.md](../IMPLEMENTATION_TEST_VM.md) § 6
- [AGENTS.md](../AGENTS.md) § 5 (R2 inline docs + module frontmatter)

## Vultr / msb tooling (required)

Use **`msb` CLI/SDK** (and Vultr MCP / `vultr-cli` to verify the VX1 host) per [VULTR.md](VULTR.md) and `D59`. Do not fake Plane 2 with Docker.

## Do

- [ ] Trusted bootstrap profile → `MSB_DEFAULT_IMAGE="ubuntu-24.04-killhub"` create (before discovery — `D36`, `D69`)
- [ ] Clone/resolve target **inside** Plane 2 (`msb exec`/`copy`, never privileged host install); persist **`resolved_commit`** (`D62`)
- [ ] **Environment/Install Planner (`explore/agents/env_planner.py` + `explore/profile.py`):**
  - Emit and validate runtime `environment_profile.json` against `schemas/environment_profile.v1.json` (`source.commit` required, `intent` = `git_mcp` | `webapp` | `demo`, `D34`, `D51`)
  - Emit and validate **`DynamicInstallSpec`** against `schemas/dynamic_install_spec.v1.json` (`D69`: mounts/seeds, TAP/`mitmdump`, IPC, 3-layer kill-switch limits)
  - Append profile revision + install spec under `storage/profiles/{job_id}/` and `storage/specs/{job_id}/` (`D64`); invalid runtime profile/spec blocks provisioning
- [ ] **Discovery → Test-Planner Pipeline (`explore/agents/test_planner.py` + `explore/helpers/mcp_discover.py`, `D73`):**
  - Run `@modelcontextprotocol/inspector --cli --format json` (`initialize`, `tools/list`, `resources/list`, `prompts/list`), falling back to `mcp_discover.py` (Python MCP SDK) when tool catalogs are large or truncated
  - Compute SHA-256 **`t0_tools_sha256`** over canonicalized `tools/list`
  - Feed Discovery JSON (wrapped in untrusted-data delimiters — `ALIGNMENT_PLAN.md` S6) to the Plane 1 Test-Planner Agent (`VULTR_INFERENCE_MODEL_TESTER`) to generate schema-valid **`TestScenarioPlan`** (`schemas/test_scenario_plan.v1.json`, `storage/plans/{job_id}/scenario_plan.json`) targeting `AML.TA*` and `MCP01:2025`–`MCP10:2025`
- [ ] Stream `span` / `log` (`log.kind=discovery`, `test_planner`) / `status` events; consume pinned fixtures from step `10b`

## Do not

- Run full detonation execution yet (step 14)
- Create a second concurrent VM for explore vs test (`D27`)
- Discover/write runtime profile before bootstrap create (`D36`)

## Lint gate (required before Done when)

Run the **full quality gate** ([LINT.md](LINT.md) — `D68`, `D74`) including R2 compliance:

```bash
cd frontend && pnpm lint:fix && pnpm lint && pnpm knip && pnpm typecheck && pnpm build
cd ../explore && ../.venv/bin/ruff check . && ../.venv/bin/ruff format --check . && ../.venv/bin/pytest -q
cd .. && python3 -c "import json; from pathlib import Path; from jsonschema import Draft202012Validator; [Draft202012Validator.check_schema(json.loads(p.read_text())) or print('OK', p.name) for p in sorted(Path('schemas').glob('*.json'))]"
```

Must exit **0**.

## Done when

Pinned webapp + MCP fixtures emit schema-valid `environment_profile.v1.json`, `dynamic_install_spec.v1.json`, and `test_scenario_plan.v1.json` (with `t0_tools_sha256`) after bootstrap inspect; full quality gate + R2 docs pass ([LINT.md](LINT.md)).

## Next

[12-image-replace.md](12-image-replace.md)
