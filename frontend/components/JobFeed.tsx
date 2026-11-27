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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const reposRef = useRef(repos);
  reposRef.current = repos;

  const from = total === 0 ? 0 : 1;
  const to = Math.min(repos.length, total);

  // biome-ignore lint/correctness/useExhaustiveDependencies: reloadToken refreshes after batch create
  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const next = await listRepos(PAGE_SIZE, 0);
        if (cancelled) return;
        setRepos(next.repos);
        setTotal(next.total);
        setError(null);
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
  }, [reloadToken]);

  function onCreated(results: BatchResult[]) {
    if (results.some((r) => r.ok)) {
      setReloadToken((n) => n + 1);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col px-6 pb-12">
      <SiteNav />

      <header className="feed-hero mx-auto w-full max-w-3xl pb-12 pt-6 text-center sm:pt-10">
        <div className="mb-6 flex justify-center">
          <KillhubLogo size={64} />
        </div>
        <h1 className="mx-auto mb-3 max-w-2xl text-xl font-medium tracking-tight text-(--ink) sm:text-2xl">
          Plan → sandboxed execution → verifiable output → destroy
        </h1>
        <p className="mx-auto mb-8 max-w-xl text-base leading-relaxed text-(--muted) sm:text-lg">
          Paste a public git URL. The agent plans, runs real work in a
          Microsandbox, returns evidence — then destroys the VM.
        </p>
        <BatchUrlForm onCreated={onCreated} />
      </header>

      <section aria-label="Job feed" className="flex flex-col gap-3">
        <div className="flex items-baseline justify-between gap-3">
          <h2
            className="text-lg font-semibold tracking-tight"
            style={{
              fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
            }}
          >
            Recent
          </h2>
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
            <p
              className="mb-2 text-xl font-semibold tracking-tight"
              style={{
                fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
              }}
            >
              No runs yet
            </p>
            <p className="mx-auto max-w-md text-(--muted)">
              Paste a public git URL above — or connect MCP — and watch each job
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
            <div className="mt-3 flex justify-center">
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
