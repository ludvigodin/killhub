# Step 10b — Pin fixture configuration (D53)

**Goal:** Record pinned public GitHub commit SHAs (and MCP filesystem entrypoint) **before** bootstrap/discover and readiness steps that depend on them.

## Prerequisites

- [10-opencode-lockdown.md](10-opencode-lockdown.md)

## Read first

- [DECISIONS.md](../DECISIONS.md) D53, D62
- [DATABASE.md](../DATABASE.md) — `source.commit` required

## Do

- [x] Create fixture config (e.g. `explore/fixtures/` or `fixtures/m7.json`) with public HTTPS `github.com` URLs **and full commit SHAs** for:
  - webapp success — `heroku/node-js-getting-started` @ pin → `original_application`
  - `git_mcp` filesystem — `modelcontextprotocol/servers` @ pin + fixed filesystem entrypoint/path (built checkout launch — D62)
  - controlled `setup_failed` — Killhub broken-webapp fixture **or** pinned public commit with `forbid_demo_intent=true`
- [x] Document how SCA lockfile fixtures are asserted (`findings.source=sca`) separately from intentional-app labels
- [x] Do **not** use NodeGoat as the deterministic fail fixture

## Do not

- Defer first-time pinning to step 20
- Leave `source.commit` optional for fixture profiles

## Lint gate (required before Done when)

Run the full quality gate ([LINT.md](LINT.md)):

```bash
cd frontend
pnpm lint:fix && pnpm lint && pnpm knip && pnpm typecheck && pnpm build
cd ../explore && ruff check . && ruff format --check .
```

Must exit **0**.

## Done when

Fixture config exists with concrete SHAs (or clearly marked placeholders only if network/GitHub blocks resolution — then stop and report). Steps 11 and 14 can consume the pins. Quality gate passes.

## Next

[11-bootstrap-discover.md](11-bootstrap-discover.md)
