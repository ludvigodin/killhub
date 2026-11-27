"""Durable ledger helpers: create job, append event, snapshot, revisions, generations.

Supports SQLite (default) and PostgreSQL via ``LEDGER_URL`` (D41, D73).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from active_report import ACTIVE_SOURCES, active_finding, summarize_active_checks
from ledger.db import DbConnection, Row, open_ledger_connection
from ledger.migrations import migrate
from ledger.url import LedgerTarget, parse_ledger_url, parse_sqlite_path
from models import (
    CleanupState,
    EnvironmentProfileRevision,
    EventType,
    Job,
    JobEvent,
    JobStatus,
    ProfilePhase,
    ReconcileReport,
    SandboxGeneration,
    SandboxState,
)

# Re-export for callers that imported parse_sqlite_path from store.
__all__ = ["Ledger", "parse_ledger_url", "parse_sqlite_path"]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validate_github_url(url: str) -> str:
    """Validate create payload; field name is historical (D78 allowlisted git hosts)."""
    from git_url import validate_public_git_url

    return validate_public_git_url(url)


TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
VULN_REPORT_STATUSES = frozenset({"ok", "partial", "failed"})
FINDING_SOURCES = frozenset(
    {
        "sca",
        "mcp_assessment",
        "intentional_app",
        "canary",
        "network",
        "containment",
        "preflight",
        "activity",
        "mcp_tool_review",
    }
)
# Destroy lifecycle phases that prove teardown (D57); never pruned before a receipt exists.
_PROTECTED_LIFECYCLE_PHASES = frozenset({"destroyed", "destroy_failed"})


def _is_protected_event(typ: str, payload_json: str | None) -> bool:
    if typ not in {"status", "lifecycle"}:
        return False
    try:
        payload = json.loads(payload_json or "{}")
    except ValueError:
        return False
    if typ == "status":
        return payload.get("status") in TERMINAL_STATUSES
    return payload.get("phase") in _PROTECTED_LIFECYCLE_PHASES


def _dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _loads(value: str | None, default: Any = None) -> Any:
    if value is None:
        return default
    return json.loads(value)


def _event_byte_size(
    event_id: str, typ: str, message: str, payload: dict[str, Any], ts: str
) -> int:
    return len(
        _dumps(
            {
                "event_id": event_id,
                "type": typ,
                "message": message,
                "payload": payload,
                "timestamp": ts,
            }
        ).encode("utf-8")
    )


class Ledger:
    """Durable job/event store owned by the explore sidecar (D41, D73)."""

    def __init__(
        self,
        db_path: Path | None = None,
        *,
        max_job_log_bytes: int = 2_000_000,
        _conn: DbConnection | None = None,
        _target: LedgerTarget | None = None,
    ) -> None:
        self.max_job_log_bytes = max_job_log_bytes
        if _conn is not None:
            self._conn = _conn
            self._target = _target or LedgerTarget(
                engine=getattr(_conn, "engine", "sqlite"),
                path=db_path,
            )
            self.db_path = db_path
        elif db_path is not None:
            self.db_path = Path(db_path)
            self._target = LedgerTarget(engine="sqlite", path=self.db_path)
            self._conn = open_ledger_connection(self._target)
        else:
            raise ValueError("Ledger requires db_path or an open connection")
        path_for_migrate = self.db_path if self._target.engine == "sqlite" else None
        self.schema_version = migrate(
            self._conn,
            path_for_migrate,
            engine=self._target.engine,
        )

    @classmethod
    def from_url(cls, ledger_url: str, *, max_job_log_bytes: int = 2_000_000) -> Ledger:
        target = parse_ledger_url(ledger_url)
        conn = open_ledger_connection(target)
        return cls(
            target.path,
            max_job_log_bytes=max_job_log_bytes,
            _conn=conn,
            _target=target,
        )

    @property
    def engine(self) -> str:
        return self._target.engine

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Ledger:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- jobs ------------------------------------------------------------------

    def create_job(
        self,
        github_url: str,
        *,
        env_ttl_seconds: int,
        job_id: str | None = None,
        status: JobStatus = "pending",
        current_step: str = "accepted",
    ) -> Job:
        github_url = validate_github_url(github_url)
        now = utc_now()
        expires = (
            (datetime.now(timezone.utc) + timedelta(seconds=env_ttl_seconds))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        jid = job_id or str(uuid.uuid4())
        cleanup = CleanupState(status="pending", attempts=0, updated_at=now)

        self._conn.begin()
        try:
            self._conn.execute(
                """
                INSERT INTO jobs (
                    job_id, github_url, resolved_commit, status, progress,
                    current_step, steps_completed, error, readiness, verification,
                    verify_result, sandbox_id, current_profile_revision,
                    current_sandbox_generation, inference_model, inference_usage,
                    event_cursor, expires_at, cleanup, destroyed_at,
                    cancel_requested_at, created_at, updated_at
                ) VALUES (
                    ?, ?, NULL, ?, 0, ?, '[]', NULL, NULL, NULL,
                    NULL, NULL, NULL, NULL, NULL, NULL,
                    NULL, ?, ?, NULL, NULL, ?, ?
                )
                """,
                (
                    jid,
                    github_url,
                    status,
                    current_step,
                    expires,
                    _dumps(cleanup.to_dict()),
                    now,
                    now,
                ),
            )
            event = self._insert_event_unlocked(
                jid,
                typ="status",
                message=f"job created ({status})",
                payload={"status": status, "github_url": github_url},
                timestamp=now,
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        job = self.get_job(jid)
        assert job is not None
        assert job.event_cursor == event.event_id
        return job

    def get_job(self, job_id: str) -> Job | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_job(row)

    def list_jobs(self) -> list[Job]:
        rows = self._conn.execute(
            "SELECT * FROM jobs ORDER BY created_at ASC, job_id ASC"
        ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def count_jobs(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()
        if row is None:
            return 0
        return int(row["n"])

    def list_recent_jobs(self, *, limit: int = 48, offset: int = 0) -> list[Job]:
        """Newest-first job rows for the public feed (D69 / D77)."""
        capped = max(1, min(int(limit), 200))
        skip = max(0, int(offset))
        order = self._jobs_newest_order()
        rows = self._conn.execute(
            f"SELECT * FROM jobs {order} LIMIT ? OFFSET ?",
            (capped, skip),
        ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def count_repos(self) -> int:
        """Distinct canonical github_url values in the ledger (D79)."""
        row = self._conn.execute("SELECT COUNT(DISTINCT github_url) AS n FROM jobs").fetchone()
        if row is None:
            return 0
        return int(row["n"])

    def list_recent_repos(self, *, limit: int = 48, offset: int = 0) -> list[tuple[Job, int]]:
        """One latest job per github_url, newest activity first (D79).

        Returns ``(latest_job, run_count)`` tuples.
        """
        capped = max(1, min(int(limit), 200))
        skip = max(0, int(offset))
        tie = self._jobs_tie_break_col()
        # Window over partition: rn=1 is the newest run; run_count is all runs.
        # Explicitly project the tie-break col — SELECT * omits SQLite rowid /
        # Postgres ctid, so the outer ORDER BY would fail without it.
        sql = f"""
            WITH ranked AS (
                SELECT jobs.*,
                    jobs.{tie} AS _tie,
                    ROW_NUMBER() OVER (
                        PARTITION BY github_url
                        ORDER BY created_at DESC, {tie} DESC
                    ) AS rn,
                    COUNT(*) OVER (PARTITION BY github_url) AS run_count
                FROM jobs
            )
            SELECT * FROM ranked
            WHERE rn = 1
            ORDER BY created_at DESC, _tie DESC
            LIMIT ? OFFSET ?
        """
        rows = self._conn.execute(sql, (capped, skip)).fetchall()
        out: list[tuple[Job, int]] = []
        for row in rows:
            out.append((self._row_to_job(row), int(row["run_count"])))
        return out

    def count_jobs_for_url(self, github_url: str) -> int:
        """Jobs for one canonical github_url (D79)."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE github_url = ?",
            (github_url,),
        ).fetchone()
        if row is None:
            return 0
        return int(row["n"])

    def list_jobs_for_url(self, github_url: str, *, limit: int = 48, offset: int = 0) -> list[Job]:
        """Newest-first jobs for one canonical github_url (D79)."""
        capped = max(1, min(int(limit), 200))
        skip = max(0, int(offset))
        order = self._jobs_newest_order()
        rows = self._conn.execute(
            f"SELECT * FROM jobs WHERE github_url = ? {order} LIMIT ? OFFSET ?",
            (github_url, capped, skip),
        ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def _jobs_tie_break_col(self) -> str:
        # created_at is second-precision; tie-break with insertion order (rowid)
        # so same-second creates stay newest-first. Postgres uses ctid.
        if getattr(self._conn, "engine", "sqlite") == "postgres":
            return "ctid"
        return "rowid"

    def _jobs_newest_order(self) -> str:
        tie = self._jobs_tie_break_col()
        return f"ORDER BY created_at DESC, {tie} DESC"

    def get_snapshot(self, job_id: str) -> dict[str, Any] | None:
        """Public Jobs API snapshot shape (API.md)."""
        job = self.get_job(job_id)
        if job is None:
            return None

        profile = None
        if job.current_profile_revision is not None:
            for rev in self.list_profile_revisions(job_id):
                if rev.revision == job.current_profile_revision:
                    profile = rev.profile
                    break

        environment = None
        if job.current_sandbox_generation is not None:
            for gen in self.list_sandbox_generations(job_id):
                if gen.generation == job.current_sandbox_generation:
                    environment = {
                        "environment_id": gen.environment_id,
                        "generation": gen.generation,
                        "state": gen.state,
                        "expires_at": gen.expires_at,
                    }
                    break

        receipt, report = self.report_for_display(job_id)
        return {
            "job_id": job.job_id,
            "github_url": job.github_url,
            "status": job.status,
            "progress": job.progress,
            "current_step": job.current_step,
            "steps_completed": list(job.steps_completed),
            "updated_at": job.updated_at,
            "created_at": job.created_at,
            "error": job.error,
            "event_cursor": job.event_cursor,
            "profile": profile,
            "readiness": job.readiness,
            "verification": job.verification,
            "verify_result": job.verify_result,
            "sandbox_id": job.sandbox_id,
            "resolved_commit": job.resolved_commit,
            "current_profile_revision": job.current_profile_revision,
            "current_sandbox_generation": job.current_sandbox_generation,
            "inference_model": job.inference_model,
            "inference_usage": job.inference_usage,
            "expires_at": job.expires_at,
            "cleanup": job.cleanup.to_dict(),
            "destroyed_at": job.destroyed_at,
            "cancel_requested_at": job.cancel_requested_at,
            "environment": environment,
            "vuln_report": report,
            "screenshot_ids": [s["screenshot_id"] for s in self.list_screenshots(job_id)],
            "receipt": receipt,
        }

    class WriterFrozenError(RuntimeError):
        """Raised when ordinary writers mutate a cancel-frozen job (D61)."""

    class ReceiptRequiredError(RuntimeError):
        """Raised when a job would go terminal before its receipt is persisted (D61)."""

    def _has_receipt(self, job_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM job_receipts WHERE job_id = ?", (job_id,)
        ).fetchone()
        return row is not None

    def _assert_receipt_before_terminal(self, job: Job, new_status: Any) -> None:
        if (
            new_status in TERMINAL_STATUSES
            and new_status != job.status
            and not self._has_receipt(job.job_id)
        ):
            raise Ledger.ReceiptRequiredError(
                f"job {job.job_id} cannot become {new_status} before its receipt is "
                "persisted (D61); use finalize_job()"
            )

    def _assert_ordinary_writable(self, job: Job) -> None:
        if job.cancel_requested_at is not None:
            raise Ledger.WriterFrozenError(
                f"job {job.job_id} is cancel-frozen (cancel_requested_at set)"
            )
        if job.status in {"completed", "failed", "cancelled"}:
            raise Ledger.WriterFrozenError(f"job {job.job_id} is terminal ({job.status})")

    _JOB_JSON_FIELDS = frozenset(
        {
            "steps_completed",
            "readiness",
            "verification",
            "verify_result",
            "inference_usage",
            "cleanup",
        }
    )
    _UPDATABLE_JOB_FIELDS = frozenset(
        {
            "resolved_commit",
            "status",
            "progress",
            "current_step",
            "steps_completed",
            "error",
            "readiness",
            "verification",
            "verify_result",
            "sandbox_id",
            "current_profile_revision",
            "current_sandbox_generation",
            "inference_model",
            "inference_usage",
            "expires_at",
            "cleanup",
            "destroyed_at",
            "cancel_requested_at",
        }
    )

    def _check_job_fields(self, fields: dict[str, Any]) -> None:
        unknown = set(fields) - self._UPDATABLE_JOB_FIELDS
        if unknown:
            raise ValueError(f"unsupported job fields: {sorted(unknown)}")

    def _write_job_fields_unlocked(self, job_id: str, fields: dict[str, Any]) -> None:
        sets: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            sets.append(f"{key} = ?")
            if key in self._JOB_JSON_FIELDS:
                if key == "cleanup" and isinstance(value, CleanupState):
                    values.append(_dumps(value.to_dict()))
                else:
                    values.append(_dumps(value) if value is not None else None)
            else:
                values.append(value)
        sets.append("updated_at = ?")
        values.append(utc_now())
        values.append(job_id)
        self._conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE job_id = ?", values)

    def update_job_fields(self, job_id: str, *, finalizer: bool = False, **fields: Any) -> Job:
        """Patch allowlisted job columns. Ordinary writers freeze after cancel (D61).

        A terminal ``status`` is refused until the job's receipt exists (D61);
        use ``finalize_job`` to write both atomically.
        """
        self._check_job_fields(fields)
        self._conn.begin()
        try:
            job = self.get_job(job_id)
            if job is None:
                raise KeyError(f"unknown job_id: {job_id}")
            if not finalizer:
                self._assert_ordinary_writable(job)
            if "status" in fields:
                self._assert_receipt_before_terminal(job, fields["status"])
            self._write_job_fields_unlocked(job_id, fields)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        job = self.get_job(job_id)
        assert job is not None
        return job

    # --- events ----------------------------------------------------------------

    def append_event(
        self,
        job_id: str,
        *,
        typ: EventType,
        message: str,
        payload: dict[str, Any] | None = None,
        finalizer: bool = False,
    ) -> JobEvent:
        self._conn.begin()
        try:
            job = self.get_job(job_id)
            if job is None:
                raise KeyError(f"unknown job_id: {job_id}")
            if not finalizer:
                self._assert_ordinary_writable(job)
            event = self._insert_event_unlocked(
                job_id,
                typ=typ,
                message=message,
                payload=payload or {},
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return event

    def has_event(self, job_id: str, event_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM job_events WHERE job_id = ? AND event_id = ?",
            (job_id, event_id),
        ).fetchone()
        return row is not None

    def cursor_is_valid(self, job_id: str, after_event_id: str | None) -> bool:
        """True when `after` is absent or names a currently retained event (D55/D67)."""
        if after_event_id is None or after_event_id == "":
            return True
        return self.has_event(job_id, after_event_id)

    def list_events(self, job_id: str, *, after_event_id: str | None = None) -> list[JobEvent]:
        if after_event_id is None:
            rows = self._conn.execute(
                """
                SELECT * FROM job_events
                WHERE job_id = ?
                ORDER BY CAST(event_id AS INTEGER) ASC
                """,
                (job_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT * FROM job_events
                WHERE job_id = ? AND CAST(event_id AS INTEGER) > CAST(? AS INTEGER)
                ORDER BY CAST(event_id AS INTEGER) ASC
                """,
                (job_id, after_event_id),
            ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def list_events_recent(self, job_id: str, *, limit: int = 50) -> list[JobEvent]:
        """Last N durable events for a job, returned in ascending event_id order."""
        capped = max(1, min(int(limit), 200))
        rows = self._conn.execute(
            """
            SELECT * FROM (
                SELECT * FROM job_events
                WHERE job_id = ?
                ORDER BY CAST(event_id AS INTEGER) DESC
                LIMIT ?
            ) recent
            ORDER BY CAST(event_id AS INTEGER) ASC
            """,
            (job_id, capped),
        ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def retained_event_bytes(self, job_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(byte_size), 0) AS total FROM job_events WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        return int(row["total"])

    def _insert_event_unlocked(
        self,
        job_id: str,
        *,
        typ: EventType,
        message: str,
        payload: dict[str, Any],
        timestamp: str | None = None,
    ) -> JobEvent:
        ts = timestamp or utc_now()
        next_id = self._next_event_id(job_id)
        size = _event_byte_size(next_id, typ, message, payload, ts)
        self._conn.execute(
            """
            INSERT INTO job_events (job_id, event_id, type, message, payload, timestamp, byte_size)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (job_id, next_id, typ, message, _dumps(payload), ts, size),
        )
        self._conn.execute(
            "UPDATE jobs SET event_cursor = ?, updated_at = ? WHERE job_id = ?",
            (next_id, ts, job_id),
        )
        self._prune_events_unlocked(job_id)
        return JobEvent(
            event_id=next_id,
            job_id=job_id,
            type=typ,
            message=message,
            payload=payload,
            timestamp=ts,
        )

    def _next_event_id(self, job_id: str) -> str:
        row = self._conn.execute(
            """
            SELECT COALESCE(MAX(CAST(event_id AS INTEGER)), 0) AS max_id
            FROM job_events WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()
        return str(int(row["max_id"]) + 1)

    def _prune_events_unlocked(self, job_id: str) -> None:
        """Contiguous prefix prune + single gap tombstone (D67)."""
        total = self.retained_event_bytes(job_id)
        if total <= self.max_job_log_bytes:
            return

        rows = self._conn.execute(
            """
            SELECT event_id, type, payload, byte_size FROM job_events
            WHERE job_id = ?
            ORDER BY CAST(event_id AS INTEGER) ASC
            """,
            (job_id,),
        ).fetchall()
        if len(rows) <= 1:
            return

        # Terminal status / destroy evidence may only go once the receipt holds the dossier.
        protect = not self._has_receipt(job_id)

        # Reserve room for the gap event (~512 bytes upper bound).
        budget = max(self.max_job_log_bytes - 512, 0)
        running = total
        to_delete: list[str] = []
        blocked = False
        for row in rows[:-1]:  # never delete the newest event in this pass
            if running <= budget:
                break
            if protect and _is_protected_event(row["type"], row["payload"]):
                blocked = True  # prefix-only: stop here rather than leave a middle hole
                break
            to_delete.append(row["event_id"])
            running -= int(row["byte_size"])

        if not to_delete:
            return

        pruned_before = to_delete[-1]
        delete_set = set(to_delete)
        bytes_freed = sum(int(r["byte_size"]) for r in rows if r["event_id"] in delete_set)
        placeholders = ",".join("?" for _ in to_delete)
        self._conn.execute(
            f"DELETE FROM job_events WHERE job_id = ? AND event_id IN ({placeholders})",
            [job_id, *to_delete],
        )

        # Reuse the last pruned id so the gap sits at the start of the retained window (D67).
        gap_id = pruned_before
        gap_payload = {
            "pruned_before_event_id": pruned_before,
            "pruned_count": len(to_delete),
            "bytes_freed": bytes_freed,
        }
        ts = utc_now()
        gap_msg = f"pruned {len(to_delete)} events through {pruned_before} ({bytes_freed} bytes)"
        gap_size = _event_byte_size(gap_id, "gap", gap_msg, gap_payload, ts)
        self._conn.execute(
            """
            INSERT INTO job_events (job_id, event_id, type, message, payload, timestamp, byte_size)
            VALUES (?, ?, 'gap', ?, ?, ?, ?)
            """,
            (job_id, gap_id, gap_msg, _dumps(gap_payload), ts, gap_size),
        )
        newest = self._conn.execute(
            """
            SELECT event_id FROM job_events
            WHERE job_id = ?
            ORDER BY CAST(event_id AS INTEGER) DESC
            LIMIT 1
            """,
            (job_id,),
        ).fetchone()
        self._conn.execute(
            "UPDATE jobs SET event_cursor = ?, updated_at = ? WHERE job_id = ?",
            (newest["event_id"], ts, job_id),
        )

        # Prefix-only second pass if still over budget (may prune a prior gap).
        # Stop when only gap+newest remain — never delete the newest event, so
        # further passes cannot make progress and would recurse forever.
        remaining = len(rows) - len(to_delete) + 1  # + gap
        if (
            not blocked
            and remaining > 2
            and self.retained_event_bytes(job_id) > self.max_job_log_bytes
        ):
            self._prune_events_unlocked(job_id)

    # --- profile revisions (D64) -----------------------------------------------

    def append_profile_revision(
        self,
        job_id: str,
        *,
        phase: ProfilePhase,
        schema_version: str,
        profile: dict[str, Any],
        storage_path: str | None = None,
        finalizer: bool = False,
    ) -> EnvironmentProfileRevision:
        self._conn.begin()
        try:
            job = self.get_job(job_id)
            if job is None:
                raise KeyError(f"unknown job_id: {job_id}")
            if not finalizer:
                self._assert_ordinary_writable(job)
            row = self._conn.execute(
                """
                SELECT COALESCE(MAX(revision), 0) AS max_rev
                FROM environment_profile_revisions WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
            revision = int(row["max_rev"]) + 1
            now = utc_now()
            path = storage_path or f"storage/profiles/{job_id}/r{revision}.json"
            self._conn.execute(
                """
                INSERT INTO environment_profile_revisions (
                    job_id, revision, phase, schema_version, profile, storage_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, revision, phase, schema_version, _dumps(profile), path, now),
            )
            self._conn.execute(
                """
                UPDATE jobs
                SET current_profile_revision = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (revision, now, job_id),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return EnvironmentProfileRevision(
            job_id=job_id,
            revision=revision,
            phase=phase,
            schema_version=schema_version,
            profile=profile,
            storage_path=path,
            created_at=now,
        )

    def list_profile_revisions(self, job_id: str) -> list[EnvironmentProfileRevision]:
        rows = self._conn.execute(
            """
            SELECT * FROM environment_profile_revisions
            WHERE job_id = ?
            ORDER BY revision ASC
            """,
            (job_id,),
        ).fetchall()
        return [
            EnvironmentProfileRevision(
                job_id=r["job_id"],
                revision=int(r["revision"]),
                phase=r["phase"],
                schema_version=r["schema_version"],
                profile=_loads(r["profile"], {}),
                storage_path=r["storage_path"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    # --- sandbox generations (D64) ---------------------------------------------

    def append_sandbox_generation(
        self,
        job_id: str,
        *,
        environment_id: str,
        image: str,
        expires_at: str,
        state: SandboxState = "provisioning",
        cpus: float | None = None,
        memory: str | None = None,
        finalizer: bool = False,
    ) -> SandboxGeneration:
        self._conn.begin()
        try:
            job = self.get_job(job_id)
            if job is None:
                raise KeyError(f"unknown job_id: {job_id}")
            if not finalizer:
                self._assert_ordinary_writable(job)
            row = self._conn.execute(
                """
                SELECT COALESCE(MAX(generation), 0) AS max_gen
                FROM sandbox_generations WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
            generation = int(row["max_gen"]) + 1
            # Replace must reuse job expires_at (D64) — callers should pass job.expires_at.
            self._conn.execute(
                """
                INSERT INTO sandbox_generations (
                    job_id, generation, environment_id, image, cpus, memory,
                    expires_at, state, destroyed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    job_id,
                    generation,
                    environment_id,
                    image,
                    cpus,
                    memory,
                    expires_at,
                    state,
                ),
            )
            now = utc_now()
            self._conn.execute(
                """
                UPDATE jobs
                SET current_sandbox_generation = ?, sandbox_id = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (generation, environment_id, now, job_id),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return SandboxGeneration(
            job_id=job_id,
            generation=generation,
            environment_id=environment_id,
            image=image,
            expires_at=expires_at,
            state=state,
            cpus=cpus,
            memory=memory,
            destroyed_at=None,
        )

    def list_sandbox_generations(self, job_id: str) -> list[SandboxGeneration]:
        rows = self._conn.execute(
            """
            SELECT * FROM sandbox_generations
            WHERE job_id = ?
            ORDER BY generation ASC
            """,
            (job_id,),
        ).fetchall()
        return [self._row_to_generation(r) for r in rows]

    def mark_generation_state(
        self,
        job_id: str,
        generation: int,
        state: SandboxState,
        *,
        destroyed_at: str | None = None,
    ) -> SandboxGeneration:
        self._conn.begin()
        try:
            self._conn.execute(
                """
                UPDATE sandbox_generations
                SET state = ?, destroyed_at = COALESCE(?, destroyed_at)
                WHERE job_id = ? AND generation = ?
                """,
                (state, destroyed_at, job_id, generation),
            )
            self._conn.execute(
                "UPDATE jobs SET updated_at = ? WHERE job_id = ?",
                (utc_now(), job_id),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        gens = {g.generation: g for g in self.list_sandbox_generations(job_id)}
        if generation not in gens:
            raise KeyError(f"unknown generation {generation} for job {job_id}")
        return gens[generation]

    # --- screenshots / vulns / receipts ----------------------------------------

    def list_screenshots(self, job_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT screenshot_id, job_id, step, caption, storage_path, created_at
            FROM screenshots
            WHERE job_id = ?
            ORDER BY created_at ASC, screenshot_id ASC
            """,
            (job_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_screenshot(self, job_id: str, screenshot_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT screenshot_id, job_id, step, caption, storage_path, created_at
            FROM screenshots
            WHERE job_id = ? AND screenshot_id = ?
            """,
            (job_id, screenshot_id),
        ).fetchone()
        return dict(row) if row else None

    def insert_screenshot(
        self,
        job_id: str,
        *,
        step: str,
        caption: str,
        storage_path: str,
        screenshot_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist screenshot metadata (bytes already on host via D60 copy_out)."""
        shot_id = screenshot_id or str(uuid.uuid4())
        now = utc_now()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO screenshots (
                    screenshot_id, job_id, step, caption, storage_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (shot_id, job_id, step, caption, storage_path, now),
            )
        row = self.get_screenshot(job_id, shot_id)
        assert row is not None
        return row

    def report_for_display(self, job_id: str) -> tuple[dict | None, dict | None]:
        receipt = self.get_receipt(job_id)
        report = self.get_vuln_report(job_id)
        if not receipt or not report or "active_checks" in receipt["dossier"]:
            return receipt, report
        # Older workers emitted these events but omitted them from finalized reports.
        rows = self._conn.execute(
            """
            SELECT * FROM job_events WHERE job_id = ? AND (
                (type = 'finding' AND (payload LIKE '%"source":"activity"%'
                                    OR payload LIKE '%"source":"mcp_tool_review"%'))
                OR (type = 'log' AND (payload LIKE '%"kind":"install_activity"%'
                                   OR payload LIKE '%"kind":"mcp_tool_review"%')))
            ORDER BY CAST(event_id AS INTEGER)
            """,
            (job_id,),
        ).fetchall()
        if rows:
            events = [self._row_to_event(row) for row in rows]
            findings = report["findings"]
            ids = {f["id"] for f in findings}
            for event in events:
                if (
                    event.type == "finding"
                    and (event.payload or {}).get("source") in ACTIVE_SOURCES
                ):
                    finding = active_finding(event)
                    if finding["id"] not in ids:
                        findings.append(finding)
                        ids.add(finding["id"])
            checks = summarize_active_checks(events, findings)
            receipt["dossier"]["active_checks"] = checks
            receipt["dossier"]["finding_ids"] = [f["id"] for f in findings]
            if leading := checks["leading_finding"]:
                prior = report["summary"]
                if prior == "No scan findings. Clean bill for this job's scanned surfaces.":
                    prior = "Historical dependency scan coverage is unknown."
                    if report["status"] == "ok":
                        report["status"] = "partial"
                report["summary"] = f"{leading['title']} [{leading['id']}]. {prior}"
                receipt["dossier"]["vuln_review"] = report["summary"]
        return receipt, report

    def get_vuln_report(self, job_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM vuln_reports WHERE job_id = ?", (job_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "job_id": row["job_id"],
            "summary": row["summary"],
            "findings": _loads(row["findings"], []),
            "mcp_assessment": _loads(row["mcp_assessment"]),
            "status": row["status"],
        }

    def upsert_receipt(
        self,
        job_id: str,
        *,
        verification: dict[str, Any] | None = None,
        containment: dict[str, Any] | None = None,
        lifecycle: dict[str, Any] | None = None,
        dossier: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "verification": verification,
            "containment": containment,
            "lifecycle": lifecycle,
            "dossier": dossier or {},
        }
        self._conn.begin()
        try:
            if self.get_job(job_id) is None:
                raise KeyError(f"unknown job_id: {job_id}")
            self._conn.execute(
                """
                INSERT INTO job_receipts (job_id, verification, containment, lifecycle, dossier)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    verification = excluded.verification,
                    containment = excluded.containment,
                    lifecycle = excluded.lifecycle,
                    dossier = excluded.dossier
                """,
                (
                    job_id,
                    _dumps(payload["verification"]),
                    _dumps(payload["containment"]),
                    _dumps(payload["lifecycle"]),
                    _dumps(payload["dossier"]),
                ),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        receipt = self.get_receipt(job_id)
        assert receipt is not None
        return receipt

    def finalize_job(
        self,
        job_id: str,
        *,
        status: JobStatus,
        receipt: dict[str, Any],
        event_message: str | None = None,
        event_payload: dict[str, Any] | None = None,
        **fields: Any,
    ) -> Job:
        """Persist the receipt, then the terminal status + status event, atomically (D61).

        ``receipt`` takes the ``upsert_receipt`` keys (verification, containment,
        lifecycle, dossier); keys left out keep any existing receipt value. Runs with
        finalizer rights, so it also works on cancel-frozen jobs.
        """
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"finalize_job needs a terminal status, got {status!r}")
        unknown = set(receipt) - {"verification", "containment", "lifecycle", "dossier"}
        if unknown:
            raise ValueError(f"unsupported receipt keys: {sorted(unknown)}")
        self._check_job_fields(fields)

        self._conn.begin()
        try:
            job = self.get_job(job_id)
            if job is None:
                raise KeyError(f"unknown job_id: {job_id}")
            self._finalize_unlocked(job_id, status, receipt, event_message, event_payload, fields)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        job = self.get_job(job_id)
        assert job is not None
        return job

    def _finalize_unlocked(
        self,
        job_id: str,
        status: JobStatus,
        receipt: dict[str, Any],
        event_message: str | None,
        event_payload: dict[str, Any] | None,
        fields: dict[str, Any],
    ) -> None:
        existing = self.get_receipt(job_id) or {}
        merged = {
            key: receipt[key] if key in receipt else existing.get(key)
            for key in ("verification", "containment", "lifecycle", "dossier")
        }
        self._conn.execute(
            """
            INSERT INTO job_receipts (job_id, verification, containment, lifecycle, dossier)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                verification = excluded.verification,
                containment = excluded.containment,
                lifecycle = excluded.lifecycle,
                dossier = excluded.dossier
            """,
            (
                job_id,
                _dumps(merged["verification"]),
                _dumps(merged["containment"]),
                _dumps(merged["lifecycle"]),
                _dumps(merged["dossier"] or {}),
            ),
        )
        self._insert_event_unlocked(
            job_id,
            typ="status",
            message=event_message or status,
            payload={"status": status, **(event_payload or {})},
        )
        self._write_job_fields_unlocked(job_id, {**fields, "status": status})

    def finalize_missing_generation(self, observed: Job, *, reason: str | None = None) -> bool:
        """Atomically close only the same interrupted run observed before inventory."""
        self._conn.begin()
        try:
            job = self.get_job(observed.job_id)
            if job is None or job != observed or job.status in TERMINAL_STATUSES:
                self._conn.rollback()
                return False
            now = utc_now()
            status = "cancelled" if job.cancel_requested_at else "failed"
            reason = reason or "Worker restarted and the recorded sandbox is absent from inventory."
            lifecycle = {
                "confirmed": True,
                "environment_id": job.sandbox_id,
                "generation": job.current_sandbox_generation,
                "destroyed_at": now,
                "reason": "worker_restart",
                "phase": "destroyed",
            }
            self._conn.execute(
                "UPDATE sandbox_generations SET state='destroyed', destroyed_at=? "
                "WHERE job_id=? AND generation=? AND environment_id=?",
                (now, job.job_id, job.current_sandbox_generation, job.sandbox_id),
            )
            self._insert_event_unlocked(
                job.job_id, typ="lifecycle", message=reason, payload=lifecycle
            )
            self._finalize_unlocked(
                job.job_id,
                status,
                {
                    "verification": job.verification,
                    "lifecycle": lifecycle,
                    "dossier": {
                        "outcome": status,
                        "code": "worker_restart",
                        "interrupted_step": job.current_step,
                    },
                },
                reason,
                {"reason": "worker_restart"},
                {
                    "current_step": status,
                    "error": reason,
                    "progress": 100,
                    "destroyed_at": now,
                    "cleanup": CleanupState(
                        status="destroyed", attempts=job.cleanup.attempts, updated_at=now
                    ),
                },
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return True

    def finalize_interrupted_before_sandbox(self, observed: Job) -> bool:
        """Close an interrupted run that never created a sandbox (D82).

        Same observed-row guard as ``finalize_missing_generation``; no
        lifecycle ``destroyed`` claim because no VM ever existed (D57).
        """
        self._conn.begin()
        try:
            job = self.get_job(observed.job_id)
            if job is None or job != observed or job.status in TERMINAL_STATUSES or job.sandbox_id:
                self._conn.rollback()
                return False
            status = "cancelled" if job.cancel_requested_at else "failed"
            reason = "Worker restarted before this run created a sandbox."
            self._finalize_unlocked(
                job.job_id,
                status,
                {
                    "verification": job.verification
                    or {
                        "kind": "setup_failed",
                        "original_failure": {"step": "worker_restart", "summary": reason},
                    },
                    "dossier": {
                        "outcome": status,
                        "code": "worker_restart",
                        "interrupted_step": job.current_step,
                    },
                },
                reason,
                {"reason": "worker_restart"},
                {"current_step": status, "error": reason, "progress": 100},
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return True

    def upsert_vuln_report(
        self,
        job_id: str,
        *,
        summary: str,
        findings: list[dict[str, Any]],
        status: str,
        mcp_assessment: dict[str, Any] | None = None,
        finalizer: bool = False,
    ) -> dict[str, Any]:
        """Write the job's VulnReport (DATABASE.md VulnReport, D48, D53)."""
        if status not in VULN_REPORT_STATUSES:
            raise ValueError(f"vuln report status must be one of {sorted(VULN_REPORT_STATUSES)}")
        normalized: list[dict[str, Any]] = []
        for i, finding in enumerate(findings):
            if not finding.get("id"):
                raise ValueError(f"finding {i} missing id")
            if finding.get("source") not in FINDING_SOURCES:
                raise ValueError(f"finding {i} has unknown source {finding.get('source')!r}")
            # Stream-lifted findings may omit these; keep them renderable.
            normalized.append(
                {
                    **finding,
                    "severity": finding.get("severity") or "medium",
                    "title": finding.get("title") or str(finding["id"]),
                }
            )
        findings = normalized
        self._conn.begin()
        try:
            job = self.get_job(job_id)
            if job is None:
                raise KeyError(f"unknown job_id: {job_id}")
            if not finalizer:
                self._assert_ordinary_writable(job)
            self._conn.execute(
                """
                INSERT INTO vuln_reports (job_id, summary, findings, mcp_assessment, status)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    summary = excluded.summary,
                    findings = excluded.findings,
                    mcp_assessment = excluded.mcp_assessment,
                    status = excluded.status
                """,
                (
                    job_id,
                    summary,
                    _dumps(findings),
                    _dumps(mcp_assessment) if mcp_assessment is not None else None,
                    status,
                ),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        report = self.get_vuln_report(job_id)
        assert report is not None
        return report

    def get_receipt(self, job_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM job_receipts WHERE job_id = ?", (job_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "job_id": row["job_id"],
            "verification": _loads(row["verification"]),
            "containment": _loads(row["containment"]),
            "lifecycle": _loads(row["lifecycle"]),
            "dossier": _loads(row["dossier"], {}),
        }

    # --- reconciliation (D41) --------------------------------------------------

    def reconcile_startup(
        self,
        *,
        live_environment_ids: set[str] | None = None,
        now: datetime | None = None,
    ) -> ReconcileReport:
        """
        Compare ledger generations to known-live Microsandbox ids.

        Without harness inventory, pass `live_environment_ids=None` to only
        classify absolute expiry from the ledger (msb wiring comes later).
        """
        now = now or datetime.now(timezone.utc)
        live = live_environment_ids
        live_gens: list[SandboxGeneration] = []
        expired: list[SandboxGeneration] = []
        notes: list[str] = []

        jobs = self.list_jobs()
        for job in jobs:
            for gen in self.list_sandbox_generations(job.job_id):
                if gen.state in {"destroyed", "replaced", "failed"}:
                    continue
                try:
                    exp = datetime.fromisoformat(gen.expires_at.replace("Z", "+00:00"))
                except ValueError:
                    notes.append(f"unparseable expires_at for {job.job_id} gen {gen.generation}")
                    continue
                if exp <= now:
                    expired.append(gen)
                    continue
                if live is not None and gen.environment_id not in live:
                    notes.append(
                        f"orphan ledger generation {job.job_id}/{gen.generation} "
                        f"({gen.environment_id}) not in live inventory"
                    )
                else:
                    live_gens.append(gen)

        if live is not None:
            known = {
                g.environment_id for job in jobs for g in self.list_sandbox_generations(job.job_id)
            }
            for env_id in sorted(live - known):
                notes.append(f"live sandbox {env_id} has no ledger generation")

        return ReconcileReport(
            job_count=len(jobs),
            live_generations=live_gens,
            expired_generations=expired,
            orphan_notes=notes,
        )

    # --- row mappers -----------------------------------------------------------

    def _row_to_job(self, row: Row) -> Job:
        return Job(
            job_id=row["job_id"],
            github_url=row["github_url"],
            resolved_commit=row["resolved_commit"],
            status=row["status"],
            progress=int(row["progress"]),
            current_step=row["current_step"],
            steps_completed=_loads(row["steps_completed"], []),
            error=row["error"],
            readiness=_loads(row["readiness"]),
            verification=_loads(row["verification"]),
            verify_result=_loads(row["verify_result"]),
            sandbox_id=row["sandbox_id"],
            current_profile_revision=row["current_profile_revision"],
            current_sandbox_generation=row["current_sandbox_generation"],
            inference_model=row["inference_model"],
            inference_usage=_loads(row["inference_usage"]),
            event_cursor=row["event_cursor"],
            expires_at=row["expires_at"],
            cleanup=CleanupState.from_dict(_loads(row["cleanup"], {})),
            destroyed_at=row["destroyed_at"],
            cancel_requested_at=row["cancel_requested_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_event(self, row: Row) -> JobEvent:
        return JobEvent(
            event_id=row["event_id"],
            job_id=row["job_id"],
            type=row["type"],
            message=row["message"],
            payload=_loads(row["payload"], {}),
            timestamp=row["timestamp"],
        )

    def _row_to_generation(self, row: Row) -> SandboxGeneration:
        return SandboxGeneration(
            job_id=row["job_id"],
            generation=int(row["generation"]),
            environment_id=row["environment_id"],
            image=row["image"],
            cpus=row["cpus"],
            memory=row["memory"],
            expires_at=row["expires_at"],
            state=row["state"],
            destroyed_at=row["destroyed_at"],
        )
