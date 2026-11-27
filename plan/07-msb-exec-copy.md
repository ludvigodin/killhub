# Step 07 — Microsandbox exec + copy (T1)

**Goal:** Plane 1 runs commands and moves files via **`msb exec` / `msb copy`** (or SDK equivalents) with **host-path restrictions** (D60).

## Prerequisites

- [06-msb-create-destroy.md](06-msb-create-destroy.md)

## Read first

- [VULTR.md](VULTR.md) · [IMPLEMENTATION_TEST_VM.md](../IMPLEMENTATION_TEST_VM.md) § T1
- [API.md](../API.md) — harness contract · D59 · D60

## Vultr / msb tooling (required)

- [x] Implement `exec` / `copy_in` / `copy_out` with **`msb exec`** and **`msb copy`** (or official SDK) only
- [x] Optional debug: Microsandbox MCP sandbox tools — product path remains harness → `msb` (D23)

## Do

- [x] `exec(environment_id, cmd)` → stdout/stderr/exit_code + per-call timeout
- [x] `copy_in` / `copy_out` with **D60** restrictions: logical helper ids / artifact kinds; allowlisted helper roots + per-job artifact dirs; reject `..`, symlink escape, oversized copies
- [x] Assert Killhub API/inference keys are **absent** from guest env
- [x] Stream exec failures as job `log` events (no secrets)

## Do not

- Accept arbitrary host paths from agent/harness callers
- Clone/install untrusted repos yet (next steps)
- Mount Docker socket
- Shell into the guest with ad-hoc SSH instead of `msb exec` for the harness path

## Lint gate (required before Done when)

Run the full quality gate ([LINT.md](LINT.md)).

## Done when

A remote command runs via **`msb exec`** and output returns to Plane 1; keys not visible in guest env; arbitrary host paths are rejected. Quality gate passes ([LINT.md](LINT.md)).

## Next

[08-net-policy-canaries.md](08-net-policy-canaries.md)
