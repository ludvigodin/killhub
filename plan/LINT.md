# Lint / quality gate — frontend + Python (D68)

Every `plan/` step must leave **both** trees clean and the focused contracts tested before it is marked done. Biome does **not** cover Python ([Biome languages](https://biomejs.dev/internals/language-support/)).

## Commands

### Frontend (`frontend/` — once step 01 has added tooling)

```bash
cd frontend
pnpm lint:fix     # biome check --write .
pnpm lint          # biome check .
pnpm knip          # unused exports / deps
pnpm typecheck     # tsc --noEmit (or project equivalent)
pnpm build         # next build (or project build) — proves the app compiles
```

Equivalent if scripts are missing:

```bash
pnpm exec biome check --write .
pnpm exec biome check .
pnpm exec knip
pnpm exec tsc --noEmit
pnpm exec next build
```

### Python (`explore/`)

```bash
cd explore
pnpm exec --dir .. true 2>/dev/null || true
ruff check .
ruff format --check .
# optional once configured: pytest -q
```

Or from repo root:

```bash
ruff check explore/
ruff format --check explore/
```

Install `ruff` in the explore toolchain in step 02 (or earlier Python scaffold); do not skip Python checks on Python-only edits.

### Focused tests (required as the features land)

| Area | Coverage |
|------|----------|
| Ledger transactions | Atomic job/event/profile-revision writes; restart reconciliation |
| Cancellation races | D61 ordering: `cancel_requested_at` → freeze → finalizer receipt → terminal `cancelled`; ordinary writers rejected |
| SSE handoff | Snapshot `event_cursor` → subscribe; `cursor_expired`; contiguous prune + `gap` (D55, D67) |
| Profile validation | Schema reject/accept; required `source.commit`; revision append (D51, D62, D64) |

Wire these under `explore/tests/` (and/or `frontend` contract tests) as the owning steps implement the features; later steps must keep them green.

## Rules

1. **Gate:** Biome, Knip, frontend typecheck, frontend build, and Ruff must exit **0** before checking the step’s **Done when** and before starting the next step (once each toolchain exists).
2. **Fix, don’t silence:** Prefer fixing code. Only add knip/biome/ruff ignores when justified in the step notes or DECISIONS — never to “get green” for dead wrong code.
3. **Python-only steps still run the full gate.** If you only edited `explore/`, run frontend Biome + Knip + typecheck + build **and** Ruff so neither tree rots.
4. **Frontend-only steps still run Ruff** on `explore/` once the explore tree exists (step 02+).
5. **No frontend yet?** Until step 01 finishes tooling setup, the frontend half of the gate is “install Biome + Knip + typecheck/build scripts as part of Done when.” After that, every later step uses the commands above.
6. **No explore yet?** Until step 02, the Python half is “install Ruff as part of Done when.”
7. **Report failures:** If the gate fails and you cannot fix it in-session, stop and report — do not mark the step complete.
