# Step 07 — Microsandbox exec, copy & `AF_VSOCK` / UDS IPC (T1)

**Goal:** Plane 1 runs commands and moves files via **`msb exec` / `msb copy`** (or SDK equivalents) with **D60 host-path restrictions**, and opens **`AF_VSOCK`** (control + NDJSON telemetry channels, with **UDS / `mgmt0` fallback**) (`D71`).

## Prerequisites

- [06-msb-create-destroy.md](06-msb-create-destroy.md)

## Read first

- [VULTR.md](VULTR.md) · [IMPLEMENTATION_TEST_VM.md](../IMPLEMENTATION_TEST_VM.md) § 2, § 3, § 10
- [IMPLEMENTATION_EXPLORE_SANDBOX.md](../IMPLEMENTATION_EXPLORE_SANDBOX.md) § 4 (`ipc_telemetry.py`)
- [API.md](../API.md) — harness contract · D59 · D60 · **D71**
- [AGENTS.md](../AGENTS.md) § 5 (R2 inline docs + module frontmatter)

## Vultr / msb tooling (required)

- [ ] Implement `exec` / `copy_in` / `copy_out` with **`msb exec`** and **`msb copy`** (or official SDK) only
- [ ] Optional debug: Microsandbox MCP sandbox tools — product path remains harness → `msb` (`D23`)

## Do

- [ ] `exec(environment_id, cmd)` → `{ stdout, stderr, exit_code }` + per-call timeout
- [ ] `copy_in` / `copy_out` with **D60** restrictions: logical helper ids / artifact kinds (`explore/helpers/` → guest; guest → `storage/artifacts/{job_id}/` or `storage/screenshots/{job_id}/`); `realpath` containment, reject `..`, symlink escape, and copies exceeding `MAX_COPY_BYTES`
- [ ] `explore/ipc_telemetry.py` (with R2 module docstring + inline comments): implement **`AF_VSOCK`** listener (dedicated control channel + NDJSON telemetry stream) with **UDS / `mgmt0`** fallback (`VM_IPC_MODE`), bounded NDJSON line/byte ingestion (`<= 64 KiB/line`), and artifact persistence (`storage/artifacts/{job_id}/telemetry.ndjson`)
- [ ] Support `copy_in` of guest helper scripts (`explore/helpers/mcp_stdio_verify.py`, `mcp_discover.py`, `guest_sensors.sh`, `pkg_hash.py`) and `copy_out` of `strace`, OverlayFS `upperdir` diff, MCP wire-tap, PCAP, and package-hash artifacts
- [ ] Assert Killhub `VULTR_API_KEY` and `VULTR_INFERENCE_API_KEY` are **absent** from `/proc/*/environ` and guest `env`
- [ ] Stream exec/IPC failures as job `log` events (no secrets or raw canary plaintext)

## Do not

- Accept arbitrary host paths from agent/harness callers
- Clone/install untrusted repos yet (next steps)
- Mount Docker socket or shell into the guest with ad-hoc SSH instead of `msb exec`

## Lint gate (required before Done when)

Run the **full quality gate** ([LINT.md](LINT.md) — `D68`, `D74`) including R2 compliance:

```bash
cd frontend && pnpm lint:fix && pnpm lint && pnpm knip && pnpm typecheck && pnpm build
cd ../explore && ../.venv/bin/ruff check . && ../.venv/bin/ruff format --check . && ../.venv/bin/pytest -q
cd .. && python3 -c "import json; from pathlib import Path; from jsonschema import Draft202012Validator; [Draft202012Validator.check_schema(json.loads(p.read_text())) or print('OK', p.name) for p in sorted(Path('schemas').glob('*.json'))]"
```

Must exit **0**.

## Done when

Remote commands run via **`msb exec`** and return output; `AF_VSOCK`/UDS NDJSON telemetry channel streams bounded events to Plane 1; `VULTR_*` keys are absent from guest `/proc/*/environ`; arbitrary `copy_in`/`copy_out` host paths are rejected; full quality gate + R2 docs pass ([LINT.md](LINT.md)).

## Next

[08-net-policy-canaries.md](08-net-policy-canaries.md)
