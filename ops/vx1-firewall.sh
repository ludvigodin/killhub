#!/usr/bin/env bash
# Killhub VX1 host-edge firewall helper (D70).
#
# Creates/updates a Vultr Firewall group for the demo host and optionally
# attaches it. Default is dry-run (print planned actions only).
#
# Prerequisites:
#   - vultr-cli on PATH + VULTR_API_KEY (operator machine only — never sandboxes)
#   - SSH_ALLOW_CIDRS: comma-separated CIDRs allowed to TCP/22
#
# Examples:
#   SSH_ALLOW_CIDRS='203.0.113.10/32,198.51.100.0/24' ./ops/vx1-firewall.sh
#   SSH_ALLOW_CIDRS='203.0.113.10/32' ./ops/vx1-firewall.sh --apply
#
# Safety:
#   - Refuses --apply without SSH_ALLOW_CIDRS
#   - Refuses SSH from 0.0.0.0/0 unless ALLOW_WORLD_SSH=1
#   - Does not invent instance IDs; resolves label killhub-vx1 via vultr-cli

set -euo pipefail

GROUP_DESC="${FIREWALL_GROUP_DESC:-killhub-vx1-edge}"
INSTANCE_LABEL="${INSTANCE_LABEL:-killhub-vx1}"
HTTP_PORT="${HTTP_PORT:-80}"
HTTPS_PORT="${HTTPS_PORT:-443}"
SSH_PORT="${SSH_PORT:-22}"
APPLY=0
ALLOW_WORLD_SSH="${ALLOW_WORLD_SSH:-0}"

