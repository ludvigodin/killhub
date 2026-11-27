# DATABASE.md — Database structure and rules

v1 persistence is a **durable job/event ledger** owned by the **Python `explore/` sidecar** ([DECISIONS.md](DECISIONS.md) D41, D52, D73) plus **filesystem artifacts** for profiles and screenshots (D17). Prod may mirror screenshots/artifacts (and optional ledger backups) to **Vultr Object Storage** (D72); local staging paths remain for D60 `copy_out`. In-memory-only stores are allowed solely for local scaffold before durability lands; **public/demo deploy requires the ledger**.

**Engine:** `LEDGER_URL` selects SQLite (`sqlite:///…`, default) or PostgreSQL (`postgresql://…` / `postgres://…` — Vultr Managed Databases). Field names below are identical on both engines (rule 6, D73).

Related: [API.md](API.md) · [DECISIONS.md](DECISIONS.md) · [ARCHITECTURE.md](ARCHITECTURE.md)

---

## Rules

1. **Plane 1 ledger (Python sidecar) is the source of truth** for jobs, events, profile revisions, readiness, vulns, sandbox generations, and screenshot metadata. Next.js proxies the public Jobs API; it does not own the job dictionary (D52).
2. **Plane 2 (disposable Microsandbox) holds no Killhub database.** It is ephemeral compute; any state needed after destroy must already be copied into Plane 1 artifacts / receipt (D49).
3. **Job lifetime ≠ client presence.** Rows/records remain until terminal state + TTL cleanup (or explicit cancel cleanup).
4. **Do not store secrets** (API keys, SSH private keys) in job JSON, event payloads, or screenshot captions. Redact before persist. Canaries (D44) are fake credentials tracked separately.
5. **Public allowlisted git URLs only** in `source` / create payload validation (D78: `github.com`, `gitlab.com`, `bitbucket.org`, `codeberg.org`). Wire field name remains `github_url`.
6. When changing ledger engine (SQLite ↔ Postgres), preserve field names below and document the migration in [DECISIONS.md](DECISIONS.md).
7. **Screenshots are optional** (D31); an empty screenshot list is valid.
8. **Readiness ≠ completion** (D37). `readiness.passed` is probe evidence; terminal success is `status=completed` after report + cleanup. Destroy the sandbox on terminal states / absolute expiry — **not** merely when readiness passes. Gate outcomes may fail the job without clearing readiness (D66).
9. **Bootstrap vs runtime profiles** (D36). A Killhub-owned bootstrap profile may create Plane 2 for inspect. Invalid **runtime** profiles must not start provision/install. Image replacement stays one live VM per job. Profiles are stored as **revisions** with a current pointer (D64).
10. **Job-level `destroyed_at` only after confirmed removal of the current sandbox** (D57, D64). Per-generation `destroyed_at` may record a replaced bootstrap VM while a replacement is alive. Cleanup failures are first-class state.
11. **Verification kinds** (D54) must remain distinct: original application vs generated demo vs setup failed.
12. After **`cancel_requested_at`**, reject ordinary worker mutations; **finalizer** writes (cleanup, receipt, lifecycle, then terminal `cancelled`) are authorized (D61).
13. **`resolved_commit` is required** after first successful clone and must be reused on every re-clone / replace (D62).
14. **Event byte-budget pruning is contiguous** and must leave a `gap` tombstone — never silent middle holes (D67).

---

## Entities

```mermaid
erDiagram
  Job ||--o{ JobEvent : emits
  Job ||--o{ EnvironmentProfileRevision : has
  Job ||--o{ SandboxGeneration : has
  Job ||--o{ Screenshot : has
  Job ||--o| VulnReport : has
  Job ||--o| JobReceipt : has

  Job {
    string job_id PK
    string github_url
    string resolved_commit
    string status
    int progress
    string current_step
    string error
    string sandbox_id
    int current_profile_revision
    int current_sandbox_generation
    string inference_model
    datetime expires_at
    datetime destroyed_at
    datetime cancel_requested_at
    datetime created_at
    datetime updated_at
  }

  JobEvent {
    string event_id PK
    string job_id FK
    string type
    string message
    json payload
    datetime timestamp
  }

  EnvironmentProfileRevision {
    string job_id FK
    int revision PK
    string phase
    string schema_version
    json profile
    string storage_path
    datetime created_at
  }

  SandboxGeneration {
    string job_id FK
    int generation PK
    string environment_id
    string image
    string state
    datetime expires_at
    datetime destroyed_at
  }

  Screenshot {
    string screenshot_id PK
    string job_id FK
    string step
    string caption
    string storage_path
    datetime created_at
  }

  VulnReport {
    string job_id PK
    string summary
    json findings
    string status
  }

  JobReceipt {
    string job_id PK
    json verification
    json containment
    json lifecycle
  }
```

