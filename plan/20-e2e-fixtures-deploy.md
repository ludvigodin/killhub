# Step 20 — E2E 3 baseline + 6 demo scenarios + Vultr demo deploy (M7, D46, D53, D73)

**Goal:** Assert all **3 baseline fixtures** and all **6 Demo Malicious MCP Scenarios** pass on real `msb` Ubuntu 24.04 microVMs, verify key isolation and 3-layer kill switch end-to-end, and deploy the public control plane on **Vultr Cloud Compute** bound to `127.0.0.1` behind an edge reverse proxy (`D46`).

## Prerequisites

- [18-vuln-receipt-finalize.md](18-vuln-receipt-finalize.md)
- [19-report-ui.md](19-report-ui.md)

## Read first

- [VULTR.md](VULTR.md) · [DECISIONS.md](../DECISIONS.md) D24, D40, D41, D46, D53, D54, **D59**, **D69**–**D74**
- [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md) — M7
- [IMPLEMENTATION_NEXTJS.md](../IMPLEMENTATION_NEXTJS.md) § N4
- [IMPLEMENTATION_EXPLORE_SANDBOX.md](../IMPLEMENTATION_EXPLORE_SANDBOX.md) § E6
- [IMPLEMENTATION_TEST_VM.md](../IMPLEMENTATION_TEST_VM.md) § 8
- [AGENTS.md](../AGENTS.md) § 5 (R2 inline docs + module frontmatter)

## Vultr tooling (required)

- [ ] Inspect/confirm demo + VX1 hosts with **Vultr MCP** (read-only)
- [ ] Provision/mutate demo control-plane VM with **`vultr-cli`** (or Vultr API) — not a non-Vultr host (`D24`)
- [ ] All fixture sandboxes run via harness → **`msb`** on VX1
- [ ] If MCP/`vultr-cli`/`msb` unavailable: stop and report — do not declare M7 done on localhost-only

## Do

- [ ] **Assert 3 Baseline Fixtures (`explore/fixtures/m7.json`, `D53`):**
  1. Webapp → `original_application` (`heroku/node-js-getting-started` @ pin)
  2. `git_mcp` filesystem → `original_application` readiness from **built checkout** (`D62`)
  3. Controlled fail → `setup_failed` with `findings.source=sca` separate from `intentional_app`
- [ ] **Assert All 6 Demo Malicious MCP Scenarios (`D53`, `D73`):**
  1. Indirect prompt injection via GitHub issue → caught by `mcp_wire_tap` + `mitmdump` + canary block
  2. Delayed tool obfuscation / rug pull → caught by `t0_tools_sha256` ≠ `final_tools_sha256` + `tool_diffs`
  3. Post-install modified package backdoor → caught by `package_sha256_before` ≠ `after` + OverlayFS `upperdir` + `strace`
  4. Host microVM credential exfiltration via OpenCode tools & `opencode.db` → `key_isolation_verified=true` (zero `VULTR_*` keys in Plane 2) + real-time `mitmdump`/DNS canary block
  5. External manipulation of clean MCP server via tool drift/shadowing → caught by `tool_diffs` + `mcp_wire_tap` + `mitmdump` + `strace`
  6. Resource exhaustion via infinite agent loop → bounded by **3-Layer Kill Switch** (`L1` HTTP `429` at 12 turns/60k tokens/oscillation, `L2` cgroup v2 `512M`/`0`/`64`, `L3` watchdog flush + teardown) without impacting VX1/Plane 1 liveness
- [ ] Assert absolute expiry + cancel + completed always reclaim sandbox & TAP/OverlayFS across Plane 1 restart (`D41`, `D72`)
- [ ] **Vultr Reverse-Proxy Deploy (`D46`, `D71`, `ALIGNMENT_PLAN.md` S8):**
  - Bind Next.js, `explore/`, Host LLM Proxy, and `noVNC` proxy strictly to `127.0.0.1`
  - Configure reverse proxy (Caddy/nginx) to terminate HTTPS, flush SSE (`/api/jobs/{id}/events`), proxy authenticated **view-only `noVNC`** WebSockets (`/api/jobs/{id}/novnc`), and overwrite `X-Real-IP` / `X-Forwarded-For` from socket peer IP
  - Verify admission (`429`/`503`), durable SQLite WAL ledger, and VX1 host reaper are live before public URL

## Do not

- Deploy without durable SQLite WAL ledger, host reaper, or admission controls
- Expose interactive (write-enabled) `noVNC` or unauthenticated `/internal/*` routes
- Use NodeGoat as the deterministic fail fixture (`D53`)
- Fake fixture greens without real `msb`

## Lint gate (required before Done when)

Run the **full quality gate** ([LINT.md](LINT.md) — `D68`, `D74`) including R2 compliance:

```bash
cd frontend && pnpm lint:fix && pnpm lint && pnpm knip && pnpm typecheck && pnpm build
cd ../explore && ../.venv/bin/ruff check . && ../.venv/bin/ruff format --check . && ../.venv/bin/pytest -q
cd .. && python3 -c "import json; from pathlib import Path; from jsonschema import Draft202012Validator; [Draft202012Validator.check_schema(json.loads(p.read_text())) or print('OK', p.name) for p in sorted(Path('schemas').glob('*.json'))]"
```

Must exit **0**.

## Done when

All 3 baseline fixtures and all 6 demo malicious MCP scenarios pass on real **`msb`** Ubuntu 24.04 microVMs with schema-valid `DetonationVerdict` JSONs; key isolation and 3-layer kill switch proven; demo URL is live on Vultr behind reverse proxy with SSE + view-only `noVNC`; sandboxes die on expiry across Plane 1 restart; full quality gate + R2 docs pass ([LINT.md](LINT.md)).

## Next

[21-cleanup-docs.md](21-cleanup-docs.md) — remove build scaffolding docs once M7 is green.
