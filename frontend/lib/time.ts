/** Shared job/run timestamp formatting for feed cards and headers. */

/** Align with explore `JOB_STALL_SECONDS` default (D83) — client hint only. */
const JOB_STALL_SECONDS = 600;

export function relativeTime(iso: string, now = Date.now()): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const sec = Math.max(0, Math.round((now - then) / 1000));
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 48) return `${hr}h ago`;
  const day = Math.round(hr / 24);
  return `${day}d ago`;
}

export function absoluteTime(iso: string): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(then));
}

export function formatJobWhen(
  iso: string,
  now = Date.now(),
): {
  iso: string;
  relative: string;
  absolute: string;
} {
  return {
    iso,
    relative: relativeTime(iso, now),
    absolute: absoluteTime(iso),
  };
}

/** True when a non-terminal job has had no ledger activity for the stall window. */
export function isJobStalled(
  updatedAt: string | null | undefined,
  opts?: { now?: number; stallSeconds?: number },
): boolean {
  if (!updatedAt) return false;
  const then = Date.parse(updatedAt);
  if (Number.isNaN(then)) return false;
  const now = opts?.now ?? Date.now();
  const stallSeconds = opts?.stallSeconds ?? JOB_STALL_SECONDS;
  return now - then >= stallSeconds * 1000;
}
