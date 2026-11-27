"use client";

import { type FormEvent, useEffect, useState, useTransition } from "react";
import { createJob } from "@/lib/api";
import {
  isPublicGithubUrl,
  parseGithubUrlLines,
  validateGithubUrl,
} from "@/lib/github";
import { ConnectMcpPanel } from "./ConnectMcpPanel";
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
  const [mcpOpen, setMcpOpen] = useState(false);
  const [pending, startTransition] = useTransition();

  const [catalog, setCatalog] = useState<{
    restricted: boolean;
    fixtures: { id: string; github_url: string }[];
  } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/fixtures", { signal: controller.signal })
      .then(async (response) => {
        if (response.ok) setCatalog(await response.json());
      })
      .catch(() => {});
    return () => controller.abort();
  }, []);

  const lines = parseGithubUrlLines(text);
  const invalidPreview = lines.filter((u) => !isPublicGithubUrl(u));

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBatchError(null);
    const urls = parseGithubUrlLines(text);
    if (urls.length === 0) {
      setBatchError("Paste a public git URL.");
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
        setText(draftRetry[0] ?? "");
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
          Public git repository URL
        </label>
        <div className="mx-auto flex w-full max-w-md flex-wrap items-stretch gap-2 sm:flex-nowrap">
          <input
            id="github-urls"
            name="github_urls"
            type="url"
            inputMode="url"
            autoComplete="url"
            spellCheck={false}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={
              catalog?.restricted
                ? catalog.fixtures[0]?.github_url
                : "https://github.com/org/repo"
            }
            disabled={pending}
            className="min-h-11 min-w-0 flex-1 basis-full rounded-lg border border-(--line) bg-(--paper-deep) px-4 font-mono text-sm text-(--ink) outline-none placeholder:text-(--muted) focus:border-(--accent) disabled:opacity-70 sm:basis-auto"
          />
          <button
            type="submit"
            disabled={pending || lines.length === 0}
            className="min-h-11 min-w-0 flex-1 rounded-lg bg-(--accent) px-5 text-sm font-medium text-(--paper) transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50 sm:flex-none"
          >
            {pending
              ? lines.length > 1
                ? `Starting ${lines.length}…`
                : "Starting…"
              : lines.length > 1
                ? `Verify ${lines.length}`
                : "Verify"}
          </button>
          <button
            type="button"
            onClick={() => setMcpOpen(true)}
            className="min-h-11 min-w-0 flex-1 rounded-lg border border-(--line) bg-transparent px-4 text-sm font-medium text-(--ink) transition hover:border-(--accent) hover:bg-(--paper-deep) sm:flex-none"
          >
            Connect MCP
          </button>
        </div>
      </form>
      {catalog?.restricted && (
        <div className="mt-3 flex flex-wrap gap-2">
          {catalog.fixtures.map((f) => (
            <button
              key={f.id}
              type="button"
              disabled={pending}
              onClick={() => setText(f.github_url)}
              className="rounded border border-(--line) px-2 py-1 text-sm"
            >
              {f.id}
            </button>
          ))}
        </div>
      )}
      {invalidPreview.length > 0 ? (
        <p className="mt-2 text-center text-sm text-(--muted)">
          That URL doesn&apos;t look valid yet.
        </p>
      ) : null}
      {batchError ? <ErrorBanner message={batchError} /> : null}
      {hint ? <p className="mt-3 text-sm text-(--warn)">{hint}</p> : null}
      {results.length > 0 ? (
        <ul className="mt-4 space-y-1.5 text-sm">
          {results.map((r) => (
            <li
              key={`${r.url}-${r.job_id ?? r.code ?? "x"}`}
              className={r.ok ? "text-(--accent)" : "text-(--danger)"}
            >
              {r.ok
                ? `✓ ${r.url} → ${r.job_id}`
                : `✗ ${r.url} — ${r.error}${r.code ? ` (${r.code})` : ""}`}
            </li>
          ))}
        </ul>
      ) : null}
      <ConnectMcpPanel open={mcpOpen} onClose={() => setMcpOpen(false)} />
    </div>
  );
}
