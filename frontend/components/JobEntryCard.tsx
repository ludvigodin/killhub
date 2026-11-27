"use client";

import Link from "next/link";
import { useState } from "react";
import type { JobSummary } from "@/lib/api";
import {
  hostFromGithubUrl,
  hostLabelFromGithubUrl,
  ownerRepoFromGithubUrl,
} from "@/lib/github";
import { formatQueueLine } from "@/lib/queue";
import { resolveScreenshotSrc, screenshotFallbackSrc } from "@/lib/screenshots";
import { formatJobWhen, isJobStalled } from "@/lib/time";
import { ActiveCheckSummary } from "./ActiveCheckSummary";
import { ProgressBar } from "./ProgressBar";
import { RepoThumbnail } from "./RepoThumbnail";
import { ResultStamp } from "./ResultStamp";
import { StatusBadge } from "./StatusBadge";
import { VerificationBadge } from "./VerificationBadge";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

function FeedThumb({
  jobId,
  screenshotId,
  screenshotUrl,
  repo,
}: {
  jobId: string;
  screenshotId?: string | null;
  screenshotUrl?: string | null;
  repo: string;
}) {
  const preferred = screenshotId
    ? resolveScreenshotSrc(jobId, screenshotId, screenshotUrl)
    : null;
  const [src, setSrc] = useState(preferred);
  const [failed, setFailed] = useState(false);

  if (!preferred || failed || !src) {
    return <RepoThumbnail repo={repo} />;
  }

  return (
    // biome-ignore lint/performance/noImgElement: dynamic CDN or API still bytes
    <img
      key={preferred}
      src={src}
      onError={() => {
        if (!screenshotId) {
          setFailed(true);
          return;
        }
        const fallback = screenshotFallbackSrc(jobId, screenshotId, src);
        if (fallback) {
          setSrc(fallback);
          return;
        }
        setFailed(true);
      }}
      alt=""
      className="h-full w-full object-cover"
    />
  );
}

function HostIcon({
  host,
  className,
}: {
  host: string | null;
  className?: string;
}) {
  const title =
    host === "gitlab.com"
      ? "GitLab"
      : host === "bitbucket.org"
        ? "Bitbucket"
        : host === "codeberg.org"
          ? "Codeberg"
          : host === "github.com"
            ? "GitHub"
            : "Repository";
  // Distinct simple marks per host; GitHub keeps the familiar octocat path.
  const path =
    host === "gitlab.com"
      ? "M8 .25L.86 13.4a.68.68 0 0 0 .64.97h2.65L8 5.95l3.85 8.42h2.65a.68.68 0 0 0 .64-.97L8 .25zm0 8.1L5.9 13.12h4.2L8 8.35z"
      : host === "bitbucket.org"
        ? "M1.1 2.4A.74.74 0 0 1 1.82 1.8h12.36a.74.74 0 0 1 .72.9l-1.74 10.7a.74.74 0 0 1-.73.62H3.57a.74.74 0 0 1-.73-.62L1.1 2.7v-.3zm8.7 7.2H6.2l-.55-2.9h4.7l-.55 2.9z"
        : host === "codeberg.org"
          ? "M8 1.2A6.8 6.8 0 1 0 14.8 8 6.8 6.8 0 0 0 8 1.2zm0 1.5a5.3 5.3 0 0 1 5.3 5.3A5.3 5.3 0 0 1 8 13.3 5.3 5.3 0 0 1 2.7 8 5.3 5.3 0 0 1 8 2.7zm-.75 2.1h1.5v3.4L11 10.7l-1.05 1.05L8 9.85l-1.95 1.9L5 10.7l2.25-2.5z"
          : "M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8";
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
      <title>{title}</title>
      <path d={path} />
    </svg>
  );
}

function shortJobId(jobId: string): string {
  return jobId.length > 12 ? `${jobId.slice(0, 8)}…` : jobId;
}

type JobEntryCardProps = {
  job: JobSummary;
  index?: number;
  /** Override card link (repo history vs single job). */
  href?: string;
  /** When > 1, show how many runs exist for this repo. */
  runCount?: number;
  /**
   * Repo history list: lead with when the run started instead of repeating
   * the owner/repo title.
   */
  emphasizeRun?: boolean;
};

