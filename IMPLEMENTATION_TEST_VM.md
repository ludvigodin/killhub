# Plane 2 — Disposable Microsandbox (explore + test)

Implementation plan for the **single disposable runtime** per job. Explore and Test are **not** separate VMs ([DECISIONS.md](DECISIONS.md) D27). Created, controlled, and destroyed **only** by the Plane 1 harness (`explore/harness.py`).

**Runtime:** [Microsandbox on Vultr VX1 Cloud Compute](https://docs.vultr.com/how-to-set-up-agent-sandboxing-on-vultr-cloud-compute) — each job gets a **microVM** (`libkrun` / KVM).

**Operator/agent tooling:** Vultr MCP (read inventory) · `vultr-cli` (mutate Cloud Compute) · **`msb` CLI / SDK** (sandbox lifecycle) · optional `microsandbox-mcp` for debug — [plan/VULTR.md](plan/VULTR.md) · D59. Do not substitute Docker for Plane 2.

Architecture: [ARCHITECTURE.md](ARCHITECTURE.md) · Index: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) · Workers: [IMPLEMENTATION_EXPLORE_SANDBOX.md](IMPLEMENTATION_EXPLORE_SANDBOX.md) · Decisions: D4, D22, D23, D27, D29, D59

---

## Role

```
IN:  bootstrap profile (trusted) then runtime environment_profile.json
       │
       ▼
  Create microsandbox (bootstrap image + net policy)
       → clone / inspect
       → optional replace if runtime oci_image differs (still one live VM)
       → attempt install/run → launch → readiness probes
       → optional Playwright / MCP assessment / SCA target
       │
       ▼
OUT: Running environment (or failure stdout/stderr for plan-loop retry)
     Stop + remove on completed / fail / cancel / absolute expires_at
```

One **Microsandbox microVM per job** on a Vultr VX1 host. The host is pooled; the sandbox is ephemeral. Nothing under a monorepo `test-vm/` app folder.

---

## Host vs sandbox

| Layer | What | Lifetime |
|-------|------|----------|
| **VX1 host** | Ubuntu 24.04 Vultr VX1 with `/dev/kvm`, `msb` + `libkrunfw` (`msb doctor` green) | Pooled |
| **Plane 2 sandbox** | Named microVM from an OCI image | Per job; CPU/memory capped; destroyed with job |

