export type ScreenshotItem = {
  screenshot_id: string;
  step?: string;
  caption?: string;
  url?: string;
  created_at?: string;
};

type ScreenshotTimelineProps = {
  jobId: string;
  shots: ScreenshotItem[];
};

export function ScreenshotTimeline({ jobId, shots }: ScreenshotTimelineProps) {
  return (
    <section aria-label="Screenshot timeline">
      <p className="mb-2 text-sm uppercase tracking-wide text-[var(--muted)]">
        Screenshots
      </p>
      {shots.length === 0 ? (
        <p className="border border-dashed border-[var(--line)] bg-white/40 px-3 py-4 text-sm text-[var(--muted)]">
          No stills yet — optional for this job (CLI MCP / early fail stay
          empty).
        </p>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2">
          {shots.map((shot) => {
            const src =
              shot.url ||
              `/api/jobs/${encodeURIComponent(jobId)}/screenshots/${encodeURIComponent(shot.screenshot_id)}`;
            return (
              <li key={shot.screenshot_id} className="min-w-0">
                <figure className="overflow-hidden border border-[var(--line)] bg-white/70">
                  {/* biome-ignore lint/performance/noImgElement: local API bytes, not next/image CDN */}
                  <img
                    src={src}
                    alt={shot.caption || `Screenshot ${shot.screenshot_id}`}
                    className="aspect-video w-full object-cover object-top opacity-0 transition-opacity duration-500 data-[ready=true]:opacity-100"
                    loading="lazy"
                    onLoad={(e) => {
                      e.currentTarget.dataset.ready = "true";
                    }}
                  />
                  <figcaption className="border-t border-[var(--line)] px-3 py-2 text-xs text-[var(--muted)]">
                    <span className="font-medium text-[var(--ink)]">
                      {shot.step || "still"}
                    </span>
                    {shot.caption ? ` · ${shot.caption}` : null}
                  </figcaption>
                </figure>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
