"""Active checks: install-phase activity trace + canary exfiltration matching.

Install is the riskiest moment of a job: package managers and repo scripts
run with public egress. This module

1. prepares the guest (``strace`` + a file-change marker) before install,
2. wraps every install command in ``helpers/activity_trace.sh`` (guest-side
   ``strace -f``: execve, connect, bytes sent on network sockets),
3. after install, copies the trace out and analyses it on Plane 1:
   - outbound destinations (and DNS questions, decoded from the packets),
   - processes launched, flagging network tools,
   - the job's canary values in any outbound bytes or DNS name, in plain,
     base64, base32, hex and URL-encoded form → ``canary_exfiltration``
     finding with ``classification=policy_bypass`` (hard-fail gate),
   - writes to persistence locations (cron, ssh keys, ld.so.preload, rc files),
4. reviews MCP tool descriptions for poisoning (hidden instructions,
   invisible Unicode) after the handshake.

Evidence honesty: the trace is guest-side and can be evaded by code that
targets the tracer; TLS payloads are ciphertext so only their destinations
are visible. The summary records both limits. Canary plaintext is never
written to events — only canary ids, encodings and redacted destinations.
"""

from __future__ import annotations

import base64
import codecs
import logging
import re
import shlex
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import Settings, get_settings

logger = logging.getLogger("killhub.activity")

GUEST_ACTIVITY_DIR = "/tmp/killhub/activity"
GUEST_TRACE = f"{GUEST_ACTIVITY_DIR}/trace.log"
GUEST_STATUS = f"{GUEST_ACTIVITY_DIR}/status"
GUEST_MARKER = f"{GUEST_ACTIVITY_DIR}/marker"
GUEST_MCP_TOOLS = f"{GUEST_ACTIVITY_DIR}/mcp_tools.json"
HELPER_ID = "activity_trace"

# Locations a package install has no business writing to.
PERSISTENCE_PATHS = (
    "/etc/cron.d",
    "/etc/cron.daily",
    "/etc/cron.hourly",
    "/etc/crontab",
    "/var/spool/cron",
    "/etc/ld.so.preload",
    "/etc/systemd/system",
    "/etc/rc.local",
    "/etc/profile.d",
    "/etc/sudoers.d",
    "/root/.ssh",
    "/root/.bashrc",
    "/root/.profile",
    "/root/.bash_profile",
    "/root/.zshrc",
)
NETWORK_TOOLS = frozenset({"curl", "wget", "nc", "ncat", "netcat", "socat", "ssh", "scp", "telnet"})
MIN_FORM_LEN = 8
# A chunk this long of an encoded random canary won't occur by chance (DNS label chunking).
CHUNK_LEN = 16

_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')
_FD_PEER = re.compile(r"<(?:TCP|UDP|TCPv6|UDPv6):\[[^\]]*?->([^\]]+)\]>")
_FD_INODE = re.compile(r"<(?:TCP|UDP|TCPv6|UDPv6):\[(\d+)\]>")
_SIN = re.compile(r'sin_port=htons\((\d+)\), sin_addr=inet_addr\("([^"]+)"\)')
_SIN6 = re.compile(r'sin6_port=htons\((\d+)\).*?inet_pton\(AF_INET6, "([^"]+)"')
_RESULT = re.compile(r"\)\s*=\s*(-?\d+)(?:\s+(E[A-Z0-9]+))?")
_EXECVE = re.compile(r'execve\("([^"]+)", \[([^\]]*)\]')
_PID = re.compile(r"^(\d+)\s+")


# --- guest integration --------------------------------------------------------


def wrap_command_spec(spec: dict[str, Any], step_id: int) -> dict[str, Any]:
    """Return a copy of an install command spec that runs under the tracer."""
    if spec.get("argv"):
        inner = "exec " + " ".join(shlex.quote(str(a)) for a in spec["argv"])
    elif spec.get("shell"):
        inner = str(spec["shell"])
    else:
        return spec
    helper = f"/opt/killhub/helpers/{HELPER_ID}.sh"
    wrapped = {k: v for k, v in spec.items() if k not in {"argv", "shell"}}
    label = f"tool-{int(step_id)}" if spec.get("killhub_tooling") else str(int(step_id))
    wrapped["shell"] = f"sh {helper} {label} {shlex.quote(inner)}"
    return wrapped


