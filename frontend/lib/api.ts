/** Browser client → same-origin `/api` (never holds INTERNAL_API_TOKEN). */

import type {
  DetonationVerdict,
  DynamicInstallSpec,
  EnvironmentProfile,
  TestScenarioPlan,
} from "./job-artifacts";

type ApiError = {
  error: string;
  code: string;
};

export type CreateJobResponse = { job_id: string };

type CleanupState = {
  status: "pending" | "destroying" | "destroyed" | "destroy_failed";
  attempts: number;
  last_error: string | null;
  updated_at: string | null;
};

type VerificationInfo = {
  kind: "original_application" | "generated_demo" | "setup_failed";
  original_failure?:
    | {
        step?: string;
        summary: string;
        detail?: unknown;
      }
    | string
    | null;
};

export type SafetyOutcome = "safe" | "high_risk" | "review" | "unknown";

export type ActiveChecks = {
  install_trace: "full" | "partial" | "none" | null;
  mcp_tools_reviewed: number | null;
  finding_count: number;
  leading_finding: VulnFinding | null;
  by_check?: {
    check: string;
    label: string;
    count: number;
    finding_id: string;
    severity: string;
  }[];
};

export type JobSummary = {
  active_checks?: ActiveChecks | null;
  job_id: string;
  github_url: string;
  status: string;
  progress: number;
  current_step: string;
  created_at: string;
  updated_at?: string;
  screenshot_id?: string | null;
  /** Absolute CDN URL when Object Storage + CDN configured (D76); else API path. */
  screenshot_url?: string | null;
  error?: string | null;
  verification?: VerificationInfo | null;
  /** Slim security stamp for feed cards; null while running / no receipt. */
  safety?: SafetyOutcome | null;
  /** 1-based FIFO place when pending/queued; null otherwise. */
  queue_position?: number | null;
  /** Soft ETA while pending/queued; null otherwise. */
  expected_wait_seconds?: number | null;
};

export type JobListResponse = {
  jobs: JobSummary[];
  total: number;
  limit: number;
  offset: number;
};

export type RepoSummary = {
  github_url: string;
  run_count: number;
  latest: JobSummary;
};

export type RepoListResponse = {
  repos: RepoSummary[];
  total: number;
  limit: number;
  offset: number;
};

type ReadinessInfo = {
  passed: boolean;
  probe?: string | null;
  detail?: unknown;
  at?: string;
};

// Older SCA and stream findings may omit the fields required by a v1 verdict.
type VerdictFinding = DetonationVerdict["findings"][number];
export type VulnFinding = Partial<
  Omit<VerdictFinding, "severity" | "detail">
> & {
  severity?: string;
  package?: string;
  advisory_url?: string;
  detail?: unknown;
};

type VulnReportStatus = "ok" | "partial" | "failed";

export type VulnReportData = {
  job_id: string;
  summary: string;
  findings: VulnFinding[];
  mcp_assessment: {
    // The trusted fixture runner includes its check name in newer receipts.
    check?: string;
    enabled?: boolean;
    status?: "passed" | "ok" | "partial" | "skipped" | "failed";
    transport?: "stdio" | "streamable_http" | null;
    helper?: "present" | "missing";
    finding_id?: string;
    reason?: string;
    note?: string;
    at?: string;
  } | null;
  status: VulnReportStatus;
};

type TerminalStatus = "completed" | "failed" | "cancelled";

type JobReceipt = {
  job_id: string;
  verification: VerificationInfo | null;
  containment: {
    claim?: "proven" | "incomplete" | "complete";
    status?: "skipped";
    reason?: string;
    at?: string;
    dimensions?: Record<string, unknown>;
    network_probes?: unknown[];
    canary_scan?: Record<string, unknown>;
    install_cp_probe?: Record<string, unknown> | null;
  } | null;
  lifecycle: {
    destroyed_at?: string | null;
    cleanup?: CleanupState["status"];
    destroy_error?: string | null;
    confirmed?: boolean;
    cancel?: boolean;
  } | null;
  // Early failure/cancel receipts can omit the normal finalizer's gate evidence.
  dossier: ReceiptDossier;
  detonation_verdict?: DetonationVerdict | null;
};

