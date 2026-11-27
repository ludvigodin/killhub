"use client";

import { useEffect, useRef, useState } from "react";
import { type JobSummary, listJobs } from "@/lib/api";
import { formatJobWhen } from "@/lib/time";
import { JobEntryCard } from "./JobEntryCard";
import { JobLiveView } from "./JobLiveView";
import { SectionHeader } from "./SectionHeader";
import { SECTION_SCROLL_MT } from "./SectionNav";
import { StatusBadge } from "./StatusBadge";

const POLL_MS = 4000;
const PAGE_SIZE = 12;

type RepoHistoryProps = {
  githubUrl: string;
  title: string;
};

export function RepoHistory({ githubUrl, title }: RepoHistoryProps) {
  const [latest, setLatest] = useState<JobSummary | null>(null);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionsHost, setActionsHost] = useState<HTMLElement | null>(null);
  const jobsRef = useRef(jobs);
  jobsRef.current = jobs;

  const offset = page * PAGE_SIZE;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const earlierJobs =
    page === 0 && latest
      ? jobs.filter((job) => job.job_id !== latest.job_id)
      : jobs;
  const showEarlier = earlierJobs.length > 0 || (total > 1 && !loading);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [latestPage, next] = await Promise.all([
          listJobs(1, 0, githubUrl),
          listJobs(PAGE_SIZE, offset, githubUrl),
        ]);
        if (cancelled) return;
        setLatest(latestPage.jobs[0] ?? null);
        setJobs(next.jobs);
        setTotal(next.total);
        setError(null);
        const maxPage = Math.max(0, Math.ceil(next.total / PAGE_SIZE) - 1);
        if (page > maxPage) {
          setPage(maxPage);
        }
      } catch (err) {
        if (cancelled) return;
        const e = err as Error;
        if (jobsRef.current.length === 0) {
          setError(e.message || "Could not load runs");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    const timer = setInterval(() => {
      void load();
    }, POLL_MS);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [githubUrl, page, offset]);

  const latestWhen = latest ? formatJobWhen(latest.created_at) : null;
  const latestUpdated =
    latest?.updated_at && latest.updated_at !== latest.created_at
      ? formatJobWhen(latest.updated_at)
      : null;

  const earlierBlock = showEarlier ? (
    <div
      id="section-earlier"
      className={`flex flex-col gap-3 ${SECTION_SCROLL_MT}`}
    >
      <SectionHeader
        eyebrow="History"
        title="Earlier runs"
        meta={
          total > 1 ? (
            <p className="text-sm text-(--muted)">
              {Math.max(0, total - 1)} older
            </p>
          ) : null
        }
      />
      {earlierJobs.length > 0 ? (
        <div className="overflow-hidden rounded-lg border border-(--line) bg-(--paper-deep)/40">
          {earlierJobs.map((job, i) => (
            <JobEntryCard key={job.job_id} job={job} index={i} emphasizeRun />
          ))}
        </div>
      ) : !loading && total <= 1 ? null : (
        <p className="text-sm text-(--muted)">No earlier runs on this page.</p>
      )}
      {total > PAGE_SIZE ? (
        <nav
          aria-label="Run pages"
          className="mt-2 flex items-center justify-between gap-3"
        >
          <button
            type="button"
            className="rounded-md border border-(--line) bg-(--paper-deep) px-3 py-1.5 text-sm text-(--ink) transition enabled:hover:border-(--accent) disabled:cursor-not-allowed disabled:opacity-40"
            disabled={page <= 0 || loading}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
          >
            Previous
          </button>
          <p className="text-sm text-(--muted)">
            Page {page + 1} of {pageCount}
          </p>
          <button
            type="button"
            className="rounded-md border border-(--line) bg-(--paper-deep) px-3 py-1.5 text-sm text-(--ink) transition enabled:hover:border-(--accent) disabled:cursor-not-allowed disabled:opacity-40"
            disabled={page + 1 >= pageCount || loading}
            onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
          >
            Next
          </button>
        </nav>
      ) : null}
    </div>
  ) : null;

  return (
    <>
      <header className="mb-10 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 max-w-3xl">
          <h1 className="type-page-title mb-2 wrap-anywhere">
            <a
              href={githubUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-inherit no-underline underline-offset-2 hover:underline"
            >
              {title}
            </a>
          </h1>
          <p className="mb-3 text-sm text-(--muted)">
            Latest run in full, with earlier runs listed below.
          </p>
          {latest && latestWhen ? (
            <div className="mb-3 flex flex-wrap items-center gap-x-2 gap-y-1.5 text-sm text-(--muted)">
              <StatusBadge status={latest.status} />
              <span aria-hidden className="text-(--line)">
                ·
              </span>
              <time
                dateTime={latestWhen.iso}
                className="tabular-nums text-(--ink)"
                title={latestWhen.absolute || undefined}
              >
                Started {latestWhen.relative || latestWhen.absolute}
              </time>
              {latestWhen.absolute ? (
                <>
                  <span aria-hidden className="text-(--line)">
                    ·
                  </span>
                  <span className="tabular-nums">{latestWhen.absolute}</span>
                </>
              ) : null}
              {latestUpdated ? (
                <>
                  <span aria-hidden className="text-(--line)">
                    ·
                  </span>
                  <time
                    dateTime={latestUpdated.iso}
                    className="tabular-nums"
                    title={latestUpdated.absolute || undefined}
                  >
                    Updated {latestUpdated.relative}
                  </time>
                </>
              ) : null}
            </div>
          ) : null}
        </div>
        <div ref={setActionsHost} className="shrink-0 self-start sm:pt-1" />
      </header>

      <section aria-label="Repo runs" className="flex flex-col gap-8">
        {error ? <p className="text-sm text-(--danger)">{error}</p> : null}

        {!loading && total === 0 ? (
          <div className="rounded-lg border border-dashed border-(--line) bg-(--paper-deep)/50 px-6 py-12 text-center">
            <p className="text-(--muted)">No runs for this repository yet.</p>
          </div>
        ) : null}

        {latest ? (
          <JobLiveView
            key={latest.job_id}
            jobId={latest.job_id}
            embedded
            actionsHost={actionsHost}
            extraNavItems={
              showEarlier
                ? [{ id: "section-earlier", label: "Earlier runs" }]
                : []
            }
            after={earlierBlock}
          />
        ) : (
          earlierBlock
        )}
      </section>
    </>
  );
}
