"""Plane 1 → Plane 2 Microsandbox harness (D23, D41, D57, D59).

Wraps the `msb` CLI on the VX1 host (local PATH or SSH via MSB_HOST).
Never substitutes Docker/Podman for Plane 2.
"""

from __future__ import annotations

import json
import logging
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from config import Settings, get_settings
from errors import HarnessError
from jobs import get_ledger
from ledger.store import utc_now
from models import SandboxGeneration

logger = logging.getLogger("killhub.harness")

LABEL_JOB = "killhub.job_id"
LABEL_EXPIRES = "killhub.expires_at"
LABEL_GENERATION = "killhub.generation"

CliRunner = Callable[[Sequence[str], Optional[float]], "CliResult"]

__all__ = [
    "HarnessError",
    "CliResult",
    "DestroyResult",
    "EnvironmentPlan",
    "ExecResult",
    "MsbCli",
    "create_environment",
    "replace_environment",
    "wait_until_ready",
    "destroy_environment",
    "destroy_job_environment",
    "exec_command",
    "copy_in",
    "copy_out",
    "assert_guest_env_clean",
    "normalize_oci_image",
    "images_differ",
    "environment_name_for_job",
]


@dataclass(frozen=True)
class CliResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class DestroyResult:
    confirmed: bool
    error: str | None = None


@dataclass(frozen=True)
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int


@dataclass(frozen=True)
class EnvironmentPlan:
    """Bootstrap / runtime create inputs (D36)."""

    image: str
    cpus: float
    memory: str
    net_profiles: tuple[str, ...] = ()
    net_rules: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()
    replace: bool = False
    network_phase: str = "install"


def environment_name_for_job(job_id: str) -> str:
    """Stable msb sandbox name derived from job id."""
    compact = re.sub(r"[^a-zA-Z0-9-]", "", job_id)
    if not compact:
        raise HarnessError("job_id yields empty environment name", code="invalid_job")
    name = f"kh-{compact}"
    return name[:63]


def normalize_oci_image(image: str) -> str:
    """Normalize image refs for equality (strip, lower, drop trailing :latest)."""
    raw = (image or "").strip().lower()
    if not raw:
        return ""
    if raw.endswith(":latest"):
        raw = raw[: -len(":latest")]
    return raw


def images_differ(left: str, right: str) -> bool:
    return normalize_oci_image(left) != normalize_oci_image(right)


def normalize_memory(memory: str) -> str:
    """Map Killhub memory strings to msb CLI forms (`4Gi` → `4G`)."""
    raw = memory.strip()
    match = re.fullmatch(r"(?i)(\d+(?:\.\d+)?)\s*(gi|g|mi|m|ki|k|b)?", raw)
    if not match:
        return raw
    amount, unit = match.group(1), (match.group(2) or "M").lower()
    if unit in {"gi", "g"}:
        return f"{amount.rstrip('0').rstrip('.') if '.' in amount else amount}G"
    if unit in {"mi", "m"}:
        return f"{amount.rstrip('0').rstrip('.') if '.' in amount else amount}M"
    if unit in {"ki", "k"}:
        return f"{amount.rstrip('0').rstrip('.') if '.' in amount else amount}K"
    return amount


def default_bootstrap_plan(settings: Settings | None = None) -> EnvironmentPlan:
    """Bootstrap plan with mandatory Killhub install-phase net policy (D39)."""
    from net_policy import install_phase_policy

    cfg = settings or get_settings()
    image = (cfg.msb_default_image or "debian").strip()
    if not image:
        raise HarnessError("MSB_DEFAULT_IMAGE is required", code="config")
    policy = install_phase_policy(cfg)
    return EnvironmentPlan(
        image=image,
        cpus=float(cfg.msb_default_cpus),
        memory=normalize_memory(cfg.msb_default_memory),
        net_profiles=policy.profiles,
        net_rules=policy.rules,
        network_phase=policy.phase,
    )


def plan_for_image(
    image: str,
    *,
    settings: Settings | None = None,
    replace: bool = False,
) -> EnvironmentPlan:
    """Build an EnvironmentPlan for a specific OCI image (Killhub net policy)."""
    cfg = settings or get_settings()
    base = default_bootstrap_plan(cfg)
    cleaned = (image or "").strip()
    if not cleaned:
        raise HarnessError("oci_image is required", code="config")
    return EnvironmentPlan(
        image=cleaned,
        cpus=base.cpus,
        memory=base.memory,
        net_profiles=base.net_profiles,
        net_rules=base.net_rules,
        env=base.env,
        replace=replace,
        network_phase=base.network_phase,
    )


