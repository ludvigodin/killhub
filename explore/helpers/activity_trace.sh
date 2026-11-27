#!/bin/sh
# Killhub install-phase activity trace (guest side, trusted helper).
#
#   activity_trace.sh <step-id> <shell-command>
#
# Runs <shell-command> under `strace -f`, recording process launches
# (execve), outbound connections (connect) and bytes sent on network
# sockets (%network: sendto/sendmsg/sendmmsg). Only those lines are kept,
# appended to /tmp/killhub/activity/trace.log for host-side analysis.
#
# This is guest-side evidence: code that targets the tracer can evade it.
# TLS payloads are ciphertext here — only their destinations are useful.
# The command's exit code is preserved; without strace it runs untraced and
# that is recorded so the host never reports "no activity" for an untraced step.
set -u
id="$1"
cmd="$2"
dir=/tmp/killhub/activity
mkdir -p "$dir"
if ! command -v strace >/dev/null 2>&1; then
  echo "untraced $id" >> "$dir/status"
  sh -c "$cmd"
  exit $?
fi
raw="$dir/raw.$id"
strace -f -qq -s 4096 -yy -o "$raw" -e trace=execve,connect,%network sh -c "$cmd"
rc=$?
grep -E 'execve\(|connect\(|send(to|msg|mmsg)?\(' "$raw" >> "$dir/trace.log" 2>/dev/null || true
rm -f "$raw"
echo "traced $id rc=$rc" >> "$dir/status"
exit $rc
