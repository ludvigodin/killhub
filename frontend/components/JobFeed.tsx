"use client";

import { useEffect, useRef, useState } from "react";
import { listRepos, type RepoSummary } from "@/lib/api";
import { repoPathFromGithubUrl } from "@/lib/github";
import { type BatchResult, BatchUrlForm } from "./BatchUrlForm";
import { JobEntryCard } from "./JobEntryCard";

const POLL_MS = 4000;
const PAGE_SIZE = 9;

export function JobFeed() {
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const reposRef = useRef(repos);
  reposRef.current = repos;

  const offset = page * PAGE_SIZE;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + repos.length, total);

  // biome-ignore lint/correctness/useExhaustiveDependencies: reloadToken refreshes after batch create
  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const next = await listRepos(PAGE_SIZE, offset);
        if (cancelled) return;
        setRepos(next.repos);
        setTotal(next.total);
        setError(null);
        // If the current page is past the end (jobs deleted / pruned), snap back.
        const maxPage = Math.max(0, Math.ceil(next.total / PAGE_SIZE) - 1);
        if (page > maxPage) {
          setPage(maxPage);
        }
      } catch (err) {
        if (cancelled) return;
        const e = err as Error;
        // Keep the last good feed; only surface the error when empty.
        if (reposRef.current.length === 0) {
          setError(e.message || "Could not load jobs");
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
  }, [reloadToken, page, offset]);

  function onCreated(results: BatchResult[]) {
    if (results.some((r) => r.ok)) {
      setPage(0);
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
        <p className="mb-8 max-w-xl text-lg leading-relaxed text-(--muted)">
          Drop public git URLs into the feed. Each entry is a disposable sandbox
          — watch it verify, then keep the receipt.
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
          <p className="text-sm text-(--muted)">
            {loading
              ? "Loading…"
              : total === 0
                ? "0 recent"
                : `${from}–${to} of ${total}`}
          </p>
        </div>

        {error ? <p className="text-sm text-[#9b2c2c]">{error}</p> : null}

        {!loading && repos.length === 0 ? (
          <div className="rounded-lg border border-dashed border-(--line) bg-white/40 px-6 py-16 text-center">
            <p
              className="mb-2 text-2xl font-semibold tracking-tight"
              style={{
                fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
              }}
            >
              Your feed is empty
            </p>
            <p className="mx-auto max-w-md text-(--muted)">
              Paste the first public git URL above — or a whole list — and
              entries appear here as Killhub claims each job.
            </p>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {repos.map((repo, i) => {
                const href =
                  repoPathFromGithubUrl(repo.github_url) ??
                  `/jobs/${encodeURIComponent(repo.latest.job_id)}`;
                return (
                  <JobEntryCard
                    key={repo.github_url}
                    job={repo.latest}
                    index={i}
                    href={href}
                    runCount={repo.run_count}
                  />
                );
              })}
            </div>
            {total > PAGE_SIZE ? (
              <nav
                aria-label="Feed pages"
                className="mt-2 flex items-center justify-between gap-3"
              >
                <button
                  type="button"
                  className="rounded-md border border-(--line) bg-white/60 px-3 py-1.5 text-sm text-(--ink) transition enabled:hover:border-(--accent) enabled:hover:bg-white disabled:cursor-not-allowed disabled:opacity-40"
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
                  className="rounded-md border border-(--line) bg-white/60 px-3 py-1.5 text-sm text-(--ink) transition enabled:hover:border-(--accent) enabled:hover:bg-white disabled:cursor-not-allowed disabled:opacity-40"
                  disabled={page + 1 >= pageCount || loading}
                  onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
                >
                  Next
                </button>
              </nav>
            ) : null}
          </>
        )}
      </section>
    </div>
  );
}
