import type { SafetyOutcome } from "@/lib/api";

const STAMP: Record<
  SafetyOutcome,
  { label: string; tone: "ok" | "danger" | "warn" }
> = {
  safe: { label: "No risks flagged", tone: "ok" },
  high_risk: { label: "High risk", tone: "danger" },
  review: { label: "Review", tone: "warn" },
  unknown: { label: "Unknown", tone: "warn" },
};

const COMPACT_TONE: Record<
  "ok" | "danger" | "warn",
  { bg: string; fg: string }
> = {
  ok: { bg: "var(--ok-soft)", fg: "var(--ok)" },
  danger: { bg: "var(--danger-soft)", fg: "var(--danger)" },
  warn: { bg: "var(--warn-soft)", fg: "var(--warn)" },
};

type ResultStampProps = {
  safety: SafetyOutcome;
  /** Badge-sized variant that lines up with status/verification badges in lists. */
  compact?: boolean;
};

export function ResultStamp({ safety, compact = false }: ResultStampProps) {
  const stamp = STAMP[safety];
  if (compact) {
    const tone = COMPACT_TONE[stamp.tone];
    return (
      <span
        className="inline-flex shrink-0 items-center rounded-md px-2 py-0.5 text-xs font-medium tracking-wide"
        style={{ background: tone.bg, color: tone.fg }}
      >
        {stamp.label}
      </span>
    );
  }
  return (
    <p className={`result-stamp result-stamp-${stamp.tone}`}>{stamp.label}</p>
  );
}
