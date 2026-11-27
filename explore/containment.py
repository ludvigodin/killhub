"""Containment evidence matrix + network/canary probes (D26, D58, D65, D44).

Does not weaponize project CVEs (D33). Does not destroy or mark completed.
"""

from __future__ import annotations

import logging
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from canaries import scan_canaries
from config import Settings, get_settings
from harness import (
    LABEL_EXPIRES,
    LABEL_PROBE_OWNER,
    EnvironmentPlan,
    MsbCli,
    apply_killhub_net_policy,
    exec_command,
    list_live_environment_ids,
    wait_until_ready,
)
from jobs import get_ledger
from ledger.store import utc_now

logger = logging.getLogger("killhub.containment")

DIMENSIONS = (
    "timeout_enforcement",
    "host_access_denied",
    "sibling_access_denied",
    "host_liveness",
)


@dataclass
class ContainmentResult:
    job_id: str
    environment_id: str
    claim: str
    dimensions: dict[str, Any] = field(default_factory=dict)
    network_probes: list[dict[str, Any]] = field(default_factory=list)
    canary_scan: dict[str, Any] = field(default_factory=dict)
    install_cp_probe: dict[str, Any] | None = None


class ContainmentError(Exception):
    def __init__(self, message: str, *, code: str = "containment_failed") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _log(job_id: str, message: str, *, settings: Settings, kind: str, **payload: Any) -> None:
    get_ledger(settings).append_event(
        job_id,
        typ="log",
        message=message,
        payload={"kind": kind, **payload},
    )


def _finding(
    job_id: str,
    message: str,
    *,
    settings: Settings,
    source: str,
    code: str,
    severity: str = "medium",
    **extra: Any,
) -> None:
    get_ledger(settings).append_event(
        job_id,
        typ="finding",
        message=message,
        payload={
            "source": source,
            "code": code,
            "severity": severity,
            **extra,
        },
    )


def _containment_event(
    job_id: str,
    message: str,
    *,
    settings: Settings,
    dimension: str,
    **payload: Any,
) -> None:
    get_ledger(settings).append_event(
        job_id,
        typ="containment",
        message=message,
        payload={"dimension": dimension, **payload},
    )


def _host_fetch_ok(url: str, *, timeout: float = 5.0) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "killhub-containment-probe/0.1"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            return 200 <= int(code) < 400, f"http_{code}"
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        return False, f"{exc.__class__.__name__}"


def _tcp_positive_control(url: str) -> tuple[str | None, str]:
    """Return the exact responsive peer for comparison from the verify guest."""
    endpoint = urlsplit(url)
    port = endpoint.port or (443 if endpoint.scheme == "https" else 80)
    try:
        with socket.create_connection((endpoint.hostname or "", port), timeout=5) as sock:
            address = sock.getpeername()[0]
    except OSError as exc:
        return None, type(exc).__name__
    host = f"[{address}]" if ":" in address else address
    return f"tcp://{host}:{port}", "connected"


def _gateway_control(interface: str) -> tuple[str | None, str]:
    """Only test the fixed gateway through its operator-designated guest interface."""
    if not interface:
        return None, "guest_network_positive_control_unavailable"
    try:
        routes = [line.split() for line in Path("/proc/net/route").read_text().splitlines()[1:]]
        if not routes or any(row[:2] == [interface, "00000000"] for row in routes):
            return None, "dedicated_guest_interface_required"
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(5)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, interface.encode() + b"\0")
            sock.connect(("172.16.0.5", 80))
    except (OSError, AttributeError, ValueError) as exc:
        return None, type(exc).__name__
    return "tcp://172.16.0.5:80", "connected_on_guest_interface"