---

## Job

| Field | Type | Rules |
|-------|------|-------|
| `job_id` | string (UUID) | Immutable PK |
| `github_url` | string | Validated public HTTPS git URL on an allowlisted host (D78); field name retained for API stability |
| `resolved_commit` | string \| null | Full SHA after first successful clone; **required** before provision/install and on every re-clone (D62). Null only pre-clone / preflight-fail |
| `status` | enum | `pending` → `queued`? → `analyzing` → `planning` → `provisioning` → `installing` → `verifying` ⇄ `repairing` → `scanning` → `finalizing` → `completed` \| `failed` \| `cancelled` |
| `progress` | int 0–100 | Monotonic non-decreasing except on documented repair resets |
| `current_step` | string | Human-readable label for UI |
| `steps_completed` | string[] | Prior major states |
| `error` | string \| null | Set on failure; cleared on retry entry if applicable |
| `readiness` | object \| null | `{ passed, probe, detail, at }` — set when probe succeeds; **not** a destroy trigger (D37); never cleared by findings/gates (D66) |
| `verification` | object \| null | `{ kind, original_failure? }` — D54 |
| `verify_result` | object \| null | Smoke/readiness evidence (mirrors / extends readiness detail; includes MCP stdio transcript summary when applicable) |
| `sandbox_id` | string \| null | **Current** generation’s Microsandbox id/name; retained after final destroy for the report UI |
| `current_profile_revision` | int \| null | Pointer to latest accepted `EnvironmentProfileRevision` (D64) |
| `current_sandbox_generation` | int \| null | Pointer to current `SandboxGeneration` (D64) |
| `inference_model` | string \| null | Vultr Serverless Inference model id (D25) |
| `inference_usage` | object \| null | Tokens / wall-clock toward budgets (D40) |
| `event_cursor` | string \| null | Last **retained** durable `event_id` (snapshot→SSE handoff — D55, D67) |
| `expires_at` | datetime | Absolute sandbox/job expiry; **not** extended by `msb touch` or image replace (D41, D64) |
| `cleanup` | object | `{ status, attempts, last_error?, updated_at }` — D57 |
| `destroyed_at` | datetime \| null | Set **only** when the **current** Plane 2 removal is confirmed; null while any live generation exists or on `destroy_failed` |
| `cancel_requested_at` | datetime \| null | Set when cancel requested; freezes ordinary writers; terminal `cancelled` comes after finalizer + receipt (D61) |
| `created_at` / `updated_at` | datetime | UTC |

### `verification` (D54)

| Field | Values / rules |
|-------|----------------|
| `kind` | `original_application` \| `generated_demo` \| `setup_failed` |
| `original_failure` | Required when `kind=generated_demo` if original install/launch/readiness failed; `{ step, summary, detail? }` — must remain visible in the receipt/UI |

### `cleanup.status` (D57)

`pending` \| `destroying` \| `destroyed` \| `destroy_failed`

`queued` is optional when admission queues a job (D40).

---

## JobEvent

Append-only timeline (SSE source of truth). **Must be durable** in the ledger (D41). Retained per `EVENT_RETENTION` (D55) with contiguous byte-budget pruning (D67). Operator MCP / clients may also peek the **last N** retained events via `GET …/events/recent` (D81) without opening SSE.

| Field | Type | Rules |
|-------|------|-------|
| `event_id` | string | Monotonic per job (for SSE resume) |
| `job_id` | string | FK |
| `type` | enum | `status` \| `progress` \| `log` \| `screenshot` \| `error` \| `span` \| `finding` \| `containment` \| `lifecycle` \| `gap` (D49, D67) |
| `message` | string | Safe for UI |
| `payload` | object | Type-specific; no real secrets. For `log`, optional `kind` (`sandbox_create` \| `sandbox_replace` \| `sandbox_destroy` \| `repair_attempt` \| `mcp_assessment` \| `mcp_stdio_verify` \| `containment_probe` \| `network_probe` \| `agent` \| `harness` \| `admission` \| `cancel`), plus ids/detail as needed. For `gap`: `{ pruned_before_event_id, pruned_count?, bytes_freed }` |
| `timestamp` | datetime | UTC |

### Retention / pruning (D67)