Reference: Vultr [agent sandboxing guide](https://docs.vultr.com/how-to-set-up-agent-sandboxing-on-vultr-cloud-compute).

---

## Harness contract (Plane 1 → this plane)

| API | Behavior (Microsandbox) |
|-----|-------------------------|
| `create_environment(job_id, plan) → environment_id` | `msb create` / SDK `Sandbox.create`; map bootstrap/runtime profile → OCI image + limits + **Killhub network policy** (D39); set absolute `expires_at`; open sandbox **generation** (D64) |
| `replace_environment(job_id, plan) → environment_id` | Stop+remove current generation; create with new image; re-clone **`resolved_commit`**; **inherit** job `expires_at`; never two concurrent (D36, D62, D64) |
| `wait_until_ready(environment_id)` | Block until guest `running` (not job readiness / not `completed`) |
| `exec(environment_id, cmd) → { stdout, stderr, exit_code }` | `msb exec` / SDK; timeouts on every call |
| `copy_in` / `copy_out` | `msb copy` host↔sandbox with **D60 path restrictions** (helpers → guest; guest → server-selected artifact dirs only; traversal/symlink/size checks) |
| `destroy_environment(environment_id)` | `msb stop` + `msb remove`; return `{ confirmed }` — false ⇒ `destroy_failed`, do not set job-level `destroyed_at` (D57) |

Prefer the **SDK** from `harness.py`. Agent-facing MCP tools only if allowed by OpenCode lockdown (D38). Destroy on `completed` / cancel / fail / absolute expiry remains harness-owned (D23, D37, D41).

---

## Lifecycle

1. **Bootstrap create** — `MSB_DEFAULT_IMAGE` + CPU/memory defaults + Killhub network policy; absolute `expires_at`; generation record (D36, D39, D41, D64)
2. **Clone / inspect** — clone `source`; persist **`resolved_commit`** (D62)
3. **Optional replace** — if runtime `oci_image` differs: destroy bootstrap generation, create new image, re-clone **same SHA**, inherit `expires_at` (still one live VM — D36, D64)
4. **Provision** — attempt `packages` / `services` / `install_commands`; **preinstall** assessment/browser/verify helpers; **flag failures** (D63)
5. **Network phase transition** — **deny-all remaining guest egress** (not registries-only) before verify (D43)
6. **Launch** — `mcp.launch_command` or `run_commands` from **built checkout** when claiming original_application (D62)
7. **Readiness** — MCP handshake (list tools) or HTTP healthcheck (Plane 1 `verify.py`) → `readiness` field only
8. **Optional MCP assessment** — when `mcp.security_assessment.enabled`, run preinstalled Inspector/SDK probes (D35, D63); does not invalidate readiness
9. **Scan / screenshot target** — lockfiles `copy_out` for **Plane-1 SCA**; Playwright stills in-guest when useful (D33, D38, D43)
10. **Containment / network probes** — full matrix with known-live targets + positive controls; install-phase CP denial; classify `policy_denied` vs infra (D58, D65)
11. **Destroy** — after receipt on terminal paths / absolute `expires_at` / orphan reaper (D61). `msb touch` may keep idle guests warm **only while** `now < expires_at` — it must not extend expiry (D41)

```mermaid
flowchart LR
  Boot["bootstrap profile"] --> Create["msb create + net policy"]
  Create --> GuestUp["wait until guest running"]
  GuestUp --> Clone["clone + inspect"]
  Clone --> Runtime["runtime profile"]
  Runtime -->|same image| Deps["attempt install"]
  Runtime -->|new oci_image| Replace["stop+remove → create → re-clone"]
  Replace --> Deps
  Deps --> Launch["MCP / app"]
  Launch --> Probe["readiness evidence"]
  Probe -->|fail| Retry["Plane 1 plan loop"]
  Retry --> Deps
  Probe -->|pass| Assess["optional MCP / shots / SCA"]
  Assess --> Destroy["msb stop + remove on completed"]
```

---

## Network policy (D39) + phases (D43)

Microsandbox defaults allow public-internet egress and deny host/private/metadata. That is **not** enough when Plane 1 has a public URL.

| Requirement | Behavior |
|-------------|----------|
| Sibling isolation | Inter-sandbox traffic denied |
| Control plane | **Deny** egress to public demo hostname/IPs (`killhub.pro`) and Jobs API destinations |
| Management | **Deny** Microsandbox / host management endpoints reachable from the guest |
| Install egress | Allow documented package/git destinations (or tighter allowlist) **during install/provision only**; CP/management still denied |
| Verify / containment | **Deny-all remaining guest egress** after install (loopback only — D43); denied attempts logged as findings |
| Assessment tooling | Preinstall Playwright / MCP Inspector/SDK / verify helpers in install phase or bake into image (D63) — do **not** install them after readiness |
| SCA | Prefer Plane-1 advisory scan of lockfiles copied to `storage/artifacts/{job_id}/`; no live registry `npm audit` after offline (D43) |
| Proof | See containment evidence rules below (D65) — failed fetch alone is insufficient |

### Concrete `msb` flags (Killhub — implemented)

**Install / provision phase** (`explore/net_policy.py` → `install_phase_policy`, always applied on create — cannot be skipped):

```bash
msb create --name kh-<job> --cpus N --memory SIZE \
  --env KILLHUB_CANARY_*=… \          # randomized canaries (D44), not real secrets
  --net public \
  --net-rule allow@dns \
  --net-rule deny@host \
  --net-rule deny@private \
  --net-rule deny@meta \
  --net-rule deny@<CONTROL_PLANE_DENY_HOSTS…> \
  --net-rule deny@<MSB_HOST ip/hostname> \
  [--net / --net-rule from MSB_NET_POLICY extras] \
  <image>
```

| Flag | Role |
|------|------|
| `--net public` | Package/git egress during install (D43 phase 1) |
| `deny@host` / `deny@private` / `deny@meta` | Host, RFC1918/link-local private, cloud metadata |
| `deny@<cp>` | Explicit control-plane / Jobs API destinations (`CONTROL_PLANE_DENY_HOSTS`) |
| Sibling isolation | Microsandbox default (inter-sandbox denied) — no extra flag |

**Verify / containment phase** (applied later in step 13 — `verify_phase_policy`):

```bash
# deny-all remaining guest egress (loopback only)
msb … --no-net
# or equivalent net-default deny with no public allows
```

Operator extras via `MSB_NET_POLICY` (comma list): bare tokens are extra `--net` profiles; `rule:TOKEN` appends `--net-rule TOKEN` after Killhub denies.

## Containment evidence (D58 + D65)

| Dimension | Required evidence |
|-----------|-------------------|
| `timeout_enforcement` | Adversarial loop absorbed by timeout/kill |
| `host_access_denied` | Guest fetch to **known-live** Plane 1 / management URL fails with classification `policy_denied`; host-side **positive control** to the same URL succeeds in the same window |
| `sibling_access_denied` | Guest cannot reach another job’s sandbox; same live-target + classification rules |
| `host_liveness` | Host/control-plane healthy during probe (no crash/OOM attributed to guest) |
| Install-phase CP denial | Also run CP/management deny probe **during install** (while package egress is allowed) so blanket offline cannot masquerade as isolation |
| Outcome classes | `policy_denied` \| `infra_error` \| `tooling_missing` \| `inconclusive` — only `policy_denied` counts toward a proven deny claim |
| Incomplete matrix | `containment.claim=incomplete` — not “proven” (D66) |

`network_probe` streams `log.kind=network_probe` / `finding.source=network` with the classification above.

## Canaries (D44 + D65)

| Requirement | Behavior |
|-------------|----------|
| Plant | On every create/replace, write randomized canary env/files (not real Killhub secrets) |
| Scan | After probes / before destroy, check for canary use or exfil indicators |
| Probe exclusion | Tag deliberate containment/canary probe sessions; exclude harness-owned probe IDs from unexpected-canary findings |
| Evidence | Unexpected hits → high-severity `finding.source=canary` + `containment` event; never log canary plaintext in SSE |

---

## Host-side reaper (D41)

| Concern | Behavior |
|---------|----------|
| Absolute expiry | Each sandbox records `expires_at` at create; host timer/process destroys when `now >= expires_at` |
| Survives Plane 1 death | Reaper runs on VX1 independently of the control-plane process |
| Touch | `msb touch` must not move `expires_at` |
| Orphans | Destroy sandboxes with no ledger job reference after Plane 1 reconciliation |

---

## Constraints

| Rule | Detail |
|------|--------|
| No Killhub secrets | Control-plane / inference keys **not** in sandbox `env` by default; canaries only (D44) |
| No install allowlist | Attempt profile commands; record failures — do not invent success (D29) |
| Network phases | Install egress → **deny-all remaining egress** for verify/containment (D43) |
| Copy paths | Helpers + per-job artifact dirs only; traversal/symlink/size enforced (D60) |
| Isolation | Separate kernel; **inter-sandbox network denied by default**; no Docker socket from control plane |
| Plane 2 ↛ Plane 1 | Explicit deny + positive-control probes in install **and** verify (D39, D65) |
| Resource caps | CPU/memory at create; wall clock + absolute `expires_at` |
| One VM | Explore + test are this same sandbox; replace keeps one live (D27, D36) |
| Destroy finally | Emit `lifecycle` on every path including failure/cancel/expiry (D49) |
| Non-root | Prefer non-root for exec inside the sandbox |

---

## What runs in the sandbox

| Intent | Typical workload |
|--------|------------------|
| `git_mcp` | Install MCP server; launch; **MCP handshake listing tools**; optional MCP Inspector/SDK when profile plans assessment (D35) |
| `webapp` | Install app; `run_commands`; HTTP healthcheck on `ports` |
| `demo` | Agent-invented minimal showcase (D34); `run_commands` + profile probe (typically HTTP) |

---

## Implementation phases

### T0 — Host + create / destroy + reaper

- [ ] VX1 host ready: kvm group, `msb` installed, `msb doctor` passes
- [ ] Harness `create_environment` → named sandbox with CPU/memory limits + network policy + canaries + `expires_at`
- [ ] `wait_until_ready` (guest running)
- [ ] `destroy_environment` in finally + Plane 1 orphan reaper + **host-side absolute expiry reaper** (D41); emit `lifecycle`
- [ ] Fail safely when host/KVM/quota unavailable

**Done when:** Harness can create and destroy a microsandbox for a job id; host reaper kills past `expires_at` without Plane 1.

### T1 — Remote exec + copy

- [ ] `exec` with stdout/stderr/exit_code + per-call timeouts
- [ ] `msb copy` (or SDK) for files in/out with **D60** allowlisted helpers / artifact dirs; reject traversal, symlink escape, oversized copies
- [ ] Confirm Killhub API keys absent from `env` inside the sandbox

**Done when:** Remote command runs and output returns to Plane 1; arbitrary host paths are rejected.

### T2 — Bootstrap + runtime provision (+ image replace)

- [ ] Map bootstrap → `MSB_DEFAULT_IMAGE`; map runtime `oci_image` / `os_image` / runtime → OCI
- [ ] Clone `source` inside the sandbox; persist **`resolved_commit`** (D62)
- [x] `replace_environment` when runtime image differs (D36); re-clone same SHA; inherit `expires_at`; log `sandbox_replace`; re-plant canaries; prior generation `replaced` without job-level `destroyed_at` (D64)
- [ ] Apply `install_commands` / packages / services with **install-phase egress**; **preinstall** assessment/browser/verify helpers (D63)
- [ ] Transition to **deny-all remaining egress** before readiness/containment (D43)
- [ ] Expose / bind ports as required for readiness

**Done when:** Fixture repo cloned under bootstrap at pinned commit; image-change path replaces once and reuses SHA; install attempted via runtime profile; tooling present before offline.

### T3 — Launch + readiness surface (+ optional MCP assessment / Playwright)

- [ ] Start MCP / webapp / demo processes per profile from **built checkout** when `original_application` (D62)
- [ ] Keep process alive for Plane 1 probes (`msb touch` only while `now < expires_at`)
- [ ] Capture failure logs (`msb logs`) for repair
- [ ] When `mcp.security_assessment.enabled`: run **preinstalled** MCP Inspector and/or SDK in-guest; return probe evidence to Plane 1 (D35, D63)
- [ ] Ship/run in-guest `mcp_stdio_verify` for `transport=stdio` via D60 `copy_in` (D51)
- [ ] Optional Playwright browser in-guest for HTTP stills (D38) — browsers preinstalled
- [ ] `copy_out` lockfiles to artifact dir for Plane-1 SCA

**Done when:** Plane 1 can complete MCP stdio or HTTP handshake (list tools) or HTTP healthcheck against the resolved commit; MCP assessment and in-guest screenshot paths work when enabled without post-offline installs.

### T4 — Hardening

- [ ] Sibling isolation evidence (`sibling_access_denied`) with live target + positive control (D65)
- [ ] Host-access deny + control-plane/management deny in **install and verify**; classify `policy_denied` vs infra (D39, D58, D65)
- [ ] Host-liveness check during adversarial probe (`host_liveness`) — timeout loop alone is not enough (D58)
- [ ] Deliberate probe traffic excluded from unexpected canary findings (D65)
- [ ] Mid-job cancel: freeze → finalizer receipt → destroy → terminal `cancelled` (D61); confirm-only job-level `destroyed_at`
- [ ] Absolute expiry destroy even if Plane 1 is down / touch is running
- [ ] No secret leakage in sandbox logs / metrics

**Done when:** Failed/cancelled/completed/expiry paths reclaim the microVM when confirmed; containment matrix complete with policy-vs-infra classification; Plane 2 cannot call Plane 1.

---

## Configuration (via Plane 1 harness)

| Variable | Purpose |
|----------|---------|
| `VULTR_API_KEY` | Host provisioning / ops only (Plane 1); **never** in sandboxes |
| `MSB_HOST` | How harness reaches the VX1 host running `msb` |
| `MSB_DEFAULT_IMAGE` | Bootstrap / discover OCI image (D36) |
| `MSB_DEFAULT_CPUS` / `MSB_DEFAULT_MEMORY` | Default resource caps |
| `MSB_NET_POLICY` / control-plane deny list | Egress policy inputs (D39) |
| `ENV_TTL_SECONDS` | Absolute `expires_at` base (not extended by touch) |
| `JOB_TIMEOUT_SECONDS` | Wall clock affecting sandbox lifetime |

---

## Milestones

- [ ] **T-M0:** Create + destroy microsandbox; host reaper
- [ ] **T-M1:** Remote exec (+ copy) with output
- [ ] **T-M2:** Bootstrap clone + runtime install + image replace
- [ ] **T-M3:** MCP/app launch reachable for readiness; optional in-guest Playwright
- [ ] **T-M4:** Cancel/completed/expiry always destroy; sibling + Plane 1 deny verified

---

## Out of scope

- UI / SSE (Plane 1)
- Plan loop / profile generation / vuln AI review (Plane 1 workers)
- Private registries / GPU / long-lived sandboxes beyond TTL
- A second “Explore VM” distinct from this sandbox
- Hosting CVE exploit / generic app/web pentest tooling aimed at the submitted application (sandbox is SCA + optional MCP assessment + containment target)

---

## Definition of done

From a bootstrap then runtime `environment_profile.json`, one Microsandbox microVM can be created (with Killhub network policy), optionally replaced on image change, used for inspect + install + launch/readiness (+ optional MCP assessment / in-guest Playwright / containment + network probes), and stopped/removed on `completed` / fail / cancel / absolute expiry — without Killhub secrets in the guest, without Plane 2 reaching Plane 1, and without weaponizing CVEs against the project.
