# Lint / quality gate — frontend + Python + JSON Schemas + R2 docs (D68, D74)

Every `plan/` step must leave **both** code trees clean, validate `schemas/*.json`, comply with `AGENTS.md` §5 (R2), and pass focused tests before it is marked done. Biome does **not** cover Python ([Biome languages](https://biomejs.dev/internals/language-support/)).

## Commands

### Frontend (`frontend/` — once step 01 has added tooling)

```bash
cd frontend
pnpm lint:fix     # biome check --write .
pnpm lint          # biome check .
pnpm knip          # unused exports / deps
pnpm typecheck     # next typegen && tsc --noEmit (typed routes)
pnpm build         # next build — proves the app compiles
```

Equivalent if scripts are missing:

```bash
pnpm exec biome check --write .
pnpm exec biome check .
pnpm exec knip
pnpm exec tsc --noEmit
pnpm exec next build
```

### Python (`explore/` — using repo-root `.venv/`)

The project Python virtualenv lives at the **repo root** (`.venv/`), targeting Python `3.10`–`3.12` (note: `explore/ruff.toml` targets `py310`+; `explore/Dockerfile` uses `3.12`):

```bash
# First-time setup from repo root:
python3 -m venv .venv
.venv/bin/pip install -r explore/requirements-dev.txt   # ruff, pytest, httpx, jsonschema

# Gate checks (run from explore/ using repo-root ../.venv):
cd explore
../.venv/bin/ruff check .
../.venv/bin/ruff format --check .
../.venv/bin/pytest -q
```

Or from repo root (when `.venv/bin` or `ruff` is on `PATH`):

```bash
.venv/bin/ruff check explore/
.venv/bin/ruff format --check explore/
.venv/bin/pytest -q explore/tests
```

Do not skip Python checks on frontend-only edits, and do not skip frontend checks on Python-only edits.

### JSON Schema Draft 2020-12 validation (`schemas/*.json`)

Whenever any file under `schemas/` or any schema producer/consumer changes, validate all 4 canonical Draft 2020-12 schemas (`jsonschema 4.23.0` on system `python3` or `.venv/bin/python`):

```bash
python3 -c "import json; from pathlib import Path; from jsonschema import Draft202012Validator; [Draft202012Validator.check_schema(json.loads(p.read_text())) or print('OK', p.name) for p in sorted(Path('schemas').glob('*.json'))]"
```

### R2 Documentation Compliance Check (`AGENTS.md` §5)

Before marking any code-writing step complete, inspect `git diff` and newly created files to verify:
1. **Inline documentation on every edit:** Added/modified code blocks include concise inline comments or docstrings explaining *what* the code does and *why* key invariants/guards/security boundaries exist.
2. **Module frontmatter/header on every new module:** Every new `.py` file starts with a module-level triple-quoted docstring (`"""..."""`, `ruff`-compliant) and every new `.ts`/`.tsx`/`.js` file starts with a top-of-file JSDoc block (`/** ... */`, `biome`-compliant) stating: (1) module purpose, (2) Plane (`Plane 1` / `Plane 2`) and trust-zone responsibility, and (3) key contracts/invariants.

### Focused tests (required as the features land)

| Area | Coverage |
|------|----------|
| Ledger transactions | Atomic job/event/profile-revision/verdict writes; SQLite WAL + `busy_timeout`; restart reconciliation |
| Cancellation races | D61 ordering: `cancel_requested_at` → freeze → finalizer receipt → terminal `cancelled`; ordinary writers rejected |
| SSE handoff | Snapshot `event_cursor` → subscribe; live `progress` hoisting; `cursor_expired`; contiguous prune + `gap` (D55, D67) |
| Schema validation | `environment_profile.v1.json`, `dynamic_install_spec.v1.json`, `test_scenario_plan.v1.json`, `detonation_verdict.v1.json` (`D51`, `D69`, `D73`) |
| Key isolation & Kill Switch | Dummy token in Plane 2 vs `VULTR_INFERENCE_API_KEY` on Plane 1 proxy; L1 `429` (`12` turns / `60k` tokens / oscillation), L2 cgroup v2 (`512M`/`0`/`64`), L3 flush+teardown (`D71`, `D72`) |
| `noVNC` & TAP/`mitmdump` | Authenticated view-only `noVNC` drops RFB input frames; DoH/DoT/QUIC drop; real-time canary blocking (`D70`, `D71`) |

Wire these under `explore/tests/` (and/or `frontend` contract tests) as the owning steps implement the features; later steps must keep them green.

## Rules

1. **Gate:** Biome, Knip, frontend typecheck, frontend build, Ruff (`check` + `format --check`), `pytest`, `schemas/*.json` validation, and R2 doc compliance must exit **0** before checking **Done when** and before starting the next step.
2. **Fix, don’t silence:** Prefer fixing code. Only add knip/biome/ruff ignores when justified in step notes or `DECISIONS.md` — never to “get green” for dead or broken code.
3. **Python-only steps still run the full gate.** If you only edited `explore/`, run frontend Biome + Knip + typecheck + build **and** Python Ruff + pytest so neither tree rots.
4. **Frontend-only steps still run Ruff + pytest** on `explore/`.
5. **Report failures:** If the gate fails and you cannot fix it in-session, stop and report — do not mark the step complete.
