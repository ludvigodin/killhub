# Step 16 — Authenticated view-only `noVNC` bridge & optional in-guest Playwright stills (E4, D18, D38, D71)

**Goal:** Expose the in-VM OpenCode detonation display strictly via an authenticated, **view-only `noVNC`** WebSocket/HTTP proxy on Plane 1 (`D71`), and capture optional Playwright stills inside Plane 2 for HTTP webapps without gating completion (`D31`, `D38`).

## Prerequisites

- [14-readiness-verify.md](14-readiness-verify.md)

## Read first

- [DECISIONS.md](../DECISIONS.md) D18, D31, D38, D46, D60, **D71**
- [API.md](../API.md) — `GET /api/jobs/{id}/novnc`, `/screenshots`
- [ALIGNMENT_PLAN.md](../ALIGNMENT_PLAN.md) § 4 (`S1` `noVNC` mitigation)
- [IMPLEMENTATION_EXPLORE_SANDBOX.md](../IMPLEMENTATION_EXPLORE_SANDBOX.md) § E4
- [AGENTS.md](../AGENTS.md) § 5 (R2 inline docs + module frontmatter)

## Vultr / msb tooling (required)

Use **`msb` CLI/SDK** (and Vultr MCP / `vultr-cli` to verify the VX1 host) per [VULTR.md](VULTR.md) and `D59`. Do not fake Plane 2 with Docker.

## Do

- [ ] **Authenticated View-Only `noVNC` Bridge (`explore/novnc_bridge.py` + `explore/api/routes.py` + `frontend/app/api/jobs/[id]/novnc/route.ts`, `D71`):**
  - Bind internal VNC/websockify bridge to `127.0.0.1` (or UDS) on Plane 1 (`D46`)
  - Require short-lived, `job_id`-scoped signed token issued by Plane 1; return `404` unknown job or `409` (`code=sandbox_not_running`) when VM is not running
  - Enforce **strict view-only mode**: guest VNC server `view_only=true` **and** drop all client→server RFB pointer/key/clipboard frames at the Plane 1 WebSocket proxy (`ALIGNMENT_PLAN.md` S1)
  - Emit `novnc` SSE (`{ available, ws_path, view_only: true, state }`) and close WebSocket cleanly on VM destroy / terminal status
- [ ] **Optional In-Guest Playwright Stills (`explore/screenshots.py`, `D31`, `D38`):**
  - Run Playwright **inside Plane 2** for HTTP webapp verify when useful; `copy_out` stills to `storage/screenshots/{job_id}/` under `D60`
  - Skip for CLI-only MCP / early fail; cap `MAX_SCREENSHOTS_PER_JOB` + disk budget; redact secrets; emit SSE `screenshot` only when captured

## Do not

- Allow interactive keyboard/mouse RFB input from browsers into the detonation microVM
- Store persistent full-session video recordings (`D18`)
- Block `completed` when screenshot timeline is empty (`D31`)
- Run Playwright against untrusted pages on Plane 1 (`D38`)

## Lint gate (required before Done when)

Run the **full quality gate** ([LINT.md](LINT.md) — `D68`, `D74`) including R2 compliance:

```bash
cd frontend && pnpm lint:fix && pnpm lint && pnpm knip && pnpm typecheck && pnpm build
cd ../explore && ../.venv/bin/ruff check . && ../.venv/bin/ruff format --check . && ../.venv/bin/pytest -q
cd .. && python3 -c "import json; from pathlib import Path; from jsonschema import Draft202012Validator; [Draft202012Validator.check_schema(json.loads(p.read_text())) or print('OK', p.name) for p in sorted(Path('schemas').glob('*.json'))]"
```

Must exit **0**.

## Done when

Authenticated view-only `noVNC` proxy streams live in-VM OpenCode while dropping client RFB input frames and closing on destroy; HTTP webapp verify attaches optional in-guest Playwright stills; MCP-only jobs complete cleanly with empty screenshot timeline; full quality gate + R2 docs pass ([LINT.md](LINT.md)).

## Next

[17-status-ui.md](17-status-ui.md)
