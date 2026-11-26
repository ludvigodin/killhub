# PRODUCT.md — What we are building and why

## What

**Killhub** turns a **public GitHub repository URL** into a **verified running environment**:

1. User pastes a link in a Next.js app (input · status · report).
2. The **control plane** (Next.js + agent/harness) runs an **Environment Agent Plan Loop**.
3. The agent writes a structured **`environment_profile.json`** (intent: `git_mcp` or `webapp`).
4. A **single disposable Microsandbox** microVM on Vultr VX1 is created for that job (explore + test are the same sandbox); deps are installed from the profile.
5. MCP (or webapp) is launched and **readiness** is verified (repair loop, capped). For `git_mcp`, readiness is a real MCP handshake that can list tools.
6. Known vulnerabilities are scanned and summarized (including best-effort scan on failure paths).
7. Live **status and progress** stream back to the UI; **screenshots when useful** (optional — never gate readiness).

## Why

Standing up someone else’s repo is slow, brittle, and unsafe if done on a shared laptop or production host. Killhub exists to:

- **Understand** a repo before trusting it (inspect docs, infer services, validate a spec).
- **Isolate** execution on a short-lived Microsandbox (not the operator’s machine).
- **Prove** it works (readiness) and **surface risk** (vuln report) before humans dig in.
- **Show work** continuously (status + optional stills) so operators trust the automation.

## Who it is for

Operators, security-minded engineers, and internal teams who need to quickly and safely “bring up” public Git MCP servers or webapps from GitHub with a clear environment profile and audit trail.

## Success looks like

A user pastes a public GitHub URL and, without refreshing, sees:

- Live status and progress  
- A validated `environment_profile.json`  
- **Verifiable execution** — MCP handshake / webapp readiness (or a clear failed probe), not a chat description of work  
- Sandbox lifecycle signals (create → work → **destroyed**)  
- An AI-reviewed vulnerability report  
- Screenshots when they add signal (HTTP verify); not required for every job  

…while Killhub secrets never enter the sandbox, adversarial probes stay contained in the Microsandbox, and the sandbox is destroyed when the agent finishes its instructions and all tests (or on TTL/cancel).

Public demos run the control plane on **Vultr Cloud Compute** with agent reasoning via **Vultr Serverless Inference** and execution in Microsandbox on VX1.

## v1 golden fixtures

| Intent / outcome | Public repo |
|------------------|-------------|
| `webapp` success | [heroku/node-js-getting-started](https://github.com/heroku/node-js-getting-started) |
| `git_mcp` success | [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) |
| Fail + vulnerabilities | [OWASP/NodeGoat](https://github.com/OWASP/NodeGoat) (expect readiness fail without durable Mongo within caps; still emit vuln findings) |

## Non-goals (v1)

- Private repos / OAuth  
- Multi-user auth / billing  
- Long-lived **customer** environments / production hosting beyond job TTL (a publicly reachable control-plane demo on Vultr is in scope)  
- GPU workloads  
- Auto-remediating vulnerabilities  
- Clouds other than Vultr for the demo control plane or sandboxes  
- Alternate LLM providers for the Environment Agent  
- Full session video (stills only when captured)  
- Separate Explore VM vs Test VM  
- Install allowlist that blocks commands Microsandbox can run (attempt + flag failures instead)

## Doc map

| Doc | Purpose |
|-----|---------|
| [AGENTS.md](AGENTS.md) | Rules every AI agent must follow |
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the platform is structured |
| [DECISIONS.md](DECISIONS.md) | Agreed technical decisions |
| [DATABASE.md](DATABASE.md) | Data model and rules |
| [API.md](API.md) | How components communicate |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | Implementation index by plane |