Cap retained event bytes per job via `MAX_JOB_LOG_BYTES` (D40):

1. When over budget, delete a **contiguous prefix** of the oldest retained events (never middle holes).
2. Insert exactly one durable `type=gap` event at the new start of the retained sequence documenting what was pruned.
3. Never drop the sole remaining terminal `status` / destroy `lifecycle` / `receipt`-critical evidence without first ensuring the receipt row itself holds that dossier.
4. Active-job retention means the **current retained window** is complete and replayable — not that every byte since create is forever available once budgets bite.
5. Snapshot `event_cursor` always points at the last retained event; cursors inside a pruned range are expired (D55).

---

## EnvironmentProfileRevision (D64)

| Field | Type | Rules |
|-------|------|-------|
| `job_id` | string | FK |
| `revision` | int | Monotonic per job; composite PK with `job_id` |
| `phase` | enum | `bootstrap` \| `runtime` |
| `schema_version` | string | e.g. `1` — must match `profile.schema_version` (D51) |
| `profile` | object | Must validate against versioned schema for its phase |
| `storage_path` | string | e.g. `storage/profiles/{job_id}/r{revision}.json` (symlink/copy `environment_profile.json` → current optional) |
| `created_at` | datetime | UTC |

`Job.current_profile_revision` points at the latest accepted revision. Repairs that rewrite the runtime profile append a new revision; they do not overwrite history the receipt cites.

Canonical JSON Schema: `schemas/environment_profile.v1.json` (ship with explore workers).

### Bootstrap profile (D36)

Killhub-owned, schema-valid, used **only** to create the inspect sandbox: `intent: bootstrap`, `MSB_DEFAULT_IMAGE`, clone-only (`install_commands` / `run_commands` empty), minimal services/ports.

### Runtime profile — executable contract (D51)

| Key | Required | Notes |
|-----|----------|-------|
| `schema_version` | yes | `1` for v1 |
| `intent` | yes | `git_mcp` \| `webapp` \| `demo` (D34) |
| `source` | yes | `{ type: "git", url, ref, commit }` — **`commit` required** (full SHA, D62); fixtures pin before step 11 (D53) |
| `runtime` | yes | e.g. `python`, `node` |
| `os_image` | yes | Logical OS hint |
| `oci_image` | recommended | If ≠ bootstrap → harness replaces VM (D36) |
| `workdir` | yes | Default guest cwd for commands (absolute or repo-relative) |
| `services` | yes | Array of service specs (may be `[]`) — see below |
| `packages` | yes | Attempted at provision; failures flagged |
| `install_commands` | yes | `CommandSpec[]` |
| `run_commands` | yes | `CommandSpec[]` — app / demo launch |
| `processes` | yes | Supervision plan for long-running targets |
| `mcp` | if `git_mcp` | Transport + launch + readiness + optional assessment |
| `healthcheck` / `probes` | if `webapp` or `demo` (typical) | Explicit probe objects |
| `ports` | yes | Exposed/probed ports |
| `summary` | yes | Human-readable |
| `verification_target` | yes | `original_application` \| `generated_demo` — what readiness claims to prove (D54) |

#### `CommandSpec`

| Field | Required | Notes |
|-------|----------|-------|
| `argv` or `shell` | yes | Prefer `argv[]`; `shell` only when necessary |
| `cwd` | no | Defaults to profile `workdir` |
| `env` | no | Merged env; never Killhub secrets by default |
| `timeout_seconds` | yes | Hard cap per invocation |

For `verification_target=original_application` / `verification.kind=original_application`, launch commands must run the **built checkout** at `source.commit` — not unpinned registry fetches such as `npx -y <package>` (D62).

#### `services[]`

| Field | Required | Notes |
|-------|----------|-------|
| `name` | yes | Unique within profile |
| `kind` | yes | e.g. `postgres` \| `redis` \| `mongodb` \| `custom` |
| `image` / `package` | one of | How to obtain the service in-guest |
| `ports` | yes | Guest ports |
| `env` | no | |
| `healthcheck` | yes | Probe before dependents start |
| `depends_on` | no | Other service names |
| `optional` | no | If true, failure is flagged but may not hard-fail provision |

Fixture policies may forbid certain `kind`s (e.g. controlled fail forbids inventable datastores — D53).

#### `processes[]` (supervision)

| Field | Required | Notes |
|-------|----------|-------|
| `name` | yes | |
| `command` | yes | `CommandSpec` |
| `supervise` | yes | `oneshot` \| `restart` |
| `stop_signal` | no | Default `SIGTERM` |
| `ready_after_seconds` | no | Delay before probe |
| `ready_probe` | no | Reference to a named probe |

