"use client";

import { useEffect, useState } from "react";
import { type JobSummary, listJobs } from "@/lib/api";
import { type BatchResult, BatchUrlForm } from "./BatchUrlForm";
import { JobEntryCard } from "./JobEntryCard";

const POLL_MS = 4000;

export function JobFeed() {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  // biome-ignore lint/correctness/useExhaustiveDependencies: reloadToken is an intentional refresh trigger after batch create
  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const { jobs: next } = await listJobs(48);
        if (cancelled) return;
        setJobs(next);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        const e = err as Error;
        setError(e.message || "Could not load jobs");
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
  }, [reloadToken]);

  function onCreated(results: BatchResult[]) {
    if (results.some((r) => r.ok)) {
      setReloadToken((n) => n + 1);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-10 px-6 pb-20 pt-12 sm:pt-16">
      <header className="feed-hero max-w-3xl">
        <p
          className="mb-3 text-5xl font-semibold tracking-tight sm:text-6xl md:text-7xl"
          style={{
            fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
          }}
        >
          Killhub
        </p>
        <p className="mb-8 max-w-xl text-lg leading-relaxed text-[var(--muted)]">
          Drop public GitHub URLs into the feed. Each entry is a disposable
          sandbox — watch it verify, then keep the receipt.
        </p>
        <BatchUrlForm onCreated={onCreated} />
      </header>

      <section aria-label="Job feed" className="flex flex-col gap-4">
        <div className="flex items-baseline justify-between gap-3">
          <h2
            className="text-xl font-semibold tracking-tight"
            style={{
              fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
            }}
          >
            Entries
          </h2>
          <p className="text-sm text-[var(--muted)]">
            {loading ? "Loading…" : `${jobs.length} recent`}
          </p>
        </div>

        {error ? <p className="text-sm text-[#9b2c2c]">{error}</p> : null}

        {!loading && jobs.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[var(--line)] bg-white/40 px-6 py-16 text-center">
            <p
              className="mb-2 text-2xl font-semibold tracking-tight"
              style={{
                fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
              }}
            >
              Your feed is empty
            </p>
            <p className="mx-auto max-w-md text-[var(--muted)]">
              Paste the first public GitHub URL above — or a whole list — and
              entries appear here as Killhub claims each job.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {jobs.map((job, i) => (
              <JobEntryCard key={job.job_id} job={job} index={i} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
