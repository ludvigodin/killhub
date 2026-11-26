# AGENTS.md — Instructions every AI agent must follow

This file is binding for any AI agent (Cursor, OpenCode, CI bots, or the in-product Environment Agent) working on or inside Killhub.

Canonical product docs: [PRODUCT.md](PRODUCT.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [DECISIONS.md](DECISIONS.md) · [DATABASE.md](DATABASE.md) · [API.md](API.md)

---

## 1. Read before you change

1. Read [PRODUCT.md](PRODUCT.md) for *what* and *why*.
2. Read [ARCHITECTURE.md](ARCHITECTURE.md) for the three planes and boundaries.
3. Read [DECISIONS.md](DECISIONS.md) before introducing new tech or patterns.
4. Touch Plane 1 / 2 / 3 implementation only via the matching doc:
   - [IMPLEMENTATION_NEXTJS.md](IMPLEMENTATION_NEXTJS.md)
   - [IMPLEMENTATION_EXPLORE_SANDBOX.md](IMPLEMENTATION_EXPLORE_SANDBOX.md)
   - [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md)

Do not invent a fourth plane or collapse planes without updating architecture + decisions first.

---

## 2. Plane boundaries (hard rules)

| Plane | May | Must not |
|-------|-----|----------|
| **1 Next.js** | UI, job create/poll/SSE client, display profile/screenshots/vulns | Provision VMs, run agent tools, hold inference keys in the browser |
| **2 Explore Sandbox** | Plan loop, profile.json, harness, screenshots, vuln review, jobs/SSE | Mount Killhub secrets into the Test VM by default; exec on Plane 1 host for untrusted repo code |
| **3 Test VM** | Run allowlisted install/launch from profile inside a Microsandbox microVM on Vultr VX1 | Call Plane 1; store control-plane API keys; persist beyond job TTL |

- Untrusted repo code runs on **Plane 3** (or tightly scoped Explore Sandbox discovery), never as privileged Plane 1 server code.
- Only **supported** dependencies are provisioned; unsupported deps are flagged, not invented.

---

## 3. Environment Agent Plan Loop

When acting as the Environment Agent:

1. Inspect repo and docs  
2. Infer required services  
3. Validate environment and spec → write/update `environment_profile.json`  
4. Provision supported deps (via harness → Test VM)  
5. Launch MCP (or webapp) and verify readiness  

- Classify intent as `git_mcp` or `webapp` (v1).  
- Loop on failure only within `MAX_REPAIR_ATTEMPTS`.  
- Emit status, progress, logs, and screenshots to the job event stream for Plane 1.  
- Do not mark the job `ready` until readiness succeeds (vuln scan still required per product rules).

---

## 4. Security

- Never commit secrets (`.env`, API keys, tokens). Use env vars only.
- Never inject `VULTR_API_KEY` / `OPENCODE_*` into the Test VM environment by default.
- Redact secrets from logs and screenshots when possible.
- Public GitHub HTTPS URLs on `github.com` only in v1; reject others with `400`.
- Destroy Plane 3 sandboxes (Microsandbox stop + remove) when the Environment Agent finishes its instructions and all tests (`ready`), or on cancel, failure, or `ENV_TTL_SECONDS` / orphan reaper.

---

## 5. Code and docs hygiene

- Prefer changing the correct plane’s tree (`frontend/`, `explore/`, harness→VM) over cross-cutting hacks.
- Update [DECISIONS.md](DECISIONS.md) when you make a lasting technical choice.
- Update [API.md](API.md) / [DATABASE.md](DATABASE.md) when contracts or schemas change.
- Do not downgrade dependencies.
- Do not edit Expo `ios/` / `android/` or Podfiles (N/A for this repo; keep the project rule if present).
- Do not use the iOS/Android simulator for this project.

---

## 6. Communication back to Plane 1

Every meaningful step must update the job:

- `status`, `progress`, `current_step`
- SSE events: `status` | `progress` | `log` | `screenshot` | `error`
- Persist `environment_profile.json`, readiness, vuln report, screenshot metadata per [DATABASE.md](DATABASE.md)

Jobs are **server-owned**: client disconnect does not cancel the pipeline.

---

## 7. Out of scope (v1) — do not build unless PRODUCT/DECISIONS change

Private repos/OAuth · multi-user auth/billing · long-lived hosting beyond TTL · GPU · auto-patching CVEs · non-Vultr clouds · session video
