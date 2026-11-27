# Validate environment_profile (Killhub — trusted prompt only)

Validate the draft runtime `environment_profile.json`:

- `schema_version` is `"1"`.
- `intent` is `git_mcp` | `webapp` | `demo`.
- `source.commit` is a full 40-character SHA.
- `git_mcp` requires `mcp.transport` (`stdio` | `streamable_http`), `launch_command`, and `readiness.type=mcp_handshake`.
- `webapp` / `demo` require probes or healthcheck.
- CommandSpecs include `timeout_seconds` and `argv` or `shell`.
- Reject profiles that would prove readiness via unpinned `npx -y` / equivalent for `original_application`.

Return either `{ "ok": true, "profile": {…} }` or `{ "ok": false, "errors": ["…"] }`.
