"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState, useTransition } from "react";
import { createJob } from "@/lib/api";
import { isPublicGithubUrl } from "@/lib/github";
import { ErrorBanner } from "./ErrorBanner";

export function UrlForm() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [error, setError] = useState<{ message: string; code?: string } | null>(
    null,
  );
  const [pending, startTransition] = useTransition();

  const hint =
    url.length > 0 && !isPublicGithubUrl(url)
      ? "Use a public https://github.com/org/repo URL"
      : null;

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!isPublicGithubUrl(url)) {
      setError({
        message: "URL must be a public https://github.com/org/repo link",
        code: "invalid_url",
      });
      return;
    }

    startTransition(async () => {
      try {
        const { job_id } = await createJob(url);
        router.push(`/jobs/${job_id}`);
      } catch (err) {
        const e = err as Error & { code?: string };
        setError({
          message: e.message || "Failed to create job",
          code: e.code,
        });
      }
    });
  }

  return (
    <div>
      <form
        className="flex w-full flex-col gap-3 sm:flex-row"
        onSubmit={onSubmit}
      >
        <label className="sr-only" htmlFor="github-url">
          Public GitHub repository URL
        </label>
        <input
          id="github-url"
          name="github_url"
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://github.com/org/repo"
          autoComplete="off"
          disabled={pending}
          className="min-h-12 flex-1 rounded-md border border-[var(--line)] bg-white/70 px-4 text-base text-[var(--ink)] outline-none placeholder:text-[var(--muted)] focus:border-[var(--accent)] disabled:opacity-70"
        />
        <button
          type="submit"
          disabled={pending || !url}
          className="min-h-12 rounded-md bg-[var(--accent)] px-5 text-base font-medium text-white disabled:cursor-not-allowed disabled:opacity-70"
        >
          {pending ? "Starting…" : "Start"}
        </button>
      </form>
      {hint ? <p className="mt-2 text-sm text-[var(--muted)]">{hint}</p> : null}
      {error ? <ErrorBanner message={error.message} code={error.code} /> : null}
    </div>
  );
}
