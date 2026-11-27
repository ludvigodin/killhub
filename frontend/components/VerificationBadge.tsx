/** Honest verification.kind label (D54) — original vs generated demo vs setup failed. */

const KIND: Record<
  string,
  { label: string; tone: "ok" | "warn" | "danger" | "muted" }
> = {
  original_application: { label: "original", tone: "ok" },
  generated_demo: { label: "demo", tone: "warn" },
  setup_failed: { label: "setup failed", tone: "danger" },
};

const TONE_STYLE: Record<
  "ok" | "warn" | "danger" | "muted",
  { bg: string; fg: string }
> = {
  ok: { bg: "var(--ok-soft)", fg: "var(--ok)" },
  warn: { bg: "var(--warn-soft)", fg: "var(--warn)" },
  danger: { bg: "var(--danger-soft)", fg: "var(--danger)" },
  muted: { bg: "var(--paper-deep)", fg: "var(--muted)" },
};

type VerificationBadgeProps = {
  kind: string | null | undefined;
};

export function VerificationBadge({ kind }: VerificationBadgeProps) {
  if (!kind) return null;
  const meta = KIND[kind] ?? { label: kind, tone: "muted" as const };
  const style = TONE_STYLE[meta.tone];
  return (
    <span
      className="inline-flex shrink-0 items-center rounded-md px-2 py-0.5 text-xs font-medium tracking-wide"
      style={{ background: style.bg, color: style.fg }}
      title={`verification.kind=${kind}`}
    >
      {meta.label}
    </span>
  );
}