#### Probes

| `type` | Use | Pass criteria |
|--------|-----|---------------|
| `http` | webapp / demo | Status in allowlist (default 200–399), optional body match |
| `tcp` | port open | Connect success within timeout |
| `command` | scripted verify | Exit 0 + logged stdout/stderr evidence |
| `mcp_handshake` | git_mcp | Transport-specific — see MCP |

#### MCP block (`intent=git_mcp`)

| Key | Required | Notes |
|-----|----------|-------|
| `transport` | yes | `stdio` \| `streamable_http` (D51) |
| `launch_command` | yes | `CommandSpec` — for `stdio`, the subprocess the verify helper launches; for original_application must use built checkout (D62) |
| `cwd` | no | Overrides workdir for launch |
| `entrypoint` | recommended | Package/path pin (fixtures **must** set — D53 filesystem server) |
| `url` | if `streamable_http` | Base URL inside guest network namespace |
| `readiness` | yes | `{ type: "mcp_handshake", transport, timeout_seconds }` |
| `security_assessment` | no | D35 |

**`stdio` verification (in-guest helper):** copy/run Killhub `mcp_stdio_verify` inside Plane 2 via **D60-restricted** `copy_in`. It must:

1. Start `launch_command` as a subprocess (`cwd` / env from profile)
2. Write newline-delimited JSON-RPC to stdin: `initialize` → `notifications/initialized` → `tools/list`
3. Read stdout JSON-RPC responses; treat stderr as logs only
4. Pass iff `tools/list` returns a JSON-RPC result with a `tools` array (may be empty only if explicitly allowed; default require `len(tools) >= 1` for fixtures)
5. Emit evidence (`log.kind=mcp_stdio_verify` / readiness detail): protocol version, tool names, timings — **not** a process-alive or HTTP ping

**`streamable_http` verification:** HTTP(S) MCP transport handshake/list-tools against `mcp.url` after process supervision says ready — still must list tools (D30), not merely TCP connect.

#### `mcp.security_assessment` (optional — D35)

Unchanged semantics: optional Inspector/SDK after readiness; must not invalidate readiness or gate `completed`. Tooling must be preinstalled before verify offline (D63).

**Invalid runtime profiles must not trigger provision/install.** Bootstrap create uses the trusted bootstrap profile only.

---

## SandboxGeneration (D64)

| Field | Type | Rules |
|-------|------|-------|
| `job_id` | string | FK |
| `generation` | int | Monotonic per job; composite PK with `job_id` |
| `environment_id` | string | Microsandbox name / id for this generation |
| `image` | string | OCI image at create |
| `cpus` / `memory` | number / string | Caps at create |
| `expires_at` | datetime | **Same absolute deadline as `Job.expires_at`** — replace must not extend (D41, D64) |
| `state` | enum | `provisioning` \| `running` \| `replaced` \| `destroying` \| `destroyed` \| `destroy_failed` \| `failed` |
| `destroyed_at` | datetime \| null | Confirmed removal time **for this generation**; set when bootstrap is removed during replace even though the job’s replacement is alive |

On image replace (D36): prior generation → `state=replaced` + its `destroyed_at` when remove confirmed; allocate `generation+1` as current; `Job.current_sandbox_generation` / `Job.sandbox_id` update to the new live VM; **job-level `destroyed_at` stays null**. On final destroy success: current generation `destroyed` + set `Job.destroyed_at`. On destroy failure: `destroy_failed`; **do not** set job-level `destroyed_at` (D57).

`TestVmRef` as a single row keyed only by `job_id` is **superseded** by `SandboxGeneration` + current pointer.

---

## Screenshot

| Field | Type | Rules |
|-------|------|-------|
| `screenshot_id` | string | PK |
| `job_id` | string | FK |
| `step` | string | Plan-loop / job state label |
| `caption` | string | No secrets |
| `storage_path` | string | Local `storage/screenshots/{job_id}/{id}.png` (D60) or `s3://{bucket}/{prefix}/screenshots/...` after object upload (D72) |
| `created_at` | datetime | UTC |

Cap: `MAX_SCREENSHOTS_PER_JOB` and disk budget (D40). Capture in Plane 2 (D38); Plane 1 stores copied stills.

---

## VulnReport

