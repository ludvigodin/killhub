# Step 21 — Cleanup build docs (post-implementation)

**Goal:** After steps 01–20 are done and M7 is green, remove scaffolding/build-step docs that no longer earn their keep, and leave a slim durable doc & schema set.

## Prerequisites

- [20-e2e-fixtures-deploy.md](20-e2e-fixtures-deploy.md) **Done when** is true (3 baseline + 6 demo fixtures + Vultr demo)
- Human confirms it is time to retire the build ladder (do not run mid-build)

## Read first

- [PRODUCT.md](../PRODUCT.md) doc map
- [AGENTS.md](../AGENTS.md) § Read before you change
- This file’s keep/remove matrix (below)

## Keep (durable — do not delete)

| Path | Why |
|------|-----|
| `PRODUCT.md` | What / why |
| `ARCHITECTURE.md` | Planes, zones, IPC, key isolation, TAP/`mitmdump`, 3-layer kill switch |
| `DECISIONS.md` | Binding choices (`D1`–`D74`) |
| `DATABASE.md` | Schema / ledger rules & ATLAS/OWASP mapping tables |
| `API.md` | Public & internal contracts (`/verdict`, `/telemetry`, `/pcap`, `/novnc`, Host LLM Proxy) |
| `AGENTS.md` | Binding agent rules (incl. R2 inline code docs & module frontmatter) |
| `ALIGNMENT_PLAN.md` | Model-selection plan (`D74`), security mitigations (`S1`–`S8`), and architecture alignment record |
| `schemas/*.json` | Canonical Draft 2020-12 JSON Schemas (`environment_profile.v1.json`, `dynamic_install_spec.v1.json`, `test_scenario_plan.v1.json`, `detonation_verdict.v1.json`) — **never delete** |
| `README.md` | Repo entry |
| `plan/LINT.md` **or** fold into `AGENTS.md` / CI docs | Quality gate (Biome, Knip, tsc/build, Ruff, pytest, `schemas/*.json`, R2 check) remains useful in CI |
| `plan/VULTR.md` **or** fold into `AGENTS.md` / `ARCHITECTURE.md` | Vultr MCP/`vultr-cli`/`msb`/VX1 TAP/cgroup rules (`D59`, `D69`–`D72`) |

Prefer **folding** unique facts from `LINT.md` / `VULTR.md` into canonical docs, then deleting the `plan/` copies — avoid duplicating forever.

## Remove (build scaffolding — delete when this step runs)

| Path | Why remove |
|------|------------|
| `plan/01-*.md` … `plan/20-*.md` | One-shot build steps; done |
| `plan/README.md` | Index for the ladder; obsolete after cleanup |
| `plan/21-cleanup-docs.md` | This step — delete **last** after checklist |
| Empty `plan/` directory | Remove if nothing remains |

## Collapse or rewrite (not blind-delete)

| Doc | Action |
|-----|--------|
| `IMPLEMENTATION_PLAN.md` | Replace with a short pointer to `PRODUCT`/`ARCHITECTURE`/`API`/`schemas` **or** delete if redundant |
| `IMPLEMENTATION_NEXTJS.md` | Delete **or** trim to a short “frontend layout” note if still useful for onboarding |
| `IMPLEMENTATION_EXPLORE_SANDBOX.md` | Delete or trim; code + `API.md`/`DATABASE.md`/`schemas/*.json` are source of truth |
| `IMPLEMENTATION_TEST_VM.md` | Keep only as an operator VX1/Ubuntu 24.04 runbook if needed; otherwise fold unique `msb`/TAP/cgroup/6-scenario specs into `ARCHITECTURE.md`, then delete |

**Rule:** Do not delete an implementation doc until its unique operator facts (env vars, `msb`/TAP/cgroup flags, Internal API paths, 6 scenario specs) live in `ARCHITECTURE.md`, `API.md`, `DATABASE.md`, `ALIGNMENT_PLAN.md`, or `AGENTS.md`.

## Do

- [ ] Confirm steps 01–20 checkboxes are done in `plan/README.md`
- [ ] Move any still-needed bits from `LINT.md` / `VULTR.md` / `IMPLEMENTATION_*.md` into canonical docs (`ARCHITECTURE.md`, `AGENTS.md`, `ALIGNMENT_PLAN.md`)
- [ ] Update all links: `PRODUCT.md` doc map, `AGENTS.md`, `ARCHITECTURE.md`, `README.md` — remove references to deleted paths
- [ ] Delete `plan/01`–`plan/20` step files (never delete `schemas/*.json` or `ALIGNMENT_PLAN.md` unless folded)
- [ ] Delete or rewrite `IMPLEMENTATION_PLAN.md` + plane `IMPLEMENTATION_*.md` per matrix above
- [ ] Delete `plan/README.md`, then `plan/LINT.md` / `plan/VULTR.md` if folded, then **this file**
- [ ] Remove empty `plan/` if applicable
- [ ] Grep the repo for `plan/0`, `IMPLEMENTATION_`, `LINT.md`, `VULTR.md` broken links and fix

## Do not

- Delete `PRODUCT.md` / `ARCHITECTURE.md` / `DECISIONS.md` / `DATABASE.md` / `API.md` / `AGENTS.md` / `ALIGNMENT_PLAN.md` / `schemas/*.json`
- Run this step before M7 / step 20 is actually done
- Leave dangling markdown links

## Lint gate (required before Done when)

Run the **full quality gate** ([LINT.md](LINT.md) — `D68`):

```bash
cd frontend && pnpm lint:fix && pnpm lint && pnpm knip && pnpm typecheck && pnpm build
cd ../explore && ../.venv/bin/ruff check . && ../.venv/bin/ruff format --check . && ../.venv/bin/pytest -q
cd .. && python3 -c "import json; from pathlib import Path; from jsonschema import Draft202012Validator; [Draft202012Validator.check_schema(json.loads(p.read_text())) or print('OK', p.name) for p in sorted(Path('schemas').glob('*.json'))]"
```

Must exit **0**.

## Done when

Build-step docs are gone; canonical docs + `schemas/*.json` accurately describe the running system; zero broken doc links; full quality gate passes ([LINT.md](LINT.md)).

## Next

None — documentation cleanup complete.