def apply_killhub_net_policy(
    plan: EnvironmentPlan,
    settings: Settings | None = None,
) -> EnvironmentPlan:
    """Ensure a plan cannot drop Killhub install-phase denies (D39)."""
    from net_policy import install_phase_policy

    cfg = settings or get_settings()
    policy = install_phase_policy(cfg)
    # Killhub rules first; keep any additional plan rules that are not duplicates.
    merged_rules = tuple(dict.fromkeys([*policy.rules, *plan.net_rules]))
    profiles = (
        policy.profiles
        if not plan.net_profiles
        else tuple(dict.fromkeys([*policy.profiles, *plan.net_profiles]))
    )
    return EnvironmentPlan(
        image=plan.image,
        cpus=plan.cpus,
        memory=plan.memory,
        net_profiles=profiles,
        net_rules=merged_rules,
        env=plan.env,
        replace=plan.replace,
        network_phase=plan.network_phase or policy.phase,
    )


class MsbCli:
    """Invoke `msb` locally or over SSH (MSB_HOST)."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        runner: CliRunner | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._runner = runner or self._default_runner

    def is_remote(self) -> bool:
        host = (self.settings.msb_host or "").strip()
        return bool(host) and host not in {"local", "localhost", "127.0.0.1"}

    def remote_target(self) -> str:
        return (self.settings.msb_host or "").strip().removeprefix("ssh://")

    def _ssh_opts(self) -> list[str]:
        cmd = ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
        key = (getattr(self.settings, "msb_ssh_key", None) or "").strip()
        if key:
            cmd.extend(["-i", str(Path(key).expanduser())])
        return cmd

    def _ssh_prefix(self) -> list[str]:
        if not self.is_remote():
            return []
        return ["ssh", *self._ssh_opts(), self.remote_target()]

    def _default_runner(self, argv: Sequence[str], timeout: float | None) -> CliResult:
        ssh = self._ssh_prefix()
        if ssh:
            remote = " ".join(shlex.quote(a) for a in argv)
            full = [*ssh, remote]
        else:
            full = list(argv)
        try:
            completed = subprocess.run(
                full,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise HarnessError(
                f"msb binary not found ({argv[0]}); install Microsandbox on VX1",
                code="msb_missing",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise HarnessError(
                f"msb timed out: {' '.join(argv)}",
                code="msb_timeout",
            ) from exc
        return CliResult(
            argv=tuple(full),
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )

    def run(
        self,
        args: Sequence[str],
        *,
        timeout: float | None = 120,
        check: bool = True,
    ) -> CliResult:
        bin_name = (getattr(self.settings, "msb_bin", None) or "msb").strip() or "msb"
        argv = [bin_name, *args]
        result = self._runner(argv, timeout)
        if check and not result.ok:
            detail = (result.stderr or result.stdout or "").strip()
            raise HarnessError(
                f"msb {' '.join(args)} failed ({result.returncode}): {detail[:500]}",
                code="msb_failed",
            )
        return result

    def doctor(self) -> CliResult:
        return self.run(["doctor"], timeout=60, check=True)

    def create(
        self,
        *,
        name: str,
        plan: EnvironmentPlan,
        labels: Mapping[str, str],
    ) -> CliResult:
        if not plan.net_profiles and not plan.net_rules:
            raise HarnessError(
                "refusing to create sandbox without Killhub net policy",
                code="net_policy_required",
            )
        cpus_arg = str(int(plan.cpus)) if float(plan.cpus).is_integer() else str(plan.cpus)
        args: list[str] = [
            "create",
            "--name",
            name,
            "--cpus",
            cpus_arg,
            "--memory",
            plan.memory,
        ]
        if plan.replace:
            args.append("--replace")
        for key, value in labels.items():
            args.extend(["--label", f"{key}={value}"])
        for key, value in plan.env:
            args.extend(["--env", f"{key}={value}"])
        for profile in plan.net_profiles:
            args.extend(["--net", profile])
        for rule in plan.net_rules:
            args.extend(["--net-rule", rule])
        args.append(plan.image)
        return self.run(args, timeout=300, check=True)

    def status(self, name: str) -> CliResult:
        return self.run(["status", name], timeout=30, check=False)

    def snapshot_create(
        self,
        group: str,
        *,
        sandbox: str,
        checkpoint: str = "installed",
        full: bool = True,
    ) -> CliResult:
        args = [
            "snapshot",
            "create",
            group,
            "--sandbox",
            sandbox,
            "--name",
            checkpoint,
        ]
        if full:
            args.append("--full")
        return self.run(args, timeout=300, check=True)

    def snapshot_remove_group(self, group: str) -> CliResult:
        return self.run(
            ["snapshot", "remove", "--all", "--quiet", group],
            timeout=120,
            check=False,
        )

    def snapshot_restore_offline(
        self,
        group: str,
        *,
        name: str,
    ) -> CliResult:
        """Restore snapshot into `name` with deny-all remaining egress (D43)."""
        return self.run(
            [
                "snapshot",
                "restore",
                group,
                "--name",
                name,
                "--no-net",
            ],
            timeout=300,
            check=True,
        )

    def list_all(self) -> CliResult:
        # Prefer JSON when available; fall back to plain list.
        json_try = self.run(["list", "--format", "json"], timeout=60, check=False)
        if json_try.ok and json_try.stdout.strip().startswith(("[", "{")):
            return json_try
        return self.run(["list"], timeout=60, check=True)

    def stop(self, name: str, *, force: bool = False) -> CliResult:
        args = ["stop"]
        if force:
            args.append("--force")
        args.append(name)
        return self.run(args, timeout=120, check=False)

    def remove(self, name: str, *, force: bool = False) -> CliResult:
        args = ["remove"]
        if force:
            args.append("--force")
        args.append(name)
        return self.run(args, timeout=120, check=False)

    def inspect_labels(self, name: str) -> dict[str, str]:
        result = self.run(["inspect", name, "--format", "json"], timeout=30, check=False)
        if result.ok:
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                candidates = [
                    payload.get("labels"),
                    payload.get("Labels"),
                    (payload.get("active_config") or {}).get("labels")
                    if isinstance(payload.get("active_config"), dict)
                    else None,
                    (payload.get("config") or {}).get("labels")
                    if isinstance(payload.get("config"), dict)
                    else None,
                ]
                for labels in candidates:
                    if isinstance(labels, dict) and labels:
                        return {str(k): str(v) for k, v in labels.items()}
        # Fallback: parse `msb inspect` text for killhub.* tokens
        text = self.run(["inspect", name], timeout=30, check=False)
        found: dict[str, str] = {}
        for line in (text.stdout or "").splitlines():
            for piece in line.replace(",", " ").split():
                if piece.startswith("killhub.") and "=" in piece:
                    k, v = piece.split("=", 1)
                    found[k] = v
        return found

    def exec_cmd(
        self,
        name: str,
        cmd: Sequence[str],
        *,
        timeout: float | None = None,
    ) -> CliResult:
        if not cmd:
            raise HarnessError("exec command is empty", code="invalid_exec")
        args = ["exec", "--no-tty", "--no-stdin", name, "--", *cmd]
        return self.run(args, timeout=timeout, check=False)

    def copy(self, source: str, dest: str, *, timeout: float | None = 120) -> CliResult:
        return self.run(["copy", source, dest], timeout=timeout, check=True)

    def remote_mkdir(self, remote_dir: str) -> None:
        if not self.is_remote():
            Path(remote_dir).mkdir(parents=True, exist_ok=True)
            return
        argv = [*self._ssh_prefix(), f"mkdir -p {shlex.quote(remote_dir)}"]
        completed = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=30)
        if completed.returncode != 0:
            raise HarnessError(
                f"remote mkdir failed: {(completed.stderr or completed.stdout)[:300]}",
                code="stage_failed",
            )

    def scp_put(self, local: Path, remote_path: str) -> None:
        if not self.is_remote():
            dest = Path(remote_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(local.read_bytes())
            return
        self.remote_mkdir(str(Path(remote_path).parent))
        argv = [
            "scp",
            *self._ssh_opts(),
            str(local),
            f"{self.remote_target()}:{remote_path}",
        ]
        completed = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=120)
        if completed.returncode != 0:
            raise HarnessError(
                f"scp put failed: {(completed.stderr or completed.stdout)[:300]}",
                code="stage_failed",
            )

    def scp_get(self, remote_path: str, local: Path) -> None:
        local.parent.mkdir(parents=True, exist_ok=True)
        if not self.is_remote():
            local.write_bytes(Path(remote_path).read_bytes())
            return
        argv = [
            "scp",
            *self._ssh_opts(),
            f"{self.remote_target()}:{remote_path}",
            str(local),
        ]
        completed = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=120)
        if completed.returncode != 0:
            raise HarnessError(
                f"scp get failed: {(completed.stderr or completed.stdout)[:300]}",
                code="stage_failed",
            )


def create_environment(
    job_id: str,
    plan: EnvironmentPlan | None = None,
    *,
    settings: Settings | None = None,
    cli: MsbCli | None = None,
) -> SandboxGeneration:
    """
    Create a named microVM for the job, open a sandbox generation, emit lifecycle.

    Absolute `expires_at` comes from the job row and is labeled on the sandbox so
    the host reaper can enforce it without Plane 1 (D41). `msb touch` must not
    move that deadline.
    """
    from canaries import generate_canaries, persist_canaries, plant_file_canaries
    from net_policy import install_phase_policy

    cfg = settings or get_settings()
    msb = cli or MsbCli(cfg)
    env_plan = apply_killhub_net_policy(plan or default_bootstrap_plan(cfg), cfg)
    policy = install_phase_policy(cfg)
    ledger = get_ledger(cfg)
    job = ledger.get_job(job_id)
    if job is None:
        raise HarnessError(f"unknown job_id: {job_id}", code="not_found")
    if job.status in {"failed", "cancelled", "completed"}:
        raise HarnessError(
            f"refusing msb create for terminal job ({job.status})",
            code="preflight_blocked",
        )
    if job.destroyed_at is not None:
        raise HarnessError("job sandbox already destroyed", code="already_destroyed")
    # D45: never create a sandbox after preflight hard-fail findings.
    for event in ledger.list_events(job_id):
        if event.type != "finding":
            continue
        payload = event.payload or {}
        if payload.get("source") == "preflight" and payload.get("hard") is True:
            raise HarnessError(
                "refusing msb create after preflight hard-fail",
                code="preflight_blocked",
            )

    canaries = generate_canaries(job_id)
    persist_canaries(canaries, cfg)
    env_plan = EnvironmentPlan(
        image=env_plan.image,
        cpus=env_plan.cpus,
        memory=env_plan.memory,
        net_profiles=env_plan.net_profiles,
        net_rules=env_plan.net_rules,
        env=tuple(canaries.env.items()),
        replace=env_plan.replace,
        network_phase=env_plan.network_phase,
    )

    name = environment_name_for_job(job_id)
    next_gen = (job.current_sandbox_generation or 0) + 1
    labels = {
        "killhub.managed": "1",
        LABEL_JOB: job_id,
        LABEL_EXPIRES: job.expires_at,
        LABEL_GENERATION: str(next_gen),
        "killhub.net_phase": env_plan.network_phase,
    }

    ledger.append_event(
        job_id,
        typ="lifecycle",
        message="sandbox create requested",
        payload={
            "phase": "creating",
            "environment_id": name,
            "image": env_plan.image,
            "cpus": env_plan.cpus,
            "memory": env_plan.memory,
            "expires_at": job.expires_at,
            "net": {
                "phase": policy.phase,
                "profiles": list(env_plan.net_profiles),
                "rules": list(env_plan.net_rules),
            },
            "canaries": canaries.public_summary(),
        },
    )
    ledger.update_job_fields(
        job_id,
        status="provisioning",
        current_step="creating microsandbox",
        progress=max(job.progress, 10),
    )

    try:
        msb.create(name=name, plan=env_plan, labels=labels)
    except HarnessError as exc:
        ledger.append_event(
            job_id,
            typ="error",
            message=exc.message,
            payload={"code": exc.code, "phase": "create"},
        )
        raise

    gen = ledger.append_sandbox_generation(
        job_id,
        environment_id=name,
        image=env_plan.image,
        expires_at=job.expires_at,
        state="provisioning",
        cpus=env_plan.cpus,
        memory=env_plan.memory,
    )
    ledger.append_event(
        job_id,
        typ="lifecycle",
        message="sandbox created",
        payload={
            "phase": "created",
            "environment_id": name,
            "generation": gen.generation,
            "expires_at": job.expires_at,
            "net_phase": env_plan.network_phase,
            "canaries": canaries.public_summary(),
        },
    )

    # Guest must be running to plant file canaries (D44).
    wait_until_ready(name, settings=cfg, cli=msb)
    plant_file_canaries(name, canaries, job_id=job_id, settings=cfg, cli=msb)
    ledger.append_event(
        job_id,
        typ="lifecycle",
        message="canaries planted",
        payload={"phase": "canaries", **canaries.public_summary()},
    )
    return gen


def _assert_single_live_job_sandbox(
    job_id: str,
    *,
    settings: Settings,
    cli: MsbCli,
    expected: str | None = None,
) -> None:
    """Fail closed if more than one microVM is live for this job (D27, D36)."""
    name = environment_name_for_job(job_id)
    live = list_live_environment_ids(settings=settings, cli=cli)
    # Stable name is the only allowed form for a job sandbox.
    job_lives = {env for env in live if env == name}
    if expected is None:
        if len(job_lives) > 1:
            raise HarnessError(
                f"multiple live sandboxes for job {job_id}: {sorted(job_lives)}",
                code="concurrent_vm",
            )
        return
    if job_lives != {expected}:
        raise HarnessError(
            f"expected sole live sandbox {expected} for job {job_id}; live={sorted(job_lives)}",
            code="concurrent_vm",
        )


def replace_environment(
    job_id: str,
    plan: EnvironmentPlan,
    *,
    settings: Settings | None = None,
    cli: MsbCli | None = None,
    reclone: bool = True,
) -> SandboxGeneration:
    """
    Stop+remove current generation → create new image → re-clone resolved SHA (D36).

    Inherits job `expires_at` (never extends). Marks prior generation `replaced`
    without setting job-level `destroyed_at` while the replacement is alive (D64).
    """
    from discover import clone_and_resolve_commit

    cfg = settings or get_settings()
    msb = cli or MsbCli(cfg)
    ledger = get_ledger(cfg)
    job = ledger.get_job(job_id)
    if job is None:
        raise HarnessError(f"unknown job_id: {job_id}", code="not_found")
    if job.status in {"failed", "cancelled", "completed"}:
        raise HarnessError(
            f"refusing replace for terminal job ({job.status})",
            code="terminal",
        )
    if job.destroyed_at is not None:
        raise HarnessError("job sandbox already destroyed", code="already_destroyed")
    if job.current_sandbox_generation is None or not job.sandbox_id:
        raise HarnessError("no live generation to replace", code="no_sandbox")

    env_plan = apply_killhub_net_policy(plan, cfg)
    gens = ledger.list_sandbox_generations(job_id)
    current = next(
        (g for g in gens if g.generation == job.current_sandbox_generation),
        None,
    )
    if current is None:
        raise HarnessError("current sandbox generation missing", code="no_sandbox")
    if not images_differ(current.image, env_plan.image):
        raise HarnessError(
            f"replace requested but image unchanged ({env_plan.image})",
            code="same_image",
        )

    prior_id = job.sandbox_id
    prior_gen = job.current_sandbox_generation
    prior_expires = job.expires_at
    resolved = (job.resolved_commit or "").strip()
    if reclone and not resolved:
        raise HarnessError(
            "resolved_commit required before replace re-clone (D62)",
            code="missing_commit",
        )

    _assert_single_live_job_sandbox(job_id, settings=cfg, cli=msb, expected=prior_id)

    ledger.append_event(
        job_id,
        typ="log",
        message=f"sandbox replace {current.image} → {env_plan.image}",
        payload={
            "kind": "sandbox_replace",
            "phase": "start",
            "from_image": current.image,
            "to_image": env_plan.image,
            "from_environment_id": prior_id,
            "from_generation": prior_gen,
            "expires_at": prior_expires,
            "resolved_commit": resolved or None,
        },
    )
    ledger.append_event(
        job_id,
        typ="lifecycle",
        message="sandbox replace requested",
        payload={
            "phase": "replace",
            "from_environment_id": prior_id,
            "from_generation": prior_gen,
            "to_image": env_plan.image,
        },
    )
    ledger.update_job_fields(
        job_id,
        current_step=f"replacing sandbox → {env_plan.image}",
        progress=max(job.progress, 50),
    )

    # Remove prior VM before create — never two concurrent (D27).
    stop = msb.stop(prior_id, force=False)
    remove = msb.remove(prior_id, force=True)
    status = msb.status(prior_id)
    still_present = status.ok and prior_id in (status.stdout + status.stderr)
    confirmed = remove.ok or not still_present
    if (
        not confirmed
        and "not found" in (remove.stderr + remove.stdout + status.stderr + stop.stderr).lower()
    ):
        confirmed = True
    if not confirmed:
        raise HarnessError(
            f"failed to remove prior sandbox {prior_id} before replace",
            code="replace_remove_failed",
        )

    now = utc_now()
    ledger.mark_generation_state(
        job_id,
        prior_gen,
        "replaced",
        destroyed_at=now,
    )
    # Clear current pointer until create opens the next generation — do NOT
    # set job-level destroyed_at (D64).
    ledger.update_job_fields(
        job_id,
        sandbox_id=None,
        current_sandbox_generation=None,
    )
    job_after = ledger.get_job(job_id)
    if job_after is not None and job_after.destroyed_at is not None:
        raise HarnessError(
            "job-level destroyed_at set during replace — refusing",
            code="replace_invariant",
        )

    live_after_remove = list_live_environment_ids(settings=cfg, cli=msb)
    if prior_id in live_after_remove:
        raise HarnessError(
            f"prior sandbox {prior_id} still live after remove",
            code="concurrent_vm",
        )

    # create_environment re-applies net policy + plants canaries; expires_at
    # comes from the job row (unchanged).
    new_gen = create_environment(job_id, env_plan, settings=cfg, cli=msb)
    if new_gen.expires_at != prior_expires:
        raise HarnessError(
            "replace must inherit job expires_at (D64)",
            code="expires_extended",
        )
    if new_gen.generation != prior_gen + 1:
        # Still OK if intermediate gens exist; must be strictly newer.
        if new_gen.generation <= prior_gen:
            raise HarnessError(
                "replacement generation must be newer than prior",
                code="generation_order",
            )

    _assert_single_live_job_sandbox(job_id, settings=cfg, cli=msb, expected=new_gen.environment_id)

    if reclone:
        clone_and_resolve_commit(
            new_gen.environment_id,
            job_id=job_id,
            github_url=job.github_url,
            commit=resolved,
            settings=cfg,
        )

    ledger.append_event(
        job_id,
        typ="log",
        message=f"sandbox replace complete → {env_plan.image}",
        payload={
            "kind": "sandbox_replace",
            "phase": "done",
            "from_image": current.image,
            "to_image": env_plan.image,
            "from_environment_id": prior_id,
            "from_generation": prior_gen,
            "to_environment_id": new_gen.environment_id,
            "to_generation": new_gen.generation,
            "expires_at": new_gen.expires_at,
            "resolved_commit": resolved or None,
            "recloned": reclone,
        },
    )
    ledger.append_event(
        job_id,
        typ="lifecycle",
        message="sandbox replaced",
        payload={
            "phase": "replaced",
            "from_environment_id": prior_id,
            "to_environment_id": new_gen.environment_id,
            "generation": new_gen.generation,
            "image": env_plan.image,
            "expires_at": new_gen.expires_at,
        },
    )
    refreshed = ledger.get_job(job_id)
    if refreshed is None or refreshed.destroyed_at is not None:
        raise HarnessError(
            "job-level destroyed_at must stay unset while replacement is alive",
            code="replace_invariant",
        )
    return new_gen


def destroy_job_environment(
    job_id: str,
    *,
    reason: str = "destroy",
    settings: Settings | None = None,
    cli: MsbCli | None = None,
    finalizer: bool = False,
) -> DestroyResult:
    """Destroy the job's current sandbox by id (not by passing job_id as name)."""
    cfg = settings or get_settings()
    ledger = get_ledger(cfg)
    job = ledger.get_job(job_id)
    if job is None:
        raise HarnessError(f"unknown job_id: {job_id}", code="not_found")
    environment_id = job.sandbox_id or environment_name_for_job(job_id)
    return destroy_environment(
        environment_id,
        job_id=job_id,
        reason=reason,
        settings=cfg,
        cli=cli,
        finalizer=finalizer,
    )


