"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { listRepos, type RepoSummary } from "@/lib/api";
import { repoPathFromGithubUrl } from "@/lib/github";
import { type BatchResult, BatchUrlForm } from "./BatchUrlForm";
import { JobEntryCard } from "./JobEntryCard";
import { KillhubLogo } from "./KillhubLogo";
import { SiteNav } from "./SiteNav";

const POLL_MS = 4000;
const PAGE_SIZE = 12;

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
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + repos.length, total);
  const maxPage = Math.max(0, Math.ceil(total / PAGE_SIZE) - 1);

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
        const nextMax = Math.max(0, Math.ceil(next.total / PAGE_SIZE) - 1);
        if (page > nextMax) {
          setPage(nextMax);
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
    <div className="mx-auto flex w-full max-w-6xl flex-col px-6 pb-12">
      <SiteNav />

      <header className="feed-hero mx-auto w-full max-w-3xl pb-12 pt-6 text-center sm:pt-10">
        <div className="mb-6 flex justify-center">
          <KillhubLogo size={64} />
        </div>
        <h1 className="type-display mx-auto mb-3 max-w-2xl text-2xl font-semibold tracking-tight text-(--ink) sm:text-3xl">
          Pull. Penetrate. Destroy.
        </h1>
        <p className="mx-auto mb-8 max-w-xl text-base leading-relaxed text-(--muted)">
          Hot repos in your area are looking for a one-run stand. Drop a public
          Git URL. We bring the sandbox and clean up afterward.
        </p>
        <BatchUrlForm onCreated={onCreated} />
      </header>

      <section aria-label="Job feed" className="flex flex-col gap-3">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="type-section-title">Recent</h2>
          <p className="text-sm text-(--muted)">
            {loading
              ? "Loading…"
              : total === 0
                ? "0 recent"
                : `${from}–${to} of ${total}`}
          </p>
        </div>

        {error ? <p className="text-sm text-(--danger)">{error}</p> : null}

        {!loading && repos.length === 0 ? (
          <div className="rounded-lg border border-dashed border-(--line) bg-(--paper-deep)/50 px-6 py-16 text-center">
            <p className="type-section-title mb-2">No runs yet</p>
            <p className="mx-auto max-w-md text-(--muted)">
              Paste a public git URL above - or connect MCP - and watch each job
              plan, execute in a sandbox, prove output, then destroy.
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
            <div className="mt-3 flex flex-wrap items-center justify-center gap-3">
              {total > PAGE_SIZE ? (
                <>
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
                </>
              ) : null}
              <Link
                href="/hubs"
                className="rounded-md border border-(--line) bg-(--paper-deep) px-4 py-1.5 text-sm text-(--ink) no-underline transition hover:border-(--accent)"
              >
                Show all
              </Link>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