def prepare_guest(environment_id: str, *, job_id: str, settings: Settings | None = None) -> bool:
    """Copy the tracer in, install strace (install phase has egress), set the marker."""
    from harness import copy_in, exec_command

    cfg = settings or get_settings()
    copy_in(
        environment_id,
        HELPER_ID,
        f"/opt/killhub/helpers/{HELPER_ID}.sh",
        job_id=job_id,
        settings=cfg,
    )
    result = exec_command(
        environment_id,
        [
            "sh",
            "-lc",
            f"mkdir -p {GUEST_ACTIVITY_DIR} && : > {GUEST_TRACE} && : > {GUEST_STATUS} && "
            "(command -v strace >/dev/null 2>&1 || "
            "(command -v apt-get >/dev/null 2>&1 && DEBIAN_FRONTEND=noninteractive "
            "apt-get install -y -qq strace >/dev/null 2>&1) || "
            "(command -v apk >/dev/null 2>&1 && apk add --no-cache strace >/dev/null 2>&1) "
            "|| true); "
            f"touch {GUEST_MARKER}; command -v strace >/dev/null 2>&1 && echo strace_ok",
        ],
        job_id=job_id,
        settings=cfg,
        timeout=300,
    )
    return "strace_ok" in (result.stdout or "")


# --- parsing --------------------------------------------------------------------


@dataclass
class Activity:
    connections: list[dict[str, Any]] = field(default_factory=list)
    dns_queries: list[str] = field(default_factory=list)
    processes: list[dict[str, Any]] = field(default_factory=list)
    payloads: list[tuple[str, bytes]] = field(default_factory=list)  # (peer, bytes)


def _unescape(s: str) -> bytes:
    """Decode a strace C-escaped string (\\xNN, octal, \\n, \\") to bytes."""
    try:
        return codecs.escape_decode(s.encode("latin-1", "backslashreplace"))[0]
    except Exception:  # noqa: BLE001 — malformed escape: keep raw text
        return s.encode("latin-1", "replace")


def _dns_question(packet: bytes) -> str | None:
    """Return the QNAME of a DNS query packet, or None."""
    if len(packet) < 17:
        return None
    flags = packet[2]
    if flags & 0x80:  # response, not a query
        return None
    labels: list[str] = []
    i = 12
    while i < len(packet):
        n = packet[i]
        if n == 0:
            return ".".join(labels) if labels else None
        if n > 63 or i + 1 + n > len(packet):
            return None
        labels.append(packet[i + 1 : i + 1 + n].decode("ascii", "replace"))
        i += 1 + n
    return None


def _peer(line: str, inodes: dict[str, str] | None = None) -> str | None:
    m = _FD_PEER.search(line)
    if m:
        return m.group(1)
    # Connected socket printed by inode only: use the peer seen at connect().
    m = _FD_INODE.search(line)
    if m and inodes and m.group(1) in inodes and "sin_port" not in line:
        return inodes[m.group(1)]
    m = _FD_PEER.search(line)
    if m:
        return m.group(1)
    m = _SIN.search(line)
    if m:
        return f"{m.group(2)}:{m.group(1)}"
    m = _SIN6.search(line)
    if m:
        return f"[{m.group(2)}]:{m.group(1)}"
    return None


def parse_trace(text: str) -> Activity:
    act = Activity()
    seen_conn: set[tuple[str, str]] = set()
    inodes: dict[str, str] = {}  # socket inode → peer recorded at connect()
    step = ""
    for raw in text.splitlines():
        if raw.startswith("### step "):
            step = raw[len("### step ") :].strip()
            continue
        line = _PID.sub("", raw.strip(), count=1)
        if line.startswith("execve("):
            m = _EXECVE.search(line)
            res = _RESULT.search(line)
            if m and res and res.group(1) == "0":
                argv = [
                    _unescape(a).decode("utf-8", "replace") for a in _QUOTED.findall(m.group(2))
                ]
                act.processes.append({"exe": m.group(1), "argv": argv[:6], "step": step})
            continue
        if line.startswith("connect("):
            peer = _peer(line)
            res = _RESULT.search(line)
            ino = _FD_INODE.search(line)
            if ino and peer:
                inodes[ino.group(1)] = peer
            # Port 0: glibc's UDP connect() for source-address selection, no traffic.
            if peer and not peer.startswith("/") and not peer.endswith(":0"):
                outcome = "ok" if res and res.group(1) == "0" else (res.group(2) if res else "?")
                if outcome == "EINPROGRESS":
                    outcome = "in_progress"
                key = (peer, outcome)
                if key not in seen_conn:
                    seen_conn.add(key)
                    act.connections.append({"peer": peer, "result": outcome})
            continue
        if line.startswith(("sendto(", "sendmsg(", "sendmmsg(", "send(")):
            peer = _peer(line, inodes) or "?"
            for chunk in _QUOTED.findall(line):
                data = _unescape(chunk)
                if not data:
                    continue
                act.payloads.append((peer, data))
                if peer.endswith(":53"):
                    q = _dns_question(data)
                    if q and q not in act.dns_queries:
                        act.dns_queries.append(q)
    return act


