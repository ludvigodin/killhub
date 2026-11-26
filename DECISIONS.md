# DECISIONS.md — Agreed technical decisions

Record lasting choices here. Newest first within each section. Link related docs when behavior changes.

Product intent: [PRODUCT.md](PRODUCT.md) · Structure: [ARCHITECTURE.md](ARCHITECTURE.md)

---

## Platform shape

| ID | Decision | Rationale |
|----|----------|-----------|
| D27 | **Two planes:** (1) durable **control plane** (Next.js + agent/harness workers) · (2) **one disposable Microsandbox microVM per job**. There is no separate Explore VM vs Test VM — explore and test share that same sandbox. | Operator choice: same disposable compute for discovery and runtime; avoids dual-VM cost and drift |
| D28 | **Plane 1 owns Jobs API + SSE** (Next.js). It starts the plan loop and launches/destroys the disposable sandbox via the harness. `explore/` is a same-host worker/library under Plane 1, not a disposable VM and not a separate plane. | Durable job state cannot live in an ephemeral sandbox |
| D1 | ~~Three planes: Next.js · Explore Sandbox · Test VM~~ → **superseded by D27** | — |
| D2 | ~~Plane 1 does not run the agent or provision VMs~~ → **superseded by D28** (Plane 1 owns orchestration; browser still must not hold secrets) | — |
| D3 | ~~Plane 2 owns plan loop and harness~~ → **superseded by D28** (plan loop + harness run on the control plane) | — |
| D4 | Disposable Microsandbox per job on Vultr VX1 — **retained**; clarified by D27 that this single sandbox is both explore and test | Ephemeral KVM isolation; destroy on `completed` / cancel / fail / absolute expiry (D37, D41) |
| D5 | ~~Primary v1 intents: **`git_mcp` \| `webapp`**; unknown intents blocked/flagged~~ → **superseded by D34** | — |
| D34 | Environment Agent **decides** how to demonstrate the repo. Prefer **`git_mcp`** or **`webapp`** when those fit; otherwise invent a minimal **`demo`** (e.g. serve a lone `.txt` / puzzle as a tiny HTTP page or scripted verify) and put that plan in `environment_profile.json`. Hard-fail only when no verifiable demo can be launched within caps — not merely because the repo is not MCP/webapp. Readiness for `demo` = the profile’s declared probe (typically HTTP 200 or a command exit 0 with logged evidence); still **verifiable execution**, not a chat description. **Outcome honesty** required by D54 — a generated demo must not be labeled as original-application success. | Operator wants agent judgment: “bring it up somehow” including edge repos |
| D6 | Canonical artifact: **`environment_profile.json`** (runtime). Bootstrap create uses a separate Killhub-owned bootstrap profile (D36). Versioned executable schema: **D51**. | Clear handoff from discovery to sandbox provisioning |
| D51 | **Versioned executable profile schema (`schema_version`).** Runtime (and bootstrap) profiles are a complete contract: `services[]` (name, image/package, ports, health, env, depends_on), `commands[]` / install/run entries with **`cwd`**, argv/shell, env, timeout; **process supervision** (`supervise`: oneshot \| restart, stop signal, readiness delay); **probes** with explicit types. For MCP: required **`mcp.transport`**: `stdio` \| `streamable_http` (and optional URL for HTTP). **`stdio` readiness** is not an HTTP ping — Plane 2 runs an **in-guest MCP verify helper** that launches the server subprocess, speaks JSON-RPC over stdin/stdout (`initialize` → `notifications/initialized` → `tools/list`), and returns structured evidence. Schema lives in-repo (`schemas/environment_profile.v1.json`); breaking changes bump `schema_version`. | PROFILE was underspecified; MCP stdio ≠ HTTP healthcheck |
| D36 | **Bootstrap sandbox before discovery.** Plane 1 creates the job’s microVM from a Killhub-owned, schema-valid **bootstrap profile** (`intent: bootstrap`, `MSB_DEFAULT_IMAGE` / discover image, clone-only). Inspection runs inside that VM. The agent then writes the **runtime** `environment_profile.json`. If discovery selects a different `oci_image`, harness **replaces** the same job’s sandbox (stop+remove bootstrap → create with new image → re-clone) — **never two concurrent microVMs for one job** (D27). Same-image discovery continues in place. Invalid **runtime** profiles must not start provision/install; bootstrap create is exempt because the bootstrap profile is trusted and pre-validated. | Breaks inspect↔create circular dependency without a second plane or dual-VM explore/test split |
| D22 | Plane 2 runtime = **[Microsandbox on Vultr Cloud Compute](https://docs.vultr.com/how-to-set-up-agent-sandboxing-on-vultr-cloud-compute)** (`msb` / SDK over KVM+libkrun) | Official Vultr agent-sandboxing path |
| D24 | **Public / demo control plane** runs on **Vultr Cloud Compute**; local `docker-compose` remains for development only | Vultr is the orchestration fabric, not only sandboxes |

---

## Agent and AI

| ID | Decision | Rationale |
|----|----------|-----------|
| D7 | Agent stack: **OpenCode + Vultr Inference** | Align compute/inference with Vultr footprint |
| D25 | All Environment Agent LLM calls go through **[Vultr Serverless Inference](https://docs.vultr.com/products/serverless/inference/provisioning)** OpenAI-compatible API (`https://api.vultrinference.com/v1`); configure via `VULTR_INFERENCE_BASE_URL` / `VULTR_INFERENCE_API_KEY` / `VULTR_INFERENCE_MODEL` (control plane only) | Mandatory single inference path |
| D8 | Plan loop may draft/validate the **runtime** profile before provision/install; sandbox **create for inspect** uses the bootstrap profile (D36). Install/launch require a validated runtime profile + harness. | Spec first for mutations; bootstrap is the only pre-discovery create |
| D9 | ~~Only supported deps allowlist~~ → **superseded by D29** | — |
| D29 | **No install allowlist in v1.** Any OCI image Microsandbox can boot + any install/run commands from the profile may be attempted; **failures are flagged** (job error / unsupported outcome), not silently invented into success. Still never inject Killhub secrets into the sandbox. | Match “everything Vultr/Microsandbox can run”; honesty over false green |
| D10 | Repair/readiness retries capped by **`MAX_REPAIR_ATTEMPTS`** | Bound cost and infinite loops |
| D11 | Vuln findings are **reported**, not auto-patched; findings and optional assessment failures must **not** invalidate readiness evidence or block terminal `completed` by default | Visibility without erasing probe proof |
| D33 | **Vulnerability posture in v1:** always run **SCA / lockfile / known-advisory scans** + AI `vuln_review`. **Do not** weaponize CVEs or run generic app/web pentest / exploit suites against the submitted project. **Containment probes (D26)** prove sandbox isolation only. **MCP protocol/tool assessment** is allowed only when the agent plans it (**D35**) — that path is not a blanket pentest license. | Scan + report by default; optional MCP assessment is opt-in via profile |
| D35 | When the Environment Agent encodes an **MCP security assessment** in `environment_profile.json` (typically under `mcp.security_assessment` for `git_mcp`), Plane 2 **may** run **MCP Inspector and/or MCP SDK** probes after readiness (tool/schema surface, safe fixture-backed calls). Assessment is **agent-planned and optional**; it must **not** invalidate readiness or gate `completed` (D30 / D37). Findings stream into the job report alongside SCA. If the profile omits assessment, skip Inspector entirely. | Operators want MCP security testing when the repo warrants it, without making every job an offensive campaign |
| D30 | **`git_mcp` readiness** = real **MCP handshake** that can list tools (not merely process-alive or HTTP ping) | Proves the MCP server speaks the protocol |
| D31 | **Screenshots are optional.** Capture when useful (e.g. HTTP webapp verify); skip for CLI-only MCP or early fail. Missing screenshots must **not** invalidate readiness or block `completed`. | Not every job has a meaningful still |
| D37 | **Separate readiness from job completion.** `readiness` is probe evidence (`passed` / probe / detail) set when the profile probe succeeds. Terminal success status is **`completed`**, reached only after bounded report generation (SCA + `vuln_review`, optional MCP assessment), artifact capture, and sandbox cleanup. Do **not** destroy the sandbox merely because readiness passed. Destroy on `completed` \| `failed` \| `cancelled` \| absolute expiry (D41). Findings / optional assessment failures do not clear `readiness.passed`. | Prevents premature destroy when “ready” meant both probe-ok and job-finished |

---

## API and realtime

| ID | Decision | Rationale |
|----|----------|-----------|
| D12 | Jobs are **server-owned**; disconnect ≠ cancel | Long pipelines survive tab close; cancel is explicit `DELETE` or timeout |
| D13 | Dual channel: **poll `GET /jobs/{id}` + SSE `/events`** must stay consistent | Robust UI + live updates |
| D14 | ~~SSE types: `status`, `progress`, `log`, `screenshot`, `error`~~ → **extended by D49** (those five remain; evidence types added) | — |
| D49 | **Structured evidence stream + job receipt.** SSE types: `status` · `progress` · `log` · `screenshot` · `error` · **`span`** · **`finding`** · **`containment`** · **`lifecycle`**. Keep-alives (D50) may use comment frames or empty `progress` heartbeats. Every job produces a durable **receipt** on Plane 1 that outlives the sandbox: profile(s), readiness, findings, containment/network probe results, sandbox lifecycle (`created` / `replaced` / `destroyed`), outcome gates, and `vuln_review` citations. Destroy evidence is required on every terminal path. | Operators need an audit dossier, not only a progress bar |
| D50 | **SSE keep-alives** during long install/verify/scan steps (at least every ~15s while the stream is open) so clients do not appear stalled | Long Microsandbox steps otherwise look dead |
| D15 | Public **HTTPS github.com** URLs only in v1 | Reduce auth and SSRF surface |
| D40 | **Public demo admission controls.** Per-job CPU/memory/timeout caps do not bound aggregate demand. Plane 1 enforces: **global concurrency** (`MAX_CONCURRENT_JOBS`), a **bounded queue** (`MAX_QUEUED_JOBS`), **request throttling** (per-IP / global rate limits on `POST /api/jobs`), **per-job and rolling inference budgets** (token/wall-clock), and **disk/log caps** (profile/screenshot/event retention sizes). Reject with `429` (rate / inference budget) or `503` (concurrency / queue full) and a clear error body — never silently drop. | Anonymous access needs hard admission, not only per-sandbox limits |
| D45 | **Plane-1 pre-flight before bootstrap sandbox create.** After URL validation + admission (D15, D40), run cheap checks on the control plane (and/or read-only GitHub metadata): rate/abuse already applied; optional known-malicious dependency / advisory pre-screen when cheap; reject or short-circuit with findings **without** creating a Microsandbox when pre-flight hard-fails. Soft signals may continue into the job with findings attached. | Avoid burning VX1 for obviously hostile or invalid intakes |
| D52 | **Python sidecar owns job state.** Close the Next.js↔`explore/` non-decision: **`explore/` is a same-host localhost sidecar** that owns the durable ledger and workers. Next.js is a thin public edge (UI + `/api` proxy) and does **not** hold the job dictionary. Internal Worker API (loopback + `INTERNAL_API_TOKEN`): `POST /internal/jobs`, `GET /internal/jobs/{id}` (snapshot), `GET /internal/jobs/{id}/events` (SSE), `DELETE /internal/jobs/{id}` (cancel), plus screenshot routes as needed. Define and freeze this interface **before** N1/E1. | Next.js and Python cannot share an in-process dict; one state owner avoids split-brain |
| D55 | **SSE cursor contract.** Snapshot includes `event_cursor` (last durable `event_id`). Clients hydrate snapshot then subscribe with `Last-Event-ID` / `?after=`. Retain events for `EVENT_RETENTION` (at least job active lifetime + configurable post-terminal window). Unknown/expired cursor → `410` or SSE `error` with `code=cursor_expired`; client must re-snapshot and resubscribe — never silently skip the gap. | Prevents missed events between hydrate and subscribe |
| D56 | **Cancel is idempotent and freezes writers.** Repeated `DELETE` on an already-`cancelled` job returns success with the same terminal snapshot. Cancel during bootstrap/create aborts in-flight `msb create` (best effort) and destroys any partial sandbox. After cancel is committed, workers may only write cleanup/destroy fields; other status/progress/profile mutations are rejected by the ledger. | Avoids zombie updates and ambiguous cancel races |

---

## Data and storage

| ID | Decision | Rationale |
|----|----------|-----------|
| D16 | ~~v1 job store: in-memory first~~ → **superseded by D41** for any public/demo deploy; in-memory remains allowed only for local scaffold before M1 durability | Speed to scaffold conflicted with restart recovery and audit |
| D41 | **Durable job/event ledger** on Plane 1 before public deployment: persist jobs, events, readiness, vuln reports, sandbox refs (`sandbox_id`, `expires_at`, `destroyed_at`), and ownership. Filesystem artifacts stay for profiles/screenshots (D17). On control-plane startup: **reconcile** ledger vs live Microsandbox inventory (adopt, resume, or destroy orphans). **Host-side reaper** on the VX1 host enforces absolute `expires_at` and must **not** be extended by `msb touch` (touch may keep a guest warm only while `now < expires_at`). Exact engine: SQLite (default) or Postgres — record choice when implementing. Owned by the Python sidecar (D52). | Restart must not lose the audit trail; sandboxes must die even if Plane 1 crashes |
| D57 | **Cleanup is explicit; `destroyed_at` is confirmed-only.** Represent destroy lifecycle: `destroying` → `destroyed` \| `destroy_failed`. Set `Job.destroyed_at` / `TestVmRef.state=destroyed` **only after** confirmed `msb remove` (or equivalent). On failure, persist `cleanup.status=destroy_failed`, `cleanup.last_error`, retry/reaper continues; receipt must show incomplete destroy. | Avoids lying that the sandbox is gone |
| D17 | Profiles under `storage/profiles/{job_id}/`; screenshots under `storage/screenshots/{job_id}/` | Simple local/dev layout; object storage later via `SCREENSHOT_STORAGE` |
| D18 | Screenshot **stills only** when captured — Playwright **browser process runs inside Plane 2** (D38); Plane 1 may store stills copied out. Else terminal stills — see D31 | Enough audit trail without video cost; no untrusted page JS on the control plane |
| D54 | **Verification outcome classes.** Every job receipt records `verification.kind`: **`original_application`** \| **`generated_demo`** \| **`setup_failed`**. Prefer proving the repo’s intended app/MCP server; if the agent invents a `demo` (D34), label it `generated_demo` and retain visible **original setup failure** evidence (`verification.original_failure`) so a successful wrapper never implies the application works. Gates (D47) must not collapse these labels. | Invented demos are useful but must not inflate “success” |

---

## Security

| ID | Decision | Rationale |
|----|----------|-----------|
| D19 | Killhub control-plane secrets **never** injected into sandbox `env` by default | Prevent key exfiltration via untrusted repos |
| D20 | Agent tools may only target harness / sandbox APIs — **never** execute untrusted repo install/run on the control-plane host | Discovery reads via clone/`msb` copy/exec inside the sandbox |
| D38 | **OpenCode lockdown (enforceable).** Plane 1 runs the Environment Agent under a **trusted system/managed OpenCode config** (host-owned; outranks project/user config). Policies **deny** host `shell`, local edit/write of untrusted trees, arbitrary providers/plugins/MCP, and non-Vultr inference (`provider.use` allow only the Vultr-compatible provider — D25). Expose **only** job-scoped harness tools (create/exec/copy/destroy/readiness helpers). Submitted repository files (`AGENTS.md`, `.opencode`, prompts, scripts) are **untrusted input** — never loaded as authority for tools, providers, or plugins. **Playwright browser execution for screenshots runs inside Plane 2**; Plane 1 may orchestrate capture via harness and copy stills out. | D20 was aspirational without config; OpenCode shell runs with host user authority unless denied |
| D21 | Prefer non-root in sandbox; no Docker socket mount from control plane | Reduce breakout risk |
| D23 | Harness drives Plane 2 via **`msb` CLI / Microsandbox SDK** (create / exec / copy / stop / remove); OpenCode may use only harness-scoped MCP tools allowed by D38 | Job-owned lifecycle stays in harness; agent MCP is additive and policy-gated |
| D59 | **Vultr MCP + CLI are the operator/agent interface to Vultr.** Building and operating Killhub must use: (1) **Vultr MCP** (`https://mcp.vultr.com/mcp`) for read-only inventory/oversight when available; (2) **`vultr-cli`** (or Vultr API with `VULTR_API_KEY`) for mutating Cloud Compute; (3) **`msb` CLI / Microsandbox SDK** for Plane 2 lifecycle — optionally **`microsandbox-mcp`** for agent-assisted debug under D38. Do **not** substitute Docker-on-control-plane for Microsandbox, non-Vultr clouds for demo/VX1, or fake `msb` success. If MCP/CLI/credentials are missing, **stop and report** — do not invent a third path. Product harness remains D23 (`msb`/SDK). See [plan/VULTR.md](plan/VULTR.md). | Keeps agents on the real Vultr fabric instead of local mocks that break isolation claims |
| D26 | **Containment proof** is a first-class path — **extended by D58**. A timed-out loop alone only proves timeout enforcement, not isolation. | Isolation is only demonstrable if unsafe execution is visible and contained |
| D58 | **Containment evidence matrix.** Before claiming isolation, the harness must record structured evidence for: (1) **timeout_enforcement** — adversarial loop absorbed by timeout/kill; (2) **host_access_denied** — guest cannot reach host/control-plane/management destinations (aligns D39); (3) **sibling_access_denied** — cannot reach another job’s sandbox; (4) **host_liveness** — host/control-plane remains healthy during the probe (no crash/OOM attributed to the guest). Stream as `containment` SSE / receipt fields. Missing dimensions ⇒ containment claim incomplete, not “proven.” Not CVE exploitation of the submitted app (D33). | Broader isolation claims need multi-axis evidence |
| D39 | **Plane 2 network policy is explicit and tested.** Microsandbox defaults allow public-internet egress and deny host/private/metadata — that is **not** sufficient when the control plane has a public URL. Every sandbox create applies a Killhub policy that: (1) keeps sibling isolation; (2) **denies egress to control-plane destinations** (public demo hostname/IPs, Jobs API ports) and to **Microsandbox management endpoints** reachable from the guest; (3) allows only documented package/git egress needed for install (or a tighter allowlist if configured). Document the concrete `--net*` / SDK policy in [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md); ship a probe that fails the job (or flags containment) if Plane 2 can reach Plane 1 or management APIs. | “Plane 2 never calls Plane 1” must be enforceable, not aspirational |
| D42 | **Trust-zone boundary matrix is canonical.** [ARCHITECTURE.md](ARCHITECTURE.md) must maintain zones (Internet · Edge · Control plane · Sandbox · External services) and a **From → To \| Allowed? \| Enforced by** table. Code and deploy config must match the table; aspirational prose alone is insufficient. | Makes isolation reviewable and testable |
| D43 | **Sandbox network phases.** Within D39’s policy: during **install/provision**, allow documented package/git egress; after install succeeds (or when entering verify/containment), **detach or deny remaining egress** so readiness probes and containment checks run offline (or registries-denied). Denied egress attempts are logged as evidence (`finding` / `containment`). Does **not** reintroduce a command allowlist (D29). | Limits exfil during verify; turns network into evidence |
| D44 | **Canary secrets in Plane 2.** On each sandbox create, plant **randomized canary credentials** (env/files) that are not real Killhub secrets. Harness scans for canary hits (exfil / unexpected use) during/after probes; hits are high-severity findings and must appear in the receipt (D49). Real control-plane keys still never injected (D19). | Positive containment evidence, not only “command failed” |
| D46 | **Demo edge binding.** On public/demo Vultr deploys, Next.js / workers bind to **`127.0.0.1`**; only a reverse proxy (e.g. Caddy) faces the internet and flushes SSE. Local `docker-compose` may expose ports directly for dx. | Shrinks accidental exposure of admin/debug surfaces |
| D47 | **Deterministic outcome gates; agents advise.** Terminal outcome labels (`completed` with readiness evidence, `failed`, `cancelled`) and severity routing for findings come from **rule/gates on evidence** (readiness probe, SCA findings, canary hits, network/containment probes, admission). The Environment Agent and `vuln_review` **propose** profiles and **explain** findings; they must not invent readiness success or override gate results. Confidence/severity for the report comes from evidence, never from model self-score. | Honesty over persuasive narrative |
| D48 | **Cite-checked `vuln_review`.** Every claim in the AI vulnerability summary must cite a finding id (SCA, MCP assessment, canary, network/containment). Uncited claims are dropped or marked non-authoritative. | Prevents hallucinated risk language |

---

## v1 golden fixtures (M7)

| ID | Decision | Rationale |
|----|----------|-----------|
| D32 | ~~M7 fixtures including NodeGoat as fail+vulns~~ → **superseded by D53** | NodeGoat can succeed if the agent provisions ephemeral Mongo inside the sandbox |
| D53 | **Pinned, deterministic fixtures.** All M7 URLs are public HTTPS github.com **pinned to commit SHAs** (record SHAs in fixture config at implement time). **(1)** webapp success — [`heroku/node-js-getting-started`](https://github.com/heroku/node-js-getting-started) @ pin → `verification.kind=original_application`. **(2)** `git_mcp` success — [`modelcontextprotocol/servers`](https://github.com/modelcontextprotocol/servers) @ pin, **entrypoint fixed** to the **filesystem** server (documented package/path; stdio transport + in-guest verify helper — D51) → original MCP readiness. **(3)** controlled **setup_failed** — a fixture-locked job against a deliberately broken target (Killhub-controlled broken-webapp fixture repo **or** a pinned public commit with fixture policy `forbid_demo_intent=true` and no inventable deps); must not rely on “forgot Mongo.” **SCA / dependency advisories** are asserted via lockfile scanners (`findings.source=sca`) on fixtures that have lockfiles; **intentionally vulnerable application code** (if exercised) is labeled separately (`intentional_app` / report section) and is **not** proof of SCA. NodeGoat is **not** the deterministic fail fixture. | Determinism + honest vuln classes |

---

## Explicit non-decisions (open)

- Ledger engine beyond “SQLite default / Postgres allowed” (D41) — pick at implement time and record here  
- Object storage vendor for screenshots in prod  
- Exact public-egress allowlist tightness (broad `public` minus control-plane denylist vs strict domain allowlist) — must satisfy D39 + D43 either way  
- Exact canary planting locations (env vs files vs both) — must satisfy D44  
- Exact reverse-proxy choice for demo (Caddy vs nginx vs other) — must satisfy D46  
- Concrete M7 commit SHAs and the public URL of the controlled broken-webapp fixture — fill when pinning  

When these close, add a dated row above and update [DATABASE.md](DATABASE.md) / [API.md](API.md) as needed.
