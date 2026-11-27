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

type JobEntryCardProps = {
  job: JobSummary;
  index?: number;
};

export function JobEntryCard({ job, index = 0 }: JobEntryCardProps) {
  const title = ownerRepoFromGithubUrl(job.github_url) ?? job.github_url;
  const initial =
    (title.split("/")[1] ?? title).slice(0, 1).toUpperCase() || "K";
  const shot =
    job.screenshot_id != null && job.screenshot_id.length > 0
      ? `/api/jobs/${encodeURIComponent(job.job_id)}/screenshots/${encodeURIComponent(job.screenshot_id)}`
      : null;
  const delay = Math.min(index, 12) * 40;

  return (
    <Link
      href={`/jobs/${encodeURIComponent(job.job_id)}`}
      className="job-entry group flex flex-col overflow-hidden rounded-lg border border-(--line) bg-white/55 no-underline shadow-[0_1px_0_rgba(21,32,43,0.04)] transition duration-300 ease-out hover:-translate-y-0.5 hover:border-(--accent) hover:bg-white/80 hover:shadow-[0_12px_28px_rgba(21,32,43,0.08)]"
      style={{ animationDelay: `${delay}ms` }}
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
        <p className="mt-auto text-xs tracking-wide text-(--muted)">
          {relativeTime(job.created_at)}
        </p>
      </div>
    </Link>
  );
}
