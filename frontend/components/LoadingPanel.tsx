type LoadingPanelProps = {
  label: string;
  detail?: string;
};

export function LoadingPanel({ label, detail }: LoadingPanelProps) {
  return (
    <section
      aria-busy="true"
      aria-live="polite"
      aria-label={label}
      className="space-y-4 border border-(--line) bg-(--paper-deep)/60 px-4 py-5"
    >
      <div className="flex items-center gap-3">
        <span className="job-loading-dot" aria-hidden />
        <div className="min-w-0">
          <p className="text-sm text-(--ink)">{label}</p>
          {detail ? (
            <p className="mt-0.5 font-mono text-xs text-(--muted)">{detail}</p>
          ) : null}
        </div>
      </div>
      <div
        className="job-loading-track h-2 overflow-hidden rounded-full bg-(--paper)"
        role="progressbar"
        aria-valuetext={label}
        aria-label={label}
      >
        <div className="job-loading-bar h-full rounded-full bg-(--accent)" />
      </div>
    </section>
  );
}
