"use client";

import { useEffect, useRef, useState } from "react";
import { listRepos, type RepoSummary } from "@/lib/api";
import { repoPathFromGithubUrl } from "@/lib/github";
import { JobEntryCard } from "./JobEntryCard";
import { SiteNav } from "./SiteNav";

const POLL_MS = 4000;
const PAGE_SIZE = 24;

export function HubsFeed() {
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const reposRef = useRef(repos);
  reposRef.current = repos;

  const offset = page * PAGE_SIZE;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + repos.length, total);
  const maxPage = Math.max(0, Math.ceil(total / PAGE_SIZE) - 1);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const next = await listRepos(PAGE_SIZE, offset);
        if (cancelled) return;
        setRepos(next.repos);
        setTotal(next.total);
        setError(null);
        const nextMax = Math.max(0, Math.ceil(next.total / PAGE_SIZE) - 1);
        if (page > nextMax) {
          setPage(nextMax);
        }
      } catch (err) {
        if (cancelled) return;
        const e = err as Error;
        if (reposRef.current.length === 0) {
          setError(e.message || "Could not load hubs");
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
  }, [page, offset]);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col px-6 pb-12">
      <SiteNav />

      <header className="pb-8 pt-4 sm:pt-6">
        <h1 className="type-page-title mb-2">Hubs</h1>
        <p className="max-w-2xl text-base leading-relaxed text-(--muted)">
          Every repo Killhub has planned, sandboxed, and verified - latest run
          first.
        </p>
      </header>

      <section aria-label="All hubs" className="flex flex-col gap-3">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="type-section-title">All tests</h2>
          <p className="text-sm text-(--muted)">
            {loading
              ? "Loading…"
              : total === 0
                ? "0 hubs"
                : `${from}–${to} of ${total}`}
          </p>
        </div>

        {error ? <p className="text-sm text-(--danger)">{error}</p> : null}

        {!loading && repos.length === 0 ? (
          <div className="rounded-lg border border-dashed border-(--line) bg-(--paper-deep)/50 px-6 py-16 text-center">
            <p className="type-section-title mb-2">No hubs yet</p>
            <p className="mx-auto max-w-md text-(--muted)">
              Paste a public git URL on the home feed to start a run. Hubs
              appear here as jobs complete their plan → execute → destroy loop.
            </p>
          </div>
        ) : (
          <>
            <div className="overflow-hidden rounded-lg border border-(--line) bg-(--paper-deep)/40">
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
              <div className="mt-3 flex items-center justify-center gap-3">
                <button
                  type="button"
                  className="rounded-md border border-(--line) bg-(--paper-deep) px-4 py-1.5 text-sm text-(--ink) transition hover:border-(--accent) disabled:cursor-not-allowed disabled:opacity-40"
                  disabled={loading || page <= 0}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                >
                  Previous
                </button>
                <p className="text-sm tabular-nums text-(--muted)">
                  Page {page + 1} of {maxPage + 1}
                </p>
                <button
                  type="button"
                  className="rounded-md border border-(--line) bg-(--paper-deep) px-4 py-1.5 text-sm text-(--ink) transition hover:border-(--accent) disabled:cursor-not-allowed disabled:opacity-40"
                  disabled={loading || page >= maxPage}
                  onClick={() => setPage((p) => Math.min(maxPage, p + 1))}
                >
                  Next
                </button>
              </div>
            ) : null}
          </>
        )}
      </section>
    </div>
  );
}
