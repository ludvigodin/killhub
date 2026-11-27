# Killhub setup (Vultr)

Operator runbook for running Killhub yourself. Product overview stays in [README.md](README.md); this page is how to stand up Plane 1 + Plane 2 on Vultr.

Two supported topologies ([ARCHITECTURE.md](ARCHITECTURE.md)):

| Path | Plane 1 (UI + explore) | Plane 2 (Microsandbox) | Inference |
|------|------------------------|------------------------|-----------|
| **Local + remote VX1** | Laptop (`docker-compose` or native) | Vultr VX1 via `MSB_HOST` SSH | Vultr Serverless Inference |
| **Vultr demo host** | Cloud Compute on `127.0.0.1` behind HTTPS (D46) | `msb` on PATH (same host) or SSH to VX1 | Same |

Control plane and VX1 may be the same machine or split. Sandboxes are always real Microsandbox microVMs — never Docker-as-Plane-2 ([DECISIONS.md](DECISIONS.md) D59).

```mermaid
flowchart LR
  subgraph local [Local_dev]
    Laptop["Laptop Plane 1"]
  end
  subgraph vultr [Vultr]
    CP["Cloud_Compute Plane 1"]
    VX1["VX1 msb Plane 2"]
    Inf["Serverless_Inference"]
  end
  Laptop -->|"MSB_HOST SSH"| VX1
  CP -->|"msb on PATH or SSH"| VX1
  Laptop --> Inf
  CP --> Inf
```

---

## 1. Prerequisites

### Accounts