| Field | Type | Rules |
|-------|------|-------|
| `job_id` | string | PK/FK |
| `summary` | string | Cite-checked AI summary (D48) |
| `findings` | array | `{ id, severity, package?, title, advisory_url?, source, detail? }[]` |
| `mcp_assessment` | object \| null | When D35 ran |
| `status` | enum | `ok` \| `partial` \| `failed` |

| `findings[].source` | Meaning |
|---------------------|---------|
| `sca` | Lockfile / advisory scanner — primarily Plane 1 against copied lockfiles (D43, D63) |
| `mcp_assessment` | MCP Inspector/SDK probe when planned |
| `intentional_app` | Intentionally vulnerable application patterns (if reported) — **not** SCA proof |
| `canary` | Unexpected canary credential hit (D44); excludes deliberate probe sessions (D65) |
| `network` / `containment` | Policy / isolation evidence (`policy_denied` vs `infra_error` — D65) |

Findings do not delete readiness evidence. Report generation is bounded in `scanning` / `finalizing` before terminal status (D37, D66).

---

## JobReceipt (D49)

Durable dossier outliving the sandbox: profile **revision ids** + snapshots, readiness, `verification`, findings, containment matrix (D58/D65), network probes, sandbox **generation** lifecycle, outcome gates (D66), `vuln_review` citations, cleanup status.

Receipt is persisted on **every** terminal path — including cancel — **before** terminal status is set (D61).

---

## Filesystem layout (v1)

```
storage/
├── ledger/                 # durable job/event DB — D41 (Python sidecar)
├── profiles/{job_id}/
│   ├── r1.json
│   ├── r2.json
│   └── environment_profile.json   # optional pointer/copy of current revision
├── artifacts/{job_id}/     # lockfiles, logs, helpers copy_out — D60
└── screenshots/{job_id}/{screenshot_id}.png

explore/helpers/            # allowlisted copy_in sources — D60
schemas/
└── environment_profile.v1.json
```

---

## Durability and reconciliation (D41)

| Concern | Behavior |
|---------|----------|
| **Ledger** | Persist Job, JobEvent, EnvironmentProfileRevision, SandboxGeneration, readiness, verification, VulnReport, receipt, ownership |
| **Startup** | Load ledger; list live sandboxes; adopt/resume; destroy orphans / past `expires_at`; retry `destroy_failed` |
| **Host reaper** | VX1-side destroy when `now >= expires_at` even if Plane 1 is down |
| **Touch** | Keep-alive only while `now < expires_at`; never moves `expires_at` |
| **Schema version** | `ledger_meta.schema_version` (baseline `1`). On open, `explore/ledger/migrations.py` stamps fresh databases, applies pending numbered migrations one transaction each (SQLite also copies the file to `<db>.pre-v<N>.bak`), and refuses a ledger newer than the build. Schema changes = append a `Migration` **and** update `ledger/schema.py` (SQLite + Postgres DDL) so fresh databases match |
| **Terminal writes** | The ledger refuses `status=completed\|failed\|cancelled` until a `job_receipts` row exists (D61). Use `Ledger.finalize_job()` to write receipt + terminal `status` event + job status in one transaction |
| **Vuln report** | Written via `Ledger.upsert_vuln_report()`; validates `status` and each finding's `id`/`severity`/`title`/`source` against the source table above |
| **Pruning guard** | Until the receipt exists, byte-budget pruning stops before terminal `status` and `lifecycle` `destroyed`/`destroy_failed` events (D67 rule 3) |
| **Engine** | `LEDGER_URL=sqlite:///…` (default) or `postgresql://user:pass@host:port/db?sslmode=require` (Vultr Managed Postgres — D73). Driver `psycopg` v3. Credentials Plane-1-only |
| **Backups** | SQLite: `python -m ledger.backup --dest DIR --keep N` (optional `--upload` / `LEDGER_BACKUP_UPLOAD=true` → Vultr Object Storage — D72). Postgres: Vultr Managed Database backups / `pg_dump` — not the SQLite file-copy tool |

---

## Cleanup

| Trigger | Action |
|---------|--------|
| Job reaching finalizer for `completed` / `failed` / `cancelled` | Enter `cleanup.status=destroying`; confirm remove of **current** generation; then generation + job `destroyed` + `destroyed_at` — or `destroy_failed` with error (D57, D61) |
| Absolute `expires_at` / host reaper | Same confirm-only semantics |
| Image replace | Prior generation destroyed/replaced; job-level `destroyed_at` unchanged while replacement live (D64) |
| Orphan reaper | Stop/remove sandboxes with no live job/generation reference |
