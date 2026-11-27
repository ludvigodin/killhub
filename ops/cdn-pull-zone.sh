#!/usr/bin/env bash
# Killhub Vultr CDN Pull Zone helper (D76) — Object Storage origin for screenshot thumbs.
#
# Default is dry-run. Requires an existing Object Storage bucket (D72).
# Operator machine only — never run inside sandboxes; never inject keys into guests.
#
# Examples:
#   OBJECT_STORAGE_ENDPOINT=https://ewr1.vultrobjects.com \
#   OBJECT_STORAGE_BUCKET=killhub \
#     ./ops/cdn-pull-zone.sh
#
#   OBJECT_STORAGE_ENDPOINT=https://ewr1.vultrobjects.com \
#   OBJECT_STORAGE_BUCKET=killhub \
#     ./ops/cdn-pull-zone.sh --apply
#
# After --apply, set Plane 1:
#   OBJECT_STORAGE_CDN_BASE_URL=https://cdn-xxxxx.vultrcdn.com

set -euo pipefail

LABEL="${CDN_PULL_LABEL:-killhub-screenshots}"
APPLY=0

usage() {
  cat <<'EOF'
Usage: ops/cdn-pull-zone.sh [--apply] [--help]

  Default: dry-run (print planned vultr-cli create only).
  --apply  Create the CDN Pull Zone (idempotent skip if label already exists).

Env:
  VULTR_API_KEY              Required (operator machine)
  OBJECT_STORAGE_ENDPOINT    e.g. https://ewr1.vultrobjects.com
  OBJECT_STORAGE_BUCKET      bucket name (virtual-host origin)
  CDN_PULL_LABEL             default: killhub-screenshots
  CDN_ORIGIN_DOMAIN          optional override (bucket.cluster.vultrobjects.com)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

need_cmd vultr-cli
need_cmd jq
need_cmd python3

if [[ -z "${VULTR_API_KEY:-}" ]]; then
  echo "VULTR_API_KEY is unset. Export it or use ~/.vultr-cli.yaml (operator only)." >&2
  exit 1
fi

ORIGIN_DOMAIN="${CDN_ORIGIN_DOMAIN:-}"
if [[ -z "$ORIGIN_DOMAIN" ]]; then
  if [[ -z "${OBJECT_STORAGE_ENDPOINT:-}" || -z "${OBJECT_STORAGE_BUCKET:-}" ]]; then
    echo "Set OBJECT_STORAGE_ENDPOINT + OBJECT_STORAGE_BUCKET (or CDN_ORIGIN_DOMAIN)." >&2
    exit 1
  fi
  ORIGIN_DOMAIN="$(
    OBJECT_STORAGE_ENDPOINT="$OBJECT_STORAGE_ENDPOINT" \
    OBJECT_STORAGE_BUCKET="$OBJECT_STORAGE_BUCKET" \
    python3 - <<'PY'
import os
from urllib.parse import urlparse

ep = os.environ["OBJECT_STORAGE_ENDPOINT"].strip()
bkt = os.environ["OBJECT_STORAGE_BUCKET"].strip()
if ep.startswith("http://") or ep.startswith("https://"):
    host = urlparse(ep).hostname or ""
else:
    host = ep.split("/")[0]
host = host.strip().rstrip(".")
if not host or not bkt:
    raise SystemExit("invalid endpoint/bucket")
if host.startswith(bkt + "."):
    print(host)
else:
    print(f"{bkt}.{host}")
PY
  )"
fi

echo "CDN Pull Zone label: $LABEL"
echo "Origin domain:       $ORIGIN_DOMAIN (scheme=https)"
echo "Features:            gzip + cors (for killhub.pro thumbs)"

EXISTING="$(vultr-cli cdn pull list -o json 2>/dev/null || echo '{"pull_zones":[]}')"
MATCH="$(echo "$EXISTING" | jq -r --arg l "$LABEL" '
  [.pull_zones[]? | select(.label == $l)] | first // empty
')"

if [[ -n "$MATCH" && "$MATCH" != "null" ]]; then
  CDN_URL="$(echo "$MATCH" | jq -r '.cdn_url // .url // empty')"
  if [[ -z "$CDN_URL" ]]; then
    CDN_URL="$(echo "$MATCH" | jq -r '.cdn_domain // .domain // empty')"
  fi
  echo "Pull zone already exists for label=$LABEL"
  if [[ -n "$CDN_URL" ]]; then
    case "$CDN_URL" in
      https://*|http://*) ;;
      *) CDN_URL="https://${CDN_URL}" ;;
    esac
    echo "Set Plane 1: OBJECT_STORAGE_CDN_BASE_URL=${CDN_URL%/}"
  else
    echo "Inspect with: vultr-cli cdn pull list -o json"
  fi
  exit 0
fi

CMD=(
  vultr-cli cdn pull create
  --domain "$ORIGIN_DOMAIN"
  --scheme https
  --label "$LABEL"
  --gzip
  --cors
)

if [[ "$APPLY" -ne 1 ]]; then
  printf '+ [dry-run] '
  printf '%q ' "${CMD[@]}"
  printf '\n'
  echo "Re-run with --apply to create. Then set OBJECT_STORAGE_CDN_BASE_URL from the CDN hostname."
  exit 0
fi

echo "Creating pull zone…"
CREATE_OUT="$("${CMD[@]}" -o json)"
echo "$CREATE_OUT" | jq .

CDN_URL="$(echo "$CREATE_OUT" | jq -r '
  .pull_zone.cdn_url // .cdn_url // .pull_zone.url // .url //
  .pull_zone.cdn_domain // .cdn_domain // empty
')"
if [[ -z "$CDN_URL" || "$CDN_URL" == "null" ]]; then
  echo "Created; parse CDN hostname from output above, then:"
  echo "  OBJECT_STORAGE_CDN_BASE_URL=https://cdn-xxxxx.vultrcdn.com"
else
  case "$CDN_URL" in
    https://*|http://*) ;;
    *) CDN_URL="https://${CDN_URL}" ;;
  esac
  echo
  echo "Set Plane 1 env (no trailing slash) and restart explore:"
  echo "  OBJECT_STORAGE_CDN_BASE_URL=${CDN_URL%/}"
fi
