# Step 10b — Pin 3 baseline fixtures + 6 Demo Malicious MCP Scenarios (D53, D73)

**Goal:** Record pinned commit SHAs, MCP registry versions, and fixture metadata in `explore/fixtures/m7.json` for the **3 baseline fixtures** and all **6 Demo Malicious MCP Scenarios** **before** bootstrap/discover and detonation steps (`11`–`20`) consume them.

## Prerequisites

- [10-opencode-lockdown.md](10-opencode-lockdown.md)

## Read first

- [DECISIONS.md](../DECISIONS.md) D53, D62, **D73**
- [DATABASE.md](../DATABASE.md) — `source.commit` / `resolved_ref` required
- [IMPLEMENTATION_TEST_VM.md](../IMPLEMENTATION_TEST_VM.md) § 8 (6 Demo Scenarios)
- [AGENTS.md](../AGENTS.md) § 5 (R2 inline docs + module frontmatter)

## Do

- [ ] Create `explore/fixtures/m7.json` (and loader helper with R2 docstring) containing pinned public HTTPS `github.com` SHAs / registry specs / fixture IDs for:
  - **3 Baseline v1 Golden Fixtures (`D53`):**
    1. Webapp success — `https://github.com/heroku/node-js-getting-started` @ pinned 40-char SHA → `original_application`
    2. `git_mcp` filesystem (stdio) — `https://github.com/modelcontextprotocol/servers` @ pinned 40-char SHA + fixed filesystem entrypoint/path (built checkout launch — `D62`)
    3. Controlled `setup_failed` + SCA — deliberately broken fixture (not NodeGoat) with `forbid_demo_intent=true` and `findings.source=sca` asserted separately from `intentional_app`
  - **6 Demo Malicious MCP Scenarios (`D53`, `D73` — DVMCP + targeted fixtures):**
    1. `scenario-1-indirect-prompt-injection` — Indirect prompt injection via GitHub issue (`AML.TA0004`, `AML.TA0010`; `MCP06:2025`)
    2. `scenario-2-tool-rug-pull` — Delayed tool obfuscation / rug pull (`AML.TA0001`, `AML.TA0008`; `MCP03:2025`)
    3. `scenario-3-post-install-backdoor` — Post-install modified package backdoor (`npm:` / `pypi:` / tarball fixture; `AML.TA0003`, `AML.TA0006`; `MCP04:2025`, `MCP09:2025`)
    4. `scenario-4-credential-exfiltration` — Host microVM credential exfiltration via OpenCode tools & `opencode.db` (`AML.TA0009`, `AML.TA0010`, `AML.TA0013`; `MCP01:2025`, `MCP05:2025`)
    5. `scenario-5-tool-drift-shadowing` — External manipulation of a clean MCP server via tool drift / shadowing (`AML.TA0008`, `AML.TA0014`, `AML.TA0015`; `MCP03:2025`, `MCP06:2025`)
    6. `scenario-6-infinite-loop-exhaustion` — Resource exhaustion via infinite agent loop (`AML.TA0011`; `MCP08:2025`, `MCP10:2025`)
- [ ] Document expected trigger steps, invariants, and catching sensors for each fixture (`D73`) and how `findings.source=sca` stays separate from `intentional_app` (`D53`)
- [ ] Do **not** use NodeGoat as the deterministic fail fixture

## Do not

- Defer first-time pinning to step 20
- Leave `source.commit` / `resolved_ref` optional for fixture profiles

## Lint gate (required before Done when)

Run the **full quality gate** ([LINT.md](LINT.md) — `D68`, `D74`) including R2 compliance:

```bash
cd frontend && pnpm lint:fix && pnpm lint && pnpm knip && pnpm typecheck && pnpm build
cd ../explore && ../.venv/bin/ruff check . && ../.venv/bin/ruff format --check . && ../.venv/bin/pytest -q
cd .. && python3 -c "import json; from pathlib import Path; from jsonschema import Draft202012Validator; [Draft202012Validator.check_schema(json.loads(p.read_text())) or print('OK', p.name) for p in sorted(Path('schemas').glob('*.json'))]"
```

Must exit **0**.

## Done when

`explore/fixtures/m7.json` pins all 3 baseline fixtures and all 6 demo malicious MCP scenarios with concrete SHAs/versions, entrypoints, and expected sensor invariants; steps 11, 14, and 20 can consume them directly; full quality gate + R2 docs pass ([LINT.md](LINT.md)).

## Next

[11-bootstrap-discover.md](11-bootstrap-discover.md)
