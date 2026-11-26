# Step 11 — Bootstrap + discover runtime profile (D36)

**Goal:** Bootstrap sandbox → inspect → validated runtime `environment_profile.json` (`git_mcp` \| `webapp` \| `demo`).

## Prerequisites

- [09-preflight.md](09-preflight.md)
- [10-opencode-lockdown.md](10-opencode-lockdown.md)
- [08-net-policy-canaries.md](08-net-policy-canaries.md)

## Read first

- [DECISIONS.md](../DECISIONS.md) D36, D34, D6
- [DATABASE.md](../DATABASE.md) — bootstrap vs runtime profile
- [IMPLEMENTATION_EXPLORE_SANDBOX.md](../IMPLEMENTATION_EXPLORE_SANDBOX.md) § E2

## Vultr / msb tooling (required)

Use **`msb` CLI/SDK** (and Vultr MCP / `vultr-cli` to verify the VX1 host) per [VULTR.md](VULTR.md) and D59. Do not fake Plane 2 with Docker.

## Do

- [ ] Trusted bootstrap profile → `MSB_DEFAULT_IMAGE` create
- [ ] Clone/inspect **inside** sandbox (copy/exec) — not privileged host install
- [ ] Prompts: `discover_environment` + `validate_environment_spec`
- [ ] Write runtime profile under `storage/profiles/{job_id}/`
- [ ] Invalid runtime profile blocks provision
- [ ] Stream plan-loop steps as `span` / `log` / status

## Do not

- Run full install/readiness yet
- Create a second concurrent VM for explore vs test

## Lint gate (required before Done when)

Run Biome + Knip and fix all findings before marking this step done (see [LINT.md](LINT.md)):

```bash
cd frontend
pnpm lint:fix && pnpm lint && pnpm knip
```

Must exit **0**. Do **not** start the next step while either tool fails. Python-only changes still require a green gate.

## Done when

Pinned webapp + MCP fixture URLs emit valid runtime profiles after bootstrap inspect. Biome + Knip lint gate passes ([LINT.md](LINT.md)).

## Next

[12-image-replace.md](12-image-replace.md)
