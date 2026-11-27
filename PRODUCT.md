# PRODUCT.md — What we are building and why

## What

**Killhub** is a Pattern A agent loop on Vultr: **plan → sandboxed execution → verifiable output → destroy**. It turns a **public git repository URL** (allowlisted hosts — GitHub, GitLab, Bitbucket, Codeberg) into a **verified running environment** plus an **intake dossier** (durable receipt of how it ran and what risk was found):

1. User pastes one or many public git URLs on the home **feed** (video-site entry grid · status · report) — or an MCP client calls the same Jobs API via the operator stdio MCP (D81).
2. Plane 1 runs **pre-flight** (URL, admission, cheap risk) before spending a sandbox when hard-fail applies.
3. The **control plane** (Next.js edge + Python `explore/` sidecar) runs an **Environment Agent Plan Loop**. The agent **proposes** how to demonstrate the repo and writes a **versioned executable** **`environment_profile.json`** (`git_mcp`, `webapp`, or `demo`); **deterministic gates** decide readiness and terminal outcomes from evidence. Invented demos are labeled `generated_demo` and must retain visible original setup failures.
4. A **single disposable Microsandbox** microVM on Vultr VX1 is created from a **bootstrap** image (with canary secrets + network policy), then provisioned from the discovered runtime profile (explore + test are the same sandbox; image replace keeps one live VM).
5. Install uses **phased egress** (registries/git) and preinstalls assessment tooling; verify/containment run with **deny-all remaining guest egress** (not merely registries-denied). The target is launched from the **resolved commit** and **readiness** is verified (repair loop, capped). MCP **stdio** uses an in-guest JSON-RPC helper (`initialize` → `tools/list`), not an HTTP ping. Readiness is evidence — not job completion and not a destroy trigger. SCA advisories are resolved from Plane 1 against copied lockfiles.
6. Known vulnerabilities are **scanned and summarized with citations** (SCA / advisories; best-effort on failure paths). Optional MCP Inspector/SDK assessment when planned. Killhub does **not** weaponize CVEs or run generic app/web exploit suites.
7. After bounded report generation, probes, artifact capture, and sandbox cleanup (**finally**), the job is **`completed`** (or `failed` / `cancelled`) with a durable **receipt**. Live status/progress/evidence stream to the UI; screenshots when useful (optional — never gate completion).
8. **Containment / network / canary probes** demonstrate isolation and that Plane 2 cannot call Plane 1 (not CVE exploitation).

## Why

Standing up someone else’s repo is slow, brittle, and unsafe if done on a shared laptop or production host — and a chat agent that only describes a run is not proof. Killhub exists to:

- **Plan** how to demonstrate the repo (inspect docs, infer services, write an executable profile).
- **Execute in a sandbox** on a short-lived Microsandbox (not the operator’s machine).
- **Return verifiable output** (readiness, optional stills, containment absorption) and **surface risk** (cited SCA; optional MCP assessment) before humans dig in.
- **Destroy** the VM and **leave a receipt** — profile, probes, findings, lifecycle — that outlives the sandbox.
- **Show work** continuously (structured events + optional stills) so operators trust the automation.

## Who it is for

Operators, security-minded engineers, and internal teams who need to quickly and safely “bring up” (or invent a minimal demo of) public git repos — MCP servers, webapps, or oddball content — with a clear environment profile and audit trail.

## Success looks like

A user pastes public git URL(s) into the home feed and, without refreshing, sees the Pattern A loop for each job:

- **Plan** — live status/progress plus a validated `environment_profile.json`  
- **Sandboxed execution** — bootstrap create → optional image replace → clone/install/launch in one disposable microVM  
- **Verifiable output** — MCP handshake / HTTP (or other profile) readiness with an honest label (`original_application` · `generated_demo` · `setup_failed`); optional screenshots; containment absorption  
- **Destroy** — sandbox **destroyed** only when removal is confirmed; durable **receipt** (cited SCA separate from other findings) outlives the VM  

…while Killhub secrets never enter the sandbox (canaries only), OpenCode cannot shell the control plane, Plane 2 cannot call Plane 1, adversarial probes stay contained, and the sandbox is destroyed on job completion / fail / cancel / absolute expiry (even if the control plane restarts).

The public demo is **[https://killhub.pro](https://killhub.pro)** — control plane on **Vultr Cloud Compute** (app on localhost behind a reverse proxy), agent reasoning via **Vultr Serverless Inference**, execution in Microsandbox on VX1 — behind admission limits and a durable job ledger.

## v1 golden fixtures

Pinned commit SHAs live in [explore/fixtures/m7.json](explore/fixtures/m7.json) ([DECISIONS.md](DECISIONS.md) D53).

| Intent / outcome | Public repo |
|------------------|-------------|
| `webapp` → `original_application` | [heroku/nodejs-getting-started](https://github.com/heroku/nodejs-getting-started) @ pin (alias: `node-js-getting-started`) |
| `git_mcp` → filesystem server (stdio) | [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) @ pin + fixed filesystem entrypoint |
| Controlled `setup_failed` + SCA | Deliberately broken fixture (not NodeGoat); dependency advisories via lockfile SCA, separate from intentional app vulns |

## Non-goals (v1)

- Private repos / OAuth  
- Multi-user auth / billing  
- Long-lived **customer** environments / production hosting beyond job TTL (**[killhub.pro](https://killhub.pro)** on Vultr is the in-scope public control-plane demo)  
- GPU workloads  
- Auto-remediating vulnerabilities  
- Weaponizing CVEs / generic app/web pentest exploit suites (SCA + report always; optional MCP Inspector/SDK assessment only when the agent plans it — D35; containment probes are separate)  
- Clouds other than Vultr for the demo control plane or sandboxes  
- Alternate LLM providers for the Environment Agent  
- Full session video (stills only when captured)  
- Separate Explore VM vs Test VM  
- Install allowlist that blocks commands Microsandbox can run (attempt + flag failures instead)

## Doc map

| Doc | Purpose |
|-----|---------|
| [AGENTS.md](AGENTS.md) | Rules every AI agent must follow (quality gate + Vultr tooling) |
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the platform is structured |
| [DECISIONS.md](DECISIONS.md) | Agreed technical decisions |
| [DATABASE.md](DATABASE.md) | Data model and rules |
| [API.md](API.md) | How components communicate |
| [README.md](README.md) | Repo entry + quick start |
| [explore/fixtures/m7.json](explore/fixtures/m7.json) | Pinned M7 fixture SHAs (D53) |