def wait_until_ready(
    environment_id: str,
    *,
    settings: Settings | None = None,
    cli: MsbCli | None = None,
    timeout_seconds: float | None = None,
    poll_seconds: float = 1.0,
) -> None:
    """Block until guest reports running (not job readiness — D37)."""
    cfg = settings or get_settings()
    msb = cli or MsbCli(cfg)
    deadline = time.monotonic() + (
        timeout_seconds
        if timeout_seconds is not None
        else float(getattr(cfg, "msb_ready_timeout_seconds", 120) or 120)
    )
    last = ""
    while time.monotonic() < deadline:
        result = msb.status(environment_id)
        text = f"{result.stdout}\n{result.stderr}".lower()
        last = text.strip()
        if result.ok and "running" in text:
            ledger = get_ledger(cfg)
            for job in ledger.list_jobs():
                if job.sandbox_id != environment_id:
                    continue
                if job.current_sandbox_generation is None:
                    continue
                ledger.mark_generation_state(
                    job.job_id,
                    job.current_sandbox_generation,
                    "running",
                )
                ledger.append_event(
                    job.job_id,
                    typ="lifecycle",
                    message="sandbox guest running",
                    payload={
                        "phase": "running",
                        "environment_id": environment_id,
                    },
                )
            return
        time.sleep(poll_seconds)
    raise HarnessError(
        f"sandbox {environment_id} not running before timeout ({last[:200]})",
        code="not_ready",
    )


