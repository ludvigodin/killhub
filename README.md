# Killhub

**Paste a public GitHub URL. Get a verified running environment — and a receipt that outlives the sandbox.**

**Try it live → [https://killhub.pro](https://killhub.pro)**

Killhub stands up someone else’s repo the way you’d want a security-minded operator to: understand first, isolate always, prove readiness, surface known risk, then destroy the machine.

Built on **Vultr** end-to-end — Cloud Compute control plane, [Serverless Inference](https://docs.vultr.com/products/serverless/inference/provisioning) for the agent, [Microsandbox](https://docs.vultr.com/how-to-set-up-agent-sandboxing-on-vultr-cloud-compute) microVMs for untrusted code.

---

## Try Killhub

1. Open **[killhub.pro](https://killhub.pro)**
2. Paste a **public** `https://github.com/...` URL
3. Watch live status, readiness evidence, and the intake receipt — then the disposable sandbox is destroyed

Public demo is anonymous and admission-limited (rate / concurrency / queue). Prefer small getting-started or MCP repos for a first run.

---

## The problem

Bringing up a stranger’s GitHub repo is slow, brittle, and unsafe on a shared laptop or production host.

```mermaid
flowchart LR
  A["Public GitHub repo"] --> B{"Run it where?"}
  B -->|"Your laptop"| C["Risk · pollution · no audit trail"]
  B -->|"Shared host"| D["Blast radius · secret leakage"]
  B -->|"Killhub"| E["Isolated microVM · readiness · receipt"]
  style E fill:#1a7f37,color:#fff
  style C fill:#cf222e,color:#fff
  style D fill:#cf222e,color:#fff
```

Killhub exists so you can **understand**, **isolate**, **prove**, and **leave a dossier** — without trusting the repo with your keys or your machine.

---

## What you get

| Outcome | Meaning |
|---------|---------|
| **Live job** | Status, progress, structured evidence — no refresh required |
| **`environment_profile.json`** | Versioned plan: how Killhub decided to demo the repo |
| **Honest label** | `original_application` · `generated_demo` · `setup_failed` |
| **Readiness evidence** | MCP handshake (`tools/list`) or HTTP / profile probe |
| **Intake receipt** | Cited SCA findings (+ optional MCP assessment when planned) |
| **Containment proof** | Isolation probes absorbed inside the sandbox — then destroy |

Screenshots appear when they add signal. They never gate completion.

---

## How it works

One public URL in. One disposable microVM. One durable receipt out.

```mermaid
flowchart TB
  U["Paste public GitHub URL"] --> P["Pre-flight<br/>URL · admission · cheap risk"]
  P --> V["Bootstrap Microsandbox on VX1"]
  V --> A["Environment Agent inspect / discover<br/>OpenCode → Vultr Inference"]
  A --> F["runtime environment_profile.json<br/>git_mcp · webapp · demo"]
  F --> I["Phased install · launch · readiness"]
  I --> S["SCA scan · optional MCP assessment"]
  S --> R["Receipt · destroy sandbox · terminal status"]
  R --> UI["UI: profile · evidence · report"]
```

Bootstrap comes **before** runtime-profile discovery ([DECISIONS.md](DECISIONS.md) D36).

**Jobs are server-owned.** Close the tab — the pipeline keeps running. Reopen `/jobs/{id}` to resume. Only cancel or timeout stops a job.

---

## Architecture at a glance

Two planes. Hard boundary. Secrets stay on the control plane.

```mermaid
flowchart TB
  subgraph plane1 ["Plane 1 · Control plane"]
    UI["Next.js UI"]
    API["Jobs API + SSE"]
    Agent["Environment Agent"]
    Harness["Harness"]
    Ledger["Durable ledger"]
  end

  subgraph plane2 ["Plane 2 · Disposable Microsandbox"]
    VM["One microVM per job"]
    Work["Clone · install · launch · readiness"]
  end

  UI --> API
  API --> Agent
  Agent --> Harness
  Harness -->|"msb create / exec / destroy"| VM
  Work --> Harness
  Harness --> API
  API --> Ledger
```

| Plane | What it is | Owns |
|------:|------------|------|
| **1** | Next.js + `explore/` workers on Vultr Cloud Compute | UI, Jobs API/SSE, plan loop, harness, vuln review, secrets |
| **2** | One Microsandbox microVM per job on VX1 | Untrusted clone/install/run — explore and test share the same VM |

There is **no** separate Explore VM vs Test VM.

### Trust zones

```mermaid
flowchart LR
  subgraph Z0["Internet"]
    Browser["Operator browser"]
  end
  subgraph Host["Vultr fabric"]
    Edge["Reverse proxy"]
    CP["Control plane<br/>+ ledger + keys"]
    SB["Disposable sandbox"]
  end
  subgraph Ext["External"]
    Inf["Vultr Inference"]
    GH["GitHub"]
    Reg["Registries"]
  end

  Browser --> Edge --> CP
  CP --> Inf
  CP --> GH
  CP -->|"msb + net policy"| SB
  SB -.->|"install phase only"| Reg
  CP -.->|"secrets never injected"| SB
```

Sandbox → control plane is **denied**. Real Killhub secrets never enter the guest (canaries only).

---

## Job lifecycle

```mermaid
stateDiagram-v2
  [*] --> pending
  pending --> queued
  queued --> analyzing
  analyzing --> planning
  planning --> provisioning
  provisioning --> installing
  installing --> verifying
  verifying --> repairing: probe fails
  repairing --> verifying: retry ≤ MAX_REPAIR_ATTEMPTS
  verifying --> scanning: ready evidence
  scanning --> finalizing
  finalizing --> completed
  verifying --> failed: repairs exhausted
  pending --> cancelled
  analyzing --> cancelled
  installing --> cancelled
  completed --> [*]
  failed --> [*]
  cancelled --> [*]
```

Readiness is **evidence**, not a destroy trigger. The sandbox dies on `completed` / fail / cancel / absolute TTL — even if the control plane restarts.

---

## Security story (in one picture)

```mermaid
flowchart TB
  subgraph yes ["In scope"]
    SCA["SCA / advisories with citations"]
    MCP["Optional MCP Inspector/SDK when planned"]
    CONT["Containment + network + canary probes"]
  end
  subgraph no ["Out of scope"]
    EXP["Weaponize CVEs"]
    PEN["Generic app/web exploit suites"]
    PATCH["Auto-patch / remediate"]
  end
```

Untrusted code never runs as a privileged control-plane process. OpenCode only sees harness tools. Plane 2 network policy is probe-tested.

---

## Vultr-native stack

| Layer | Where |
|-------|-------|
| Public demo | **[https://killhub.pro](https://killhub.pro)** — Vultr Cloud Compute behind HTTPS reverse proxy (app on `127.0.0.1`) |
| Agent reasoning | Vultr Serverless Inference (`api.vultrinference.com`) |
| Untrusted execution | Microsandbox on Vultr VX1 — one microVM per job |
| Local dev | `docker-compose` for Plane 1; sandboxes still provisioned on VX1 |

---

## Golden fixtures (v1)

Pinned commits live in fixture config ([DECISIONS.md](DECISIONS.md) D53).

| Outcome | Repo |
|---------|------|
| `webapp` → `original_application` | [heroku/node-js-getting-started](https://github.com/heroku/node-js-getting-started) |
| `git_mcp` filesystem (stdio) | [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) |
| Controlled `setup_failed` + SCA | Deliberately broken fixture (not NodeGoat) |

---

## Who it’s for

Operators, security-minded engineers, and internal teams who need to quickly and safely bring up — or invent a minimal demo of — public GitHub repos (MCP servers, webapps, oddball content) with a clear environment profile and audit trail.

---

## Quick start

**Use the product:** [https://killhub.pro](https://killhub.pro)

**Hack on the repo:**

1. Read [PRODUCT.md](PRODUCT.md) — *what* and *why*
2. Read [ARCHITECTURE.md](ARCHITECTURE.md) — planes, trust zones, lifecycle
3. Follow [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) — build order by plane
4. Copy [`.env.example`](.env.example) → `.env` (never commit secrets)

---

## Docs & roadmap

| Doc | Purpose |
|-----|---------|
| [PRODUCT.md](PRODUCT.md) | Product intent |
| [AGENTS.md](AGENTS.md) | Rules for AI agents working in this repo |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Two planes, trust zones, data flow |
| [DECISIONS.md](DECISIONS.md) | Locked technical choices |
| [DATABASE.md](DATABASE.md) | Job / receipt model |
| [API.md](API.md) | Jobs API + SSE contracts |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | Milestone index |
| [IMPLEMENTATION_NEXTJS.md](IMPLEMENTATION_NEXTJS.md) | Plane 1 UI + Jobs API |
| [IMPLEMENTATION_EXPLORE_SANDBOX.md](IMPLEMENTATION_EXPLORE_SANDBOX.md) | Plane 1 agent / harness |
| [IMPLEMENTATION_TEST_VM.md](IMPLEMENTATION_TEST_VM.md) | Plane 2 Microsandbox |

```mermaid
flowchart LR
  M0["M0 Plane 1 boots"] --> M1["M1 Jobs + SSE"]
  M1 --> M2["M2 Harness lifecycle"]
  M2 --> M3["M3 Profile"]
  M3 --> M4["M4 Readiness"]
  M4 --> M5["M5 Screenshots"]
  M5 --> M6["M6 Vuln report"]
  M6 --> M6b["M6b Containment"]
  M6b --> M7["M7 Fixtures + isolation"]
```

### API surface

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/jobs` | Create `{ github_url }` → `{ job_id }` |
| `GET` | `/api/jobs/{id}` | Snapshot |
| `GET` | `/api/jobs/{id}/events` | SSE stream |
| `GET` | `/api/jobs/{id}/screenshots` | Timeline (may be empty) |
| `DELETE` | `/api/jobs/{id}` | Cancel + destroy |
| `GET` | `/health` | Liveness |

Full contracts: [API.md](API.md). Config and admission caps: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

---

## Out of scope (v1)

Private repos / OAuth · multi-user billing · long-lived customer sandboxes · GPU · auto-patch CVEs · weaponizing exploits · non-Vultr clouds · alternate agent LLM providers · session video · separate Explore vs Test VM · install allowlists that block runnable commands

---

## Definition of done

On **[killhub.pro](https://killhub.pro)** (or a local control plane), a user pastes a public GitHub URL and, without refreshing, sees live status, a validated profile, verifiable readiness with an honest label, and a cited intake receipt — while one Microsandbox absorbs the work and is destroyed on completion, with Killhub secrets never entering the guest.
