#!/usr/bin/env bash
# Host-side docker login to Vultr Container Registry (D74).
#
# Run on the Plane 1 / VX1 host where `msb` pulls OCI images — NEVER inside a
# guest sandbox. Robot credentials stay in the operator environment / docker
# credential store; Killhub does not inject them into sandbox env (D19, D44).
#
# Prerequisites:
#   - docker (or compatible) CLI on the msb host
#   - VULTR_CR_ENDPOINT   e.g. ewr.vultrcr.com/killhub
#   - VULTR_CR_ROBOT_USERNAME / VULTR_CR_ROBOT_PASSWORD  (pull robot)
#
# Optional: source /etc/killhub/killhub.env or repo .env before running.
set -euo pipefail

ENDPOINT="${VULTR_CR_ENDPOINT:-}"
USER="${VULTR_CR_ROBOT_USERNAME:-}"
PASS="${VULTR_CR_ROBOT_PASSWORD:-}"

if [[ -z "${ENDPOINT}" || -z "${USER}" || -z "${PASS}" ]]; then
  cat >&2 <<'EOF'
Missing VULTR_CR_ENDPOINT, VULTR_CR_ROBOT_USERNAME, or VULTR_CR_ROBOT_PASSWORD.

Operator flow (no secrets in git):
  1. vultr-cli container-registry create …   # or Vultr console
  2. Create a pull robot (or mint docker credentials)
  3. export VULTR_CR_ENDPOINT=ewr.vultrcr.com/<registry-name>
  4. export VULTR_CR_ROBOT_USERNAME='…' VULTR_CR_ROBOT_PASSWORD='…'
  5. ./explore/scripts/vultr_cr_login.sh
  6. Pin MSB_DEFAULT_IMAGE=<endpoint>/bootstrap@sha256:<digest>

See SETUP.md §6 (Vultr Container Registry).
EOF
  exit 1
fi

# docker login expects the registry host URL; strip scheme if present.
LOGIN_HOST="${ENDPOINT#https://}"
LOGIN_HOST="${LOGIN_HOST#http://}"

echo "docker login https://${LOGIN_HOST} (user=${USER})" >&2
# Password via stdin — avoid argv exposure in process lists where possible.
printf '%s' "${PASS}" | docker login "https://${LOGIN_HOST}" -u "${USER}" --password-stdin

echo "OK — host credential store ready for msb pulls of ${LOGIN_HOST}/…" >&2
echo "Pin MSB_DEFAULT_IMAGE with a digest, e.g. ${LOGIN_HOST}/bootstrap@sha256:…" >&2