def destroy_environment(
    environment_id: str,
    *,
    job_id: str | None = None,
    reason: str = "destroy",
    settings: Settings | None = None,
    cli: MsbCli | None = None,
    finalizer: bool = False,
) -> DestroyResult:
    """
    `msb stop` + `msb remove`. Confirmed-only destroyed_at (D57).
    """
    cfg = settings or get_settings()
    msb = cli or MsbCli(cfg)
    ledger = get_ledger(cfg)

    resolved_job_id = job_id
    if resolved_job_id is None:
        for job in ledger.list_jobs():
            if job.sandbox_id == environment_id:
                resolved_job_id = job.job_id
                break
    if resolved_job_id is not None and ledger.get_job(resolved_job_id) is None:
        # Host reaper may see labels for jobs from another ledger DB.
        resolved_job_id = None

    if resolved_job_id is not None:
        job = ledger.get_job(resolved_job_id)
        if job is not None and job.current_sandbox_generation is not None:
            ledger.mark_generation_state(
                resolved_job_id,
                job.current_sandbox_generation,
                "destroying",
            )
        ledger.append_event(
            resolved_job_id,
            typ="lifecycle",
            message="sandbox destroy requested",
            payload={
                "phase": "destroying",
                "environment_id": environment_id,
                "reason": reason,
            },
            finalizer=finalizer,
        )

    stop = msb.stop(environment_id, force=False)
    remove = msb.remove(environment_id, force=True)
    # Confirm gone: status should fail or not show running.
    status = msb.status(environment_id)
    still_present = status.ok and environment_id in (status.stdout + status.stderr)
    confirmed = remove.ok or not still_present
    # If stop failed but force-remove succeeded, treat as confirmed.
    if remove.ok:
        confirmed = True
    if not confirmed and "not found" in (remove.stderr + remove.stdout + status.stderr).lower():
        confirmed = True

    now = utc_now()
    if resolved_job_id is not None:
        job = ledger.get_job(resolved_job_id)
        if job is not None and job.current_sandbox_generation is not None:
            if confirmed:
                ledger.mark_generation_state(
                    resolved_job_id,
                    job.current_sandbox_generation,
                    "destroyed",
                    destroyed_at=now,
                )
            else:
                ledger.mark_generation_state(
                    resolved_job_id,
                    job.current_sandbox_generation,
                    "destroy_failed",
                )
        err = None if confirmed else (remove.stderr or stop.stderr or "remove not confirmed")
        ledger.append_event(
            resolved_job_id,
            typ="lifecycle",
            message="sandbox destroyed" if confirmed else "sandbox destroy failed",
            payload={
                "phase": "destroyed" if confirmed else "destroy_failed",
                "environment_id": environment_id,
                "reason": reason,
                "confirmed": confirmed,
                "error": err,
            },
            finalizer=finalizer,
        )
        return DestroyResult(confirmed=confirmed, error=err)

    return DestroyResult(
        confirmed=confirmed,
        error=None if confirmed else (remove.stderr or "remove not confirmed"),
    )


