"use client";

import { useEffect, useRef, useState } from "react";
import { type JobSummary, listJobs } from "@/lib/api";
import { JobEntryCard } from "./JobEntryCard";
import { JobLiveView } from "./JobLiveView";

const POLL_MS = 4000;
const PAGE_SIZE = 12;

type RepoHistoryProps = {
  githubUrl: string;
};

export function RepoHistory({ githubUrl }: RepoHistoryProps) {
  const [latest, setLatest] = useState<JobSummary | null>(null);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const jobsRef = useRef(jobs);
  jobsRef.current = jobs;

  const offset = page * PAGE_SIZE;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const earlierJobs =
    page === 0 && latest
      ? jobs.filter((job) => job.job_id !== latest.job_id)
      : jobs;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + jobs.length, total);

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

  return (
    <section aria-label="Repo runs" className="flex flex-col gap-8">
      <div className="flex items-baseline justify-between gap-3">
        <h2
          className="text-lg font-semibold tracking-tight"
          style={{
            fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
          }}
        >
          Runs
        </h2>
        <p className="text-sm text-(--muted)">
          {loading
            ? "Loading…"
            : total === 0
              ? "0 runs"
              : `${from}–${to} of ${total}`}
        </p>
      </div>

      {error ? <p className="text-sm text-(--danger)">{error}</p> : null}

      {!loading && total === 0 ? (
        <div className="rounded-lg border border-dashed border-(--line) bg-(--paper-deep)/50 px-6 py-12 text-center">
          <p className="text-(--muted)">No runs for this repository yet.</p>
        </div>
      ) : null}

      {latest ? (
        <div className="flex max-w-3xl flex-col gap-3">
          <h3
            className="text-base font-semibold tracking-tight"
            style={{
              fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
            }}
          >
            Latest run
          </h3>
          <JobLiveView key={latest.job_id} jobId={latest.job_id} embedded />
        </div>
      ) : null}

      {earlierJobs.length > 0 || (total > 1 && !loading) ? (
        <div className="flex flex-col gap-3">
          <div className="flex items-baseline justify-between gap-3">
            <h3
              className="text-base font-semibold tracking-tight"
              style={{
                fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
              }}
            >
              Earlier runs
            </h3>
            {total > 1 ? (
              <p className="text-sm text-(--muted)">
                {Math.max(0, total - 1)} older
              </p>
            ) : null}
          </div>
          {earlierJobs.length > 0 ? (
            <div className="overflow-hidden rounded-lg border border-(--line) bg-(--paper-deep)/40">
              {earlierJobs.map((job, i) => (
                <JobEntryCard key={job.job_id} job={job} index={i} />
              ))}
            </div>
          ) : !loading && total <= 1 ? null : (
            <p className="text-sm text-(--muted)">
              No earlier runs on this page.
            </p>
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
      ) : null}
    </section>
  );
}
