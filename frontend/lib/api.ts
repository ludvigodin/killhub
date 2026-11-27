/** Browser client → same-origin `/api` (never holds INTERNAL_API_TOKEN). */

type ApiError = {
  error: string;
  code: string;
};

export type CreateJobResponse = { job_id: string };

export type JobSnapshot = {
  job_id: string;
  status: string;
  progress: number;
  current_step: string;
  event_cursor: string | null;
  error: string | null;
  cancel_requested_at: string | null;
  updated_at: string;
  screenshot_ids?: string[];
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
  return (await res.json()) as T;
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
