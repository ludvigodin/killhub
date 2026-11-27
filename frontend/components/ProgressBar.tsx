type ProgressBarProps = {
  progress: number;
  label?: string;
  /** Animate the fill so a slow/running job still feels live. */
  active?: boolean;
};

export function ProgressBar({
  progress,
  label,
  active = false,
}: ProgressBarProps) {
  const clamped = Math.max(0, Math.min(100, Math.round(progress || 0)));
  return (
    <div className="w-full">
      <div className="mb-1.5 flex items-baseline justify-between gap-3 text-sm">
        <span className="text-(--muted)">{label || "Progress"}</span>
        <span className="font-mono tabular-nums text-(--ink)">{clamped}%</span>
      </div>
      <div
        className={`h-2 overflow-hidden rounded-full bg-(--paper-deep)${active ? " job-progress-active" : ""}`}
        role="progressbar"
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-busy={active || undefined}
        aria-label={label || "Job progress"}
      >
        <div
          className={`relative h-full overflow-hidden rounded-full bg-(--accent) transition-[width] duration-500 ease-out${active ? " job-progress-fill-active" : ""}`}
          style={{ width: `${clamped}%` }}
        >
          {active ? <span className="job-progress-sheen" aria-hidden /> : null}
        </div>
      </div>
    </div>
  );
}