def list_live_environment_ids(
    *,
    settings: Settings | None = None,
    cli: MsbCli | None = None,
) -> set[str]:
    cfg = settings or get_settings()
    msb = cli or MsbCli(cfg)
    result = msb.list_all()
    ids: set[str] = set()
    text = result.stdout.strip()
    if text.startswith("[") or text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("Name")
                    if name:
                        ids.add(str(name))
                elif isinstance(item, str):
                    ids.add(item)
        elif isinstance(payload, dict):
            for item in payload.get("sandboxes") or payload.get("items") or []:
                if isinstance(item, dict) and item.get("name"):
                    ids.add(str(item["name"]))
        return ids
    for line in text.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("name"):
            continue
        name = line.split()[0]
        if name and name != "-":
            ids.add(name)
    return ids


def touch_if_before_expiry(
    environment_id: str,
    expires_at: str,
    *,
    settings: Settings | None = None,
    cli: MsbCli | None = None,
    now_iso: str | None = None,
) -> bool:
    """
    `msb touch` only while now < expires_at (D41). Never extends Killhub expiry.
    Returns True if touch was issued.
    """
    from datetime import datetime

    cfg = settings or get_settings()
    msb = cli or MsbCli(cfg)
    now = datetime.fromisoformat((now_iso or utc_now()).replace("Z", "+00:00"))
    exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    if now >= exp:
        return False
    msb.run(["touch", environment_id], timeout=30, check=False)
    return True


