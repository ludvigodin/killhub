"""Absolute expiry + orphan reaper (D41, D57, D81).

Plane 1 loop: reconcile ledger vs live msb inventory and destroy expired gens,
then fail timed-out / stalled / expired non-terminal jobs (D81).
Host-side entry (`python -m reaper --host`): scan msb labels and destroy past
`killhub.expires_at` even if Plane 1 is down — does not trust `msb touch`.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from config import Settings, get_settings
from harness import (
    LABEL_EXPIRES,
    LABEL_JOB,
    DestroyResult,
    HarnessError,
    MsbCli,
    destroy_environment,
    list_live_environment_ids,
)
from jobs import get_ledger, init_ledger
from ledger.store import utc_now
from models import CleanupState

logger = logging.getLogger("killhub.reaper")


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _job_in_flight(ledger: Any, job_id: str | None) -> bool:
    if not job_id:
        return False
    job = ledger.get_job(job_id)
    if job is None or job.status in {"failed", "cancelled", "completed"}:
        return False
    if job.cancel_requested_at is not None or job.destroyed_at is not None:
        return False
    expires = _parse_iso(job.expires_at) if job.expires_at else None
    return expires is None or expires > datetime.now(timezone.utc)


def reap_expired_from_ledger(
    *,
    settings: Settings | None = None,
    cli: MsbCli | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Destroy ledger generations past expires_at; confirm-only destroyed_at."""
    cfg = settings or get_settings()
    msb = cli or MsbCli(cfg)
    ledger = get_ledger(cfg)
    now = now or datetime.now(timezone.utc)
    try:
        live = list_live_environment_ids(settings=cfg, cli=msb)
    except HarnessError as exc:
        logger.warning("live inventory unavailable: %s", exc.message)
        live = None

    report = ledger.reconcile_startup(live_environment_ids=live, now=now)
    actions: list[dict[str, Any]] = []

    for gen in report.expired_generations:
        if gen.state in {"destroyed", "replaced"}:
            continue
        logger.info(
            "reaping expired generation job=%s env=%s expires_at=%s",
            gen.job_id,
            gen.environment_id,
            gen.expires_at,
        )
        result = _destroy_for_reaper(
            gen.job_id,
            gen.environment_id,
            reason="expires_at",
            settings=cfg,
            cli=msb,
        )
        actions.append(
            {
                "job_id": gen.job_id,
                "environment_id": gen.environment_id,
                "reason": "expires_at",
                "confirmed": result.confirmed,
                "error": result.error,
            }
        )

    for note in report.orphan_notes:
        logger.info("reconcile note: %s", note)
        if note.startswith("live sandbox ") and " has no ledger generation" in note:
            env_id = note[len("live sandbox ") :].split(" ", 1)[0]
            # Host-managed killhub sandboxes without ledger → destroy (orphan).
            labels = msb.inspect_labels(env_id)
            if _job_in_flight(ledger, labels.get(LABEL_JOB)):
                # D80: create → ledger generation write is not atomic; a VM
                # whose job is still running is mid-provisioning, not an
                # orphan. Absolute expires_at reaping still applies.
                logger.info("skip orphan destroy for in-flight job env=%s", env_id)
                continue
            if labels.get("killhub.managed") == "1" or LABEL_JOB in labels:
                result = destroy_environment(
                    env_id,
                    job_id=labels.get(LABEL_JOB),
                    reason="orphan",
                    settings=cfg,
                    cli=msb,
                    finalizer=True,
                )
                actions.append(
                    {
                        "job_id": labels.get(LABEL_JOB),
                        "environment_id": env_id,
                        "reason": "orphan",
                        "confirmed": result.confirmed,
                        "error": result.error,
                    }
                )

    # D81: terminalize jobs past wall clock / stall silence / expires_at.
    from stall import reap_stale_jobs

    actions.extend(reap_stale_jobs(settings=cfg, cli=msb, now=now))
    return actions


