# Step 14 — Readiness verify, `TestScenarioPlan` detonation & `tool_diffs` (D37, D54, D73)

**Goal:** Launch the built checkout (`D62`), set readiness evidence (`D30`, `D51`) and `verification.kind` (`D54`), execute `TestScenarioPlan` scenarios via **in-VM victim OpenCode** under Phase 2a monitored detonation, collect `strace` + MCP wire tap + OverlayFS `upperdir` telemetry, and compute `final_tools_sha256` & `tool_diffs[]` (`D73`).

## Prerequisites

- [13-install-offline.md](13-install-offline.md)
- [10b-pin-fixtures.md](10b-pin-fixtures.md)

## Read first

- [DECISIONS.md](../DECISIONS.md) D30, D37, D47, D51, D54, D62, D66, **D73**
- [IMPLEMENTATION_EXPLORE_SANDBOX.md](../IMPLEMENTATION_EXPLORE_SANDBOX.md) § "Discovery → Test-Planner" & § E3
- [IMPLEMENTATION_TEST_VM.md](../IMPLEMENTATION_TEST_VM.md) § 3, § 6, § 8
- [AGENTS.md](../AGENTS.md) § 5 (R2 inline docs + module frontmatter)

## Vultr / msb tooling (required)

Use **`msb` CLI/SDK** (and Vultr MCP / `vultr-cli` to verify the VX1 host) per [VULTR.md](VULTR.md) and `D59`. Do not fake Plane 2 with Docker.

## Do

- [ ] `explore/verify.py`:
  - Launch **built checkout** at `resolved_commit` (`D62`, no unpinned `npx -y`) inside Layer 2 cgroup v2 slice with `strace` and MCP wire tap attached
  - `git_mcp` (`stdio`) → `mcp_stdio_verify.py` (`initialize` → `notifications/initialized` → `tools/list`, `D51`); `git_mcp` (`streamable_http`) → HTTP MCP handshake listing tools; `webapp` / `demo` → profile probe
  - On pass: set `readiness` + `verification.kind` (`original_application` | `generated_demo` | `setup_failed`); retain `verification.original_failure` if `generated_demo` (`D54`); **do not** destroy or mark `completed` (`D37`, `D66`)
- [ ] **Phase 2a Scenario Detonation (`D73`):**
  - Drive in-VM OpenCode (`/home/agent/.config/opencode/`, talking to Plane 1 Host LLM Proxy with L1 breaker) through `TestScenarioPlan.scenarios[]`
  - Stream `mcp_wire_tap`, `strace` (`execve`, `openat`, `connect`), `overlayfs` `upperdir` diff, `opencode_db_audit`, and `mitmdump` HTTP/S+DNS / real-time canary-block events over `AF_VSOCK`/UDS + TAP
  - Re-run `tools/list` post-detonation to compute **`final_tools_sha256`** and **`tool_diffs[]`** (`added`, `removed`, `modified_schema`, `modified_description`), emitting `tool_diff` SSE events (catches Scenarios 2 & 5)
- [ ] Consume pinned baseline + 6 demo fixtures from step `10b`; deterministic gates own readiness (`D47`, `D66`)

## Do not

- Destroy sandbox on readiness alone (`D37`)
- Collapse `generated_demo` into “original app works” (`D54`)
- Satisfy original-application readiness via unversioned registry package launch (`D62`)

## Lint gate (required before Done when)

Run the **full quality gate** ([LINT.md](LINT.md) — `D68`, `D74`) including R2 compliance:

```bash
cd frontend && pnpm lint:fix && pnpm lint && pnpm knip && pnpm typecheck && pnpm build
cd ../explore && ../.venv/bin/ruff check . && ../.venv/bin/ruff format --check . && ../.venv/bin/pytest -q
cd .. && python3 -c "import json; from pathlib import Path; from jsonschema import Draft202012Validator; [Draft202012Validator.check_schema(json.loads(p.read_text())) or print('OK', p.name) for p in sorted(Path('schemas').glob('*.json'))]"
```

Must exit **0**.

## Done when

Pinned webapp + filesystem MCP fixtures set readiness against their SHAs; controlled fail fixture is `setup_failed`; in-VM OpenCode executes `TestScenarioPlan` capturing `t0_tools_sha256` vs `final_tools_sha256`, `tool_diffs`, `strace`, and MCP wire-tap telemetry while sandbox remains alive; full quality gate + R2 docs pass ([LINT.md](LINT.md)).

## Next

[15-containment-probes.md](15-containment-probes.md)
