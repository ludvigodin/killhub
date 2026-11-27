"use client";

import { useState } from "react";
import { resolveScreenshotSrc, screenshotFallbackSrc } from "@/lib/screenshots";
import { SectionHeader } from "./SectionHeader";
import { SECTION_SCROLL_MT } from "./SectionNav";

export type ScreenshotItem = {
  screenshot_id: string;
  step?: string;
  caption?: string;
  /** Absolute CDN URL (D76) or relative `/api/…` path. */
  url?: string;
  created_at?: string;
};

type ScreenshotTimelineProps = {
  jobId: string;
  shots: ScreenshotItem[];
};

function shotSrc(jobId: string, shot: ScreenshotItem): string {
  return resolveScreenshotSrc(jobId, shot.screenshot_id, shot.url);
}

function ShotImage({
  jobId,
  screenshotId,
  src,
  alt,
  className,
  priority = false,
}: {
  jobId: string;
  screenshotId: string;
  src: string;
  alt: string;
  className?: string;
  priority?: boolean;
}) {
  const [currentSrc, setCurrentSrc] = useState(src);

  return (
    // biome-ignore lint/performance/noImgElement: dynamic CDN or API still bytes
    <img
      src={currentSrc}
      alt={alt}
      className={`opacity-0 transition-opacity duration-500 data-[ready=true]:opacity-100 ${className ?? ""}`}
      loading={priority ? "eager" : "lazy"}
      onLoad={(e) => {
        e.currentTarget.dataset.ready = "true";
      }}
      onError={() => {
        const fallback = screenshotFallbackSrc(jobId, screenshotId, currentSrc);
        if (fallback) setCurrentSrc(fallback);
      }}
    />
  );
}

export function ScreenshotTimeline({ jobId, shots }: ScreenshotTimelineProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  if (shots.length === 0) return null;

  const activeId =
    selectedId && shots.some((s) => s.screenshot_id === selectedId)
      ? selectedId
      : shots[shots.length - 1].screenshot_id;
  const featured =
    shots.find((s) => s.screenshot_id === activeId) ?? shots[shots.length - 1];
  const featuredSrc = shotSrc(jobId, featured);

  return (
    <section
      id="section-screenshots"
      aria-label="Screenshot trail"
      className={`overflow-hidden border border-(--line) bg-(--paper-deep)/55 ${SECTION_SCROLL_MT}`}
    >
      <div className="border-b border-(--line) px-3 py-4 sm:px-4">
        <SectionHeader
          eyebrow="Verifiable stills"
          title="Screenshot trail"
          meta={
            <p className="type-mono text-(--muted)">
              {shots.length} still{shots.length === 1 ? "" : "s"}
            </p>
          }
        />
      </div>

      <figure className="relative bg-(--paper)">
        <ShotImage
          key={`${featured.screenshot_id}:${featuredSrc}`}
          jobId={jobId}
          screenshotId={featured.screenshot_id}
          src={featuredSrc}
          alt={featured.caption || `Screenshot ${featured.screenshot_id}`}
          priority
          className="aspect-[16/9] w-full object-cover object-top sm:aspect-[2/1]"
        />
        <figcaption className="absolute inset-x-0 bottom-0 bg-linear-to-t from-[#0a0b0d]/95 via-[#0a0b0d]/55 to-transparent px-3 pb-3 pt-10 sm:px-4">
          <p className="type-display text-sm font-semibold tracking-tight text-(--ink) sm:text-base">
            {featured.step || "still"}
          </p>
          {featured.caption ? (
            <p className="mt-0.5 text-xs text-(--muted) sm:text-sm">
              {featured.caption}
            </p>
          ) : null}
        </figcaption>
      </figure>

      {shots.length > 1 ? (
        <ol
          className="flex gap-2 overflow-x-auto border-t border-(--line) px-3 py-3 sm:px-4"
          aria-label="Screenshot history"
        >
          {shots.map((shot, index) => {
            const src = shotSrc(jobId, shot);
            const selected = shot.screenshot_id === featured.screenshot_id;
            return (
              <li key={shot.screenshot_id} className="shrink-0">
                <button
                  type="button"
                  onClick={() => setSelectedId(shot.screenshot_id)}
                  aria-pressed={selected}
                  aria-label={`Show still ${index + 1}: ${shot.step || shot.screenshot_id}`}
                  className={`block w-28 overflow-hidden border transition duration-200 sm:w-32 ${
                    selected
                      ? "border-(--accent) ring-2 ring-(--accent-soft)"
                      : "border-(--line) opacity-75 hover:opacity-100"
                  }`}
                >
                  <ShotImage
                    key={`${shot.screenshot_id}:${src}`}
                    jobId={jobId}
                    screenshotId={shot.screenshot_id}
                    src={src}
                    alt=""
                    className="aspect-video w-full object-cover object-top"
                  />
                  <span className="block truncate px-1.5 py-1 type-mono text-(--muted)">
                    {index + 1}. {shot.step || "still"}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      ) : null}
    </section>
  );
}