def _guest_fetch(
    environment_id: str,
    url: str,
    *,
    job_id: str,
    settings: Settings,
    timeout: float = 5.0,
    probe_session: str,
) -> tuple[str, int, str]:
    """Return (classification, exit_code, detail)."""
    # Check the TCP boundary directly. HTTP authorization and TLS errors can
    # occur after a connection succeeds and must never count as a network deny.
    endpoint = urlsplit(url)
    script = """import errno, socket, sys
try:
    with socket.create_connection((sys.argv[1], int(sys.argv[2])), float(sys.argv[3])):
        print("connected")
except OSError as exc:
    unreachable = (errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EACCES, errno.EPERM)
    if isinstance(exc, TimeoutError) or exc.errno in unreachable:
        print("unreachable")
    else:
        print("inconclusive")
"""
    result = exec_command(
        environment_id,
        [
            "env",
            f"KILLHUB_PROBE_SESSION={probe_session}",
            "python3",
            "-I",
            "-c",
            script,
            endpoint.hostname or "",
            str(endpoint.port or (443 if endpoint.scheme == "https" else 80)),
            str(timeout),
        ],
        job_id=job_id,
        settings=settings,
        timeout=timeout + 20,
    )
    marker = (result.stdout or "").strip()
    if result.exit_code == 0 and marker == "connected":
        return "ok", 0, marker
    if result.exit_code == 0 and marker == "unreachable":
        return "denied", 0, marker
    return "inconclusive", result.exit_code, "no verified network result"


def _collect_install_cp_probe(job_id: str, settings: Settings) -> dict[str, Any] | None:
    """Retain install-phase CP denial evidence from the job stream (D65)."""
    for event in reversed(get_ledger(settings).list_events(job_id)):
        if event.type != "log":
            continue
        payload = event.payload or {}
        if payload.get("kind") != "network_probe":
            continue
        if payload.get("probe_session") == "install_cp_deny" or payload.get("phase") == "install":
            return {
                "classification": payload.get("classification"),
                "reason": payload.get("reason"),
                "target": payload.get("target"),
                "host_ok": payload.get("host_ok"),
                "egress_class": payload.get("egress_class"),
                "probe_session": payload.get("probe_session") or "install_cp_deny",
                "retained_from": "install",
            }
    return None


def probe_timeout_enforcement(
    environment_id: str,
    *,
    job_id: str,
    settings: Settings,
) -> dict[str, Any]:
    """Adversarial busy-loop absorbed by exec timeout (D58)."""
    session = "containment_timeout"
    # Short timeout — harness must kill the guest command.
    try:
        result = exec_command(
            environment_id,
            [
                "sh",
                "-lc",
                f"export KILLHUB_PROBE_SESSION={_shell_quote(session)}; while true; do :; done",
            ],
            job_id=job_id,
            settings=settings,
            timeout=3.0,
        )
        timed_out = False
        exit_code = result.exit_code
        detail = (result.stderr or result.stdout or "")[:200]
    except Exception as exc:  # noqa: BLE001 — timeout surfaces as HarnessError
        timed_out = "timed out" in str(exc).lower() or "timeout" in str(exc).lower()
        exit_code = None
        detail = str(exc)[:200]

    # Guest must still be reachable after the kill.
    alive = exec_command(
        environment_id,
        ["sh", "-lc", "echo alive"],
        job_id=job_id,
        settings=settings,
        timeout=30,
    )
    guest_alive = alive.exit_code == 0 and "alive" in (alive.stdout or "")
    ok = timed_out and guest_alive
    absorption = {
        "kind": "infinite_loop",
        "command": "while true; do :; done",
        "absorbed": ok,
        "summary": (
            "Adversarial busy-loop absorbed by exec timeout; guest still alive"
            if ok
            else "Busy-loop was not cleanly absorbed (timeout or guest liveness failed)"
        ),
    }
    evidence = {
        "dimension": "timeout_enforcement",
        "ok": ok,
        "timed_out": timed_out,
        "guest_alive": guest_alive,
        "exit_code": exit_code,
        "detail": detail,
        "probe_session": session,
        "classification": "policy_denied" if ok else "inconclusive",
        "absorption": absorption,
    }
    _containment_event(
        job_id,
        (
            "ABSORBED ∞ loop — sandbox timeout killed busy-loop; guest alive"
            if ok
            else f"timeout_enforcement → {'ok' if ok else 'incomplete'}"
        ),
        settings=settings,
        **evidence,
    )
    _log(
        job_id,
        (
            "containment ABSORBED infinite_loop → guest alive"
            if ok
            else f"containment timeout_enforcement → {evidence['classification']}"
        ),
        settings=settings,
        kind="containment_probe",
        **evidence,
    )
    return evidence


