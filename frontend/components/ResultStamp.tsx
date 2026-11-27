import type { SafetyOutcome } from "@/lib/api";

const STAMP: Record<
  SafetyOutcome,
  { label: string; tone: "ok" | "danger" | "warn" }
> = {
  safe: { label: "Safe", tone: "ok" },
  high_risk: { label: "High risk", tone: "danger" },
  review: { label: "Review", tone: "warn" },
  unknown: { label: "Unknown", tone: "warn" },
};

type ResultStampProps = {
  safety: SafetyOutcome;
};

export function ResultStamp({ safety }: ResultStampProps) {
  const stamp = STAMP[safety];
  return (
    <p className={`result-stamp result-stamp-${stamp.tone}`}>{stamp.label}</p>
  );
}