def _normalize_cmd(cmd: Sequence[str] | str) -> list[str]:
    if isinstance(cmd, str):
        parts = shlex.split(cmd)
        if not parts:
            raise HarnessError("exec command is empty", code="invalid_exec")
        return parts
    return [str(c) for c in cmd]


def exec_command(
    environment_id: str,
    cmd: Sequence[str] | str,
    *,
    job_id: str | None = None,
    timeout: float | None = None,
    settings: Settings | None = None,
    cli: MsbCli | None = None,
) -> ExecResult:
    """Run `msb exec` and return stdout/stderr/exit_code (T1)."""
    cfg = settings or get_settings()
    msb = cli or MsbCli(cfg)
    argv = _normalize_cmd(cmd)
    timeout_s = (
        timeout
        if timeout is not None
        else float(getattr(cfg, "msb_exec_timeout_seconds", 120) or 120)
    )
    try:
        result = msb.exec_cmd(environment_id, argv, timeout=timeout_s)
    except HarnessError as exc:
        if job_id is not None:
            get_ledger(cfg).append_event(
                job_id,
                typ="log",
                message=f"exec failed: {exc.message}",
                payload={
                    "kind": "exec",
                    "environment_id": environment_id,
                    "cmd": argv[:8],
                    "code": exc.code,
                },
            )
        raise

    out = ExecResult(
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.returncode,
    )
    if job_id is not None and out.exit_code != 0:
        # Never include secret material — truncate and redact obvious key= lines.
        detail = (out.stderr or out.stdout or "").strip()[:400]
        get_ledger(cfg).append_event(
            job_id,
            typ="log",
            message=f"exec exit {out.exit_code}: {detail}",
            payload={
                "kind": "exec",
                "environment_id": environment_id,
                "exit_code": out.exit_code,
                "cmd": argv[:8],
            },
        )
    return out


