/** Plane 1 display helpers for the worker’s advisory queue position and ETA (D40). */

const QUEUE_STATUSES = new Set(["pending", "queued"]);

export function isInQueue(status: string): boolean {
  return QUEUE_STATUSES.has(status);
}

export function formatExpectedWait(
  seconds: number | null | undefined,
): string | null {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return null;
  if (seconds < 45) return "~under 1m";
  const mins = Math.max(1, Math.round(seconds / 60));
  if (mins < 60) return `~${mins}m`;
  const hours = Math.floor(mins / 60);
  const rem = mins % 60;
  return rem > 0 ? `~${hours}h ${rem}m` : `~${hours}h`;
}

export function formatQueueLine(opts: {
  status: string;
  queue_position?: number | null;
  expected_wait_seconds?: number | null;
  fallback?: string | null;
}): string | null {
  if (!isInQueue(opts.status)) return null;
  const parts = ["In queue"];
  if (
    typeof opts.queue_position === "number" &&
    Number.isFinite(opts.queue_position) &&
    opts.queue_position > 0
  ) {
    parts.push(`#${Math.round(opts.queue_position)}`);
  }
  const wait = formatExpectedWait(opts.expected_wait_seconds);
  if (wait) parts.push(wait);
  if (parts.length === 1 && opts.fallback) return opts.fallback;
  return parts.join(" · ");
}
