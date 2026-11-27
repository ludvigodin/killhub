#!/bin/sh
# Presence probe for Killhub assessment/verify tooling (D63).
set -eu
missing=0
for p in \
  /opt/killhub/helpers/mcp_stdio_verify.py \
  /opt/killhub/helpers/tooling_probe.sh \
  /opt/killhub/helpers/screenshot_capture.py
do
  if [ ! -f "$p" ]; then
    echo "missing:$p"
    missing=1
  fi
done
# Playwright / MCP Inspector are optional until screenshots/assessment run —
# record availability without inventing success.
if command -v node >/dev/null 2>&1; then
  echo "node:$(command -v node)"
else
  echo "node:absent"
fi
if command -v python3 >/dev/null 2>&1; then
  echo "python3:$(command -v python3)"
else
  echo "python3:absent"
fi
if [ -d /opt/killhub/tooling/playwright ]; then
  echo "playwright_dir:present"
else
  echo "playwright_dir:absent"
fi
if [ -d /opt/killhub/tooling/mcp-inspector ]; then
  echo "mcp_inspector_dir:present"
else
  echo "mcp_inspector_dir:absent"
fi
echo "helpers:ok"
exit "$missing"