# --- canary matching --------------------------------------------------------------


def canary_forms(value: str) -> dict[str, bytes]:
    """Encodings an exfiltration attempt plausibly uses, lower-cased where case-free."""
    raw = value.encode("utf-8")
    b64 = base64.b64encode(raw)
    forms = {
        "plain": raw,
        "base64": b64.rstrip(b"="),
        "base64url": base64.urlsafe_b64encode(raw).rstrip(b"="),
        "base32": base64.b32encode(raw).rstrip(b"=").lower(),
        "hex": raw.hex().encode(),
        "urlencoded": urllib.parse.quote(value, safe="").encode(),
    }
    if forms["base64url"] == forms["base64"]:
        del forms["base64url"]
    return {k: v for k, v in forms.items() if len(v) >= MIN_FORM_LEN}


def _canary_values(record: Any) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, val in (getattr(record, "env", None) or {}).items():
        values[f"env:{key}"] = val
    for path, val in (getattr(record, "files", None) or {}).items():
        values.setdefault(f"file:{path}", val)
    # One canonical id per distinct value (token is planted in env and file).
    distinct: dict[str, str] = {}
    for cid, val in values.items():
        if val not in distinct.values():
            distinct[cid] = val
    return distinct


def _find_form(form: bytes, hay: bytes) -> bool | None:
    """True = whole form present, False = only a CHUNK_LEN slice present, None = absent."""
    if form in hay:
        return True
    for i in range(0, max(len(form) - CHUNK_LEN + 1, 0)):
        if form[i : i + CHUNK_LEN] in hay:
            return False
    return None


def match_canaries(act: Activity, canaries: dict[str, str]) -> list[dict[str, Any]]:
    """Every (canary id, encoding, destination) seen leaving the guest.

    Matches the whole encoded value, or any CHUNK_LEN slice of it (flagged
    ``partial``) because DNS exfiltration splits data across labels/queries.
    """
    hits: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    all_forms = {cid: canary_forms(v) for cid, v in canaries.items()}

    def redact(text: str) -> str:
        out = text
        for forms in all_forms.values():
            for form in forms.values():
                for i in range(0, max(len(form) - CHUNK_LEN + 1, 1)):
                    piece = form[i : i + max(CHUNK_LEN, 1)].decode("latin-1")
                    if len(piece) >= CHUNK_LEN:
                        out = re.sub(re.escape(piece), "<canary>", out, flags=re.I)
        return re.sub(r"(<canary>[0-9A-Za-z+/=_-]*)+", "<canary>", out)

    def check(hay: bytes, channel: str, dest: str) -> None:
        low = hay.lower()
        for cid, forms in all_forms.items():
            for enc, form in forms.items():
                case_free = enc in {"base32", "hex"} or channel == "dns"
                found = _find_form(form.lower() if case_free else form, low if case_free else hay)
                if found is None:
                    continue
                key = (cid, enc, dest)
                if key in seen:
                    continue
                seen.add(key)
                hits.append(
                    {
                        "canary_id": cid,
                        "encoding": enc,
                        "channel": channel,
                        "destination": dest,
                        "partial": not found,
                    }
                )

    for peer, data in act.payloads:
        if peer.endswith(":53"):
            continue  # DNS handled below via decoded questions
        check(data, "network", peer)
    for q in act.dns_queries:
        check(q.encode(), "dns", redact(q))
    return hits


