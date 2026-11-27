# Vultr tooling — MCP + CLI (required)

When a plan step touches Vultr fabric or Plane 2 sandboxes, **use official Vultr / Microsandbox MCP or CLI**. Do not invent alternate clouds, fake sandboxes with Docker-on-the-control-plane, or hand-wave host setup.

Canonical product rules: [DECISIONS.md](../DECISIONS.md) D22, D23, D24, D25, **D59**.

---

## Tool matrix

| Need | Prefer | Fallback | Must not |
|------|--------|----------|----------|
| **Inventory / inspect** Vultr account, instances, regions, plans | **Vultr MCP** (`https://mcp.vultr.com/mcp`, OAuth, read-only) | `vultr-cli` read commands | Guess instance IDs or SSH into random hosts |
| **Mutate** Cloud Compute (create/resize/firewall/SSH keys for demo or VX1 host) | **`vultr-cli`** (API key on operator machine / CI secret) | Vultr API HTTPS with `VULTR_API_KEY` | Non-Vultr providers; “local Docker = Plane 2” |
| **Plane 2 sandbox lifecycle** (create / exec / copy / stop / remove / logs / doctor) | **`msb` CLI** on the VX1 host; harness wraps CLI or official Microsandbox **SDK** | **`microsandbox-mcp`** (`npx -y microsandbox-mcp`) for agent-assisted debug **only** if D38 allows that MCP in the trusted config | Docker/Podman as a stand-in for Microsandbox; mocking `msb` success |
| **Inference** | Vultr Serverless Inference HTTPS (`https://api.vultrinference.com/v1`) | — | Alternate LLM providers (D25) |

---

## How building agents should work

1. **Before** sandbox steps (06+): confirm VX1 / `msb` via `msb doctor` (CLI) or Microsandbox MCP `runtime_check`. Confirm the host exists via **Vultr MCP** or `vultr-cli instance list`.
2. **Harness code** in Killhub must call **`msb` / SDK** (D23) — not a homemade hypervisor. MCP is for *operators/agents building and debugging*; the durable product path is harness → `msb`.
3. **Demo deploy (step 20):** provision/inspect the control-plane VM with Vultr MCP (read) + `vultr-cli` (write). Public hostname **[killhub.pro](https://killhub.pro)**. Do not deploy Killhub demos off Vultr (D24).
4. **If MCP or CLI is unavailable:** **stop and report**. Do not mark the step done with a simulated Plane 2.
5. **Secrets:** `VULTR_API_KEY` / inference keys stay on Plane 1 / operator env — never injected into sandboxes (D19).

---

## Quick references

- Vultr MCP getting started: https://docs.vultr.com/reference/mcp-server/getting-started  
- Agent sandboxing on VX1 (`msb`): https://docs.vultr.com/how-to-set-up-agent-sandboxing-on-vultr-cloud-compute  
- `vultr-cli`: https://docs.vultr.com/platform/getting-started/vultr-cli  
- Microsandbox MCP: `npx -y microsandbox-mcp` (stdio)

---

## Per-step expectation

| Steps | Tooling |
|------:|---------|
| 01–05 | No Plane 2 required; optional Vultr MCP only if checking account |
| 06–08, 11–16, 18 | **`msb` CLI/SDK** required; Vultr MCP/`vultr-cli` to locate/verify VX1 |
| 10 | Vultr Inference API only (D25); verify with real call or fail closed |
| 20 | Vultr MCP + `vultr-cli` for demo host; `msb` for fixture sandboxes |