def probe_host_access_denied(
    environment_id: str,
    *,
    job_id: str,
    settings: Settings,
    install_cp: dict[str, Any] | None,
) -> dict[str, Any]:
    """Guest cannot reach host/CP/management with live target + positive control."""
    cfg = settings
    session = "containment_host_deny"
    targets: list[dict[str, str]] = []

    cp_url = (cfg.control_plane_probe_url or "").strip()
    if cp_url:
        targets.append({"name": "control_plane", "url": cp_url})

    # Microsandbox host alias observed on VX1 guests.
    targets.append(
        {
            "name": "host_internal",
            "url": "http://host.microsandbox.internal/",
        }
    )
    targets.append({"name": "host_gateway_ip", "url": "http://172.16.0.5/"})

    # Management-ish: MSB host hostname if parseable as SSH target.
    host = (cfg.msb_host or "").strip()
    if "@" in host:
        host = host.split("@", 1)[1]
    host = host.split(":")[0]
    if host and host not in {"local", "localhost", "127.0.0.1"}:
        targets.append({"name": "msb_host", "url": f"http://{host}/"})

    if cfg.install_egress_probe_url:
        targets.append({"name": "public_egress", "url": cfg.install_egress_probe_url})
    if cfg.management_probe_address:
        authority = urlsplit(f"tcp://{cfg.management_probe_address}").hostname
        host_literal = f"[{authority}]" if authority and ":" in authority else authority
        targets.append({"name": "host_web", "url": f"http://{host_literal}:80/"})
        targets.append({"name": "host_management", "url": f"tcp://{cfg.management_probe_address}"})

    probes: list[dict[str, Any]] = []
    any_bypass = False

    gateway_peer, gateway_detail = _gateway_control(cfg.containment_gateway_interface.strip())
    for target in targets:
        url = target["url"]
        if target["name"] in {"host_internal", "host_gateway_ip"}:
            # These addresses belong to the guest virtual network. Dialling
            # them from Plane 1 can reach an unrelated host on its default route.
            peer, host_detail = gateway_peer, gateway_detail
            if peer and target["name"] == "host_internal":
                # Require the guest alias to resolve exclusively to the same reference peer.
                resolved = exec_command(
                    environment_id,
                    [
                        "python3",
                        "-I",
                        "-c",
                        "import socket; print(sorted({r[4][0] for r in socket.getaddrinfo("
                        "'host.microsandbox.internal', 80, type=socket.SOCK_STREAM)}) "
                        "== ['172.16.0.5'])",
                    ],
                    job_id=job_id,
                    settings=cfg,
                    timeout=10,
                )
                if resolved.exit_code != 0 or resolved.stdout.strip() != "True":
                    peer, host_detail = None, "guest_alias_peer_unverified"
        else:
            peer, host_detail = _tcp_positive_control(url)
        host_ok = peer is not None
        guest_class, guest_code, guest_detail = _guest_fetch(
            environment_id,
            peer or url,
            job_id=job_id,
            settings=cfg,
            probe_session=session,
        )

        if guest_class == "ok":
            classification = "policy_bypass"
            any_bypass = True
        elif host_ok and guest_class == "denied":
            classification = "policy_denied"
        elif guest_class == "tooling_missing":
            classification = "tooling_missing"
        else:
            classification = "inconclusive"

        item = {
            "name": target["name"],
            "url": url,
            "host_ok": host_ok,
            "host_detail": host_detail,
            "checked_peer": peer,
            "guest_class": guest_class,
            "guest_exit": guest_code,
            "guest_detail": guest_detail,
            "classification": classification,
            "probe_session": session,
            "phase": "verify",
        }
        probes.append(item)
        _log(
            job_id,
            f"host_access probe {target['name']} → {classification}",
            settings=cfg,
            kind="network_probe",
            **item,
        )
        if classification == "policy_denied":
            _finding(
                job_id,
                f"host/management egress denied ({target['name']})",
                settings=cfg,
                source="network",
                code="host_denied_verify",
                severity="info",
                classification=classification,
                probe_session=session,
                target=url,
            )
        elif classification == "policy_bypass":
            _finding(
                job_id,
                f"host/management reachable from guest ({target['name']})",
                settings=cfg,
                source="network",
                code="host_bypass_verify",
                severity="critical",
                classification=classification,
                probe_session=session,
                target=url,
            )

    install_ok = bool(install_cp and install_cp.get("classification") == "policy_denied")
    # Guest-network aliases (host_internal / gateway) cannot get a Plane-1 positive
    # control without dialling an unrelated host (D65). Record them, but only score
    # probes that had a live host positive control — otherwise claim stays forever
    # incomplete even when CP + management denials are solid.
    scorable = [p for p in probes if p.get("host_ok")]
    for probe in probes:
        probe["scorable"] = bool(probe.get("host_ok"))
    cp_probe = next((p for p in probes if p["name"] == "control_plane"), None)
    # Proven host deny needs verify-phase policy_denied on every scorable probe
    # AND install-phase CP deny so offline mode cannot masquerade as isolation.
    proven = (
        bool(cp_url)
        and install_ok
        and cp_probe is not None
        and cp_probe["classification"] == "policy_denied"
        and bool(scorable)
        and all(p["classification"] == "policy_denied" for p in scorable)
        and not any_bypass
    )
    if any_bypass:
        classification = "policy_bypass"
    elif proven:
        classification = "policy_denied"
    else:
        classification = "inconclusive"

    evidence = {
        "dimension": "host_access_denied",
        "ok": proven,
        "classification": classification,
        "probes": probes,
        "scorable_count": len(scorable),
        "install_cp_probe": install_cp,
        "probe_session": session,
    }
    _containment_event(
        job_id,
        f"host_access_denied → {classification}",
        settings=cfg,
        **{k: v for k, v in evidence.items() if k != "probes"},
        probe_count=len(probes),
    )
    return evidence