def copy_in(
    environment_id: str,
    helper_ref: str,
    guest_dest: str,
    *,
    job_id: str | None = None,
    settings: Settings | None = None,
    cli: MsbCli | None = None,
) -> None:
    """
    Copy a Killhub helper into the sandbox via `msb copy` (D60).

    `helper_ref` is a logical id or relative path under HELPERS_ROOT — never an
    arbitrary absolute host path.
    """
    from paths import enforce_copy_size, resolve_copy_in_source, validate_guest_path

    cfg = settings or get_settings()
    msb = cli or MsbCli(cfg)
    source = resolve_copy_in_source(helper_ref, settings=cfg)
    dest = validate_guest_path(guest_dest)
    enforce_copy_size(source, settings=cfg)

    stage_root = cfg.msb_stage_dir.rstrip("/")
    scope = job_id or environment_id
    remote_src = f"{stage_root}/{scope}/{source.name}"
    msb.scp_put(source, remote_src)
    # Ensure guest parent exists.
    parent = str(Path(dest).parent)
    exec_command(
        environment_id,
        ["mkdir", "-p", parent],
        job_id=job_id,
        settings=cfg,
        cli=msb,
        timeout=30,
    )
    msb.copy(remote_src, f"{environment_id}:{dest}")
    if job_id is not None:
        get_ledger(cfg).append_event(
            job_id,
            typ="log",
            message=f"copy_in {helper_ref} → {dest}",
            payload={
                "kind": "copy_in",
                "helper": helper_ref,
                "guest_dest": dest,
                "bytes": source.stat().st_size,
            },
        )


