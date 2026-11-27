# Step 17 — Status window UI (`noVNC` + live telemetry SSE) (N2, D49, D71)

**Goal:** Live status/progress/logs/telemetry and authenticated **view-only `noVNC`** stream without refresh; reconnect restores state via `event_cursor`; verify `routes.py:141-152` live `progress` hoisting fix.

## Prerequisites

- [05-jobs-proxy-admission.md](05-jobs-proxy-admission.md)
- [09-preflight.md](09-preflight.md) (baseline `explore/api/routes.py` live `progress` & poll-sleep fix)
- Prefer pipeline through [16-screenshots.md](16-screenshots.md) so `noVNC`, telemetry, and stills have live data

## Read first

- [IMPLEMENTATION_NEXTJS.md](../IMPLEMENTATION_NEXTJS.md) § N2
- [API.md](../API.md) — SSE types, `log.kind`s, `/novnc`, `/telemetry`, keep-alives (`D49`, `D50`, `D71`)
- [AGENTS.md](../AGENTS.md) § 5 (R2 inline docs + module frontmatter)

## Do

- [ ] Verify `explore/api/routes.py:141-152` hoists `progress` and `current_step` in the live-tailing SSE loop and does not stall 13–15s on empty polls
- [ ] Strongly type `frontend/lib/api.ts` (replace `[key: string]: unknown` with typed `JobSnapshot`, `DetonationVerdict`, `EnvironmentProfile`, `DynamicInstallSpec`, `TestScenarioPlan`, `NoVncInfo`, telemetry events)
- [ ] `StatusBadge` + `ProgressBar` + `current_step` (updating live from SSE `progress` events)
- [ ] `JobLiveView.tsx` + `TelemetryFeed.tsx`:
  - Subscribe to all v1 + `[v2]` SSE types (`status`, `progress`, `log`, `screenshot`, `error`, `span`, `finding`, `containment`, `lifecycle`, `gap`, `telemetry`, `tool_diff`, `kill_switch`, `novnc`)
  - Render `mitmdump` HTTP/S+DNS interceptions, DoH/DoT/QUIC drops, real-time canary blocks, `strace`, OverlayFS `upperdir`, MCP wire tap, cgroup v2, `tool_diff`, and 3-layer kill-switch alerts
- [ ] `NoVncViewer.tsx` + `frontend/app/api/jobs/[id]/novnc/route.ts`:
  - Render authenticated **view-only `noVNC`** iframe/canvas when `novnc.available === true` (`D71`)
  - Display clear "View-Only Live Detonation" badge; handle closed/destroyed state cleanly
- [ ] Tolerate SSE keep-alives without UI flicker (`D50`); render `gap` tombstone banner if pruned (`D67`)
- [ ] `ScreenshotTimeline` for optional Playwright stills (empty OK — `D31`)
- [ ] On load: snapshot + SSE reconnect with `Last-Event-ID` / `?after=` (`D55`)

## Do not

- Build the full `DetonationVerdict` / receipt report dossier UI here (step 19)
- Expose interactive VNC input controls or control-plane secrets in client bundles

## Lint gate (required before Done when)

Run the **full quality gate** ([LINT.md](LINT.md) — `D68`, `D74`) including R2 compliance:

```bash
cd frontend && pnpm lint:fix && pnpm lint && pnpm knip && pnpm typecheck && pnpm build
cd ../explore && ../.venv/bin/ruff check . && ../.venv/bin/ruff format --check . && ../.venv/bin/pytest -q
cd .. && python3 -c "import json; from pathlib import Path; from jsonschema import Draft202012Validator; [Draft202012Validator.check_schema(json.loads(p.read_text())) or print('OK', p.name) for p in sorted(Path('schemas').glob('*.json'))]"
```

Must exit **0**.

## Done when

Live status/progress, sensor telemetry, kill-switch/tool-diff alerts, and authenticated view-only `noVNC` update without refresh; leave/return restores via snapshot + SSE; full quality gate + R2 docs pass ([LINT.md](LINT.md)).

## Next

[18-vuln-receipt-finalize.md](18-vuln-receipt-finalize.md)
