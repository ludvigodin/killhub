/** Public still URLs — prefer CDN (D76), fall back to Plane-1 proxy. */

function apiScreenshotPath(jobId: string, screenshotId: string): string {
  return `/api/jobs/${encodeURIComponent(jobId)}/screenshots/${encodeURIComponent(screenshotId)}`;
}

/** Prefer an absolute CDN / public URL; otherwise the same-origin API path. */
export function resolveScreenshotSrc(
  jobId: string,
  screenshotId: string,
  publicUrl?: string | null,
): string {
  const trimmed = publicUrl?.trim();
  if (trimmed) return trimmed;
  return apiScreenshotPath(jobId, screenshotId);
}

/** When a CDN URL fails (private pre-D76 object), retry via the API proxy. */
export function screenshotFallbackSrc(
  jobId: string,
  screenshotId: string,
  failedSrc: string,
): string | null {
  const api = apiScreenshotPath(jobId, screenshotId);
  if (failedSrc === api) return null;
  return api;
}
