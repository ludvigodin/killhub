const TONE: Record<string, { bg: string; fg: string; label?: string }> = {
  pending: { bg: "var(--paper-deep)", fg: "var(--muted)" },
  queued: { bg: "var(--paper-deep)", fg: "var(--muted)" },
  analyzing: { bg: "var(--accent-soft)", fg: "var(--accent)" },
  planning: { bg: "var(--accent-soft)", fg: "var(--accent)" },
  provisioning: { bg: "var(--accent-soft)", fg: "var(--accent)" },
  installing: { bg: "var(--accent-soft)", fg: "var(--accent)" },
  verifying: { bg: "var(--accent-soft)", fg: "var(--accent)" },
  repairing: { bg: "var(--warn-soft)", fg: "var(--warn)" },
  scanning: { bg: "var(--accent-soft)", fg: "var(--accent)" },
  finalizing: { bg: "var(--accent-soft)", fg: "var(--accent)" },
  completed: { bg: "var(--ok-soft)", fg: "var(--ok)" },
  failed: { bg: "var(--danger-soft)", fg: "var(--danger)" },
  cancelled: { bg: "var(--paper-deep)", fg: "var(--muted)" },
};

type StatusBadgeProps = {
  status: string;
};

export function StatusBadge({ status }: StatusBadgeProps) {
  const tone = TONE[status] ?? { bg: "var(--paper-deep)", fg: "var(--ink)" };
  return (
    <span
      className="inline-flex shrink-0 items-center rounded-md px-2 py-0.5 text-xs font-medium tracking-wide transition-colors duration-300"
      style={{ background: tone.bg, color: tone.fg }}
    >
      {tone.label ?? status}
    </span>
  );
}
