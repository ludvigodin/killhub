type ProgressBarProps = {
  progress: number;
  label?: string;
};

export function ProgressBar({ progress, label }: ProgressBarProps) {
  const clamped = Math.max(0, Math.min(100, Math.round(progress || 0)));
  return (
    <div className="w-full">
      <div className="mb-1.5 flex items-baseline justify-between gap-3 text-sm">
        <span className="text-(--muted)">{label || "Progress"}</span>
        <span className="font-mono tabular-nums text-(--ink)">
          {clamped}%
        </span>
      </div>
      <div
        className="h-2 overflow-hidden rounded-full bg-(--paper-deep)"
        role="progressbar"
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label || "Job progress"}
      >
        <div
          className="h-full rounded-full bg-(--accent) transition-[width] duration-500 ease-out"
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  );
}
