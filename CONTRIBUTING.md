# CONTRIBUTING.md — Working on Killhub

For engineers and agents contributing to this repo. Binding agent rules: [AGENTS.md](AGENTS.md). Run/deploy: [SETUP.md](SETUP.md). Module map: [docs/CODEMAP.md](docs/CODEMAP.md). Terms: [docs/GLOSSARY.md](docs/GLOSSARY.md).

---

## Read order

1. [PRODUCT.md](PRODUCT.md) — *what* and *why*
2. [ARCHITECTURE.md](ARCHITECTURE.md) — two planes, trust zones, plan loop
3. [docs/CODEMAP.md](docs/CODEMAP.md) — where to change code
4. [DECISIONS.md](DECISIONS.md) — before new tech or patterns (use the Decision index)
5. [API.md](API.md) / [DATABASE.md](DATABASE.md) — when touching contracts
6. [SETUP.md](SETUP.md) — local Plane 1, pipeline flags, VX1 / `msb`

---

## Where to edit

| Concern | Tree |
|---------|------|
| UI, public `/api` proxy, edge rate limits | `frontend/` |
| Ledger, Jobs API, worker, harness, inference | `explore/` |
| Guest probe helpers copied into the VM | `explore/helpers/` |
| VX1 firewall / offline egress wrappers | `ops/` |
| Product contracts / decisions | Root `*.md` — update when behavior changes |

Do **not**:

- Put secrets in the browser or inject Killhub keys into sandboxes by default
- Run untrusted repo install/run on the control-plane host
- Fake Plane 2 with Docker or mark sandbox work done without real `msb`
- Invent a third durable plane or split explore/test into two VMs without updating ARCHITECTURE + DECISIONS

Frontend-specific notes: [frontend/AGENTS.md](frontend/AGENTS.md).

---

## Local development (short)

Native DX (preferred for iteration):

```bash
# explore — see SETUP §4A / §5 for pipeline flags
cd explore && .venv/bin/python -m main

# frontend
cd frontend && pnpm dev
```

Copy [`.env.example`](.env.example) → `.env`. Enable `MSB_AUTO_CREATE` and the `*_ON_CLAIM` flags or jobs will not progress through the pipeline.

`docker compose` is production-style Next for the control plane — not a substitute for native `pnpm dev` when hacking UI. Plane 2 still needs Microsandbox/`msb` (SETUP §6).

Full procedure: [SETUP.md](SETUP.md).

---

## Quality gate (D68)

Every substantive change must leave **both** trees green ([AGENTS.md](AGENTS.md) §8):

```bash
cd frontend
pnpm lint:fix && pnpm lint && pnpm knip && pnpm typecheck && pnpm build

cd explore
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -q
```

Fix, don’t silence. Focused coverage must stay green for ledger transactions, cancel races (D61), SSE cursor/handoff (D55/D67), and profile schema validation (D51).

---

## When to update docs

| Change | Update |
|--------|--------|
| Lasting technical choice | [DECISIONS.md](DECISIONS.md) (+ index row) |
| HTTP/SSE/harness contracts | [API.md](API.md) |
| Ledger / profile / receipt fields | [DATABASE.md](DATABASE.md) |
| Plane boundaries / trust zones / lifecycle | [ARCHITECTURE.md](ARCHITECTURE.md) |
| New module ownership | [docs/CODEMAP.md](docs/CODEMAP.md) |
| New jargon | [docs/GLOSSARY.md](docs/GLOSSARY.md) |
| Install / deploy / env vars | [SETUP.md](SETUP.md) · `.env.example` |

Never commit secrets (`.env`, API keys, tokens).

---

## Related

[README.md](README.md) · [AGENTS.md](AGENTS.md) §9 (Vultr / `msb` tooling)
