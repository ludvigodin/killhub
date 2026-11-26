# AGENTS.md — Instructions every AI agent must follow

This file is binding for any AI agent (Cursor, OpenCode, CI bots, or the in-product Environment Agent) working on or inside Killhub.

Canonical product docs: [PRODUCT.md](PRODUCT.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [DECISIONS.md](DECISIONS.md) · [DATABASE.md](DATABASE.md) · [API.md](API.md)

---

## 1. Read before you change

1. Read [PRODUCT.md](PRODUCT.md) for *what* and *why*.
2. Read [ARCHITECTURE.md](ARCHITECTURE.md) for the **two planes** and boundaries.
3. Read [DECISIONS.md](DECISIONS.md) before introducing new tech or patterns.
4. Touch implementation only via the matching doc:
   - [IMPLEMENTATION_NEXTJS.md](IMPLEMENTATION_NEXTJS.md) — Plane 1 UI + Jobs API/SSE
   - [IMPLEMENTATION_EXPLORE_SANDBOX.md](IMPLEMENTATION_EXPLORE_SANDBOX.md) — Plane 1 agent/harness workers (`explore/`)
   - [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md) — Plane 2 disposable Microsandbox

Do not invent a third durable plane or split explore/test into two VMs without updating architecture + decisions first ([DECISIONS.md](DECISIONS.md) D27–D28).

---

## 2. Plane boundaries (hard rules)

| Plane | May | Must not |
|-------|-----|----------|
| **1 Control plane** (Next.js + `explore/` workers) | UI; **own** job create/poll/SSE; Environment Agent Plan Loop; harness; screenshots/vuln review; hold inference keys **server-side** | Put secrets in the browser; execute untrusted repo install/run on the control-plane host; inject Killhub secrets into the sandbox by default |
| **2 Disposable Microsandbox** | Clone, install, launch, readiness target, vuln scan target, containment probes — **one microVM per job** for both explore and test | Call Plane 1; store control-plane API keys; persist beyond job TTL |

- Untrusted repo code runs only on **Plane 2**, never as privileged control-plane host processes.
- **No install allowlist** (D29): attempt profile install/run commands; **flag failures**, do not invent success.
- Explore and Test are **not** separate VMs — same disposable sandbox (D27).

---

## 3. Environment Agent Plan Loop

When acting as the Environment Agent:

1. Inspect repo and docs (via sandbox clone/copy/exec — not privileged host exec of untrusted code)  
2. Infer required services  
3. Validate environment and spec → write/update `environment_profile.json`  
4. Provision deps (via harness → same disposable sandbox)  
5. Launch MCP (or webapp) and verify readiness  

- Classify intent as `git_mcp` or `webapp` (v1).  
- **`git_mcp` ready** = MCP handshake that can list tools (D30).  
- Loop on failure only within `MAX_REPAIR_ATTEMPTS`.  
- Emit status, progress, logs, and **optional** screenshots to the job event stream.  
- Do not mark the job `ready` until readiness succeeds (vuln **scan** still required per product rules). Screenshots must not gate `ready` (D31).
- **Vulns:** SCA / advisory scan + `vuln_review` only. Do **not** run exploits or pentest the submitted project (D33). Containment probes (D26) prove isolation only.

---

## 4. Security

- Never commit secrets (`.env`, API keys, tokens). Use env vars only.
- Never inject `VULTR_API_KEY` / `VULTR_INFERENCE_*` / `OPENCODE_*` into the sandbox environment by default.
- Redact secrets from logs and screenshots when possible.
- Public GitHub HTTPS URLs on `github.com` only in v1; reject others with `400`.
- Destroy Plane 2 sandboxes (Microsandbox stop + remove) when the Environment Agent finishes its instructions and all tests (`ready`), or on cancel, failure, or `ENV_TTL_SECONDS` / orphan reaper.
- **Inference:** Environment Agent LLM calls must go through **Vultr Serverless Inference** (`https://api.vultrinference.com/v1`) only ([DECISIONS.md](DECISIONS.md) D25). Do not add alternate providers without a new decision.
- **Containment:** Adversarial / containment probes run only inside Plane 2; stream create/probe/destroy evidence to the job stream ([DECISIONS.md](DECISIONS.md) D26).
- **Demo deploy:** Public control-plane demos run on **Vultr Cloud Compute**, not non-Vultr hosts, unless [DECISIONS.md](DECISIONS.md) is updated (D24).

---

## 5. Code and docs hygiene

- Prefer changing the correct tree (`frontend/`, `explore/`, harness→sandbox) over cross-cutting hacks.
- Update [DECISIONS.md](DECISIONS.md) when you make a lasting technical choice.
- Update [API.md](API.md) / [DATABASE.md](DATABASE.md) when contracts or schemas change.
- Do not downgrade dependencies.
- Do not edit Expo `ios/` / `android/` or Podfiles (N/A for this repo; keep the project rule if present).
- Do not use the iOS/Android simulator for this project.

---

## 6. Communication on the job stream

Every meaningful step must update the job:

- `status`, `progress`, `current_step`
- SSE events: `status` | `progress` | `log` | `screenshot` | `error`
- Persist `environment_profile.json`, readiness, vuln report, optional screenshot metadata, and sandbox lifecycle fields (`sandbox_id`, `destroyed_at`, `inference_model`) per [DATABASE.md](DATABASE.md)
- Log sandbox **create**, repair **attempt n**, containment probe results, and **destroy**

Jobs are **server-owned** (Plane 1): client disconnect does not cancel the pipeline.

---

## 7. Out of scope (v1) — do not build unless PRODUCT/DECISIONS change

Private repos/OAuth · multi-user auth/billing · long-lived customer envs beyond TTL · GPU · auto-patching CVEs · non-Vultr clouds for demo control plane or sandboxes · alternate agent LLM providers · session video · separate Explore VM vs Test VM
