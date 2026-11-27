"use client";

import { type FormEvent, useState, useTransition } from "react";
import { createJob } from "@/lib/api";
import {
  isPublicGithubUrl,
  parseGithubUrlLines,
  validateGithubUrl,
} from "@/lib/github";
import { ErrorBanner } from "./ErrorBanner";

export type BatchResult = {
  url: string;
  ok: boolean;
  job_id?: string;
  error?: string;
  code?: string;
  status?: number;
};

type BatchUrlFormProps = {
  onCreated?: (results: BatchResult[]) => void;
};

function admissionHint(code?: string, status?: number): string | null {
  if (code === "rate_limited" || status === 429) {
    return "Rate limited — wait a moment, then retry the remaining URLs.";
  }
  if (code === "queue_full" || status === 503) {
    return "Queue is full — try again when active jobs finish.";
  }
  if (code === "inference_budget") {
    return "Inference budget exhausted for this demo window.";
  }
  return null;
}

export function BatchUrlForm({ onCreated }: BatchUrlFormProps) {
  const [text, setText] = useState("");
  const [results, setResults] = useState<BatchResult[]>([]);
  const [batchError, setBatchError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const lines = parseGithubUrlLines(text);
  const invalidPreview = lines.filter((u) => !isPublicGithubUrl(u));

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBatchError(null);
    const urls = parseGithubUrlLines(text);
    if (urls.length === 0) {
      setBatchError("Paste one or more public git URLs (one per line).");
      return;
    }

    startTransition(async () => {
      const out: BatchResult[] = [];
      const draftRetry: string[] = [];
      for (const raw of urls) {
        if (!isPublicGithubUrl(raw)) {
          out.push({
            url: raw,
            ok: false,
            error:
              "Must be a public HTTPS git URL on github.com, gitlab.com, bitbucket.org, or codeberg.org",
            code: "invalid_url",
            status: 400,
          });
          continue;
        }
        try {
          const cleaned = validateGithubUrl(raw);
          const { job_id } = await createJob(cleaned);
          out.push({ url: cleaned, ok: true, job_id });
        } catch (err) {
          const e = err as Error & { code?: string; status?: number };
          out.push({
            url: raw,
            ok: false,
            error: e.message || "Failed to create job",
            code: e.code,
            status: e.status,
          });
          if (e.status === 429 || e.status === 503 || e.code === "queue_full") {
            draftRetry.push(raw);
          }
        }
      }
      setResults(out);
      if (draftRetry.length > 0) {
        setText(draftRetry.join("\n"));
      } else if (out.some((r) => r.ok)) {
        setText("");
      }
      onCreated?.(out);
    });
  }

  const hint = admissionHint(
    results.find((r) => !r.ok && (r.status === 429 || r.status === 503))?.code,
    results.find((r) => !r.ok && (r.status === 429 || r.status === 503))
      ?.status,
  );

  return (
    <div className="w-full">
      <form className="flex w-full flex-col gap-3" onSubmit={onSubmit}>
        <label className="sr-only" htmlFor="github-urls">
          Public git repository URLs (one per line)
        </label>
        <textarea
          id="github-urls"
          name="github_urls"
          rows={4}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={
            "https://github.com/org/repo\nhttps://gitlab.com/group/project"
          }
          disabled={pending}
          className="min-h-28 w-full resize-y rounded-md border border-(--line) bg-white/70 px-4 py-3 font-mono text-sm leading-relaxed text-(--ink) outline-none placeholder:text-(--muted) focus:border-(--accent) disabled:opacity-70"
        />
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={pending || lines.length === 0}
            className="min-h-12 rounded-md bg-(--accent) px-5 text-base font-medium text-white transition hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-70"
          >
            {pending
              ? `Starting ${lines.length}…`
              : lines.length > 1
                ? `Start ${lines.length} jobs`
                : "Start"}
          </button>
          <p className="text-sm text-(--muted)">
            One public git URL per line (GitHub, GitLab, Bitbucket, Codeberg).
            Admission caps still apply.
          </p>
        </div>
      </form>
      {invalidPreview.length > 0 ? (
        <p className="mt-2 text-sm text-(--muted)">
          {invalidPreview.length} line
          {invalidPreview.length === 1 ? "" : "s"} look invalid before submit.
        </p>
      ) : null}
      {batchError ? <ErrorBanner message={batchError} /> : null}
      {hint ? <p className="mt-3 text-sm text-[#8a5a1a]">{hint}</p> : null}
      {results.length > 0 ? (
        <ul className="mt-4 space-y-1.5 text-sm">
          {results.map((r) => (
            <li
              key={`${r.url}-${r.job_id ?? r.code ?? "x"}`}
              className={r.ok ? "text-(--accent)" : "text-[#9b2c2c]"}
            >
              {r.ok
                ? `✓ ${r.url} → ${r.job_id}`
                : `✗ ${r.url} — ${r.error}${r.code ? ` (${r.code})` : ""}`}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