/** Durable receipt metadata shared by the report and feed. */
type ReceiptDossier = {
  active_checks?: ActiveChecks | null;
  outcome?: TerminalStatus | "setup_failed";
  gates?: {
    terminal: TerminalStatus;
    reasons: string[];
    hard_fail: boolean;
    readiness_passed: boolean;
  };
  readiness?: ReadinessInfo | null;
  verification?: VerificationInfo | null;
  profile_revisions?: {
    revision: number;
    phase: "bootstrap" | "runtime";
    schema_version: string;
  }[];
  sandbox_generations?: (EnvironmentGen & {
    image: string;
    destroyed_at: string | null;
  })[];
  finding_ids?: (string | null)[];
  vuln_report_status?: VulnReportStatus | null;
  vuln_review?: string | null;
  scan_error?: string | null;
  code?: string;
  phase?: string;
  cancel_requested_at?: string;
  containment_at?: string;
  at?: string;
  detonation_verdict?: DetonationVerdict | null;
};

type EnvironmentGen = {
  environment_id: string;
  generation: number;
  state:
    | "provisioning"
    | "running"
    | "replaced"
    | "destroying"
    | "destroyed"
    | "destroy_failed"
    | "failed";
  expires_at: string;
  image?: string | null;
  destroyed_at?: string | null;
};

// The existing worker stores bootstrap and runtime profiles under the same
// version string as the alignment schema. Legacy source.type is "git".
type LegacyEnvironmentProfile = {
  schema_version: "1";
  intent: "bootstrap" | EnvironmentProfile["intent"];
  phase?: string;
  source?: { type: "git"; url: string; ref?: string; commit?: string };
  runtime?: string;
  os_image?: string;
  oci_image?: string;
  workdir?: string;
  services?: unknown[];
  packages?: unknown[];
  install_commands?: unknown[];
  run_commands?: unknown[];
  processes?: unknown[];
  ports?: unknown[];
  summary?: string;
  verification_target?: EnvironmentProfile["verification_target"];
  mcp?: Record<string, unknown>;
  probes?: unknown[];
  healthcheck?: Record<string, unknown>;
  policy?: Record<string, unknown>;
  original_failure?: VerificationInfo["original_failure"];
};

/** Plane 1 publishes current availability without issuing a viewing grant. */
export type NoVncInfo = { view_only: true } & (
  | { available: true; ws_path: string; generation: number }
  | { available: false; ws_path?: null }
);

type InferenceCounts = {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  calls: number;
};

export type JobSnapshot = {
  job_id: string;
  github_url: string;
  status: string;
  progress: number;
  current_step: string;
  steps_completed: string[];
  event_cursor: string | null;
  error: string | null;
  cancel_requested_at: string | null;
  updated_at: string;
  created_at: string;
  screenshot_ids: string[];
  profile: EnvironmentProfile | LegacyEnvironmentProfile | null;
  readiness: ReadinessInfo | null;
  verification: VerificationInfo | null;
  verify_result: Record<string, unknown> | null;
  sandbox_id: string | null;
  resolved_commit: string | null;
  current_profile_revision: number | null;
  current_sandbox_generation: number | null;
  inference_model: string | null;
  inference_usage:
    | (InferenceCounts & {
        budget_tokens: number;
        wall_ms?: number;
        // Older jobs and unscoped optional calls only have the aggregate counters.
        by_role?: Partial<
          Record<"planner" | "review", InferenceCounts & { model: string }>
        >;
      })
    | null;
  expires_at: string;
  cleanup: CleanupState;
  destroyed_at: string | null;
  environment: EnvironmentGen | null;
  vuln_report: VulnReportData | null;
  receipt: JobReceipt | null;
  // Alignment fields are absent from snapshots written by the legacy worker.
  target_type?: DynamicInstallSpec["target"]["source_type"];
  target_locator?: string | null;
  install_spec?: DynamicInstallSpec | null;
  scenario_plan?: TestScenarioPlan | null;
  detonation_verdict?: DetonationVerdict | null;
  novnc?: NoVncInfo | null;
  /** 1-based FIFO place when pending/queued; null otherwise. */
  queue_position?: number | null;
  /** Soft ETA while pending/queued; null otherwise. */
  expected_wait_seconds?: number | null;
};