def _guest_ipv4(environment_id: str, *, job_id: str, settings: Settings) -> str | None:
    result = exec_command(
        environment_id,
        ["sh", "-lc", "hostname -I 2>/dev/null || true"],
        job_id=job_id,
        settings=settings,
        timeout=30,
    )
    for token in (result.stdout or "").split():
        if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", token):
            return token
    return None


def probe_sibling_access_denied(
    environment_id: str,
    *,
    job_id: str,
    settings: Settings,
    cli: MsbCli | None = None,
) -> dict[str, Any]:
    """Create ephemeral sibling; guest must not reach it (D58/D65)."""
    cfg = settings
    msb = cli or MsbCli(cfg)
    session = "containment_sibling_deny"
    sibling_name = f"kh-sib-{job_id.replace('-', '')[:20]}"
    evidence: dict[str, Any] = {
        "dimension": "sibling_access_denied",
        "probe_session": session,
        "sibling": sibling_name,
    }

    try:
        owner = get_ledger(cfg).get_job(job_id)
        if owner is None:
            raise ContainmentError("Sibling probe requires a ledger job")
        plan = apply_killhub_net_policy(
            EnvironmentPlan(
                image=(cfg.containment_sibling_image or cfg.msb_default_image or "debian").strip(),
                cpus=1,
                memory="512M",
            ),
            cfg,
        )
        # Best-effort remove leftover.
        msb.remove(sibling_name, force=True)
        msb.create(
            name=sibling_name,
            plan=plan,
            labels={
                "killhub.managed": "1",
                "killhub.probe": "sibling",
                LABEL_PROBE_OWNER: job_id,
                LABEL_EXPIRES: owner.expires_at,
                "killhub.probe_session": session,
            },
        )
        wait_until_ready(sibling_name, settings=cfg, cli=msb, timeout_seconds=90)

        # Bare MSB_DEFAULT_IMAGE has no python/wget — install minimal serve tooling
        # while sibling still has create-time public egress (D65 positive control).
        tools = exec_command(
            sibling_name,
            [
                "sh",
                "-lc",
                "export DEBIAN_FRONTEND=noninteractive; "
                "if command -v python3 >/dev/null 2>&1 && "
                "(command -v wget >/dev/null 2>&1 || command -v curl >/dev/null 2>&1); then "
                "echo tools_ok; exit 0; fi; "
                "if command -v apt-get >/dev/null 2>&1; then "
                "apt-get -o Acquire::Retries=2 update -qq && "
                "apt-get -o Acquire::Retries=2 install -y -qq python3 wget ca-certificates; "
                "elif command -v apk >/dev/null 2>&1; then "
                "apk add --no-cache python3 wget curl ca-certificates; "
                "else echo tooling_missing; exit 3; fi",
            ],
            job_id=job_id,
            settings=cfg,
            timeout=300,
        )
        evidence["sibling_tools_exit"] = tools.exit_code
        if tools.exit_code != 0:
            evidence.update(
                {
                    "ok": False,
                    "classification": "tooling_missing" if tools.exit_code == 3 else "infra_error",
                    "reason": "sibling_tooling_install_failed",
                    "detail": ((tools.stderr or tools.stdout) or "")[:200],
                }
            )
            _containment_event(
                job_id,
                f"sibling_access_denied → {evidence.get('classification')}",
                settings=cfg,
                **{k: v for k, v in evidence.items() if k != "guest_detail"},
            )
            return evidence

        # Start an HTTP server on all interfaces so a cross-sandbox attempt is meaningful.
        start = exec_command(
            sibling_name,
            [
                "sh",
                "-lc",
                "mkdir -p /tmp/killhub && "
                "nohup python3 -m http.server 8080 --bind 0.0.0.0 "
                ">/tmp/killhub/sib.log 2>&1 & echo $!",
            ],
            job_id=job_id,
            settings=cfg,
            timeout=30,
        )
        sibling_ip = _guest_ipv4(sibling_name, job_id=job_id, settings=cfg)
        evidence["sibling_ip"] = sibling_ip
        evidence["sibling_start_exit"] = start.exit_code

        # Positive control: sibling serves locally (retry — server needs a beat).
        if sibling_ip is None:
            evidence.update(ok=False, classification="inconclusive", reason="no_sibling_ip")
            return evidence
        sibling_url = f"http://{sibling_ip}:8080/"
        local = exec_command(
            sibling_name,
            [
                "sh",
                "-lc",
                "for i in 1 2 3 4 5 6; do "
                f"wget -qO- --timeout=2 {sibling_url} >/dev/null 2>&1 && exit 0; "
                f"curl -fsS --max-time 2 {sibling_url} >/dev/null 2>&1 && exit 0; "
                "sleep 1; done; exit 1",
            ],
            job_id=job_id,
            settings=cfg,
            timeout=40,
        )
        sibling_up = local.exit_code == 0
        evidence["sibling_local_ok"] = sibling_up

        if not sibling_ip or not sibling_up:
            evidence.update(
                {
                    "ok": False,
                    "classification": "inconclusive",
                    "reason": "sibling_not_addressable_or_not_serving",
                }
            )
        else:
            url = sibling_url
            guest_class, guest_code, guest_detail = _guest_fetch(
                environment_id,
                url,
                job_id=job_id,
                settings=cfg,
                probe_session=session,
            )
            if guest_class == "ok":
                classification = "policy_bypass"
                ok = False
            elif guest_class == "tooling_missing":
                classification = "tooling_missing"
                ok = False
            elif guest_class == "denied":
                classification = "policy_denied"
                ok = True
            else:
                classification = "inconclusive"
                ok = False
            evidence.update(
                {
                    "ok": ok,
                    "classification": classification,
                    "target": url,
                    "guest_class": guest_class,
                    "guest_exit": guest_code,
                    "guest_detail": guest_detail,
                }
            )
            _log(
                job_id,
                f"sibling_access probe → {classification}",
                settings=cfg,
                kind="network_probe",
                probe_session=session,
                target=url,
                classification=classification,
                sibling=sibling_name,
            )
            if classification == "policy_denied":
                _finding(
                    job_id,
                    "sibling sandbox egress denied (expected)",
                    settings=cfg,
                    source="network",
                    code="sibling_denied",
                    severity="info",
                    classification=classification,
                    probe_session=session,
                )
            elif classification == "policy_bypass":
                _finding(
                    job_id,
                    "sibling sandbox reachable from guest",
                    settings=cfg,
                    source="network",
                    code="sibling_bypass",
                    severity="critical",
                    classification=classification,
                    probe_session=session,
                )
    except Exception as exc:  # noqa: BLE001
        evidence.update(
            {
                "ok": False,
                "classification": "infra_error",
                "reason": f"{exc.__class__.__name__}: {exc}"[:300],
            }
        )
        logger.exception("sibling probe failed for %s", job_id)
    finally:
        try:
            msb.stop(sibling_name, force=True)
            msb.remove(sibling_name, force=True)
        except Exception:  # noqa: BLE001
            logger.exception("sibling cleanup failed for %s", sibling_name)

    _containment_event(
        job_id,
        f"sibling_access_denied → {evidence.get('classification')}",
        settings=cfg,
        **{k: v for k, v in evidence.items() if k != "guest_detail"},
    )
    return evidence