usage() {
  cat <<'EOF'
Usage: ops/vx1-firewall.sh [--apply] [--help]

  Default: dry-run (no create/update/attach).
  --apply  Create/update rules and attach the group to the instance.

Env:
  VULTR_API_KEY       Required for any live API call (also dry-run inventory)
  SSH_ALLOW_CIDRS     Required for --apply (comma-separated, e.g. 203.0.113.10/32)
  FIREWALL_GROUP_DESC Default: killhub-vx1-edge
  INSTANCE_LABEL      Default: killhub-vx1
  ALLOW_WORLD_SSH     Set to 1 to permit SSH from 0.0.0.0/0 (dangerous)
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
  echo "VULTR_API_KEY is unset. Export it or use ~/.vultr-cli.yaml (operator machine only)." >&2
  echo "Inventory may also fail with 401 if Account > API Access Control blocks this IP (#20)." >&2
  exit 1
fi

run() {
  if [[ "$APPLY" -eq 1 ]]; then
    "$@"
  else
    printf '+ [dry-run]';
    printf '%q ' "$@"
    printf '\n'
  fi
}

parse_cidr() {
  # stdout: subnet size
  local cidr="$1"
  python3 - "$cidr" <<'PY'
import ipaddress, sys
raw = sys.argv[1].strip()
net = ipaddress.ip_network(raw, strict=False)
if net.version != 4:
    raise SystemExit(f"only IPv4 CIDRs supported in v1: {raw}")
print(f"{net.network_address} {net.prefixlen}")
PY
}

IFS=',' read -r -a SSH_CIDRS_RAW <<<"${SSH_ALLOW_CIDRS:-}"
SSH_CIDRS=()
for c in "${SSH_CIDRS_RAW[@]:-}"; do
  c="$(echo "$c" | tr -d '[:space:]')"
  [[ -z "$c" ]] && continue
  SSH_CIDRS+=("$c")
done

if [[ "$APPLY" -eq 1 ]]; then
  if [[ ${#SSH_CIDRS[@]} -eq 0 ]]; then
    echo "--apply requires SSH_ALLOW_CIDRS (operator CIDRs for TCP/22). Refusing lockout risk." >&2
    exit 1
  fi
  for c in "${SSH_CIDRS[@]}"; do
    if [[ "$c" == "0.0.0.0/0" && "$ALLOW_WORLD_SSH" != "1" ]]; then
      echo "Refusing SSH from 0.0.0.0/0. Set ALLOW_WORLD_SSH=1 only with an out-of-band console path." >&2
      exit 1
    fi
  done
fi

echo "== Inventory =="
if ! INSTANCES_JSON="$(vultr-cli instance list -o json 2>/tmp/killhub-fw-instance.err)"; then
  echo "vultr-cli instance list failed:" >&2
  cat /tmp/killhub-fw-instance.err >&2 || true
  echo "If this is 401 Invalid authentication, fix Account > API Access Control (#20)." >&2
  echo "Manual fallback: resolve instance ID for label '${INSTANCE_LABEL}' in the Vultr console, then follow SETUP.md §7 Vultr Firewall." >&2
  exit 1
fi

INSTANCE_ID="$(
  printf '%s' "$INSTANCES_JSON" | jq -r --arg label "$INSTANCE_LABEL" '
    (.instances // .)
    | if type=="array" then . else .instances // empty end
    | map(select(.label == $label))
    | .[0].id // empty
  '
)"

# vultr-cli json shapes vary slightly by version; try alternate unwrap
if [[ -z "$INSTANCE_ID" ]]; then
  INSTANCE_ID="$(
    printf '%s' "$INSTANCES_JSON" | jq -r --arg label "$INSTANCE_LABEL" '
      .. | objects | select(has("label") and has("id") and .label == $label) | .id
    ' | head -n1
  )"
fi

if [[ -z "$INSTANCE_ID" ]]; then
  echo "No instance with label '${INSTANCE_LABEL}' found. Do not invent IDs." >&2
  echo "Available labels:" >&2
  printf '%s' "$INSTANCES_JSON" | jq -r '.. | objects | select(has("label")) | .label' 2>/dev/null | sort -u >&2 || true
  exit 1
fi

echo "Instance label=${INSTANCE_LABEL} id=${INSTANCE_ID}"

GROUPS_JSON="$(vultr-cli firewall group list -o json)"
GROUP_ID="$(
  printf '%s' "$GROUPS_JSON" | jq -r --arg desc "$GROUP_DESC" '
    (.. | objects | select(has("description") and has("id") and .description == $desc) | .id)
  ' | head -n1
)"

if [[ -z "$GROUP_ID" ]]; then
  echo "Firewall group '${GROUP_DESC}' not found — will create."
  if [[ "$APPLY" -eq 1 ]]; then
    CREATE_OUT="$(vultr-cli firewall group create -d "$GROUP_DESC" -o json)"
    GROUP_ID="$(printf '%s' "$CREATE_OUT" | jq -r '.. | objects | select(has("id")) | .id' | head -n1)"
    if [[ -z "$GROUP_ID" ]]; then
      echo "Failed to parse firewall group id from create output:" >&2
      echo "$CREATE_OUT" >&2
      exit 1
    fi
  else
    GROUP_ID='<new-group-id>'
    run vultr-cli firewall group create -d "$GROUP_DESC"
  fi
else
  echo "Firewall group '${GROUP_DESC}' id=${GROUP_ID}"
fi

rule_exists() {
  local port="$1" subnet="$2" size="$3"
  if [[ "$GROUP_ID" == '<new-group-id>' ]]; then
    return 1
  fi
  local rules
  rules="$(vultr-cli firewall rule list "$GROUP_ID" -o json 2>/dev/null || true)"
  printf '%s' "$rules" | jq -e --argjson port "$port" --arg subnet "$subnet" --argjson size "$size" '
    [.. | objects | select(has("port") and has("subnet") and (.protocol|ascii_downcase)=="tcp")]
    | any(
        (.port|tostring) == ($port|tostring)
        and .subnet == $subnet
        and ((.subnet_size // .size // -1)|tonumber) == $size
      )
  ' >/dev/null 2>&1
}

ensure_rule() {
  local port="$1" subnet="$2" size="$3" notes="$4"
  if rule_exists "$port" "$subnet" "$size"; then
    echo "Rule exists: tcp/${port} from ${subnet}/${size}"
    return 0
  fi
  echo "Need rule: tcp/${port} from ${subnet}/${size} (${notes})"
  run vultr-cli firewall rule create \
    --id="$GROUP_ID" \
    --ip-type=v4 \
    --protocol=tcp \
    --subnet="$subnet" \
    --size="$size" \
    --port="$port" \
    --notes="$notes"
}

echo "== Desired policy (IPv4 inbound) =="
echo "  TCP ${HTTP_PORT}/443 from 0.0.0.0/0  (Caddy + ACME)"
if [[ ${#SSH_CIDRS[@]} -eq 0 ]]; then
  echo "  TCP ${SSH_PORT} from <unset SSH_ALLOW_CIDRS>  (required before --apply)"
else
  for c in "${SSH_CIDRS[@]}"; do
    echo "  TCP ${SSH_PORT} from ${c}"
  done
fi
echo "  All other inbound: default deny (Vultr Firewall once ≥1 rule exists)"
echo "  Outbound: unrestricted (host edge ≠ Plane 2 D39/D43 guest policy)"

ensure_rule "$HTTP_PORT" "0.0.0.0" 0 "killhub HTTP / ACME"
ensure_rule "$HTTPS_PORT" "0.0.0.0" 0 "killhub HTTPS"

if [[ ${#SSH_CIDRS[@]} -gt 0 ]]; then
  for c in "${SSH_CIDRS[@]}"; do
    read -r subnet size <<<"$(parse_cidr "$c")"
    ensure_rule "$SSH_PORT" "$subnet" "$size" "killhub SSH operator"
  done
fi

echo "== Attach =="
if [[ "$APPLY" -eq 1 ]]; then
  if [[ "$GROUP_ID" == '<new-group-id>' || -z "$GROUP_ID" ]]; then
    echo "No real firewall group id; cannot attach." >&2
    exit 1
  fi
  # Confirm SSH rule present before attach
  RULES_JSON="$(vultr-cli firewall rule list "$GROUP_ID" -o json)"
  SSH_OK="$(
    printf '%s' "$RULES_JSON" | jq -r --argjson port "$SSH_PORT" '
      [.. | objects | select(has("port") and (.protocol|ascii_downcase)=="tcp" and ((.port|tostring)==($port|tostring)))]
      | length
    '
  )"
  if [[ "${SSH_OK:-0}" -lt 1 ]]; then
    echo "No TCP/${SSH_PORT} rule on group ${GROUP_ID}; refusing attach (lockout risk)." >&2
    exit 1
  fi
  vultr-cli instance update-firewall-group \
    --instance-id="$INSTANCE_ID" \
    --firewall-group-id="$GROUP_ID"
  echo "Attached group ${GROUP_ID} to instance ${INSTANCE_ID}."
  echo "Verify: ssh from an allowlisted IP, then curl -I https://killhub.pro/"
else
  run vultr-cli instance update-firewall-group \
    --instance-id="$INSTANCE_ID" \
    --firewall-group-id="$GROUP_ID"
  echo "Dry-run complete. Re-run with --apply after confirming SSH_ALLOW_CIDRS."
fi
