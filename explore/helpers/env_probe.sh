#!/bin/sh
# Trusted Killhub helper (D60) — prints a marker; used to verify copy_in/exec.
set -eu
echo "killhub-helper-ok"
env | awk -F= '{print $1}' | sort
