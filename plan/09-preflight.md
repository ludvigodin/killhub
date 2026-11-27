# Step 09 — Plane-1 pre-flight + intake extension + baseline fixes (D15, D45)

**Goal:** Run cheap validation/pre-flight on Plane 1 for both public HTTPS `github.com` URLs and validated MCP registry/fixture targets (`npm:`, `pypi:`, `fixture:`) before creating any sandbox; fold in verified baseline `explore/` & `docker-compose.yml` fixes (`ALIGNMENT_PLAN.md` §3).

## Prerequisites

- [05-jobs-proxy-admission.md](05-jobs-proxy-admission.md)
- [08-net-policy-canaries.md](08-net-policy-canaries.md) optional but preferred before plan loop

## Read first

- [DECISIONS.md](../DECISIONS.md) D15, D40, D45 · [API.md](../API.md) `POST /api/jobs` · [DATABASE.md](../DATABASE.md)
- [ALIGNMENT_PLAN.md](../ALIGNMENT_PLAN.md) § 3 (baseline fixes) · [ARCHITECTURE.md](../ARCHITECTURE.md) — plan loop step −1
- [AGENTS.md](../AGENTS.md) § 5 (R2 inline docs + module frontmatter)

## Do

- [ ] **Fold in verified baseline fixes (`ALIGNMENT_PLAN.md` § 3):**
  - `explore/api/routes.py:141-152`: hoist `progress` and `current_step` in the live-tailing SSE loop (matching replay lines `111-114`) + fix the 13–15s empty-poll sleep (`routes.py:122-139`) with regression test in `explore/tests/test_internal_api.py`
  - `explore/ledger/store.py:99-106`: enable `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000;`
  - `docker-compose.yml:7-8`: bind `127.0.0.1:8100:8100` (not `0.0.0.0`)
  - `explore/ruff.toml` & `explore/requirements-dev.txt`: update `target-version = "py310"` and add `jsonschema>=4.23.0`
- [ ] Extend intake validation (`explore/preflight.py`, `explore/api/routes.py`, `frontend/lib/github.ts`, `frontend/components/UrlForm.tsx`) for `D15`:
  - Public HTTPS `https://github.com/<org>/<repo>` (default `target_type="github_repo"`)
  - Optional validated MCP registry / fixture targets (`target_type` = `npm_package` | `pypi_package` | `fixture`, with `mcp_registry_ref` or `fixture_id`) — reject malformed/arbitrary URLs or unknown schemes with HTTP `400` (`invalid_url` / `invalid_target`)
- [ ] Plane-1 pre-flight (`explore/preflight.py`): metadata / cheap risk checks after URL + admission; hard-fail → terminal `failed` with `finding.source=preflight` (`code=preflight_blocked`), **no** `msb create`; soft signals continue with findings attached
- [ ] Emit `log.kind=preflight` / `finding` events

## Do not

- Run untrusted `npm`/`pip` install on the control plane
- Create a Microsandbox “just to inspect” on hard-fail paths

## Lint gate (required before Done when)

Run the **full quality gate** ([LINT.md](LINT.md) — `D68`, `D74`) including R2 compliance:

```bash
cd frontend && pnpm lint:fix && pnpm lint && pnpm knip && pnpm typecheck && pnpm build
cd ../explore && ../.venv/bin/ruff check . && ../.venv/bin/ruff format --check . && ../.venv/bin/pytest -q
cd .. && python3 -c "import json; from pathlib import Path; from jsonschema import Draft202012Validator; [Draft202012Validator.check_schema(json.loads(p.read_text())) or print('OK', p.name) for p in sorted(Path('schemas').glob('*.json'))]"
```

Must exit **0**.

## Done when

Invalid/hostile GitHub URLs or MCP registry targets fail at Plane-1 pre-flight without creating a VM; valid GitHub and `npm:`/`pypi:`/`fixture:` targets proceed; baseline SSE `progress` hoisting, SQLite WAL, and `docker-compose.yml` `127.0.0.1` fixes are verified by tests; full quality gate + R2 docs pass ([LINT.md](LINT.md)).

## Next

[10-opencode-lockdown.md](10-opencode-lockdown.md)
