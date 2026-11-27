#!/bin/sh
# Guest network probe — fetch a URL; exit 0 on HTTP success, 1 on failure.
set -eu
URL="${1:-}"
TIMEOUT="${2:-5}"
if [ -z "$URL" ]; then
  echo "usage: network_probe.sh URL [timeout]" >&2
  exit 2
fi
if command -v wget >/dev/null 2>&1; then
  if wget -qO- --timeout="$TIMEOUT" "$URL" >/tmp/killhub-net-probe.out 2>/tmp/killhub-net-probe.err; then
    echo "ok:wget"
    exit 0
  fi
  echo "fail:wget"
  head -c 200 /tmp/killhub-net-probe.err || true
  exit 1
fi
if command -v curl >/dev/null 2>&1; then
  if curl -fsS --max-time "$TIMEOUT" "$URL" >/tmp/killhub-net-probe.out 2>/tmp/killhub-net-probe.err; then
    echo "ok:curl"
    exit 0
  fi
  echo "fail:curl"
  head -c 200 /tmp/killhub-net-probe.err || true
  exit 1
fi
echo "tooling_missing:no wget/curl"
exit 3