export function JobEntryCard({
  job,
  index = 0,
  href,
  runCount,
  emphasizeRun = false,
}: JobEntryCardProps) {
  const title = ownerRepoFromGithubUrl(job.github_url) ?? job.github_url;
  const host = hostFromGithubUrl(job.github_url);
  const hostLabel = hostLabelFromGithubUrl(job.github_url);
  const when = formatJobWhen(job.created_at);
  const updated =
    job.updated_at && job.updated_at !== job.created_at
      ? formatJobWhen(job.updated_at)
      : null;
  const delay = Math.min(index, 12) * 35;
  const repoHref = job.github_url;
  const cardHref = href ?? `/jobs/${encodeURIComponent(job.job_id)}`;
  const runsLabel =
    runCount != null && runCount > 1
      ? `${runCount} runs`
      : runCount === 1
        ? "1 run"
        : null;
  const terminal = TERMINAL.has(job.status);
  const stalled = !terminal && isJobStalled(job.updated_at);
  const active = !terminal && !stalled;
  const runLabel = when.absolute || when.relative || shortJobId(job.job_id);
  const verificationKind = job.verification?.kind;
  const errorLine =
    typeof job.error === "string" && job.error.trim().length > 0
      ? job.error.trim()
      : null;
  const queueLine = formatQueueLine({
    status: job.status,
    queue_position: job.queue_position,
    expected_wait_seconds: job.expected_wait_seconds,
    fallback: job.current_step || "Waiting…",
  });

  return (
    <article
      className="job-entry group relative flex items-center border-b border-(--line) transition-colors duration-200 last:border-b-0 hover:bg-(--paper-deep)/80"
      style={{ animationDelay: `${delay}ms` }}
    >
      <Link
        href={cardHref}
        className="flex min-w-0 flex-1 items-center gap-3 px-3 py-3 no-underline -outline-offset-2 sm:gap-4 sm:px-4 sm:pr-2"
        aria-label={
          emphasizeRun
            ? `Open run from ${runLabel}`
            : runsLabel
              ? `Open history for ${title}`
              : `Open job ${title}`
        }
      >
        <div className="relative size-10 shrink-0 overflow-hidden rounded-md bg-(--paper-deep) sm:size-11">
          <FeedThumb
            key={`${job.job_id}:${job.screenshot_id ?? ""}:${job.screenshot_url ?? ""}`}
            jobId={job.job_id}
            screenshotId={job.screenshot_id}
            screenshotUrl={job.screenshot_url}
            repo={title}
          />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="type-display truncate text-sm font-semibold tracking-tight text-(--ink) sm:text-base">
              {emphasizeRun ? runLabel : title}
            </p>
            {job.safety ? (
              <ResultStamp safety={job.safety} />
            ) : (
              <StatusBadge status={job.status} />
            )}
            <VerificationBadge kind={verificationKind} />
            {runsLabel ? (
              <span className="text-xs text-(--muted)">{runsLabel}</span>
            ) : null}
          </div>
          <p className="mt-0.5 text-sm text-(--muted)">
            {errorLine && terminal ? (
              <span className="line-clamp-2 wrap-anywhere text-(--danger)">
                {errorLine}
              </span>
            ) : emphasizeRun ? (
              <span className="line-clamp-2">
                <span className="type-mono tracking-wide">
                  {shortJobId(job.job_id)}
                </span>
                {queueLine || job.current_step ? (
                  <>
                    <span aria-hidden className="mx-1.5 text-(--line)">
                      ·
                    </span>
                    {queueLine || job.current_step}
                  </>
                ) : null}
              </span>
            ) : (
              <span className="line-clamp-2">
                {queueLine || job.current_step || "Waiting…"}
                {stalled ? (
                  <>
                    <span aria-hidden className="mx-1.5 text-(--line)">
                      ·
                    </span>
                    <span className="text-(--muted)">May be stalled</span>
                  </>
                ) : null}
              </span>
            )}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 sm:hidden">
            <time
              dateTime={when.iso}
              className="text-xs tabular-nums text-(--muted)"
              title={when.absolute || undefined}
            >
              {when.relative || when.absolute}
            </time>
            {updated ? (
              <span className="text-xs tabular-nums text-(--muted)">
                {terminal ? "ended" : "updated"} {updated.relative}
              </span>
            ) : null}
          </div>
          {terminal && <ActiveCheckSummary checks={job.active_checks} />}
          <div className="mt-2">
            <ProgressBar progress={job.progress} active={active} />
          </div>
        </div>
      </Link>

      {!emphasizeRun ? (
        <a
          href={repoHref}
          target="_blank"
          rel="noopener noreferrer"
          className="mr-2 inline-flex size-9 shrink-0 items-center justify-center rounded-md text-(--muted) transition hover:bg-(--accent-soft) hover:text-(--ink) sm:hidden"
          aria-label={`Open ${title} on ${hostLabel}`}
          title={`Open on ${hostLabel}`}
        >
          <HostIcon host={host} className="size-4" />
        </a>
      ) : null}

      <div className="hidden shrink-0 flex-col items-end justify-center gap-1 py-3 pr-3 sm:flex sm:pr-4">
        <time
          dateTime={when.iso}
          className="text-xs tabular-nums text-(--ink)"
          title={when.absolute || undefined}
        >
          {when.relative || when.absolute}
        </time>
        {when.absolute ? (
          <p className="type-meta max-w-44 truncate text-right text-(--muted)">
            {when.absolute}
          </p>
        ) : null}
        {updated ? (
          <p className="type-meta text-(--muted)">
            {terminal ? "ended" : "updated"} {updated.relative}
          </p>
        ) : null}
        {!emphasizeRun ? (
          <a
            href={repoHref}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-0.5 inline-flex size-7 items-center justify-center rounded-md text-(--muted) transition hover:bg-(--accent-soft) hover:text-(--ink)"
            aria-label={`Open ${title} on ${hostLabel}`}
            title={`Open on ${hostLabel}`}
          >
            <HostIcon host={host} className="size-4" />
          </a>
        ) : (
          <p className="type-mono mt-0.5 tracking-wide text-(--muted)">
            {shortJobId(job.job_id)}
          </p>
        )}
      </div>
    </article>
  );
}