def probe_host_liveness(
    environment_id: str,
    *,
    job_id: str,
    settings: Settings,
    during: str = "after_timeout_probe",
) -> dict[str, Any]:
    """Host/control-plane remains healthy during containment (D58)."""
    cfg = settings
    session = "containment_host_liveness"
    checks: list[dict[str, Any]] = []

    # 1) Guest still responds (sandbox not crashed by probes).
    guest = exec_command(
        environment_id,
        ["sh", "-lc", "echo host_liveness_guest_ok"],
        job_id=job_id,
        settings=cfg,
        timeout=30,
    )
    guest_ok = guest.exit_code == 0 and "host_liveness_guest_ok" in (guest.stdout or "")
    checks.append({"name": "guest_exec", "ok": guest_ok})

    # 2) Known-live CP URL from host.
    cp_url = (cfg.control_plane_probe_url or "").strip()
    if cp_url:
        host_ok, host_detail = _host_fetch_ok(cp_url)
        checks.append(
            {
                "name": "control_plane_host_fetch",
                "ok": host_ok,
                "detail": host_detail,
                "url": cp_url,
            }
        )

    # 3) Live inventory still lists this sandbox.
    try:
        live = list_live_environment_ids(settings=cfg)
        listed = environment_id in live
    except Exception as exc:  # noqa: BLE001
        listed = False
        checks.append(
            {
                "name": "live_inventory",
                "ok": False,
                "detail": f"{exc.__class__.__name__}",
            }
        )
    else:
        checks.append({"name": "live_inventory", "ok": listed})

    ok = all(c.get("ok") for c in checks) and len(checks) >= 2
    evidence = {
        "dimension": "host_liveness",
        "ok": ok,
        "classification": "policy_denied" if ok else "inconclusive",
        "during": during,
        "checks": checks,
        "probe_session": session,
    }
    # host_liveness success is not a "deny" — remap claim language for clarity.
    if ok:
        evidence["classification"] = "healthy"
    _containment_event(
        job_id,
        f"host_liveness → {'healthy' if ok else 'degraded'}",
        settings=cfg,
        **evidence,
    )
    _log(
        job_id,
        f"containment host_liveness → {evidence['classification']}",
        settings=cfg,
        kind="containment_probe",
        **{k: v for k, v in evidence.items() if k != "checks"},
        check_count=len(checks),
    )
    return evidence


