const TONE: Record<string, { bg: string; fg: string; label?: string }> = {
  pending: { bg: "var(--paper-deep)", fg: "var(--muted)" },
  queued: { bg: "var(--paper-deep)", fg: "var(--muted)" },
  analyzing: { bg: "var(--accent-soft)", fg: "var(--accent)" },
  planning: { bg: "var(--accent-soft)", fg: "var(--accent)" },
  provisioning: { bg: "var(--accent-soft)", fg: "var(--accent)" },
  installing: { bg: "var(--accent-soft)", fg: "var(--accent)" },
  verifying: { bg: "var(--accent-soft)", fg: "var(--accent)" },
  repairing: { bg: "#f3e8d4", fg: "#8a5a1a" },
  scanning: { bg: "var(--accent-soft)", fg: "var(--accent)" },
  finalizing: { bg: "var(--accent-soft)", fg: "var(--accent)" },
  completed: { bg: "#d8edd8", fg: "#1f6b3a" },
  failed: { bg: "#f8d9d6", fg: "#9b2c2c" },
  cancelled: { bg: "var(--paper-deep)", fg: "var(--muted)" },
};

type StatusBadgeProps = {
  status: string;
};

export function StatusBadge({ status }: StatusBadgeProps) {
  const tone = TONE[status] ?? { bg: "var(--paper-deep)", fg: "var(--ink)" };
  return (
    <span
      className="inline-flex items-center rounded-md px-2.5 py-1 text-sm font-medium tracking-wide transition-colors duration-300"
      style={{ background: tone.bg, color: tone.fg }}
    >
      {tone.label ?? status}
    </span>
  );
}