export type ScreenshotMeta = {
  screenshot_id: string;
  job_id?: string;
  step?: string;
  caption?: string;
  storage_path?: string;
  created_at?: string;
  /** Absolute CDN URL when Object Storage + CDN configured (D76); else API path. */
  url?: string;
};

async function parseJson<T>(res: Response): Promise<T> {
  const text = await res.text();
  if (!text.trim()) {
    throw Object.assign(
      new Error(
        res.ok ? "Empty response from server" : "Explore sidecar unavailable",
      ),
      {
        code: res.ok ? "empty_response" : "explore_unreachable",
        status: res.status,
      },
    );
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    throw Object.assign(new Error("Invalid JSON from server"), {
      code: "invalid_json",
      status: res.status,
    });
  }
}

export async function createJob(
  target: string | { fixture_id: string },
): Promise<CreateJobResponse> {
  const res = await fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    // Existing GitHub callers keep the same wire payload.
    body: JSON.stringify(
      typeof target === "string" ? { github_url: target } : target,
    ),
  });
  const body = await parseJson<CreateJobResponse & ApiError>(res);
  if (!res.ok) {
    throw Object.assign(new Error(body.error || "create failed"), {
      code: body.code || "error",
      status: res.status,
    });
  }
  return body;
}

export async function listJobs(
  limit = 9,
  offset = 0,
  githubUrl?: string,
): Promise<JobListResponse> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(Math.max(0, offset)),
  });
  if (githubUrl) {
    params.set("github_url", githubUrl);
  }
  const res = await fetch(`/api/jobs?${params.toString()}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  const body = await parseJson<JobListResponse & ApiError>(res);
  if (!res.ok) {
    throw Object.assign(new Error(body.error || "list failed"), {
      code: body.code || "error",
      status: res.status,
    });
  }
  return {
    jobs: Array.isArray(body.jobs) ? body.jobs : [],
    total: typeof body.total === "number" ? body.total : 0,
    limit: typeof body.limit === "number" ? body.limit : limit,
    offset: typeof body.offset === "number" ? body.offset : offset,
  };
}

export async function listRepos(
  limit = 9,
  offset = 0,
): Promise<RepoListResponse> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(Math.max(0, offset)),
  });
  const res = await fetch(`/api/repos?${params.toString()}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  const body = await parseJson<RepoListResponse & ApiError>(res);
  if (!res.ok) {
    throw Object.assign(new Error(body.error || "list failed"), {
      code: body.code || "error",
      status: res.status,
    });
  }
  return {
    repos: Array.isArray(body.repos) ? body.repos : [],
    total: typeof body.total === "number" ? body.total : 0,
    limit: typeof body.limit === "number" ? body.limit : limit,
    offset: typeof body.offset === "number" ? body.offset : offset,
  };
}

export async function getJob(jobId: string): Promise<JobSnapshot> {
  const res = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  const body = await parseJson<JobSnapshot & ApiError>(res);
  if (!res.ok) {
    throw Object.assign(new Error(body.error || "fetch failed"), {
      code: body.code || "error",
      status: res.status,
    });
  }
  return body;
}

export async function cancelJob(jobId: string): Promise<JobSnapshot> {
  const res = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, {
    method: "DELETE",
    headers: { Accept: "application/json" },
  });
  const body = await parseJson<JobSnapshot & ApiError>(res);
  if (!res.ok) {
    throw Object.assign(new Error(body.error || "cancel failed"), {
      code: body.code || "error",
      status: res.status,
    });
  }
  return body;
}

export function jobEventsUrl(jobId: string, after: string | null): string {
  const base = `/api/jobs/${encodeURIComponent(jobId)}/events`;
  if (!after) return base;
  return `${base}?after=${encodeURIComponent(after)}`;
}

export async function listScreenshots(
  jobId: string,
): Promise<ScreenshotMeta[]> {
  const res = await fetch(
    `/api/jobs/${encodeURIComponent(jobId)}/screenshots`,
    {
      headers: { Accept: "application/json" },
      cache: "no-store",
    },
  );
  const body = await parseJson<ScreenshotMeta[] & ApiError>(res);
  if (!res.ok) {
    const errBody = body as unknown as ApiError;
    throw Object.assign(new Error(errBody.error || "screenshots failed"), {
      code: errBody.code || "error",
      status: res.status,
    });
  }
  return Array.isArray(body) ? body : [];
}
