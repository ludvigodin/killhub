"""Job-scoped harness tools exposed to the Environment Agent (D38, D60).

These are the *only* agent-facing side effects on Plane 1. Host shell, arbitrary
path IO, and non-harness MCP are denied by the trusted OpenCode config.
"""

from __future__ import annotations

from typing import Any, Sequence

from config import Settings, get_settings
from errors import HarnessError
from harness import (
    EnvironmentPlan,
    copy_in,
    copy_out,
    create_environment,
    default_bootstrap_plan,
    destroy_environment,
    exec_command,
    wait_until_ready,
)
from jobs import get_ledger


class HarnessTools:
    """Thin job-scoped façade — stubs are callable; real msb when configured."""

    ALLOWED = frozenset(
        {
            "create",
            "exec",
            "copy_in",
            "copy_out",
            "destroy",
            "wait_ready",
            "readiness_probe_stub",
        }
    )

    def __init__(self, job_id: str, *, settings: Settings | None = None) -> None:
        self.job_id = job_id
        self.settings = settings or get_settings()

    def list_tools(self) -> list[str]:
        return sorted(self.ALLOWED)

    def call(self, name: str, **kwargs: Any) -> dict[str, Any]:
        if name not in self.ALLOWED:
            raise HarnessError(
                f"tool '{name}' is not exposed to the Environment Agent",
                code="tool_denied",
            )
        handler = getattr(self, f"tool_{name}")
        return handler(**kwargs)

    def _environment_id(self) -> str:
        job = get_ledger(self.settings).get_job(self.job_id)
        if job is None:
            raise HarnessError(f"unknown job_id: {self.job_id}", code="not_found")
        if not job.sandbox_id:
            raise HarnessError(
                "job has no sandbox yet — call create first",
                code="no_sandbox",
            )
        return job.sandbox_id

    def tool_create(self, plan: EnvironmentPlan | None = None) -> dict[str, Any]:
        gen = create_environment(
            self.job_id,
            plan or default_bootstrap_plan(self.settings),
            settings=self.settings,
        )
        return {
            "environment_id": gen.environment_id,
            "generation": gen.generation,
            "state": gen.state,
            "expires_at": gen.expires_at,
        }

    def tool_wait_ready(self, environment_id: str | None = None) -> dict[str, Any]:
        env_id = environment_id or self._environment_id()
        wait_until_ready(env_id, settings=self.settings)
        return {"environment_id": env_id, "ready": True}

    def tool_exec(
        self,
        command: str | Sequence[str],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        env_id = self._environment_id()
        result = exec_command(
            env_id,
            command,
            job_id=self.job_id,
            timeout=timeout,
            settings=self.settings,
        )
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def tool_copy_in(self, helper_ref: str, guest_dest: str) -> dict[str, Any]:
        env_id = self._environment_id()
        copy_in(
            env_id,
            helper_ref,
            guest_dest,
            job_id=self.job_id,
            settings=self.settings,
        )
        return {"copied": "in", "guest_dest": guest_dest}

    def tool_copy_out(
        self,
        guest_src: str,
        *,
        artifact_kind: str = "artifacts",
        filename: str | None = None,
    ) -> dict[str, Any]:
        env_id = self._environment_id()
        dest = copy_out(
            env_id,
            guest_src,
            artifact_kind,
            job_id=self.job_id,
            filename=filename,
            settings=self.settings,
        )
        return {"copied": "out", "host_path": str(dest)}

    def tool_destroy(self) -> dict[str, Any]:
        destroy_environment(self.job_id, settings=self.settings)
        return {"destroyed": True, "job_id": self.job_id}

    def tool_readiness_probe_stub(self) -> dict[str, Any]:
        """Placeholder until step 14 wires real readiness probes."""
        return {
            "status": "stub",
            "message": "readiness helpers land in plan 14",
            "job_id": self.job_id,
        }
