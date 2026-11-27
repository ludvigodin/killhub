"""SQLite ledger helpers: create job, append event, snapshot, revisions, generations."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from ledger.schema import SCHEMA_SQL
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


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_sqlite_path(ledger_url: str) -> Path:
    """Resolve SQLAlchemy-style SQLite URLs to a filesystem path.

    - `sqlite:///relative.db` → cwd-relative
    - `sqlite:////abs/path.db` → absolute `/abs/path.db`
    """
    prefix = "sqlite://"
    if not ledger_url.startswith(prefix):
        parsed = urlparse(ledger_url)
        if parsed.scheme and parsed.scheme != "sqlite":
            raise ValueError(f"Unsupported ledger engine URL: {ledger_url}")
        raise ValueError(f"Invalid LEDGER_URL: {ledger_url}")

    rest = ledger_url[len(prefix) :]
    if rest.startswith("//"):
        # sqlite:////abs/path → rest="//abs/path"
        return Path(unquote(rest[1:])).resolve()
    if rest.startswith("/"):
        # sqlite:///relative → rest="/relative"
        path = Path(unquote(rest[1:]))
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.resolve()
    raise ValueError(f"Invalid LEDGER_URL: {ledger_url}")


def validate_github_url(url: str) -> str:
    cleaned = url.strip().rstrip("/")
    if not re.match(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", cleaned):
        raise ValueError("github_url must be a public https://github.com/org/repo URL")
    return cleaned


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
    """Durable SQLite job/event store owned by the explore sidecar (D41)."""

    def __init__(self, db_path: Path, *, max_job_log_bytes: int = 2_000_000) -> None:
        self.db_path = Path(db_path)
        self.max_job_log_bytes = max_job_log_bytes
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            self.db_path,
            isolation_level=None,  # manage transactions explicitly
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.executescript(SCHEMA_SQL)
        self._conn.execute(
            "INSERT OR REPLACE INTO ledger_meta(key, value) VALUES (?, ?)",
            ("engine", "sqlite"),
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO ledger_meta(key, value) VALUES (?, ?)",
            ("schema_version", "1"),
        )

    @classmethod
    def from_url(cls, ledger_url: str, *, max_job_log_bytes: int = 2_000_000) -> Ledger:
        return cls(parse_sqlite_path(ledger_url), max_job_log_bytes=max_job_log_bytes)

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

        self._conn.execute("BEGIN IMMEDIATE")
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
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
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
        rows = self._conn.execute("SELECT * FROM jobs ORDER BY created_at ASC").fetchall()
        return [self._row_to_job(r) for r in rows]

    def list_recent_jobs(self, *, limit: int = 48) -> list[Job]:
        """Newest-first job rows for the public feed (D69)."""
        capped = max(1, min(int(limit), 200))
        rows = self._conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (capped,),
        ).fetchall()
        return [self._row_to_job(r) for r in rows]

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
            "vuln_report": self.get_vuln_report(job_id),
            "screenshot_ids": [s["screenshot_id"] for s in self.list_screenshots(job_id)],
            "receipt": self.get_receipt(job_id),
        }

    class WriterFrozenError(RuntimeError):
        """Raised when ordinary writers mutate a cancel-frozen job (D61)."""

    def _assert_ordinary_writable(self, job: Job) -> None:
        if job.cancel_requested_at is not None:
            raise Ledger.WriterFrozenError(
                f"job {job.job_id} is cancel-frozen (cancel_requested_at set)"
            )
        if job.status in {"completed", "failed", "cancelled"}:
            raise Ledger.WriterFrozenError(f"job {job.job_id} is terminal ({job.status})")

    def update_job_fields(self, job_id: str, *, finalizer: bool = False, **fields: Any) -> Job:
        """Patch allowlisted job columns. Ordinary writers freeze after cancel (D61)."""
        allowed = {
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
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unsupported job fields: {sorted(unknown)}")

        json_fields = {
            "steps_completed",
            "readiness",
            "verification",
            "verify_result",
            "inference_usage",
            "cleanup",
        }

        self._conn.execute("BEGIN IMMEDIATE")
        try:
            job = self.get_job(job_id)
            if job is None:
                raise KeyError(f"unknown job_id: {job_id}")
            if not finalizer:
                self._assert_ordinary_writable(job)
            sets: list[str] = []
            values: list[Any] = []
            for key, value in fields.items():
                sets.append(f"{key} = ?")
                if key in json_fields:
                    if key == "cleanup" and isinstance(value, CleanupState):
                        values.append(_dumps(value.to_dict()))
                    else:
                        values.append(_dumps(value) if value is not None else None)
                else:
                    values.append(value)
            now = utc_now()
            sets.append("updated_at = ?")
            values.append(now)
            values.append(job_id)
            self._conn.execute(
                f"UPDATE jobs SET {', '.join(sets)} WHERE job_id = ?",
                values,
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
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
        self._conn.execute("BEGIN IMMEDIATE")
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
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
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
            SELECT event_id, byte_size FROM job_events
            WHERE job_id = ?
            ORDER BY CAST(event_id AS INTEGER) ASC
            """,
            (job_id,),
        ).fetchall()
        if len(rows) <= 1:
            return

        # Reserve room for the gap event (~512 bytes upper bound).
        budget = max(self.max_job_log_bytes - 512, 0)
        running = total
        to_delete: list[str] = []
        for row in rows[:-1]:  # never delete the newest event in this pass
            if running <= budget:
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
        remaining = len(rows) - len(to_delete) + 1  # + gap
        if self.retained_event_bytes(job_id) > self.max_job_log_bytes and remaining > 1:
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
        self._conn.execute("BEGIN IMMEDIATE")
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
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
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
        self._conn.execute("BEGIN IMMEDIATE")
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
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
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
        self._conn.execute("BEGIN IMMEDIATE")
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
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
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

    def upsert_vuln_report(
        self,
        job_id: str,
        *,
        summary: str,
        findings: list[dict[str, Any]],
        status: str,
        mcp_assessment: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if status not in {"ok", "partial", "failed"}:
            raise ValueError(f"invalid vuln_report status: {status}")
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO vuln_reports (
                    job_id, summary, findings, mcp_assessment, status
                ) VALUES (?, ?, ?, ?, ?)
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
        report = self.get_vuln_report(job_id)
        assert report is not None
        return report

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
        self._conn.execute("BEGIN IMMEDIATE")
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
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        receipt = self.get_receipt(job_id)
        assert receipt is not None
        return receipt

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

    def _row_to_job(self, row: sqlite3.Row) -> Job:
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

    def _row_to_event(self, row: sqlite3.Row) -> JobEvent:
        return JobEvent(
            event_id=row["event_id"],
            job_id=row["job_id"],
            type=row["type"],
            message=row["message"],
            payload=_loads(row["payload"], {}),
            timestamp=row["timestamp"],
        )

    def _row_to_generation(self, row: sqlite3.Row) -> SandboxGeneration:
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
