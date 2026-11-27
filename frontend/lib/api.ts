/** Browser client → same-origin `/api` (never holds INTERNAL_API_TOKEN). */

type ApiError = {
  error: string;
  code: string;
};

export type CreateJobResponse = { job_id: string };

type CleanupState = {
  status?: string;
  attempts?: number;
  last_error?: string | null;
  updated_at?: string | null;
};

type VerificationInfo = {
  kind?: string;
  original_failure?: unknown;
  [key: string]: unknown;
};

export type JobSummary = {
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
};

export type JobListResponse = {
  jobs: JobSummary[];
  total: number;
  limit: number;
  offset: number;
};

type ReadinessInfo = {
  passed?: boolean;
  probe?: string;
  detail?: unknown;
  at?: string;
  [key: string]: unknown;
};

export type VulnFinding = {
  id?: string;
  severity?: string;
  package?: string;
  title?: string;
  advisory_url?: string;
  source?: string;
  detail?: unknown;
};

export type VulnReportData = {
  job_id?: string;
  summary?: string;
  findings?: VulnFinding[];
  mcp_assessment?: Record<string, unknown> | null;
  status?: string;
};

type JobReceipt = {
  job_id?: string;
  verification?: VerificationInfo | null;
  containment?: Record<string, unknown> | null;
  lifecycle?: Record<string, unknown> | null;
  dossier?: Record<string, unknown> | null;
};

type EnvironmentGen = {
  environment_id?: string;
  generation?: number;
  state?: string;
  expires_at?: string;
};

export type JobSnapshot = {
  job_id: string;
  status: string;
  progress: number;
  current_step: string;
  event_cursor: string | null;
  error: string | null;
  cancel_requested_at: string | null;
  updated_at: string;
  github_url?: string;
  created_at?: string;
  screenshot_ids?: string[];
  profile?: Record<string, unknown> | null;
  readiness?: ReadinessInfo | null;
  verification?: VerificationInfo | null;
  verify_result?: Record<string, unknown> | null;
  sandbox_id?: string | null;
  resolved_commit?: string | null;
  expires_at?: string;
  cleanup?: CleanupState | null;
  destroyed_at?: string | null;
  environment?: EnvironmentGen | null;
  vuln_report?: VulnReportData | null;
  receipt?: JobReceipt | null;
  [key: string]: unknown;
};

export type ScreenshotMeta = {
  screenshot_id: string;
  job_id?: string;
  step?: string;
  caption?: string;
  storage_path?: string;
  created_at?: string;
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

export async function createJob(githubUrl: string): Promise<CreateJobResponse> {
  const res = await fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ github_url: githubUrl }),
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
): Promise<JobListResponse> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(Math.max(0, offset)),
  });
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