def redact_queries(queries: list[str], canaries: dict[str, str]) -> list[str]:
    """DNS names safe to persist: canary-derived label text replaced with <canary>."""
    forms = [f for v in canaries.values() for f in canary_forms(v).values()]
    out = []
    for q in queries:
        r = q
        for form in forms:
            for i in range(0, max(len(form) - CHUNK_LEN + 1, 0)):
                piece = form[i : i + CHUNK_LEN].decode("latin-1")
                r = re.sub(re.escape(piece), "<canary>", r, flags=re.I)
        out.append(re.sub(r"(<canary>[0-9A-Za-z+/=_-]*)+", "<canary>", r))
    return out


# --- post-install collection --------------------------------------------------------


def _persistence_changes(environment_id: str, *, job_id: str, settings: Settings) -> list[str]:
    from harness import exec_command

    paths = " ".join(PERSISTENCE_PATHS)
    result = exec_command(
        environment_id,
        [
            "sh",
            "-lc",
            f"[ -f {GUEST_MARKER} ] || exit 0; "
            f'for p in {paths}; do [ -e "$p" ] && find "$p" -newer {GUEST_MARKER} '
            "-print 2>/dev/null; done | head -n 50",
        ],
        job_id=job_id,
        settings=settings,
        timeout=60,
    )
    return [ln.strip() for ln in (result.stdout or "").splitlines() if ln.strip().startswith("/")]


def collect_and_analyze(
    environment_id: str, *, job_id: str, settings: Settings | None = None
) -> dict[str, Any]:
    """Copy the install trace out, analyse it, and emit evidence + findings."""
    from canaries import load_canaries
    from harness import copy_out, exec_command
    from jobs import get_ledger

    cfg = settings or get_settings()
    ledger = get_ledger(cfg)
    status = exec_command(
        environment_id,
        ["sh", "-lc", f"cat {GUEST_STATUS} 2>/dev/null; wc -c < {GUEST_TRACE} 2>/dev/null"],
        job_id=job_id,
        settings=cfg,
        timeout=30,
    )
    status_lines = [ln for ln in (status.stdout or "").splitlines() if ln.strip()]
    untraced = [ln.split()[1] for ln in status_lines if ln.startswith("untraced ")]
    traced = [ln.split()[1] for ln in status_lines if ln.startswith("traced ")]

    text = ""
    try:
        local: Path = copy_out(
            environment_id,
            GUEST_TRACE,
            "log",
            job_id=job_id,
            filename="install-activity.trace",
            settings=cfg,
        )
        text = local.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 — missing trace is reported, not fatal
        logger.warning("activity trace copy_out failed for %s: %s", job_id, exc)

    act = parse_trace(text)
    record = load_canaries(job_id, cfg)
    values = _canary_values(record) if record else {}
    hits = match_canaries(act, values) if values else []
    persistence = _persistence_changes(environment_id, job_id=job_id, settings=cfg)
    net_tools = sorted(
        {
            Path(p["exe"]).name
            for p in act.processes
            if Path(p["exe"]).name in NETWORK_TOOLS and not p.get("step", "").startswith("tool-")
        }
    )
    destinations = sorted({c["peer"] for c in act.connections})

    summary = {
        "traced_steps": len(traced),
        "untraced_steps": untraced,
        "trace_bytes": len(text),
        "process_count": len(act.processes),
        "network_tools": net_tools,
        "destinations": destinations[:50],
        "dns_queries": redact_queries(act.dns_queries[:50], values),
        "canary_hits": hits,
        "persistence_writes": persistence,
        "limits": [
            "guest-side trace: code that targets the tracer can evade it",
            "TLS payloads are encrypted: only their destinations are checked",
        ],
    }
    if not traced or not text:
        summary["coverage"] = "none"
    elif untraced:
        summary["coverage"] = "partial"
    else:
        summary["coverage"] = "full"

    if not traced:
        message = "No install commands were traced."
    elif not text:
        message = "Install trace data unavailable."
    else:
        message = (
            f"install activity: {len(act.processes)} processes, {len(destinations)} destinations, "
            f"{len(act.dns_queries)} DNS queries, {len(hits)} canary hits "
            f"(coverage {summary['coverage']})"
        )
    ledger.append_event(
        job_id,
        typ="log",
        message=message,
        payload={"kind": "install_activity", **summary},
    )
    if hits:
        ledger.append_event(
            job_id,
            typ="finding",
            message="The install trace matched a test secret in an outgoing network attempt",
            payload={
                "source": "activity",
                "code": "canary_exfiltration",
                "severity": "critical",
                # Hard-fail gate in finalize keys on policy_bypass (D58/D44).
                "classification": "policy_bypass",
                "hits": hits,
            },
        )
    if persistence:
        ledger.append_event(
            job_id,
            typ="finding",
            message="Install wrote to system persistence locations",
            payload={
                "source": "activity",
                "code": "persistence_write",
                "severity": "high",
                "paths": persistence,
            },
        )
    if net_tools:
        ledger.append_event(
            job_id,
            typ="finding",
            message=f"Install ran network tools: {', '.join(net_tools)}",
            payload={
                "source": "activity",
                "code": "install_network_tools",
                "repository_steps_only": True,
                "severity": "low",
                "tools": net_tools,
            },
        )
    return summary


