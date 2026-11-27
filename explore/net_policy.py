"""Killhub Plane 2 network policy composition for `msb create` (D39, D43)."""

from __future__ import annotations

from dataclasses import dataclass

from config import Settings, get_settings


@dataclass(frozen=True)
class NetPolicy:
    """Concrete msb flags for a network phase."""

    profiles: tuple[str, ...]
    rules: tuple[str, ...]
    net_default: str | None = None  # "allow" | "deny" | None
    no_net: bool = False
    phase: str = "install"

    def as_msb_args(self) -> list[str]:
        args: list[str] = []
        if self.no_net:
            args.append("--no-net")
        if self.net_default:
            args.extend(["--net-default", self.net_default])
        for profile in self.profiles:
            args.extend(["--net", profile])
        for rule in self.rules:
            args.extend(["--net-rule", rule])
        return args


def _extra_from_msb_net_policy(raw: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not raw or not raw.strip():
        return (), ()
    profiles: list[str] = []
    rules: list[str] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        if token.startswith("rule:"):
            rules.append(token[len("rule:") :])
        else:
            profiles.append(token)
    return tuple(profiles), tuple(rules)


def _deny_targets_from_settings(cfg: Settings) -> list[str]:
    """Control-plane + management deny targets (hostnames / IPs / CIDRs)."""
    targets: list[str] = []
    raw = (getattr(cfg, "control_plane_deny_hosts", None) or "").strip()
    for part in raw.split(","):
        t = part.strip()
        if t and t not in targets:
            targets.append(t)
    # Always deny the VX1 host address when MSB_HOST looks like user@ip.
    host = (cfg.msb_host or "").strip().removeprefix("ssh://")
    if "@" in host:
        host = host.split("@", 1)[1]
    if host and host not in {"local", "localhost", "127.0.0.1"} and host not in targets:
        # Bare hostname/IP only — skip if it still contains path junk.
        if "/" not in host and " " not in host:
            targets.append(host)
    return targets


def install_phase_policy(settings: Settings | None = None) -> NetPolicy:
    """
    Install/provision phase (D39 + D43 phase 1).

    Concrete flags (also documented in ARCHITECTURE.md):

      msb create … \\
        --net public \\
        --net-rule deny@host \\
        --net-rule deny@private \\
        --net-rule deny@meta \\
        --net-rule deny@<control-plane-host>… \\
        [--net / --net-rule from MSB_NET_POLICY]

    Sibling isolation remains Microsandbox default (inter-sandbox denied).
    """
    cfg = settings or get_settings()
    # allow@dns must precede deny@private: Microsandbox gateway DNS sits on the
    # guest private pool (172.16/12); denying private first blackholes apt/git.
    rules = [
        "allow@dns",
        "deny@host",
        "deny@private",
        "deny@meta",
    ]
    for target in _deny_targets_from_settings(cfg):
        rules.append(f"deny@{target}")
    extra_profiles, extra_rules = _extra_from_msb_net_policy(cfg.msb_net_policy)
    profiles = ("public",) + tuple(p for p in extra_profiles if p != "public")
    # Extra rules after Killhub denies so operator allows are still evaluated —
    # msb says explicit --net-rule entries are evaluated before profile rules;
    # order among explicit rules: first match wins, so Killhub denies come first
    # (except allow@dns, which must win over deny@private).
    return NetPolicy(
        profiles=profiles,
        rules=tuple(dict.fromkeys([*rules, *extra_rules])),
        phase="install",
    )


def verify_phase_policy() -> NetPolicy:
    """Verify/containment phase (D43 phase 2) — deny-all remaining egress (loopback only).

    Applied via snapshot restore / create --no-net (msb cannot change net live).
    Equivalent to `--net-default deny` with no public allows — not merely
    registries-denied.
    """
    return NetPolicy(
        profiles=(),
        rules=(),
        no_net=True,
        net_default="deny",
        phase="verify",
    )


def merge_plan_with_killhub_policy(
    *,
    image: str,
    cpus: float,
    memory: str,
    replace: bool = False,
    settings: Settings | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return (profiles, rules) that always include Killhub install policy."""
    policy = install_phase_policy(settings)
    return policy.profiles, policy.rules
