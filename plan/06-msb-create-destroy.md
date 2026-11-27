# Step 06 — Ubuntu 24.04 microVM create / destroy + L3 watchdog + reaper (T0)

**Goal:** Harness creates and destroys a named Ubuntu 24.04 detonation microVM via **`msb` CLI/SDK** (`ubuntu-24.04-killhub`) with read-only rootfs + OverlayFS, `/workspace` cap, TAP & `noVNC` bindings, and Layer 3 watchdog + host reaper enforcing absolute `expires_at` (`D69`, `D72`).

## Prerequisites

- [04-internal-worker-api.md](04-internal-worker-api.md) (harness lives in `explore/`)
- Vultr VX1 host exists and `msb doctor` is green (plus KVM, OverlayFS, cgroup v2, TAP/`mitmdump` support — block if unavailable, do not fake)

## Read first

- [VULTR.md](VULTR.md) · [DECISIONS.md](../DECISIONS.md) D22, D23, D41, D57, **D59**, **D69**, **D72**
- [IMPLEMENTATION_TEST_VM.md](../IMPLEMENTATION_TEST_VM.md) § 1, § 2, § 5, § 9–10
- [AGENTS.md](../AGENTS.md) § 5 (R2 inline docs + module frontmatter)

## Vultr / msb tooling (required)

- [ ] Locate/verify the VX1 instance with **Vultr MCP** or `vultr-cli instance list` (D59)
- [ ] On the VX1 host: `msb doctor` (or Microsandbox MCP `runtime_check`) must pass; verify `ubuntu-24.04-killhub` base image has `python`, `pip`, `uv`, Node `22+`, `git`, `strace`, `OpenCode`, `@modelcontextprotocol/inspector`, and `noVNC`/Xvfb/VNC
- [ ] Harness implements create/destroy by calling **`msb` CLI or official SDK** — not Docker, not a mock

## Do

- [ ] `explore/harness.py` (with R2 top-of-file module docstring & inline comments): `create_environment` / `wait_until_ready` / `destroy_environment` wrapping `msb create` / status / `msb stop` + `msb remove`
- [ ] Configure Ubuntu 24.04 base (`MSB_DEFAULT_IMAGE="ubuntu-24.04-killhub"`): read-only rootfs + per-job OverlayFS (`lowerdir`/`upperdir`/`workdir`/`merged`) + size-capped `/workspace` + `/run/mcp-package-cache` tmpfs
- [ ] Attach per-job host TAP bridge stub and bind guest `noVNC` VNC server (`view_only=true`) to internal `127.0.0.1`/IPC bridge (`D46`, `D71`)
- [ ] Set absolute `expires_at` at create; `msb touch` must not extend it (`D41`)
- [ ] Implement **Layer 3 hypervisor wall-clock watchdog** (`JOB_TIMEOUT_SECONDS`): bounded graceful telemetry flush (`flush_grace_seconds`) before hard `msb stop` + `msb remove` + deterministic TAP/iptables/OverlayFS teardown (`D72`)
- [ ] Emit `lifecycle` (`sandbox_create` / `sandbox_destroy`) events to the ledger; confirm destroy only sets job-level `destroyed_at` after successful remove (`D57`)
- [ ] Host-side reaper for past `expires_at` + Plane 1 startup orphan reconcile (`reconcile_startup`)

## Do not

- Install untrusted repo deps or run readiness probes yet
- Skip real `msb` with a pretend success
- Use Docker/Podman as Plane 2

## Lint gate (required before Done when)

Run the **full quality gate** ([LINT.md](LINT.md) — `D68`, `D74`), including R2 inline-doc/module-frontmatter checks (`AGENTS.md` §5):

```bash
cd frontend && pnpm lint:fix && pnpm lint && pnpm knip && pnpm typecheck && pnpm build
cd ../explore && ../.venv/bin/ruff check . && ../.venv/bin/ruff format --check . && ../.venv/bin/pytest -q
cd .. && python3 -c "import json; from pathlib import Path; from jsonschema import Draft202012Validator; [Draft202012Validator.check_schema(json.loads(p.read_text())) or print('OK', p.name) for p in sorted(Path('schemas').glob('*.json'))]"
```

Must exit **0**. Do **not** start the next step while any check fails.

## Done when

Harness creates and destroys an Ubuntu 24.04 microsandbox for a job id **via `msb`** with RO rootfs + OverlayFS + TAP/noVNC wiring; Layer 3 watchdog flushes then tears down VM + TAP/overlay; host reaper kills past `expires_at` without Plane 1; VX1 verified via Vultr MCP/`vultr-cli`; full quality gate + R2 docs pass ([LINT.md](LINT.md)).

## Next

[07-msb-exec-copy.md](07-msb-exec-copy.md)