# --- MCP tool description review ----------------------------------------------------

_POISON_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "override_instructions",
        re.compile(
            r"\b(ignore|disregard|forget)\b.{0,30}\b(previous|prior|above|all|other)\b.{0,20}\binstructions?\b",
            re.I,
        ),
    ),
    ("hidden_tag", re.compile(r"<\s*(important|system|secret|hidden|instructions?)\s*>", re.I)),
    (
        "conceal_from_user",
        re.compile(
            r"\b(do not|don'?t|never)\b.{0,20}"
            r"\b(tell|mention|inform|reveal|show)\b.{0,20}\b(the )?user\b",
            re.I,
        ),
    ),
    (
        "sensitive_file",
        re.compile(
            r"(~/\.ssh|id_rsa|id_ed25519|\.aws/credentials|/etc/passwd|/etc/shadow|mcp\.json|\.env\b)",
            re.I,
        ),
    ),
    (
        "exfil_instruction",
        re.compile(
            r"\b(send|pass|include|forward|upload|post)\b.{0,40}"
            r"\b(token|secret|password|credential|api[_ ]?key|private key)s?\b",
            re.I,
        ),
    ),
    (
        "shadow_other_tool",
        re.compile(
            r"\b(when|whenever|before|after)\b.{0,30}\b(using|calling|invoking)\b.{0,30}\btool\b.{0,40}\b(must|always|instead)\b",
            re.I,
        ),
    ),
)
_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿]|[\U000e0000-\U000e007f]")


def review_tool_descriptions(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Heuristic tool-poisoning review of MCP tool names/descriptions/schemas."""
    findings: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name") or "")
        text = " ".join(
            str(x) for x in (tool.get("description") or "", tool.get("input_schema_text") or "")
        )
        reasons = [rid for rid, rx in _POISON_PATTERNS if rx.search(text)]
        if _INVISIBLE.search(text) or _INVISIBLE.search(name):
            reasons.append("invisible_unicode")
        if reasons:
            findings.append(
                {
                    "tool": name[:120],
                    "reasons": reasons,
                    "severity": "high"
                    if set(reasons) - {"sensitive_file", "invisible_unicode"}
                    else "medium",
                    "excerpt": _INVISIBLE.sub("�", text[:300]),
                }
            )
    return findings


def review_mcp_tools(job_id: str, *, settings: Settings | None = None) -> list[dict[str, Any]]:
    """Copy the handshake's tool list out of the guest and emit poisoning findings."""
    import json

    from harness import copy_out
    from jobs import get_ledger

    cfg = settings or get_settings()
    ledger = get_ledger(cfg)
    job = ledger.get_job(job_id)
    if job is None or not job.sandbox_id:
        return []
    try:
        local = copy_out(
            job.sandbox_id,
            GUEST_MCP_TOOLS,
            "log",
            job_id=job_id,
            filename="mcp-tools.json",
            settings=cfg,
        )
        tools = json.loads(local.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — no MCP handshake ran / no dump: nothing to review
        return []
    if not isinstance(tools, list) or not tools:
        return []
    found = review_tool_descriptions(tools)
    ledger.append_event(
        job_id,
        typ="log",
        message=f"MCP tool description review: {len(tools)} tools, {len(found)} flagged",
        payload={"kind": "mcp_tool_review", "tool_count": len(tools), "flagged": len(found)},
    )
    for f in found:
        ledger.append_event(
            job_id,
            typ="finding",
            message=(
                f"MCP tool '{f['tool']}' description was flagged for suspicious text "
                f"({', '.join(f['reasons'])})"
            ),
            payload={"source": "mcp_tool_review", "code": "mcp_tool_poisoning", **f},
        )
    return found
