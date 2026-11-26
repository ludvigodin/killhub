# Lint gate — Biome + Knip

Every `plan/` step must leave the JS/TS tree clean before it is marked done.

## Commands

Run from `frontend/` once step 01 has added the tooling (use the package manager chosen in that step):

```bash
pnpm lint          # biome check .
pnpm lint:fix     # biome check --write .   — prefer this, then re-check
pnpm knip           # unused exports / deps
```

Equivalent if scripts are missing:

```bash
pnpm exec biome check --write .
pnpm exec biome check .
pnpm exec knip
```

## Rules

1. **Gate:** Both Biome and Knip must exit **0** before checking the step’s **Done when** and before starting the next step.
2. **Fix, don’t silence:** Prefer fixing code. Only add knip/biome ignores when the ignore is justified in the step notes or DECISIONS — never to “get green” for dead wrong code.
3. **Python-only steps still run the gate.** If you only edited `explore/`, run Biome + Knip anyway so the frontend tree did not rot.
4. **No frontend yet?** Until step 01 finishes tooling setup, the gate is “install Biome + Knip as part of Done when.” After that, every later step uses the commands above.
5. **Report failures:** If the gate fails and you cannot fix it in-session, stop and report — do not mark the step complete.
