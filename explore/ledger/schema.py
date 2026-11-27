"""SQLite DDL for the Plane 1 ledger (DATABASE.md / D41 / D64)."""

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    github_url TEXT NOT NULL,
    resolved_commit TEXT,
    status TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    current_step TEXT NOT NULL DEFAULT '',
    steps_completed TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    readiness TEXT,
    verification TEXT,
    verify_result TEXT,
    sandbox_id TEXT,
    current_profile_revision INTEGER,
    current_sandbox_generation INTEGER,
    inference_model TEXT,
    inference_usage TEXT,
    event_cursor TEXT,
    expires_at TEXT NOT NULL,
    cleanup TEXT NOT NULL,
    destroyed_at TEXT,
    cancel_requested_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_events (
    job_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    type TEXT NOT NULL,
    message TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    timestamp TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    PRIMARY KEY (job_id, event_id),
    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_job_events_job_id ON job_events(job_id);

CREATE TABLE IF NOT EXISTS environment_profile_revisions (
    job_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    phase TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    profile TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (job_id, revision),
    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sandbox_generations (
    job_id TEXT NOT NULL,
    generation INTEGER NOT NULL,
    environment_id TEXT NOT NULL,
    image TEXT NOT NULL,
    cpus REAL,
    memory TEXT,
    expires_at TEXT NOT NULL,
    state TEXT NOT NULL,
    destroyed_at TEXT,
    PRIMARY KEY (job_id, generation),
    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS screenshots (
    screenshot_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    step TEXT NOT NULL,
    caption TEXT NOT NULL DEFAULT '',
    storage_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS vuln_reports (
    job_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL DEFAULT '',
    findings TEXT NOT NULL DEFAULT '[]',
    mcp_assessment TEXT,
    status TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS job_receipts (
    job_id TEXT PRIMARY KEY,
    verification TEXT,
    containment TEXT,
    lifecycle TEXT,
    dossier TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ledger_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""
