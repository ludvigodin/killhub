#!/bin/sh
# Killhub install-phase activity trace (guest side, trusted helper).
#
#   activity_trace.sh <step-id> <shell-command>
#
# Runs <shell-command> under `strace -f`, recording process launches
# (execve), outbound connections (connect), bytes sent on network sockets
# (%network: sendto/sendmsg/sendmmsg) and whether a peer answered (recv*
# lines, kept head-only: socket + byte count, never the response bytes).
# Only those lines are kept, appended to /tmp/killhub/activity/trace.log
# for host-side analysis.
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
echo "### step $id" >> "$dir/trace.log"
grep -E 'execve\(|connect\(|(send|recv)(to|from|msg|mmsg)?\(' "$raw" \
  | sed -E '/^[0-9]+ +recv(from|msg|mmsg)?\(/ s/^(.{0,120}).*(\) += -?[0-9]+.*)$/\1\2/' \
  >> "$dir/trace.log" 2>/dev/null || true
rm -f "$raw"
echo "traced $id rc=$rc" >> "$dir/status"
exit $rc