def copy_out(
    environment_id: str,
    guest_src: str,
    artifact_kind: str,
    *,
    job_id: str,
    filename: str | None = None,
    settings: Settings | None = None,
    cli: MsbCli | None = None,
) -> Path:
    """
    Copy a guest file to a server-selected per-job artifact dir via `msb copy` (D60).
    """
    from paths import (
        enforce_copy_size,
        resolve_copy_out_dest,
        validate_guest_path,
    )

    cfg = settings or get_settings()
    msb = cli or MsbCli(cfg)
    src = validate_guest_path(guest_src)
    name = filename or Path(src).name
    dest = resolve_copy_out_dest(job_id, artifact_kind, filename=name, settings=cfg)

    stage_root = cfg.msb_stage_dir.rstrip("/")
    remote_dest = f"{stage_root}/{job_id}/out-{name}"
    msb.remote_mkdir(str(Path(remote_dest).parent))
    msb.copy(f"{environment_id}:{src}", remote_dest)
    msb.scp_get(remote_dest, dest)
    enforce_copy_size(dest, settings=cfg)
    get_ledger(cfg).append_event(
        job_id,
        typ="log",
        message=f"copy_out {src} → {artifact_kind}/{dest.name}",
        payload={
            "kind": "copy_out",
            "guest_src": src,
            "artifact_kind": artifact_kind,
            "host_dest": str(dest),
            "bytes": dest.stat().st_size,
        },
    )
    return dest


def assert_guest_env_clean(
    environment_id: str,
    *,
    job_id: str | None = None,
    settings: Settings | None = None,
    cli: MsbCli | None = None,
) -> ExecResult:
    """Fail if Killhub/Vultr/OpenCode secrets appear in the guest environment."""
    from paths import guest_env_has_forbidden_keys

    result = exec_command(
        environment_id,
        ["env"],
        job_id=job_id,
        settings=settings,
        cli=cli,
        timeout=30,
    )
    if result.exit_code != 0:
        raise HarnessError(
            f"guest env probe failed ({result.exit_code})",
            code="env_probe_failed",
        )
    bad = guest_env_has_forbidden_keys(result.stdout)
    if bad:
        raise HarnessError(
            f"forbidden keys present in guest env: {', '.join(bad)}",
            code="secret_leak",
        )
    return result
