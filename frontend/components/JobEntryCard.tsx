"use client";

import Link from "next/link";
import type { JobSummary } from "@/lib/api";
import { ownerRepoFromGithubUrl } from "@/lib/github";
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
};

export function JobEntryCard({ job, index = 0 }: JobEntryCardProps) {
  const title = ownerRepoFromGithubUrl(job.github_url) ?? job.github_url;
  const initial =
    (title.split("/")[1] ?? title).slice(0, 1).toUpperCase() || "K";
  const shot =
    job.screenshot_url && job.screenshot_url.length > 0
      ? job.screenshot_url
      : job.screenshot_id != null && job.screenshot_id.length > 0
        ? `/api/jobs/${encodeURIComponent(job.job_id)}/screenshots/${encodeURIComponent(job.screenshot_id)}`
        : null;
  const delay = Math.min(index, 12) * 40;
  const githubHref = job.github_url;

  return (
    <article
      className="job-entry group relative flex flex-col overflow-hidden rounded-lg border border-(--line) bg-white/55 shadow-[0_1px_0_rgba(21,32,43,0.04)] transition duration-300 ease-out hover:-translate-y-0.5 hover:border-(--accent) hover:bg-white/80 hover:shadow-[0_12px_28px_rgba(21,32,43,0.08)]"
      style={{ animationDelay: `${delay}ms` }}
    >
      <Link
        href={`/jobs/${encodeURIComponent(job.job_id)}`}
        className="flex flex-1 flex-col no-underline outline-offset-[-2px]"
        aria-label={`Open job ${title}`}
      >
        <div className="relative aspect-16/10 overflow-hidden bg-(--paper-deep)">
          {shot ? (
            // biome-ignore lint/performance/noImgElement: dynamic API screenshot bytes
            <img
              src={shot}
              alt=""
              className="h-full w-full object-cover transition duration-500 ease-out group-hover:scale-[1.03]"
            />
          ) : (
            <div
              className="flex h-full w-full items-center justify-center"
              style={{
                background:
                  "linear-gradient(145deg, var(--accent-soft) 0%, var(--paper-deep) 55%, #c9d5e0 100%)",
              }}
              aria-hidden
            >
              <span
                className="text-5xl font-semibold text-(--accent) opacity-80"
                style={{
                  fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
                }}
              >
                {initial}
              </span>
            </div>
          )}
          <div className="absolute inset-x-0 bottom-0 h-1.5 bg-black/10">
            <div
              className="h-full bg-(--accent) transition-[width] duration-700 ease-out"
              style={{ width: `${Math.max(0, Math.min(100, job.progress))}%` }}
            />
          </div>
        </div>
        <div className="flex flex-1 flex-col gap-2 px-3.5 py-3">
          <div className="flex items-start justify-between gap-2">
            <p
              className="truncate text-base font-semibold tracking-tight text-(--ink)"
              style={{
                fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
              }}
            >
              {title}
            </p>
            <StatusBadge status={job.status} />
          </div>
          <p className="line-clamp-2 text-sm text-(--muted)">
            {job.current_step || "Waiting…"}
          </p>
          <p className="mt-auto pr-8 text-xs tracking-wide text-(--muted)">
            {relativeTime(job.created_at)}
          </p>
        </div>
      </Link>
      <a
        href={githubHref}
        target="_blank"
        rel="noopener noreferrer"
        className="absolute bottom-3 right-3 z-10 inline-flex size-7 items-center justify-center rounded-md text-(--muted) transition hover:bg-(--accent-soft) hover:text-(--ink)"
        aria-label={`Open ${title} on GitHub`}
        title="Open on GitHub"
      >
        <GithubIcon className="size-4" />
      </a>
    </article>
  );
}
