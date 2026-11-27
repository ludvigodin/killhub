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
    # The Plane 1 model resolver falls back to the existing default (D74).
    vultr_inference_model_planner: str = Field(default="", alias="VULTR_INFERENCE_MODEL_PLANNER")
    vultr_inference_model_review: str = Field(default="", alias="VULTR_INFERENCE_MODEL_REVIEW")
    # Optional extras on the same Killhub subscription (D75 under D25).
    vultr_inference_embedding_model: str = Field(
        default="",
        alias="VULTR_INFERENCE_EMBEDDING_MODEL",
    )
    vultr_inference_vision_model: str = Field(
        default="",
        alias="VULTR_INFERENCE_VISION_MODEL",
    )
    # When set, cite-checked vuln_review drafts via POST /chat/completions/RAG.
    vultr_rag_collection: str = Field(default="", alias="VULTR_RAG_COLLECTION")
    # When true + collection set, upsert this job's finding snippets into the store.
    vultr_rag_seed_findings: bool = Field(
        default=False,
        alias="VULTR_RAG_SEED_FINDINGS",
    )
    # AI draft for vuln_review (still cite-filtered — D48). Fail closed → deterministic.
    enable_vuln_review_llm: bool = Field(default=True, alias="ENABLE_VULN_REVIEW_LLM")
    # Optional screenshot captioning; never gates completion (D31).
    enable_screenshot_vision: bool = Field(
        default=False,
        alias="ENABLE_SCREENSHOT_VISION",
    )

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
    # Vultr Container Registry — host/msb pull only (D74); never guest env.
    # Example pin: ewr.vultrcr.com/killhub/bootstrap@sha256:<digest>
    vultr_cr_endpoint: str = Field(default="", alias="VULTR_CR_ENDPOINT")
    vultr_cr_robot_username: str = Field(default="", alias="VULTR_CR_ROBOT_USERNAME")
    vultr_cr_robot_password: str = Field(default="", alias="VULTR_CR_ROBOT_PASSWORD")
    vultr_cr_require_creds: bool = Field(default=True, alias="VULTR_CR_REQUIRE_CREDS")
    # Comma-separated hostnames/IPs/CIDRs denied on every create (D39).
    control_plane_deny_hosts: str = Field(
        default="",
        alias="CONTROL_PLANE_DENY_HOSTS",
    )
    containment_gateway_interface: str = Field(default="", alias="CONTAINMENT_GATEWAY_INTERFACE")
    containment_sibling_image: str = Field(default="", alias="CONTAINMENT_SIBLING_IMAGE")
    management_probe_address: str = Field(default="", alias="MANAGEMENT_PROBE_ADDRESS")
    msb_ready_timeout_seconds: int = Field(
        default=120,
        alias="MSB_READY_TIMEOUT_SECONDS",
    )
    canary_storage: str = Field(
        default="./storage/canaries",
        alias="CANARY_STORAGE",
    )

    # Plane-1 pre-flight (D45)
    public_demo_fixtures_only: bool = Field(default=False, alias="PUBLIC_DEMO_FIXTURES_ONLY")
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
    # D80: re-provision a vanished sandbox this many times per job (0 = off).
    max_sandbox_heals: int = Field(default=1, alias="MAX_SANDBOX_HEALS")
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
    # Rolling (cross-job) inference token budget; 0 disables (D40 / D71).
    inference_budget_tokens_rolling: int = Field(
        default=0,
        alias="INFERENCE_BUDGET_TOKENS_ROLLING",
    )
    inference_budget_rolling_window_seconds: int = Field(
        default=3600,
        alias="INFERENCE_BUDGET_ROLLING_WINDOW_SECONDS",
    )
    # Admission shared store: memory (default) | valkey (D71).
    admission_store: str = Field(default="memory", alias="ADMISSION_STORE")
    valkey_url: str = Field(default="", alias="VALKEY_URL")
    redis_url: str = Field(default="", alias="REDIS_URL")
    # Edge rate limits (also honored by explore when client IP is forwarded).
    rate_limit_window_ms: int = Field(default=60_000, alias="RATE_LIMIT_WINDOW_MS")
    rate_limit_post_jobs_per_ip: int = Field(
        default=10,
        alias="RATE_LIMIT_POST_JOBS_PER_IP",
    )
    rate_limit_post_jobs_global: int = Field(
        default=60,
        alias="RATE_LIMIT_POST_JOBS_GLOBAL",
    )

    # Ledger / artifacts (D41 / D60 / D73 / D72) — sqlite:// default; postgresql:// hosted
    ledger_url: str = Field(
        default="sqlite:///./storage/ledger/killhub.db",
        alias="LEDGER_URL",
    )
    # filesystem (default) | s3 | object — Plane 1 only; never inject into sandboxes.
    storage_backend: str = Field(
        default="filesystem",
        alias="STORAGE_BACKEND",
    )
    # Local staging roots (also used when STORAGE_BACKEND=filesystem).
    # Legacy: SCREENSHOT_STORAGE=s3|object selects object backend with default path.
    screenshot_storage: str = Field(
        default="./storage/screenshots",
        alias="SCREENSHOT_STORAGE",
    )
    artifact_storage: str = Field(
        default="./storage/artifacts",
        alias="ARTIFACT_STORAGE",
    )
    profile_storage: str = Field(
        default="./storage/profiles",
        alias="PROFILE_STORAGE",
    )
    # Vultr Object Storage (S3-compatible) — required when backend is s3/object (D72).
    object_storage_endpoint: str = Field(
        default="",
        alias="OBJECT_STORAGE_ENDPOINT",
    )
    object_storage_region: str = Field(
        default="us-east-1",
        alias="OBJECT_STORAGE_REGION",
    )
    object_storage_bucket: str = Field(
        default="",
        alias="OBJECT_STORAGE_BUCKET",
    )
    object_storage_access_key: str = Field(
        default="",
        alias="OBJECT_STORAGE_ACCESS_KEY",
    )
    object_storage_secret_key: str = Field(
        default="",
        alias="OBJECT_STORAGE_SECRET_KEY",
    )
    object_storage_prefix: str = Field(
        default="killhub",
        alias="OBJECT_STORAGE_PREFIX",
    )
    # Optional Vultr CDN Pull Zone base for public screenshot URLs (D76).
    # e.g. https://cdn-xxxxx.vultrcdn.com — no trailing slash.
    object_storage_cdn_base_url: str = Field(
        default="",
        alias="OBJECT_STORAGE_CDN_BASE_URL",
    )
    # Nightly ledger backup may also upload when true (and object backend configured).
    ledger_backup_upload: bool = Field(
        default=False,
        alias="LEDGER_BACKUP_UPLOAD",
    )
    # When true with MSB_AUTO_CREATE, run bootstrap discover after create (D36).
    discover_on_claim: bool = Field(default=False, alias="DISCOVER_ON_CLAIM")
    # After discover, attempt install + offline transition (D43).
    install_on_claim: bool = Field(default=False, alias="INSTALL_ON_CLAIM")
    # After install, launch + readiness verify (D37, D54) — never completes/destroys.
    verify_on_claim: bool = Field(default=False, alias="VERIFY_ON_CLAIM")
    # After verify, run containment matrix + canary scan (D58, D65) — never destroys.
    containment_on_claim: bool = Field(default=False, alias="CONTAINMENT_ON_CLAIM")
    # After verify, optional in-guest Playwright still (D31, D38) — never gates completion.
    screenshots_on_claim: bool = Field(default=False, alias="SCREENSHOTS_ON_CLAIM")
    # After probes: SCA + receipt + destroy → terminal (D37, D49, D57, D66).
    finalize_on_claim: bool = Field(default=False, alias="FINALIZE_ON_CLAIM")
    # Plane-1 OSV endpoint for lockfile SCA (D43) — never queried from guest offline.
    vuln_scan_osv_url: str = Field(
        default="https://api.osv.dev/v1/querybatch",
        alias="VULN_SCAN_OSV_URL",
    )
    # Known-live control-plane / public URL for install-phase CP denial probes (D65).
    control_plane_probe_url: str = Field(
        default="https://example.com",
        alias="CONTROL_PLANE_PROBE_URL",
    )
    # Positive-control URL that should succeed from guest during install egress
    # (must NOT be in CONTROL_PLANE_DENY_HOSTS — distinct from CP probe).
    install_egress_probe_url: str = Field(
        default="https://github.com",
        alias="INSTALL_EGRESS_PROBE_URL",
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
