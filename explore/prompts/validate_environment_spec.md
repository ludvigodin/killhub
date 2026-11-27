# Validate environment_profile (Killhub - trusted prompt only)

Killhub validates every draft runtime `environment_profile.json` deterministically (`validate_profile` plus a safety policy) before anything is persisted or executed. A profile that fails is discarded and the heuristic plan is used instead. Write profiles that will pass:

- `schema_version` is `"1"`.
- `intent` is `git_mcp` | `webapp` | `demo`.
- `source.commit` is a full 40-character SHA (Killhub overwrites it with the resolved commit).
- `git_mcp` requires `mcp.transport` (`stdio` | `streamable_http`), `mcp.launch_command`, `mcp.readiness.type=mcp_handshake`. `streamable_http` also requires `mcp.url` on loopback.
- `webapp` / `demo` require `probes` (HTTP, loopback only).
- CommandSpecs include `timeout_seconds` (1 to 3600) and `argv` or `shell`.
- Required arrays are always present: `services`, `packages`, `install_commands`, `run_commands`, `processes`, `ports`.
- `workdir` and every `cwd` live under the checkout root.
- No `npx -y` / `npx --yes` launches for `original_application`.
- No secrets, no `VULTR_*` / `OPENCODE_*`, no control-plane hosts in commands.
- Process `supervise` is `restart` or `oneshot`.
- Command `env` values are plain strings; names starting with `VULTR_`, `OPENCODE_`, `KILLHUB_`, `MSB_`, `KH_`, `LD_`, `DYLD_` are refused.

The draft is rejected (not repaired) when it breaks these rules, so keep it minimal and exact.
