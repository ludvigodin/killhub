"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { createJob } from "@/lib/api";
import { githubUrlFromOwnerRepo, validateGitUrl } from "@/lib/git";
import { ErrorBanner } from "./ErrorBanner";

type DeepLinkStartProps = {
  owner: string;
  repo: string;
};

/** Survives React Strict Mode remounts so one visit creates one job. */
const inFlight = new Map<string, Promise<string>>();

function admissionHint(code?: string, status?: number): string | null {
  if (code === "rate_limited" || status === 429) {
    return "Rate limited - wait a moment, then retry.";
  }
  if (code === "queue_full" || status === 503) {
    return "Queue is full - try again when active jobs finish.";
  }
  if (code === "inference_budget") {
    return "Inference budget exhausted for this demo window.";
  }
  if (code === "demo_fixture_required") {
    return "This demo only accepts the pinned Killhub fixture repositories.";
  }
  return null;
}

export function DeepLinkStart({ owner, repo }: DeepLinkStartProps) {
  const router = useRouter();
  const label = `${owner}/${repo}`;
  const [error, setError] = useState<{ message: string; code?: string } | null>(
    null,
  );
  const [hint, setHint] = useState<string | null>(null);

  useEffect(() => {
    const key = `${owner}/${repo}`;
    let cancelled = false;

    async function start() {
      const built = githubUrlFromOwnerRepo(owner, repo);
      if (!built) {
        if (!cancelled) {
          setError({
            message:
              "Not a valid GitHub owner/repo path for Killhub short links.",
            code: "invalid_url",
          });
        }
        return;
      }

      let pending = inFlight.get(key);
      if (!pending) {
        pending = (async () => {
          const cleaned = validateGitUrl(built);
          const { job_id } = await createJob(cleaned);
          return job_id;
        })();
        inFlight.set(key, pending);
      }

      try {
        const jobId = await pending;
        inFlight.delete(key);
        if (!cancelled) {
          router.replace(`/jobs/${jobId}`);
        }
      } catch (err) {
        inFlight.delete(key);
        if (cancelled) return;
        const e = err as Error & { code?: string; status?: number };
        setError({
          message: e.message || "Failed to create job",
          code: e.code,
        });
        setHint(admissionHint(e.code, e.status));
      }
    }

    void start();
    return () => {
      cancelled = true;
    };
  }, [owner, repo, router]);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col px-4 py-12 sm:px-6 sm:py-16">
      <Link
        href="/"
        className="mb-8 text-sm text-(--muted) no-underline hover:text-(--ink)"
      >
        ← Killhub
      </Link>
      <h1 className="type-page-title mb-2">{label}</h1>
      {error ? (
        <>
          <ErrorBanner
            className="mt-4"
            message={error.message}
            code={error.code}
          />
          {hint ? <p className="mt-3 text-sm text-(--muted)">{hint}</p> : null}
          <p className="mt-6 text-sm text-(--muted)">
            <Link
              href="/"
              className="text-(--accent) underline-offset-2 hover:underline"
            >
              Back to home
            </Link>{" "}
            to paste a full public git URL instead.
          </p>
        </>
      ) : (
        <p className="font-mono text-sm text-(--muted)">
          Starting scan for {label}…
        </p>
      )}
    </div>
  );
}
