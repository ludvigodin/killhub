# Step 11 — Bootstrap + discover runtime profile (D36)

**Goal:** Bootstrap sandbox → inspect → validated runtime `environment_profile.json` (`git_mcp` \| `webapp` \| `demo`).

## Prerequisites

- [09-preflight.md](09-preflight.md)
- [10-opencode-lockdown.md](10-opencode-lockdown.md)
- [10b-pin-fixtures.md](10b-pin-fixtures.md)
- [08-net-policy-canaries.md](08-net-policy-canaries.md)

## Read first

- [DECISIONS.md](../DECISIONS.md) D36, D34, D6, D62, D64
- [DATABASE.md](../DATABASE.md) — bootstrap vs runtime profile revisions
- [IMPLEMENTATION_EXPLORE_SANDBOX.md](../IMPLEMENTATION_EXPLORE_SANDBOX.md) § E2

## Vultr / msb tooling (required)

Use **`msb` CLI/SDK** (and Vultr MCP / `vultr-cli` to verify the VX1 host) per [VULTR.md](VULTR.md) and D59. Do not fake Plane 2 with Docker.

## Do

- [x] Trusted bootstrap profile → `MSB_DEFAULT_IMAGE` create (before discovery — D36)
- [x] Clone/inspect **inside** sandbox (copy/exec) — not privileged host install
- [x] Persist **`resolved_commit`**; require `source.commit` on runtime profiles (D62)
- [x] Prompts: `discover_environment` + `validate_environment_spec`
- [x] Append runtime profile as a **revision** under `storage/profiles/{job_id}/` (D64)
- [x] Invalid runtime profile blocks provision
- [x] Stream plan-loop steps as `span` / `log` / status
- [x] Consume pinned fixtures from step 10b

## Do not

- Run full install/readiness yet
- Create a second concurrent VM for explore vs test
- Discover/write runtime profile before bootstrap create

## Lint gate (required before Done when)

Run the full quality gate ([LINT.md](LINT.md)).

## Done when

Pinned webapp + MCP fixture URLs emit valid runtime profiles (with commit SHAs) after bootstrap inspect. Quality gate passes ([LINT.md](LINT.md)).

## Next

[12-image-replace.md](12-image-replace.md)
