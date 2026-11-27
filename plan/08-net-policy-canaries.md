# Step 08 — Host TAP/`mitmdump`, DoH/DoT/QUIC drop, mounts & canary seeds (D39, D44, D69, D70)

**Goal:** Every create/replace configures host-side **TAP bridge + `mitmdump`** (transparent HTTP/S + DNS interception, **DoH/DoT/QUIC drop**, real-time canary blocking, optional `tcpdump` PCAP), bakes `mitmproxy` CA + TLS env vars, and applies the full Ubuntu 24.04 **mount & seed checklist** (`D69`–`D71`).

## Prerequisites

- [07-msb-exec-copy.md](07-msb-exec-copy.md)

## Read first

- [VULTR.md](VULTR.md) · [IMPLEMENTATION_TEST_VM.md](../IMPLEMENTATION_TEST_VM.md) § 2, § 4
- [IMPLEMENTATION_EXPLORE_SANDBOX.md](../IMPLEMENTATION_EXPLORE_SANDBOX.md) § 4 (`net_tap.py`)
- [DECISIONS.md](../DECISIONS.md) D19, D39, D44, D59, **D69**, **D70**, **D71**
- [ARCHITECTURE.md](../ARCHITECTURE.md) — trust-zone matrix (D42)
- [AGENTS.md](../AGENTS.md) § 5 (R2 inline docs + module frontmatter)

## Vultr / msb tooling (required)

- [ ] Configure `msb` / VX1 TAP bridge + `iptables`/`nftables` rules on create — document exact flags/commands in `IMPLEMENTATION_TEST_VM.md`
- [ ] Verify VX1 host networking/firewall with Vultr MCP or `vultr-cli` as needed

## Do

- [ ] `explore/net_tap.py` (with R2 docstring + inline comments):
  - Attach per-job host **TAP bridge** denying Plane 1 control-plane destinations, `msb` management endpoints, and sibling microVMs (`deny_control_plane=true`, `deny_siblings=true`)
  - Launch host-side **`mitmdump`** for transparent HTTP/HTTPS + DNS interception with **real-time canary blocking** (`block_http=true`, `block_dns=true`)
  - Enforce **`iptables`/`nftables` drops** for **DoH** (known resolver IPs/endpoints), **DoT** (`TCP/853`), **QUIC/HTTP3** (`UDP/443`), and raw IP bypass (`drop_doh_dot_quic=true`), logging drops as `doh_dot_quic_drop`
  - Support optional bounded `tcpdump` PCAP capture to `storage/artifacts/{job_id}/capture.pcap` (`CAPTURE_PCAP`, `MAX_PCAP_BYTES`)
- [ ] Apply full **Mount & Seed Checklist (`D69`, `D71`)** on create/replace:
  - Baked `mitmproxy` root CA in guest trust store + exported `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `NODE_EXTRA_CA_CERTS`
  - Size-capped `/workspace` with randomized `/workspace/.env` canary
  - Randomized `/home/agent/.ssh/` and `/home/agent/.aws/` canary credentials
  - Pre-seeded `/home/agent/.local/share/opencode/opencode.db`, `/home/agent/.config/opencode/`, and `/home/agent/.gitconfig` pointing to Plane 1 Host LLM Proxy over IPC with ephemeral dummy bearer token (`kh_proxy_<job_id>_<nonce>`)
  - Writable `/run/mcp-package-cache` `tmpfs` (`size_cap_mb`)
- [ ] Never log raw canary plaintext in SSE; stub hooks for step 15 `network_probe` / canary scan

## Do not

- Implement the full 4-axis containment matrix yet (step 15)
- Reintroduce an install command allowlist (`D29`)
- Fake network isolation without TAP/`mitmdump`/firewall enforcement

## Lint gate (required before Done when)

Run the **full quality gate** ([LINT.md](LINT.md) — `D68`, `D74`) including R2 compliance:

```bash
cd frontend && pnpm lint:fix && pnpm lint && pnpm knip && pnpm typecheck && pnpm build
cd ../explore && ../.venv/bin/ruff check . && ../.venv/bin/ruff format --check . && ../.venv/bin/pytest -q
cd .. && python3 -c "import json; from pathlib import Path; from jsonschema import Draft202012Validator; [Draft202012Validator.check_schema(json.loads(p.read_text())) or print('OK', p.name) for p in sorted(Path('schemas').glob('*.json'))]"
```

Must exit **0**.

## Done when

New Ubuntu 24.04 sandboxes boot with TAP/`mitmdump` (HTTP/S+DNS), DoH/DoT/QUIC drop, baked CA + TLS env vars, `/run/mcp-package-cache` tmpfs, all canary paths (`.env`, `.ssh`, `.aws`), and pre-seeded OpenCode dummy-token config; full quality gate + R2 docs pass ([LINT.md](LINT.md)).

## Next

[09-preflight.md](09-preflight.md)