def _dimension_proven(dim: dict[str, Any]) -> bool:
    name = dim.get("dimension")
    if name == "host_liveness":
        return bool(dim.get("ok"))
    if name == "timeout_enforcement":
        return bool(dim.get("ok"))
    # Deny dimensions require policy_denied specifically (D65).
    return dim.get("classification") == "policy_denied" and bool(dim.get("ok"))


def compute_claim(dimensions: dict[str, dict[str, Any]]) -> str:
    """incomplete unless every required dimension is proven (D58/D66)."""
    for key in DIMENSIONS:
        dim = dimensions.get(key)
        if not dim or not _dimension_proven(dim):
            return "incomplete"
    return "proven"


def run_containment_probes(
    job_id: str,
    *,
    settings: Settings | None = None,
    cli: MsbCli | None = None,
) -> ContainmentResult:
    """
    Run the D58 matrix + canary scan. Persist containment events + receipt fields.

    Never sets status=completed and never destroys the sandbox.
    """
    cfg = settings or get_settings()
    ledger = get_ledger(cfg)
    job = ledger.get_job(job_id)
    if job is None:
        raise ContainmentError(f"unknown job_id: {job_id}", code="not_found")
    if not job.sandbox_id:
        raise ContainmentError("no live sandbox for containment", code="no_sandbox")
    environment_id = job.sandbox_id
    msb = cli or MsbCli(cfg)

    ledger.update_job_fields(
        job_id,
        status="scanning" if job.status not in {"failed", "cancelled"} else job.status,
        current_step="containment matrix",
        progress=max(job.progress, 92),
    )
    ledger.append_event(
        job_id,
        typ="status",
        message="scanning",
        payload={"status": "scanning", "step": "containment"},
    )

    install_cp = _collect_install_cp_probe(job_id, cfg)
    dimensions: dict[str, Any] = {}
    network_probes: list[dict[str, Any]] = []

    timeout_ev = probe_timeout_enforcement(environment_id, job_id=job_id, settings=cfg)
    dimensions["timeout_enforcement"] = timeout_ev

    host_live = probe_host_liveness(
        environment_id,
        job_id=job_id,
        settings=cfg,
        during="after_timeout_probe",
    )
    dimensions["host_liveness"] = host_live

    host_deny = probe_host_access_denied(
        environment_id,
        job_id=job_id,
        settings=cfg,
        install_cp=install_cp,
    )
    dimensions["host_access_denied"] = host_deny
    network_probes.extend(host_deny.get("probes") or [])

    sibling = probe_sibling_access_denied(environment_id, job_id=job_id, settings=cfg, cli=msb)
    dimensions["sibling_access_denied"] = sibling
    if sibling.get("target"):
        network_probes.append(
            {
                "name": "sibling",
                "url": sibling.get("target"),
                "classification": sibling.get("classification"),
                "probe_session": sibling.get("probe_session"),
            }
        )

    # Re-check host liveness after sibling/network probes.
    host_live_final = probe_host_liveness(
        environment_id,
        job_id=job_id,
        settings=cfg,
        during="after_network_probes",
    )
    # Both observations must pass. Preserve the first failure in the receipt.
    if host_live.get("ok"):
        dimensions["host_liveness"] = host_live_final

    canary = scan_canaries(
        environment_id,
        job_id=job_id,
        settings=cfg,
        probe_sessions_exclude={
            "containment_timeout",
            "containment_host_deny",
            "containment_sibling_deny",
            "containment_host_liveness",
            "install_cp_deny",
            "containment_canary_deliberate",
        },
    )

    claim = compute_claim(dimensions)
    # Canary unexpected hits are findings (D44) and do not clear a proven matrix.
    # Scanner tooling/infra failure must not invent proven (D66).
    if canary.get("status") in {"error", "tooling_missing"}:
        claim = "incomplete"

    payload = {
        "claim": claim,
        "at": utc_now(),
        "dimensions": dimensions,
        "network_probes": network_probes,
        "canary_scan": {
            "status": canary.get("status"),
            "unexpected_hits": canary.get("unexpected_hits"),
            "hit_count": canary.get("hit_count"),
            # Never include plaintext canary values.
            "known_ids": canary.get("known_ids"),
        },
        "install_cp_probe": install_cp,
    }

    ledger.append_event(
        job_id,
        typ="containment",
        message=f"containment claim={claim}",
        payload=payload,
    )
    _log(
        job_id,
        f"containment matrix claim={claim}",
        settings=cfg,
        kind="containment_probe",
        claim=claim,
        dimensions={k: v.get("classification") or v.get("ok") for k, v in dimensions.items()},
    )

    # Persist on receipt (outlives sandbox) — does not terminal-complete the job.
    existing = None
    try:
        existing = ledger.get_receipt(job_id)
    except Exception:  # noqa: BLE001
        existing = None
    ledger.upsert_receipt(
        job_id,
        verification=(existing or {}).get("verification") or job.verification,
        containment=payload,
        lifecycle=(existing or {}).get("lifecycle"),
        dossier={
            **((existing or {}).get("dossier") or {}),
            "containment_at": payload["at"],
        },
    )

    # Stay in verifying/scanning — never completed (D37). Hard bypass may fail job (D66).
    bypass = any(
        dimensions[d].get("classification") == "policy_bypass"
        for d in ("host_access_denied", "sibling_access_denied")
        if d in dimensions
    )
    if bypass and job.status not in {"failed", "cancelled", "completed"}:
        # Receipt above already holds the containment matrix; finalize atomically (D61).
        ledger.finalize_job(
            job_id,
            status="failed",
            # The verdict carries the observed policy bypass without changing readiness.
            include_verdict=True,
            receipt={},
            event_message="failed",
            event_payload={"reason": "containment_bypass"},
            current_step="containment policy bypass",
            progress=100,
            error="containment policy_bypass",
        )
    elif job.status not in {"failed", "cancelled", "completed"}:
        ledger.update_job_fields(
            job_id,
            status="verifying",
            current_step=f"containment claim={claim}",
            progress=95,
        )

    return ContainmentResult(
        job_id=job_id,
        environment_id=environment_id,
        claim=claim,
        dimensions=dimensions,
        network_probes=network_probes,
        canary_scan=canary,
        install_cp_probe=install_cp,
    )


# Back-compat wrapper used by older imports / tests.
def network_probe(
    environment_id: str,
    *,
    job_id: str,
    phase: str = "verify",
    settings: Settings | None = None,
    cli: Any = None,
) -> dict[str, Any]:
    """Run (or summarize) network containment probes for a phase."""
    cfg = settings or get_settings()
    if phase == "install":
        # Install-phase probing lives in install.py; return retained evidence.
        retained = _collect_install_cp_probe(job_id, cfg)
        return {
            "status": "retained" if retained else "missing",
            "claim": (
                "proven"
                if retained and retained.get("classification") == "policy_denied"
                else "incomplete"
            ),
            "phase": phase,
            "install_cp_probe": retained,
        }
    result = run_containment_probes(job_id, settings=cfg, cli=cli)
    return {
        "status": "ok",
        "claim": result.claim,
        "phase": phase,
        "dimensions": list(result.dimensions.keys()),
        "environment_id": environment_id,
    }
