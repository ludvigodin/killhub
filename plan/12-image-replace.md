# Step 12 — Same-job custom-OCI image replace (D36, D64, D69)

**Goal:** Continue in place on the unified Ubuntu 24.04 detonation VM by default (`D69`); if an explicit custom `oci_image` override is required, replace the VM once while re-applying all sensors, `mitmproxy` CA, mounts, canaries, cgroup v2 caps, TAP/`mitmdump`, and `AF_VSOCK`/UDS/`noVNC` — keeping one live sandbox.

## Prerequisites

- [11-bootstrap-discover.md](11-bootstrap-discover.md)

## Read first

- [DECISIONS.md](../DECISIONS.md) D27, D36, D62, D64, **D69**
- [IMPLEMENTATION_TEST_VM.md](../IMPLEMENTATION_TEST_VM.md) § 1, § 2, § 10
- [AGENTS.md](../AGENTS.md) § 5 (R2 inline docs + module frontmatter)

## Vultr / msb tooling (required)

Use **`msb` CLI/SDK** (and Vultr MCP / `vultr-cli` to verify the VX1 host) per [VULTR.md](VULTR.md) and `D59`. Do not fake Plane 2 with Docker.

## Do

- [ ] Same-image (`ubuntu-24.04-killhub`) path continues in place without replacement (`D69`)
- [ ] `replace_environment` (only when explicit custom `oci_image` ≠ bootstrap):
  - Stop + remove prior **generation** → create new VM → re-clone at **`resolved_commit`** (`D62`)
  - **Re-layer/inject** Ubuntu 24.04 observability & runtime requirements: `mitmproxy` root CA + TLS env vars (`SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `NODE_EXTRA_CA_CERTS`), `/workspace` OverlayFS & `.env`/`.ssh`/`.aws` canaries, `/home/agent/.config/opencode/` + `opencode.db` + `.gitconfig` dummy-token proxy seeds, `/run/mcp-package-cache` tmpfs, `strace` / MCP wire tap / Inspector / `noVNC` helpers, Layer 2 cgroup v2 caps (`512M`/`0`/`64`), TAP/`mitmdump` + DoH/DoT/QUIC drop, and `AF_VSOCK`/UDS IPC
- [ ] Inherit original job `expires_at` (never extend); set prior generation `state=replaced` and per-generation `destroyed_at` without setting job-level `destroyed_at` while replacement is alive (`D64`)
- [ ] Emit `lifecycle` / `log.kind=sandbox_replace` and assert never two concurrent microVMs for one job

## Do not

- Split explore/test into two concurrent VMs (`D27`)
- Drop guest sensors, CA, canaries, or Host LLM Proxy seeds during custom-OCI replace
- Re-clone at a floating ref that can drift from `resolved_commit`

## Lint gate (required before Done when)

Run the **full quality gate** ([LINT.md](LINT.md) — `D68`, `D74`) including R2 compliance:

```bash
cd frontend && pnpm lint:fix && pnpm lint && pnpm knip && pnpm typecheck && pnpm build
cd ../explore && ../.venv/bin/ruff check . && ../.venv/bin/ruff format --check . && ../.venv/bin/pytest -q
cd .. && python3 -c "import json; from pathlib import Path; from jsonschema import Draft202012Validator; [Draft202012Validator.check_schema(json.loads(p.read_text())) or print('OK', p.name) for p in sorted(Path('schemas').glob('*.json'))]"
```

Must exit **0**.

## Done when

Same-image Ubuntu 24.04 path stays in place; custom-OCI fixture replaces once, preserves `resolved_commit`, inherits `expires_at`, and re-applies all sensors/CA/mounts/canaries/IPC/cgroup v2; full quality gate + R2 docs pass ([LINT.md](LINT.md)).

## Next

[13-install-offline.md](13-install-offline.md)
