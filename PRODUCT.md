# PRODUCT.md — What we are building and why

## What

**Killhub** turns a **public GitHub repository URL** into a **verified running environment**:

1. User pastes a link in a Next.js app (input · status · report).
2. An **Explore Sandbox** runs an **Environment Agent Plan Loop** on the repo.
3. The agent writes a structured **`environment_profile.json`** (intent: `git_mcp` or `webapp`).
4. A disposable **Test VM** (Microsandbox microVM on Vultr VX1) is created from that profile; supported deps are installed.
5. MCP (or webapp) is launched and **readiness** is verified (repair loop, capped).
6. Known vulnerabilities are scanned and summarized.
7. Live **status, progress, screenshots**, profile, and reports stream back to the UI.

## Why

Standing up someone else’s repo is slow, brittle, and unsafe if done on a shared laptop or production host. Killhub exists to:

- **Understand** a repo before running it (inspect docs, infer services, validate a spec).
- **Isolate** execution on a short-lived Test VM (not the operator’s machine).
- **Prove** it works (readiness) and **surface risk** (vuln report) before humans dig in.
- **Show work** continuously (status + screenshots) so operators trust the automation.

## Who it is for

Operators, security-minded engineers, and internal teams who need to quickly and safely “bring up” public Git MCP servers or webapps from GitHub with a clear environment profile and audit trail.

## Success looks like

A user pastes a public GitHub URL and, without refreshing, sees:

- Live status and progress  
- A growing screenshot timeline  
- A validated `environment_profile.json`  
- MCP/webapp readiness  
- An AI-reviewed vulnerability report  

…while Killhub secrets never enter the Test VM, and the Microsandbox is destroyed when the agent finishes its instructions and all tests (or on TTL/cancel).

## Non-goals (v1)

- Private repos / OAuth  
- Multi-user auth / billing  
- Long-lived production hosting  
- GPU workloads  
- Auto-remediating vulnerabilities  
- Clouds other than Vultr for Test VMs  
- Full session video (stills only)

## Doc map

| Doc | Purpose |
|-----|---------|
| [AGENTS.md](AGENTS.md) | Rules every AI agent must follow |
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the platform is structured |
| [DECISIONS.md](DECISIONS.md) | Agreed technical decisions |
| [DATABASE.md](DATABASE.md) | Data model and rules |
| [API.md](API.md) | How components communicate |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | Implementation index by plane |