def reap_expired_from_host(
    *,
    settings: Settings | None = None,
    cli: MsbCli | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """
    VX1-local reaper: read killhub.expires_at labels from live sandboxes and
    destroy when now >= expires_at — independent of Plane 1 process (D41).
    """
    cfg = settings or get_settings()
    msb = cli or MsbCli(cfg)
    now = now or datetime.now(timezone.utc)
    actions: list[dict[str, Any]] = []
    try:
        live = list_live_environment_ids(settings=cfg, cli=msb)
    except HarnessError as exc:
        logger.error("host reaper cannot list sandboxes: %s", exc.message)
        return actions

    for env_id in sorted(live):
        labels = msb.inspect_labels(env_id)
        if labels.get("killhub.managed") != "1" and LABEL_EXPIRES not in labels:
            continue
        expires = labels.get(LABEL_EXPIRES)
        if not expires:
            continue
        exp_dt = _parse_iso(expires)
        if exp_dt is None:
            logger.warning("unparseable expires_at on %s: %s", env_id, expires)
            continue
        if exp_dt > now:
            continue
        logger.info("host reaper destroying %s (expires_at=%s)", env_id, expires)
        # Prefer harness destroy so ledger updates when explore DB is reachable;
        # if ledger missing, still force-remove via CLI.
        job_id = labels.get(LABEL_JOB)
        try:
            result = destroy_environment(
                env_id,
                job_id=job_id,
                reason="host_expires_at",
                settings=cfg,
                cli=msb,
                finalizer=True,
            )
        except Exception as exc:  # noqa: BLE001 — host path must still remove
            logger.exception("ledger-aware destroy failed for %s", env_id)
            stop = msb.stop(env_id, force=True)
            remove = msb.remove(env_id, force=True)
            result = DestroyResult(
                confirmed=remove.ok,
                error=None if remove.ok else (remove.stderr or str(exc)),
            )
            _ = stop
        actions.append(
            {
                "job_id": job_id,
                "environment_id": env_id,
                "reason": "host_expires_at",
                "confirmed": result.confirmed,
                "error": result.error,
            }
        )
    return actions


def exact_sandbox_names(cli: MsbCli) -> set[str]:
    inventory = cli.run(["list", "--format", "json"], timeout=60, check=True)
    rows = json.loads(inventory.stdout)
    if not isinstance(rows, list) or not all(
        isinstance(r, dict) and isinstance(r.get("name"), str) and r["name"].strip() for r in rows
    ):
        raise ValueError("unexpected sandbox inventory")
    return {r["name"] for r in rows}


def recover_interrupted_jobs(settings: Settings, cli: MsbCli) -> None:
    """Before accepting traffic on the single-host SQLite deployment, close lost runs.

    Runs only in the first worker after downtime, so every in-flight job here
    belongs to the dead process (D82):
    - no sandbox yet → finalize ``failed`` (no destroy claim);
    - recorded sandbox absent from inventory → finalize with confirmed destroy;
    - recorded sandbox still live → remove it, re-inventory, then finalize only
      if it is confirmed gone (otherwise leave it for the next start / reaper).
    """
    from service import release_admission_slot

    ledger = get_ledger(settings)
    if ledger.engine != "sqlite":
        return
    in_flight = [
        job
        for job in ledger.list_jobs()
        if job.status not in {"pending", "queued", "completed", "failed", "cancelled"}
    ]
    if not in_flight:
        return
    with_vm = []
    for job in in_flight:
        if job.sandbox_id and job.current_sandbox_generation is not None:
            with_vm.append(job)
        elif ledger.finalize_interrupted_before_sandbox(job):
            release_admission_slot(was_running=True, settings=settings)
    if not with_vm:
        return
    live = exact_sandbox_names(cli)
    leftover = {job.sandbox_id for job in with_vm if job.sandbox_id in live}
    for env_id in sorted(leftover):
        logger.warning("removing sandbox %s left running by the previous worker", env_id)
        cli.remove(env_id, force=True)
    if leftover:
        live = exact_sandbox_names(cli)
    for job in with_vm:
        if job.sandbox_id in live:
            logger.warning(
                "sandbox %s still live after removal; job %s left", job.sandbox_id, job.job_id
            )
            continue
        reason = (
            "Worker restarted; its leftover sandbox was removed."
            if job.sandbox_id in leftover
            else None
        )
        if ledger.finalize_missing_generation(job, reason=reason):
            release_admission_slot(was_running=True, settings=settings)


def reap_terminal_checkpoints(settings: Settings, cli: MsbCli) -> list[dict[str, Any]]:
    """Collect only transient install checkpoints for confirmed, finished jobs."""
    listed = cli.run(["snapshot", "list", "--format", "json"], timeout=60, check=True)
    groups = json.loads(listed.stdout)
    if not isinstance(groups, list):
        raise ValueError("unexpected snapshot inventory")
    if not groups:
        return []
    # Require an exact JSON inventory before removing a checkpoint.
    live_names = exact_sandbox_names(cli)
    ledger = get_ledger(settings)
    actions = []
    for group in groups:
        name = group.get("name", "") if isinstance(group, dict) else ""
        match = re.fullmatch(r"kh-snap-([0-9a-f]{32})", name)
        if not match:
            continue
        job_id = str(UUID(match[1]))
        job = ledger.get_job(job_id)
        if (
            not job
            or job.status not in {"completed", "cancelled", "failed"}
            or not job.destroyed_at
        ):
            continue
        receipt = ledger.get_receipt(job_id) or {}
        if (receipt.get("lifecycle") or {}).get("confirmed") is not True:
            continue
        if f"kh-{job_id}" in live_names:
            continue
        removed = cli.snapshot_remove_group(name)
        actions.append({"job_id": job_id, "checkpoint": name, "removed": removed.ok})
    return actions


def _destroy_for_reaper(
    job_id: str,
    environment_id: str,
    *,
    reason: str,
    settings: Settings,
    cli: MsbCli,
) -> DestroyResult:
    ledger = get_ledger(settings)
    job = ledger.get_job(job_id)
    attempts = (job.cleanup.attempts if job else 0) + 1
    now = utc_now()
    if job is not None:
        ledger.update_job_fields(
            job_id,
            finalizer=True,
            cleanup=CleanupState(
                status="destroying",
                attempts=attempts,
                updated_at=now,
            ),
        )
    result = destroy_environment(
        environment_id,
        job_id=job_id,
        reason=reason,
        settings=settings,
        cli=cli,
        finalizer=True,
    )
    if job is not None:
        if result.confirmed:
            ledger.update_job_fields(
                job_id,
                finalizer=True,
                cleanup=CleanupState(
                    status="destroyed",
                    attempts=attempts,
                    updated_at=utc_now(),
                ),
                destroyed_at=utc_now(),
            )
        else:
            ledger.update_job_fields(
                job_id,
                finalizer=True,
                cleanup=CleanupState(
                    status="destroy_failed",
                    attempts=attempts,
                    last_error=result.error,
                    updated_at=utc_now(),
                ),
            )
    return result


async def reaper_loop(settings: Settings | None = None) -> None:
    import asyncio

    cfg = settings or get_settings()
    if not cfg.reaper_enabled:
        logger.info("plane-1 reaper disabled")
        while True:
            await asyncio.sleep(3600)
    poll = max(float(getattr(cfg, "reaper_poll_seconds", 30) or 30), 5.0)
    logger.info("plane-1 reaper started (poll=%ss)", poll)
    while True:
        try:
            await asyncio.to_thread(reap_expired_from_ledger, settings=cfg)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("reaper iteration failed")
        await asyncio.sleep(poll)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Killhub microsandbox reaper (D41)")
    parser.add_argument(
        "--host",
        action="store_true",
        help="VX1 host mode: destroy by killhub.expires_at labels (no Plane 1 required)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single pass and exit",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    cfg = get_settings()
    if not args.host:
        init_ledger(cfg)

    def pass_once() -> list[dict[str, Any]]:
        if args.host:
            actions = reap_expired_from_host(settings=cfg)
            actions.extend(reap_terminal_checkpoints(cfg, MsbCli(cfg)))
            return actions
        return reap_expired_from_ledger(settings=cfg)

    if args.once or args.host:
        # Host cron/systemd typically uses --host --once
        actions = pass_once()
        for action in actions:
            logger.info("reaper action: %s", action)
        return 0

    import time

    poll = max(float(getattr(cfg, "reaper_poll_seconds", 30) or 30), 5.0)
    while True:
        pass_once()
        time.sleep(poll)


if __name__ == "__main__":
    sys.exit(main())
