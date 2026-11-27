# Vultr tooling — MCP + CLI + Host Proxy & VX1 Prerequisites (required)

When a plan step touches Vultr fabric, Serverless Inference, or Plane 2 sandboxes, **use official Vultr / Microsandbox MCP, `vultr-cli`, or `msb`**. Do not invent alternate clouds, fake sandboxes with Docker-on-the-control-plane, or hand-wave host setup.

Canonical product rules: [DECISIONS.md](../DECISIONS.md) D22, D23, D24, D25, **D59**, **D69**–**D74**.

---

## Tool matrix

| Need | Prefer | Fallback | Must not |
|------|--------|----------|----------|
| **Inventory / inspect** Vultr account, instances, regions, plans | **Vultr MCP** (`https://mcp.vultr.com/mcp`, OAuth, read-only) | `vultr-cli` read commands | Guess instance IDs or SSH into random hosts |
| **Mutate** Cloud Compute (create/resize/firewall/SSH keys for demo or VX1 host) | **`vultr-cli`** (API key on operator machine / CI secret) | Vultr API HTTPS with `VULTR_API_KEY` | Non-Vultr providers; “local Docker = Plane 2” |
| **Plane 2 sandbox lifecycle** (create / exec / copy / stop / remove / logs / doctor) | **`msb` CLI** on the VX1 host; harness wraps CLI or official Microsandbox **SDK** | **`microsandbox-mcp`** (`npx -y microsandbox-mcp`) for agent-assisted debug **only** if D38 allows that MCP in the trusted config | Docker/Podman as a stand-in for Microsandbox; mocking `msb` success |
| **Inference (Plane 1 planners/reviewers + Host LLM Proxy)** | **Vultr Serverless Inference** HTTPS (`https://api.vultrinference.com/v1`) using per-role env vars (`VULTR_INFERENCE_MODEL_PLANNER` / `_TESTER` / `_VICTIM` / `_REVIEW`, fallback `VULTR_INFERENCE_MODEL` — D74) | — | Alternate LLM providers (D25); injecting `VULTR_INFERENCE_API_KEY` into Plane 2 (D71) |

---

## VX1 & Control-Plane Host Prerequisites (`D69`–`D72`)

1. **VX1 Host (Plane 2 runtime):**
   - Ubuntu 24.04 with `/dev/kvm`, `msb` + `libkrunfw` (`msb doctor` green).
   - Kernel & userspace support for **OverlayFS**, **cgroup v2** (`memory`, `pids`, `cpu` controllers delegated for Layer 2 `512M`/`0`/`64`/`100000 100000` caps), **`AF_VSOCK`** (with UDS/`mgmt0` fallback), **host TAP bridge + `iptables`/`nftables`** (DoH/DoT/QUIC drop + Phase 1/2a/2b transitions), **`mitmdump`** (transparent HTTP/S + DNS interception), and optional **`tcpdump`**.
   - Pre-baked Ubuntu 24.04 detonation base image (`ubuntu-24.04-killhub`: `python`, `pip`, `uv`, Node 22+, `git`, `strace`, `OpenCode`, `@modelcontextprotocol/inspector`, `noVNC`/Xvfb/VNC, `mitmproxy` root CA).
2. **Plane 1 Host & Reverse Proxy (`D46`, `D71`):**
   - Plane 1 apps (`frontend`, `explore`, Host LLM Proxy, authenticated view-only `noVNC` proxy) bind **`127.0.0.1`**.
   - Edge reverse proxy (Caddy/nginx) terminates public HTTPS, flushes **SSE** (`/api/jobs/{id}/events`), proxies authenticated **view-only `noVNC` WebSockets** (`/api/jobs/{id}/novnc`), and overwrites `X-Real-IP` / `X-Forwarded-For` from the socket peer IP (`ALIGNMENT_PLAN.md` S8).
   - **Host LLM Proxy** (`/internal/llm-proxy/v1/chat/completions`) listens strictly on `AF_VSOCK`/UDS/`mgmt0`, accepts only the per-job ephemeral dummy bearer token from in-VM OpenCode, injects `VULTR_INFERENCE_API_KEY` exclusively on Plane 1 outbound calls to `https://api.vultrinference.com/v1`, and enforces Layer 1 circuit-breaker caps (`max_turns=12`, `max_tokens=60000`, oscillation→`429`).

---

## How building agents should work

1. **Before** sandbox steps (06+): confirm VX1 / `msb` via `msb doctor` (CLI) or Microsandbox MCP `runtime_check`, plus TAP/`mitmdump`/cgroup v2/OverlayFS readiness. Confirm the host exists via **Vultr MCP** or `vultr-cli instance list`.
2. **Harness code** in Killhub must call **`msb` / SDK** (`D23`) — not a homemade hypervisor. MCP is for *operators/agents building and debugging*; the durable product path is harness → `msb`.
3. **Demo deploy (step 20):** provision/inspect the control-plane VM with Vultr MCP (read) + `vultr-cli` (write). Do not deploy Killhub demos off Vultr (`D24`).
4. **If MCP or CLI is unavailable:** **stop and report**. Do not mark the step done with a simulated Plane 2.
5. **Secrets:** `VULTR_API_KEY` / `VULTR_INFERENCE_API_KEY` stay on Plane 1 / operator env — **never** injected into Plane 2 sandboxes (`D19`, `D71`).

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
| 06–08, 11–16, 18 | **`msb` CLI/SDK** + TAP/`mitmdump`/cgroup v2/OverlayFS/`AF_VSOCK` on VX1; Vultr MCP/`vultr-cli` to locate/verify VX1 |
| 10 | **Vultr Serverless Inference** (`VULTR_INFERENCE_MODEL_*`) + Plane 1 Host LLM Proxy (`D25`, `D71`, `D74`); verify with real call or fail closed |
| 20 | Vultr MCP + `vultr-cli` for demo host + reverse proxy (`noVNC` WS + SSE); `msb` for 3 baseline + 6 demo fixtures |