- **Vultr** account with:
  - Cloud Compute (and/or VX1) for the control plane and/or Microsandbox host
  - [Serverless Inference](https://docs.vultr.com/products/serverless/inference/provisioning) subscription — API key + a chat/text model id (D25)
- Optional: [vultr-cli](https://docs.vultr.com/platform/getting-started/vultr-cli) + Account API key for host inventory/mutations (operator machines only — never inject into sandboxes)

### Plane 2 host (VX1)

Follow Vultr’s guide: [Set up agent sandboxing on Vultr Cloud Compute](https://docs.vultr.com/how-to-set-up-agent-sandboxing-on-vultr-cloud-compute). Confirm:

```bash
msb doctor
```

### Dev / control-plane tooling

| Tool | Version hint |
|------|----------------|
| Node.js | 22 (`frontend/Dockerfile`) |
| pnpm | 11.20.0 (`frontend/package.json`) |
| Python | 3.12 (`explore/Dockerfile`) |
| Docker + Compose | Optional — local Plane 1 only |
| Reverse proxy (Caddy / nginx) | Required for a public demo (D46) |

---

## 2. Accounts and keys

All secrets stay on **Plane 1**. Sandboxes get canaries only (D44). Full catalog: [`.env.example`](.env.example).

| Variable | Where | Notes |
|----------|-------|-------|
| `INTERNAL_API_TOKEN` | Root `.env` **and** `frontend/.env.local` (or frontend env) | Must match both sides (D52) |
| `EXPLORE_BASE_URL` | Frontend env | Local: `http://127.0.0.1:8100`. Compose frontend uses `http://explore:8100` |
| `VULTR_INFERENCE_API_KEY` | Plane 1 env only | Fail-closed without it (D25) |
| `VULTR_INFERENCE_MODEL` | Plane 1 env | Id from `GET {VULTR_INFERENCE_BASE_URL}/models` |
| `VULTR_INFERENCE_BASE_URL` | Plane 1 env | Default `https://api.vultrinference.com/v1` |
| `VULTR_INFERENCE_EMBEDDING_MODEL` | Optional Plane 1 | Embeddings model id (D75); empty disables |
| `VULTR_INFERENCE_VISION_MODEL` | Optional Plane 1 | Vision model for screenshots (D75); empty → chat model |
| `VULTR_RAG_COLLECTION` | Optional Plane 1 | Vector store collection id for RAG `vuln_review` (D75) |
| `VULTR_RAG_SEED_FINDINGS` | Optional Plane 1 | `true` upserts finding snippets into the collection |
| `ENABLE_VULN_REVIEW_LLM` | Optional Plane 1 | Default `true`; fail closed to deterministic cite-check |
| `ENABLE_SCREENSHOT_VISION` | Optional Plane 1 | Default `false`; never gates completion (D31) |
| `MSB_HOST` | Plane 1 env | Empty = `msb` on local PATH. Else `user@vx1-host` |
| `MSB_BIN` | Plane 1 env | Absolute path on remote when non-login SSH PATH lacks `msb` |
| `MSB_SSH_KEY` | Plane 1 env | Private key path for `MSB_HOST` SSH |
| `VULTR_API_KEY` | Operator laptop / ops env | For `vultr-cli` / API — **not** required by explore runtime today |
| `GITHUB_TOKEN` | Optional Plane 1 | Raises pre-flight GitHub metadata rate limits (D45) |
| `ADMISSION_STORE` | Plane 1 (+ frontend when Valkey) | `memory` (default) or `valkey` for shared D40 admission (D71) |
| `VALKEY_URL` / `REDIS_URL` | Plane 1 (+ frontend) when `ADMISSION_STORE=valkey` | Vultr Managed Valkey DSN — **never** into sandboxes |
| `STORAGE_BACKEND` | Plane 1 env | `filesystem` (default) or `s3`/`object` for Vultr Object Storage (D72) |
| `OBJECT_STORAGE_*` | Plane 1 env when backend is s3/object | Endpoint, bucket, access/secret keys — **never** into sandboxes |
| `VULTR_CR_ENDPOINT` / `VULTR_CR_ROBOT_*` | Plane 1 / VX1 host only | Private bootstrap image pull (D74) — **never** into sandboxes |

Never put `VULTR_*`, `VULTR_CR_ROBOT_*`, `OBJECT_STORAGE_*`, `INTERNAL_API_TOKEN`, or SSH keys into sandbox create env.

---

## 3. Clone and environment files

```bash
git clone <your-fork-or-clone-url> killhub
cd killhub
cp .env.example .env
cp frontend/.env.example frontend/.env.local
mkdir -p storage/{ledger,profiles,screenshots,artifacts,canaries}
```

Edit `.env` and `frontend/.env.local`:

1. Set a strong shared `INTERNAL_API_TOKEN`.
2. Set `VULTR_INFERENCE_API_KEY` and `VULTR_INFERENCE_MODEL`.
3. Set `MSB_HOST` / `MSB_BIN` / `MSB_SSH_KEY` if Plane 1 is not the VX1 host.
4. Point `CONTROL_PLANE_DENY_HOSTS` and `CONTROL_PLANE_PROBE_URL` at **your** public hostname (not necessarily `killhub.pro`).

**CWD note:** `explore` loads `.env` from the **process working directory** (`Settings` in `explore/config.py`). For native runs, either:

- `ln -s ../.env explore/.env` and run uvicorn from `explore/`, or
- use systemd / compose `EnvironmentFile=` with an absolute path to the repo-root `.env`.

Never commit `.env`, `frontend/.env.local`, or real keys.

---

## 4. Local Plane 1

### A. Native (recommended for day-to-day)

```bash
# explore sidecar (from explore/, with explore/.env → ../.env)
cd explore
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
# optional for quality gate: .venv/bin/pip install -r requirements-dev.txt
ln -sf ../.env .env
.venv/bin/python -m main
# listens on EXPLORE_HOST:EXPLORE_PORT (default 127.0.0.1:8100)
```

```bash
# frontend
cd frontend
pnpm install
pnpm dev
# http://127.0.0.1:3000 — proxies /api to EXPLORE_BASE_URL
```

Worker + in-process reaper start with the explore lifespan. Plane 2 still needs reachable `msb` (usually `MSB_HOST` → VX1).

### Operator MCP (D81)

With Plane 1 up (or against production), Cursor can drive jobs without the browser:

```bash
cd explore
# uses explore/.venv; talks to public /api on KILLHUB_BASE_URL
KILLHUB_BASE_URL=http://127.0.0.1:3000 .venv/bin/python -m operator_mcp
```

- **Stdio:** Cursor MCP server cwd = `explore/`, command = `.venv/bin/python`, args = `["-m", "operator_mcp"]`.
- **HTTP:** `{ "url": "https://killhub.pro/mcp" }` (or local `http://127.0.0.1:3000/mcp`). Explore must set `KILLHUB_BASE_URL` to the public edge origin so tool calls still hit admission-gated `/api/jobs`.

Agent-shaped tools include `create_and_wait`, `get_receipt`, `run_fixture`, `tail_events`. This is **not** `killhub-harness` (agent → sandbox). Contract: [API.md](API.md)#operator-mcp-d81.

### B. Docker Compose

[`docker-compose.yml`](docker-compose.yml) builds Plane 1 only. Today it sets `env_file: .env.example` on explore — **that file has empty secrets and pipeline flags off**. For a real run:

1. Fill repo-root `.env` (and export or pass through Compose as needed).
2. Point explore at your secrets, e.g. change `env_file` to `.env`, **or** pass `MSB_HOST`, `MSB_SSH_KEY`, `VULTR_INFERENCE_*`, and pipeline flags via `environment:` / shell env (`${VAR}` already used for some keys).
3. Mount or copy an SSH key into the explore container if using remote VX1 (`MSB_SSH_KEY` must be a path **inside** the container).

```bash
export INTERNAL_API_TOKEN='your-token'
# plus MSB_* / VULTR_INFERENCE_* as needed
docker compose up --build
```

- Frontend: `http://127.0.0.1:3000`
- Explore (direct): `http://127.0.0.1:8100`

Compose binds services openly for local use; public demo must not expose 3000/8100 (D46).

---

## 5. Enable the job pipeline

[`.env.example`](.env.example) defaults these to `false` so an empty env cannot burn inference or spin VMs. For a full job loop set:

```bash
MSB_AUTO_CREATE=true
DISCOVER_ON_CLAIM=true
INSTALL_ON_CLAIM=true
VERIFY_ON_CLAIM=true
SCREENSHOTS_ON_CLAIM=true
CONTAINMENT_ON_CLAIM=true
FINALIZE_ON_CLAIM=true
REAPER_ENABLED=true
```

If they stay `false`, jobs can be created and claimed but will not progress through bootstrap → discover → install → verify → finalize (`explore/worker.py`).

---

## 6. Plane 2 (Microsandbox)

On the VX1 host (or wherever `msb` runs):

```bash
msb doctor
# optional smoke: create / exec / destroy a throwaway sandbox per Vultr docs
```

From Plane 1 env:

| Setting | Same host as `msb` | Laptop / separate CP |
|---------|--------------------|----------------------|
| `MSB_HOST` | empty | `user@vx1.example` |
| `MSB_BIN` | `msb` (or absolute) | Absolute path on remote, e.g. `/root/.local/bin/msb` |
| `MSB_SSH_KEY` | empty | Path to private key readable by explore |

Also set:

- `MSB_DEFAULT_IMAGE` (default `debian` for local dx; prod: Vultr CR digest pin — below)
- `CONTROL_PLANE_DENY_HOSTS` — include your CP hostname so install-phase denial is meaningful (D39)
- `CONTROL_PLANE_PROBE_URL` — known-live CP URL for containment probes (D65)
- `INSTALL_EGRESS_PROBE_URL` — positive control (default `https://github.com`)

Harness details: [ARCHITECTURE.md](ARCHITECTURE.md) · [DECISIONS.md](DECISIONS.md) D36 / D39 / D59 / D74.

### Vultr Container Registry (D74)

Private Killhub-owned bootstrap / runtime base images live in **Vultr Container Registry** (`*.vultrcr.com`). The **host** (where `msb` runs) pulls the image; the **guest** never receives registry robot secrets.

**Image ref form**

```text
<region>.vultrcr.com/<registry-name>/<repository>@sha256:<64-hex>
# example:
ewr.vultrcr.com/killhub/bootstrap@sha256:0123…abcd
```

Set that string as `MSB_DEFAULT_IMAGE` (and optionally as runtime `oci_image` after replace). Tags are fine for local experiments; **prod pins by digest**.

**Operator steps** (no live registry is created by Killhub code; account may start with zero registries)

1. Create a registry (console or `vultr-cli container-registry create …`) in a region near VX1 (e.g. `ewr`, `ams`, `fra`). Start-up plan is free-tier sized.
2. Create a **pull** robot (or mint docker credentials via `vultr-cli container-registry credentials docker <id>`). Prefer pull-only for the VX1 host; use a separate push robot / `--read-write` for CI image builds.
3. On the **msb host**, put robot creds in Plane 1 env only (`/etc/killhub/killhub.env` or `.env`):

```bash
VULTR_CR_ENDPOINT=ewr.vultrcr.com/killhub
VULTR_CR_ROBOT_USERNAME='robot$…'
VULTR_CR_ROBOT_PASSWORD='…'
VULTR_CR_REQUIRE_CREDS=true
```

4. Login once so the host credential store can serve `msb` pulls:

```bash
./explore/scripts/vultr_cr_login.sh
```

5. Build and push a trusted bootstrap image (bake Playwright / assess tooling when useful — D43 / D63), then pin:

```bash
docker build -t "${VULTR_CR_ENDPOINT}/bootstrap:build" -f path/to/Dockerfile .
DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' "${VULTR_CR_ENDPOINT}/bootstrap:build" | awk -F@ '{print $2}')
# or: docker push … then copy digest from vultr-cli / console
export MSB_DEFAULT_IMAGE="${VULTR_CR_ENDPOINT}/bootstrap@${DIGEST}"
```

6. Restart explore so settings reload. Harness **fail-closes** create/replace when the image is `*.vultrcr.com` and robot username/password are missing (`VULTR_CR_REQUIRE_CREDS=true`). Set `VULTR_CR_REQUIRE_CREDS=false` only for a deliberately public registry.

**Guest vs host:** `VULTR_CR_ROBOT_*` are Plane-1 / VX1 secrets. They are listed in the guest forbidden-env set and must never appear in `msb create --env`. Sandboxes still get canaries only (D44).

---

## 7. Vultr production-style host

Public demo pattern ([DECISIONS.md](DECISIONS.md) D24, D46): app on loopback; reverse proxy terminates TLS and faces the internet.

### Bind and proxy

1. Set `EXPLORE_HOST=127.0.0.1`. Run Next with hostname `127.0.0.1` (not `0.0.0.0` on a public NIC).
2. Put Caddy or nginx in front on `:443`.
3. Disable proxy buffering for SSE on `/api/jobs/*/events`.

Example **Caddy** (replace hostname):

```caddy
your-demo.example {
	encode gzip
	reverse_proxy 127.0.0.1:3000 {
		flush_interval -1
	}
}
```

Example **nginx** location for SSE (sketch):

```nginx
location /api/jobs/ {
	proxy_pass http://127.0.0.1:3000;
	proxy_http_version 1.1;
	proxy_set_header Connection "";
	proxy_buffering off;
	proxy_cache off;
	proxy_read_timeout 3600s;
}
```

Do **not** publish `3000` / `8100` publicly. Host-edge filtering is a **Vultr Firewall group** (D70) — see below.

### Vultr Firewall (host edge, D70)

Complements D46: Caddy still terminates TLS on the public NIC; the Firewall group drops everything except SSH (operator CIDRs) and HTTP/HTTPS (world). This is **not** Plane 2 Microsandbox net policy (D39/D43).

**Policy (IPv4 inbound)**

| Port | Proto | Source | Why |
|------|-------|--------|-----|
| 80 | TCP | `0.0.0.0/0` | Caddy HTTP + Let’s Encrypt ACME |
| 443 | TCP | `0.0.0.0/0` | Public demo HTTPS |
| 22 | TCP | Operator CIDRs only | SSH / `MSB_HOST` ops |
| other | — | deny (default once ≥1 rule exists) | Close scanners / stray listeners |

Outbound at the Vultr Firewall layer: leave unrestricted. Optional later: tighten SSH further; add IPv6 mirrors if the instance has public v6.

**Inventory status (this workspace, Nov 2026)**

- Vultr MCP `firewall_groups_list`: **0 groups** (account readable).
- Vultr MCP / `vultr-cli` **instance list**: often **401** until Account → API → Access Control allows the operator IP (#20). Do **not** invent instance IDs.
- Public host label: `killhub-vx1` · IP ~`140.82.59.188` · DNS zone on Vultr (registrar NS may still lag).

**Dry-run helper (preferred)**

```bash
export VULTR_API_KEY=…   # operator machine only — never sandboxes (D44)
export SSH_ALLOW_CIDRS='YOUR.OP.IP.0/32,OTHER.OP.NET.0/24'
./ops/vx1-firewall.sh            # dry-run: print planned vultr-cli calls
./ops/vx1-firewall.sh --apply    # create/update rules + attach to label killhub-vx1
```

`--apply` refuses missing `SSH_ALLOW_CIDRS` and refuses SSH from `0.0.0.0/0` unless `ALLOW_WORLD_SSH=1` (console recovery path required).

**Manual `vultr-cli` (copy-paste when inventory works)**

```bash
# 1) Resolve instance id by label — never guess
vultr-cli instance list -o json | jq -r '.instances[] | select(.label=="killhub-vx1") | .id'
# If this 401s: fix API Access Control, or copy the ID from the Vultr console for killhub-vx1.

INSTANCE_ID=…   # from above or console
vultr-cli firewall group create -d killhub-vx1-edge
GROUP_ID=…      # from create / firewall group list

# 2) Allow HTTP/HTTPS (ACME + demo)
vultr-cli firewall rule create --id="$GROUP_ID" --ip-type=v4 --protocol=tcp \
  --subnet=0.0.0.0 --size=0 --port=80 --notes='killhub HTTP / ACME'
vultr-cli firewall rule create --id="$GROUP_ID" --ip-type=v4 --protocol=tcp \
  --subnet=0.0.0.0 --size=0 --port=443 --notes='killhub HTTPS'

# 3) Allow SSH from each operator CIDR (example: single /32)
vultr-cli firewall rule create --id="$GROUP_ID" --ip-type=v4 --protocol=tcp \
  --subnet=YOUR.OP.IP.0 --size=32 --port=22 --notes='killhub SSH operator'

# 4) Attach — only after SSH rules exist for every operator who needs in
vultr-cli instance update-firewall-group \
  --instance-id="$INSTANCE_ID" --firewall-group-id="$GROUP_ID"

# 5) Verify from an allowlisted network
ssh root@140.82.59.188 'echo ok'
curl -sS -o /dev/null -w '%{http_code}\n' https://killhub.pro/health
```

**Lockout risk:** attaching with no (or wrong) SSH allowlist blocks ops until Vultr web console / rescue. Keep console access; coordinate teammate SSH keys (#22) before narrowing CIDRs. Unset firewall: `--firewall-group-id=0`.

### systemd examples

These are **illustrative** unit files — adjust paths, user, and `EnvironmentFile`. They are not a dump of any particular live host.

`/etc/systemd/system/killhub-explore.service`:

```ini
[Unit]
Description=Killhub explore sidecar
After=network.target

[Service]
Type=simple
User=killhub-worker
Group=killhub-worker
SupplementaryGroups=kvm
Environment=HOME=/var/lib/killhub-worker
UMask=0077
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/killhub-worker /var/lib/killhub/ledger /var/lib/killhub/artifacts /var/lib/killhub/screenshots /var/lib/killhub/profiles /var/lib/killhub/canaries
UnsetEnvironment=VULTR_API_KEY
WorkingDirectory=/opt/killhub/explore
EnvironmentFile=/etc/killhub/killhub.env
ExecStart=/opt/killhub/explore/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8100
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/killhub-frontend.service`:

```ini
[Unit]
Description=Killhub Next.js frontend
After=network.target killhub-explore.service

[Service]
Type=simple
User=killhub
Group=killhub
NoNewPrivileges=yes
PrivateTmp=yes
WorkingDirectory=/opt/killhub/frontend
EnvironmentFile=/etc/killhub/frontend.env
Environment=NODE_ENV=production
Environment=HOSTNAME=127.0.0.1
Environment=PORT=3000
ExecStart=/usr/bin/pnpm start
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`frontend.env` needs at least `INTERNAL_API_TOKEN` and `EXPLORE_BASE_URL=http://127.0.0.1:8100`. `killhub.env` is the explore/root catalog (inference, msb, pipeline flags, ledger paths). Mode `600`, root-owned.

Create a dedicated system account with a private home at `/var/lib/killhub-worker` and supplementary group `kvm`. Install the trusted Microsandbox binary and matching library in a root-owned directory readable by this account. Set `MSB_BIN` to that executable. Give the worker ownership of the five writable application directories above with mode `0700`. Configure absolute storage paths in the worker environment. Run the host reaper under the same identity, home, and Microsandbox installation so it sees the worker's inventory. During migration, drain existing jobs and confirm the old runtime inventory is empty. Restrict legacy environment files, backup copies, and ledger directories as well as the active files.

On a systemd VX1 host, install the files in `ops/offline/` as root. Place `killhub-msb`, `serve-restore`, and `disable-guest-links.py` beside the trusted binary at `/opt/killhub-msb/bin/`. Install the template under `/etc/systemd/system/` and the Polkit rule under `/etc/polkit-1/rules.d/`. Reload systemd and set `MSB_BIN=/opt/killhub-msb/bin/killhub-msb`. The wrapper delegates a canonical job's verify restore to its own systemd network namespace and disables guest non-loopback links before acknowledging readiness. The VM supervisor has only namespace-local loopback and the worker controls the guest over vsock.

Set `MANAGEMENT_PROBE_ADDRESS` to the operator-owned VX1 management address and TCP port to test from both sides (for example `192.0.2.10:22` for SSH). The host HTTP listener on that address and the configured install-egress destination are also checked during verification. Unreachable positive controls remain inconclusive. Temporarily enabling `PUBLIC_DEMO_FIXTURES_ONLY=true` limits admission to the three pinned SCA demo commits.

Build frontend once before `pnpm start`:

```bash
cd /opt/killhub/frontend && pnpm install && pnpm build
```

### Durability (D41, D73)

- Ledger default (local / single-host demo): `LEDGER_URL=sqlite:///./storage/ledger/killhub.db` (or an absolute path under `/var/lib/killhub/...`).
- **Optional hosted Postgres** (Vultr Managed Databases for PostgreSQL — D73): set Plane-1-only

  ```bash
  LEDGER_URL=postgresql://vultradmin:PASSWORD@HOST:PORT/defaultdb?sslmode=require
  ```

  Create the cluster in the Vultr dashboard (or `vultr-cli database create`), allow the VX1 IP in DB trusted sources, copy the connection URI (TLS — `sslmode=require`), put it in `/etc/killhub/killhub.env`, restart `killhub-explore`. Schema bootstrap runs on open. Do **not** inject DB credentials into sandboxes. This repo does not provision a cluster for you.
- In-process reaper runs with explore when `REAPER_ENABLED=true`.
- **Host reaper** (VX1, works even if Plane 1 is down):

```bash
cd /opt/killhub/explore
.venv/bin/python -m reaper --host --once
```

Cron or timer example: every 5 minutes.

- **Ledger backup** ([DATABASE.md](DATABASE.md)):

```bash
cd /opt/killhub/explore
.venv/bin/python -m ledger.backup --dest /var/lib/killhub/backups --keep 7
# Optional off-host copy (D72) when Object Storage is configured:
# .venv/bin/python -m ledger.backup --dest /var/lib/killhub/backups --keep 7 --upload
# or LEDGER_BACKUP_UPLOAD=true in killhub.env
```

Nightly timer recommended for a public demo (SQLite). For Postgres, use Vultr Managed Database backups or `pg_dump` instead of `ledger.backup`.

### Vultr Managed Valkey (optional, D71)

Local/dev keeps `ADMISSION_STORE=memory` (in-process rate limits + ledger concurrency). For multi-instance Plane 1 or a split frontend/explore host layout, use **Vultr Managed Valkey** (Redis-compatible) as the shared admission store:

1. Create a Managed Database with engine **Valkey** in the [Vultr dashboard](https://my.vultr.com/) (or `vultr-cli database create …`). Pick a region near VX1.
2. Under **Trusted Sources**, allow the control-plane host (VX1 public IP / VPC). Do not expose Valkey to the public internet.
3. Copy the connection URI (TLS preferred). Set on Plane 1 **and** the Next.js env (edge rate limits share the same keys):

```bash
ADMISSION_STORE=valkey
VALKEY_URL='rediss://default:PASSWORD@HOST:16724/0'
# REDIS_URL=…   # accepted alias
```

4. Restart explore + frontend. Misconfiguration or unreachable Valkey **fails closed** (`503` / `admission_unavailable`) — never silently unlimited admission. Credentials stay Plane-1-only (never into sandboxes). Account may start with **zero** Valkey clusters; code does not provision one.

### Vultr Object Storage (optional, D72)

Local/dev keeps `STORAGE_BACKEND=filesystem`. For prod screenshots/artifacts (and optional ledger backup upload):

1. Create an Object Storage subscription in the [Vultr dashboard](https://my.vultr.com/) (or `vultr-cli object-storage create`) in a cluster near the control plane (e.g. `ewr1.vultrobjects.com`).
2. Create a bucket; copy the subscription **hostname**, **access key**, and **secret key**.
3. Set on Plane 1 only (`/etc/killhub/killhub.env`):

```bash
STORAGE_BACKEND=s3
OBJECT_STORAGE_ENDPOINT=https://ewr1.vultrobjects.com
OBJECT_STORAGE_REGION=us-east-1
OBJECT_STORAGE_BUCKET=your-bucket
OBJECT_STORAGE_ACCESS_KEY=...
OBJECT_STORAGE_SECRET_KEY=...
OBJECT_STORAGE_PREFIX=killhub
LEDGER_BACKUP_UPLOAD=true   # optional
```

4. Restart explore. Misconfiguration **fails closed** (clear error) when backend is `s3`/`object` without credentials. Account currently needs an operator-created subscription/bucket — code does not provision one.

### Vultr CDN Pull Zone (optional, D76 — after D72)

Once screenshots land in Object Storage, put a **CDN Pull Zone** in front of the bucket so the home-feed thumbs hit the edge instead of Plane 1:

1. Create a Pull Zone (dashboard: Products → CDN → Pull Zones, or `vultr-cli`):

```bash
vultr-cli cdn pull create \
  --domain your-bucket.ewr1.vultrobjects.com \
  --scheme https \
  --label killhub-screenshots \
  --gzip \
  --cors
```

Origin must be the **virtual-host** bucket URL (`https://{bucket}.{cluster}.vultrobjects.com/`), not the path-style API endpoint.

2. Copy the assigned CDN hostname into Plane 1 env (no trailing slash):

```bash
OBJECT_STORAGE_CDN_BASE_URL=https://cdn-xxxxx.vultrcdn.com
```

3. Restart explore. New screenshot uploads get `public-read` + `Cache-Control: public, max-age=86400`. Artifacts and ledger backups stay private. Feed responses include absolute `screenshot_url` values.

4. Verify (after at least one uploaded still):

```bash
curl -I "https://cdn-xxxxx.vultrcdn.com/killhub/screenshots/{job_id}/{shot_id}.png"
```

Enable CORS on the pull zone so `killhub.pro` can load CDN images. Historical private objects are not rewritten — only new uploads get public ACL. Code does not provision the pull zone.

---

## 8. Verify

1. `curl -sS http://127.0.0.1:8100/internal/health` (or your internal health path) and public `https://your-host/health`.
2. Open the UI; paste a golden fixture URL from [explore/fixtures/m7.json](explore/fixtures/m7.json), e.g. `https://github.com/heroku/nodejs-getting-started`.
3. Confirm live status/SSE, readiness evidence, receipt, and sandbox destroy on terminal status.
4. Developer quality gate ([AGENTS.md](AGENTS.md) §8):

```bash
cd frontend && pnpm lint:fix && pnpm lint && pnpm knip && pnpm typecheck && pnpm build
cd ../explore && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q
```

---

## 9. Security checklist

- [ ] No `VULTR_*` / `VULTR_CR_ROBOT_*` / `INTERNAL_API_TOKEN` / SSH private keys in sandbox env (D44, D74)
- [ ] `CONTROL_PLANE_DENY_HOSTS` includes your public hostname
- [ ] Admission caps set before anonymous public `POST` (`MAX_CONCURRENT_JOBS`, `MAX_QUEUED_JOBS`, `RATE_LIMIT_*` — D40)
- [ ] Multi-instance / split Plane 1: `ADMISSION_STORE=valkey` + `VALKEY_URL` (Trusted Sources include VX1) — D71
- [ ] App bound to loopback; only proxy faces the internet (D46)
- [ ] Vultr Firewall group on VX1: 80/443 world, 22 operator CIDRs only (D70)
- [ ] Host reaper + ledger backups for absolute expiry / crash recovery (D41)
- [ ] Destroy on `completed` / `failed` / `cancelled` / `expires_at` — not on readiness alone (D37)

---

## 10. Troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| Job created but never progresses | Pipeline flags still `false` (§5) |
| `msb: command not found` over SSH | Set absolute `MSB_BIN`; non-login shells often miss `~/.local/bin` |
| SSH / harness failures | `MSB_HOST`, `MSB_SSH_KEY` permissions, and VX1 `authorized_keys` |
| Agent / discover fails closed | Empty `VULTR_INFERENCE_API_KEY` or invalid `VULTR_INFERENCE_MODEL` |
| Frontend 502 / auth errors to explore | Mismatched `INTERNAL_API_TOKEN` or wrong `EXPLORE_BASE_URL` |
| explore ignores your secrets | Process CWD has no `.env` — symlink or use absolute `EnvironmentFile` (§3) |
| Compose “works” but no inference/msb | `env_file: .env.example` — switch to filled `.env` / exports (§4B) |
| Containment / deny probes odd | `CONTROL_PLANE_PROBE_URL` / `CONTROL_PLANE_DENY_HOSTS` still point at someone else’s demo host |
| `vultr-cli instance list` / MCP instance 401 | Account API Access Control IP allowlist (#20); fix key AC before inventing IDs |
| SSH drops after Firewall attach | SSH source not in group rules — use Vultr console, widen CIDR, or `--firewall-group-id=0` |

---

## Docs

| Doc | Purpose |
|-----|---------|
| [README.md](README.md) | Product |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Planes, trust zones, deploy topology |
| [DECISIONS.md](DECISIONS.md) | D24, D25, D41, D46, D59, D70–D76, … |
| [`ops/vx1-firewall.sh`](ops/vx1-firewall.sh) | Dry-run / apply Vultr Firewall for VX1 (D70) |
| [AGENTS.md](AGENTS.md) | Agent rules, quality gate, Vultr tooling |
| [DATABASE.md](DATABASE.md) | Ledger, reaper, backups |
| [API.md](API.md) | Jobs API + SSE |
| [`.env.example`](.env.example) | Full env reference |
