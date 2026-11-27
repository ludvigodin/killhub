"""Plane 1 explore worker settings (env-backed). Secrets stay out of the sandbox."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Sidecar HTTP — default loopback; compose sets 0.0.0.0 for the internal network
    explore_host: str = Field(default="127.0.0.1", alias="EXPLORE_HOST")
    explore_port: int = Field(default=8100, alias="EXPLORE_PORT")
    internal_api_token: str = Field(default="", alias="INTERNAL_API_TOKEN")
    sse_keepalive_seconds: int = Field(default=15, alias="SSE_KEEPALIVE_SECONDS")
    worker_poll_seconds: float = Field(default=1.0, alias="WORKER_POLL_SECONDS")

    # Vultr
    vultr_api_key: str = Field(default="", alias="VULTR_API_KEY")
    vultr_inference_base_url: str = Field(
        default="https://api.vultrinference.com/v1",
        alias="VULTR_INFERENCE_BASE_URL",
    )
    vultr_inference_api_key: str = Field(default="", alias="VULTR_INFERENCE_API_KEY")
    vultr_inference_model: str = Field(default="", alias="VULTR_INFERENCE_MODEL")

    # OpenCode (trusted config only — D38; empty → explore/opencode/opencode.json)
    opencode_config: str = Field(default="", alias="OPENCODE_CONFIG")
    opencode_model: str = Field(default="", alias="OPENCODE_MODEL")

    # Microsandbox harness defaults (D36, D59)
    msb_host: str = Field(default="", alias="MSB_HOST")
    msb_bin: str = Field(default="msb", alias="MSB_BIN")
    msb_ssh_key: str = Field(default="", alias="MSB_SSH_KEY")
    msb_default_image: str = Field(default="debian", alias="MSB_DEFAULT_IMAGE")
    msb_default_cpus: int = Field(default=2, alias="MSB_DEFAULT_CPUS")
    msb_default_memory: str = Field(default="4Gi", alias="MSB_DEFAULT_MEMORY")
    msb_net_policy: str = Field(default="", alias="MSB_NET_POLICY")
    # Comma-separated hostnames/IPs/CIDRs denied on every create (D39).
    control_plane_deny_hosts: str = Field(
        default="",
        alias="CONTROL_PLANE_DENY_HOSTS",
    )
    msb_ready_timeout_seconds: int = Field(
        default=120,
        alias="MSB_READY_TIMEOUT_SECONDS",
    )
    canary_storage: str = Field(
        default="./storage/canaries",
        alias="CANARY_STORAGE",
    )

    # Plane-1 pre-flight (D45)
    preflight_enabled: bool = Field(default=True, alias="PREFLIGHT_ENABLED")
    preflight_deny_repos: str = Field(default="", alias="PREFLIGHT_DENY_REPOS")
    preflight_github_api: str = Field(
        default="https://api.github.com",
        alias="PREFLIGHT_GITHUB_API",
    )
    preflight_timeout_seconds: float = Field(
        default=5.0,
        alias="PREFLIGHT_TIMEOUT_SECONDS",
    )
    preflight_soft_max_size_kb: int = Field(
        default=500_000,
        alias="PREFLIGHT_SOFT_MAX_SIZE_KB",
    )
    github_token: str = Field(default="", alias="GITHUB_TOKEN")
    # When true, worker creates a bootstrap sandbox on claim (T0).
    msb_auto_create: bool = Field(default=False, alias="MSB_AUTO_CREATE")
    reaper_poll_seconds: float = Field(default=30.0, alias="REAPER_POLL_SECONDS")
    reaper_enabled: bool = Field(default=True, alias="REAPER_ENABLED")

    # Timeouts / caps
    job_timeout_seconds: int = Field(default=3600, alias="JOB_TIMEOUT_SECONDS")
    env_ttl_seconds: int = Field(default=7200, alias="ENV_TTL_SECONDS")
    max_repair_attempts: int = Field(default=3, alias="MAX_REPAIR_ATTEMPTS")
    max_concurrent_jobs: int = Field(default=2, alias="MAX_CONCURRENT_JOBS")
    max_queued_jobs: int = Field(default=8, alias="MAX_QUEUED_JOBS")
    # Optional hard reject for inference budget demos (D40).
    inference_budget_reject: bool = Field(
        default=False,
        alias="INFERENCE_BUDGET_REJECT",
    )
    max_job_log_bytes: int = Field(default=2_000_000, alias="MAX_JOB_LOG_BYTES")
    max_screenshots_per_job: int = Field(default=12, alias="MAX_SCREENSHOTS_PER_JOB")
    max_copy_bytes: int = Field(default=32_000_000, alias="MAX_COPY_BYTES")
    msb_exec_timeout_seconds: float = Field(
        default=120.0,
        alias="MSB_EXEC_TIMEOUT_SECONDS",
    )
    inference_budget_tokens_per_job: int = Field(
        default=200_000,
        alias="INFERENCE_BUDGET_TOKENS_PER_JOB",
    )

    # Ledger / artifacts (paths only for now — D41 / D60)
    ledger_url: str = Field(
        default="sqlite:///./storage/ledger/killhub.db",
        alias="LEDGER_URL",
    )
    screenshot_storage: str = Field(
        default="./storage/screenshots",
        alias="SCREENSHOT_STORAGE",
    )
    artifact_storage: str = Field(
        default="./storage/artifacts",
        alias="ARTIFACT_STORAGE",
    )
    helpers_root: str = Field(
        default="./helpers",
        alias="HELPERS_ROOT",
    )
    msb_stage_dir: str = Field(
        default="/tmp/killhub-stage",
        alias="MSB_STAGE_DIR",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
