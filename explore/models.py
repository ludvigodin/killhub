"""Shared ledger models matching DATABASE.md field names."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

JobStatus = Literal[
    "pending",
    "queued",
    "analyzing",
    "planning",
    "provisioning",
    "installing",
    "verifying",
    "repairing",
    "scanning",
    "finalizing",
    "completed",
    "failed",
    "cancelled",
]

EventType = Literal[
    "status",
    "progress",
    "log",
    "screenshot",
    "error",
    "span",
    "finding",
    "containment",
    "lifecycle",
    "gap",
]

ProfilePhase = Literal["bootstrap", "runtime"]

SandboxState = Literal[
    "provisioning",
    "running",
    "replaced",
    "destroying",
    "destroyed",
    "destroy_failed",
    "failed",
]

CleanupStatus = Literal["pending", "destroying", "destroyed", "destroy_failed"]


@dataclass
class CleanupState:
    status: CleanupStatus = "pending"
    attempts: int = 0
    last_error: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CleanupState:
        if not data:
            return cls()
        return cls(
            status=data.get("status", "pending"),
            attempts=int(data.get("attempts", 0)),
            last_error=data.get("last_error"),
            updated_at=data.get("updated_at"),
        )


@dataclass
class Job:
    job_id: str
    github_url: str
    status: JobStatus
    progress: int
    current_step: str
    expires_at: str
    created_at: str
    updated_at: str
    resolved_commit: str | None = None
    steps_completed: list[str] = field(default_factory=list)
    error: str | None = None
    readiness: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    verify_result: dict[str, Any] | None = None
    sandbox_id: str | None = None
    current_profile_revision: int | None = None
    current_sandbox_generation: int | None = None
    inference_model: str | None = None
    inference_usage: dict[str, Any] | None = None
    event_cursor: str | None = None
    cleanup: CleanupState = field(default_factory=CleanupState)
    destroyed_at: str | None = None
    cancel_requested_at: str | None = None

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "github_url": self.github_url,
            "resolved_commit": self.resolved_commit,
            "status": self.status,
            "progress": self.progress,
            "current_step": self.current_step,
            "steps_completed": list(self.steps_completed),
            "error": self.error,
            "readiness": self.readiness,
            "verification": self.verification,
            "verify_result": self.verify_result,
            "sandbox_id": self.sandbox_id,
            "current_profile_revision": self.current_profile_revision,
            "current_sandbox_generation": self.current_sandbox_generation,
            "inference_model": self.inference_model,
            "inference_usage": self.inference_usage,
            "event_cursor": self.event_cursor,
            "expires_at": self.expires_at,
            "cleanup": self.cleanup.to_dict(),
            "destroyed_at": self.destroyed_at,
            "cancel_requested_at": self.cancel_requested_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class JobEvent:
    event_id: str
    job_id: str
    type: EventType
    message: str
    payload: dict[str, Any]
    timestamp: str


@dataclass
class EnvironmentProfileRevision:
    job_id: str
    revision: int
    phase: ProfilePhase
    schema_version: str
    profile: dict[str, Any]
    storage_path: str
    created_at: str


@dataclass
class SandboxGeneration:
    job_id: str
    generation: int
    environment_id: str
    image: str
    expires_at: str
    state: SandboxState
    cpus: float | None = None
    memory: str | None = None
    destroyed_at: str | None = None


@dataclass
class ReconcileReport:
    """Expired generations and terminal cleanup still owed by the reaper."""

    job_count: int
    live_generations: list[SandboxGeneration]
    expired_generations: list[SandboxGeneration]
    orphan_notes: list[str] = field(default_factory=list)
    cleanup_retry_generations: list[SandboxGeneration] = field(default_factory=list)
