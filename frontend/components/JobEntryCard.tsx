"use client";

import Link from "next/link";
import { useState } from "react";
import type { JobSummary } from "@/lib/api";
import { ownerRepoFromGithubUrl } from "@/lib/github";
import { RepoThumbnail } from "./RepoThumbnail";
import { StatusBadge } from "./StatusBadge";

function relativeTime(iso: string): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const sec = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 48) return `${hr}h ago`;
  const day = Math.round(hr / 24);
  return `${day}d ago`;
}

function GithubIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 16 16"
      width="16"
      height="16"
      fill="currentColor"
      aria-hidden
      focusable="false"
    >
      <title>GitHub</title>
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8" />
    </svg>
  );
}

type JobEntryCardProps = {
  job: JobSummary;
  index?: number;
  /** Override card link (repo history vs single job). */
  href?: string;
  /** When > 1, show how many runs exist for this repo. */
  runCount?: number;
};

export function JobEntryCard({
  job,
  index = 0,
  href,
  runCount,
}: JobEntryCardProps) {
  const title = ownerRepoFromGithubUrl(job.github_url) ?? job.github_url;
  const [failedShot, setFailedShot] = useState<string | null>(null);
  const shot =
    job.screenshot_url && job.screenshot_url.length > 0
      ? job.screenshot_url
      : job.screenshot_id != null && job.screenshot_id.length > 0
        ? `/api/jobs/${encodeURIComponent(job.job_id)}/screenshots/${encodeURIComponent(job.screenshot_id)}`
        : null;
  const delay = Math.min(index, 12) * 35;
  const githubHref = job.github_url;
  const cardHref = href ?? `/jobs/${encodeURIComponent(job.job_id)}`;
  const runsLabel =
    runCount != null && runCount > 1
      ? `${runCount} runs`
      : runCount === 1
        ? "1 run"
        : null;
  const progress = Math.max(0, Math.min(100, job.progress));

  return (
    <article
      className="job-entry group relative flex items-center border-b border-(--line) transition-colors duration-200 last:border-b-0 hover:bg-(--paper-deep)/80"
      style={{ animationDelay: `${delay}ms` }}
    >
      <Link
        href={cardHref}
        className="flex min-w-0 flex-1 items-center gap-3 px-3 py-3 no-underline -outline-offset-2 sm:gap-4 sm:px-4 sm:pr-2"
        aria-label={
          runsLabel ? `Open history for ${title}` : `Open job ${title}`
        }
      >
        <div className="relative size-10 shrink-0 overflow-hidden rounded-md bg-(--paper-deep) sm:size-11">
          {shot && shot !== failedShot ? (
            // biome-ignore lint/performance/noImgElement: dynamic API screenshot bytes
            <img
              src={shot}
              onError={() => setFailedShot(shot)}
              alt=""
              className="h-full w-full object-cover"
            />
          ) : (
            <RepoThumbnail repo={title} />
          )}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p
              className="truncate text-sm font-semibold tracking-tight text-(--ink) sm:text-base"
              style={{
                fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
              }}
            >
              {title}
            </p>
            <StatusBadge status={job.status} />
            {runsLabel ? (
              <span className="text-xs text-(--muted)">{runsLabel}</span>
            ) : null}
          </div>
          <p className="mt-0.5 truncate text-sm text-(--muted)">
            {job.current_step || "Waiting…"}
          </p>
          <div className="mt-2 h-0.5 overflow-hidden rounded-full bg-(--line)">
            <div
              className="h-full bg-(--accent) transition-[width] duration-700 ease-out"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      </Link>

      <div className="hidden shrink-0 flex-col items-end justify-center gap-1.5 py-3 pr-3 sm:flex sm:pr-4">
        <p className="text-xs tabular-nums text-(--muted)">
          {relativeTime(job.created_at)}
        </p>
        <a
          href={githubHref}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex size-7 items-center justify-center rounded-md text-(--muted) transition hover:bg-(--accent-soft) hover:text-(--ink)"
          aria-label={`Open ${title} on GitHub`}
          title="Open on GitHub"
        >
          <GithubIcon className="size-4" />
        </a>
      </div>
    </article>
  );
}
