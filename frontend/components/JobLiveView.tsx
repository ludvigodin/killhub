"use client";

import { useEffect, useEffectEvent, useState } from "react";
import { createPortal } from "react-dom";
import {
  cancelJob,
  getJob,
  type JobSnapshot,
  jobEventsUrl,
  listScreenshots,
  type ScreenshotMeta,
} from "@/lib/api";
import { ownerRepoFromGithubUrl, repoPathFromGithubUrl } from "@/lib/github";
import { type BreadcrumbItem, Breadcrumbs } from "./Breadcrumbs";
import { ContainmentPanel } from "./ContainmentPanel";
import { ErrorBanner } from "./ErrorBanner";
import { FindingsSummary } from "./FindingsSummary";
import { HackerVision } from "./HackerVision";
import { JobHeroTimeline } from "./JobHeroTimeline";
import { JobReport } from "./JobReport";
import { LoadingPanel } from "./LoadingPanel";
import { ProgressBar } from "./ProgressBar";
import {
  isProgressLogType,
  ProgressLog,
  type ProgressLogEntry,
} from "./ProgressLog";
import { type ScreenshotItem, ScreenshotTimeline } from "./ScreenshotTimeline";
import { StatusBadge } from "./StatusBadge";

function shortJobId(jobId: string): string {
  return jobId.length > 12 ? `${jobId.slice(0, 8)}…` : jobId;
}

function jobBreadcrumbs(
  jobId: string,
  githubUrl: string | undefined,
): BreadcrumbItem[] {
  const items: BreadcrumbItem[] = [{ label: "Hubs", href: "/hubs" }];
  if (githubUrl) {
    const repo = ownerRepoFromGithubUrl(githubUrl);
    const path = repoPathFromGithubUrl(githubUrl);
    if (repo && path) {
      items.push({ label: repo, href: path, title: githubUrl });
    }
  }
  items.push({ label: shortJobId(jobId), title: jobId });
  return items;
}

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

type JobLiveViewProps = {
  jobId: string;
  /** Hide redundant chrome when nested on the repo history page. */
  embedded?: boolean;
  /** Portal Cancel / HackerVision into a page header actions host. */
  actionsHost?: HTMLElement | null;
};

type SsePayload = {
  event_id?: string;
  message?: string;
  status?: string;
  progress?: number;
  current_step?: string;
  code?: string;
  timestamp?: string;
  screenshot_id?: string;
  step?: string;
  caption?: string;
  url?: string;
  payload?: Record<string, unknown>;
};

function toShot(meta: ScreenshotMeta, jobId: string): ScreenshotItem {
  return {
    screenshot_id: meta.screenshot_id,
    step: meta.step,
    caption: meta.caption,
    created_at: meta.created_at,
    url:
      meta.url ||
      `/api/jobs/${encodeURIComponent(jobId)}/screenshots/${encodeURIComponent(meta.screenshot_id)}`,
  };
}

export function JobLiveView({
  jobId,
  embedded = false,
  actionsHost = null,
}: JobLiveViewProps) {
  const [snapshot, setSnapshot] = useState<JobSnapshot | null>(null);
  const [logs, setLogs] = useState<ProgressLogEntry[]>([]);
  const [shots, setShots] = useState<ScreenshotItem[]>([]);
  const [error, setError] = useState<{ message: string; code?: string } | null>(
    null,
  );
  const [vision, setVision] = useState(false);
  const [busy, setBusy] = useState(false);

  const onLog = useEffectEvent((line: ProgressLogEntry) => {
    setLogs((prev) => {
      if (prev.some((p) => p.id === line.id)) return prev;
      return [...prev, line].slice(-300);
    });
  });

  const onShot = useEffectEvent((shot: ScreenshotItem) => {
    setShots((prev) => {
      if (prev.some((p) => p.screenshot_id === shot.screenshot_id)) return prev;
      return [...prev, shot];
    });
  });

  const onSnapshot = useEffectEvent((snap: JobSnapshot) => {
    setSnapshot(snap);
  });

  useEffect(() => {
    let cancelled = false;
    let source: EventSource | null = null;

    async function loadScreenshots() {
      try {
        const list = await listScreenshots(jobId);
        if (cancelled) return;
        setShots(list.map((s) => toShot(s, jobId)));
      } catch {
        // Empty timeline is valid (D31); ignore hydrate miss.
      }
    }

    async function hydrateAndSubscribe() {
      try {
        const snap = await getJob(jobId);
        if (cancelled) return;
        onSnapshot(snap);
        await loadScreenshots();
        // Replay retained events from the start of the window, then tail live.
        // Snapshot carries status/progress; id-dedup keeps reconnect stable (D55).
        openSse(null);
      } catch (err) {
        if (cancelled) return;
        const e = err as Error & { code?: string };
        setError({ message: e.message, code: e.code });
      }
    }

    function openSse(after: string | null) {
      if (cancelled) return;
      source?.close();
      // EventSource ignores SSE comment keep-alives (`: keepalive`) — no flicker (D50).
      source = new EventSource(jobEventsUrl(jobId, after));

      const handlePayload = (event: MessageEvent, type: string) => {
        let data: SsePayload;
        try {
          data = JSON.parse(String(event.data)) as SsePayload;
        } catch {
          // Malformed or empty frames — ignore (keep-alive comments never reach here).
          return;
        }

        if (type === "error" && data.code === "cursor_expired") {
          source?.close();
          void resnapshot();
          return;
        }

        const id =
          data.event_id || event.lastEventId || `${type}-${Date.now()}`;

        if (
          isProgressLogType(type) ||
          ["status", "progress", "screenshot"].includes(type)
        ) {
          onLog({
            id,
            type,
            message: data.message || type,
            timestamp: data.timestamp,
          });
        }

        if (type === "screenshot") {
          const shotId =
            data.screenshot_id ||
            (typeof data.payload?.screenshot_id === "string"
              ? data.payload.screenshot_id
              : null);
          if (shotId) {
            onShot({
              screenshot_id: shotId,
              step:
                data.step ||
                (typeof data.payload?.step === "string"
                  ? data.payload.step
                  : undefined),
              caption:
                data.caption ||
                data.message ||
                (typeof data.payload?.caption === "string"
                  ? data.payload.caption
                  : undefined),
              url:
                data.url ||
                (typeof data.payload?.url === "string"
                  ? data.payload.url
                  : undefined) ||
                `/api/jobs/${encodeURIComponent(jobId)}/screenshots/${encodeURIComponent(shotId)}`,
            });
          }
        }

        if (data.event_id) {
          // cursor advanced via snapshot patch below
        }

        setSnapshot((prev) => {
          if (!prev) return prev;
          const next = { ...prev };
          if (typeof data.status === "string") next.status = data.status;
          if (typeof data.progress === "number") next.progress = data.progress;
          if (typeof data.current_step === "string") {
            next.current_step = data.current_step;
          }
          // Nested progress fields on status/log payloads.
          const payload = data.payload;
          if (payload) {
            if (typeof payload.status === "string") {
              next.status = payload.status;
            }
            if (typeof payload.progress === "number") {
              next.progress = payload.progress;
            }
            if (typeof payload.current_step === "string") {
              next.current_step = payload.current_step;
            }
          }
          if (data.event_id) next.event_cursor = data.event_id;
          return next;
        });

        const nextStatus =
          (typeof data.status === "string" && data.status) ||
          (typeof data.payload?.status === "string" && data.payload.status) ||
          null;
        if (nextStatus && TERMINAL.has(nextStatus)) {
          // Refresh snapshot so receipt / vuln_report / cleanup land in the report.
          void getJob(jobId)
            .then((snap) => {
              if (!cancelled) onSnapshot(snap);
            })
            .catch(() => {
              /* keep SSE-patched snapshot */
            });
        }
      };

      for (const type of [
        "status",
        "progress",
        "log",
        "error",
        "span",
        "finding",
        "containment",
        "lifecycle",
        "gap",
        "screenshot",
      ]) {
        source.addEventListener(type, (event) => {
          handlePayload(event as MessageEvent, type);
        });
      }

      source.onmessage = (event) => handlePayload(event, "message");
      source.onerror = () => {
        if (source?.readyState === EventSource.CLOSED) {
          void resnapshot();
        }
      };
    }

    async function resnapshot() {
      try {
        const snap = await getJob(jobId);
        if (cancelled) return;
        onSnapshot(snap);
        await loadScreenshots();
        // After cursor_expired / drop: full retained replay + live tail.
        openSse(null);
        setError(null);
      } catch (err) {
        const e = err as Error & { code?: string };
        setError({
          message: e.message || "SSE cursor expired; re-snapshot failed",
          code: e.code || "cursor_expired",
        });
      }
    }

    void hydrateAndSubscribe();

    return () => {
      cancelled = true;
      source?.close();
    };
  }, [jobId]);

  async function onCancel() {
    setBusy(true);
    setError(null);
    try {
      const snap = await cancelJob(jobId);
      setSnapshot(snap);
    } catch (err) {
      const e = err as Error & { code?: string };
      setError({ message: e.message, code: e.code });
    } finally {
      setBusy(false);
    }
  }

  const terminal = snapshot ? TERMINAL.has(snapshot.status) : false;
  const showReport = Boolean(
    snapshot &&
      (terminal ||
        snapshot.receipt ||
        snapshot.vuln_report ||
        snapshot.profile),
  );

  const actions = (
    <div className="flex flex-wrap items-center justify-end gap-2">
      <button
        type="button"
        onClick={() => void onCancel()}
        disabled={busy || terminal || !snapshot}
        className="rounded-md border border-[#ff4d4d]/55 bg-[#1a0a0a] px-4 py-2 font-mono text-sm tracking-wide text-[#ff6b6b] shadow-[0_0_8px_rgba(255,77,77,0.2)] transition-[box-shadow,border-color,opacity,background-color] hover:border-[#ff4d4d] hover:bg-[#2a1010] hover:shadow-[0_0_14px_rgba(255,77,77,0.4)] disabled:opacity-40 disabled:shadow-none"
      >
        Cancel job
      </button>
      <button
        type="button"
        aria-pressed={vision}
        onClick={() => setVision(!vision)}
        className="rounded-md border border-[#3dff9a]/50 bg-[#07151d] px-4 py-2 font-mono text-sm tracking-wide text-[#3dff9a] shadow-[0_0_8px_rgba(61,255,154,0.25)] transition-[box-shadow,border-color,background-color] hover:border-[#3dff9a] hover:shadow-[0_0_14px_rgba(61,255,154,0.45)] aria-pressed:border-[#80ffdb] aria-pressed:bg-[#102e32] aria-pressed:text-[#80ffdb] aria-pressed:shadow-[0_0_16px_rgba(128,255,219,0.4)]"
      >
        HackerVision
      </button>
    </div>
  );

  const githubUrl = snapshot?.github_url;
  const repoTitle = githubUrl
    ? (ownerRepoFromGithubUrl(githubUrl) ?? null)
    : null;

  return (
    <div className="space-y-8">
      {!embedded ? (
        <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <Breadcrumbs items={jobBreadcrumbs(jobId, githubUrl)} />
            <h1
              className="mb-1 text-3xl font-semibold tracking-tight"
              style={{
                fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
              }}
            >
              {repoTitle ?? "Job"}
            </h1>
          </div>
          {actionsHost ? null : (
            <div className="shrink-0 self-start sm:pt-1">{actions}</div>
          )}
        </header>
      ) : actionsHost ? null : (
        actions
      )}
      {actionsHost ? createPortal(actions, actionsHost) : null}

      {vision ? <HackerVision entries={logs} /> : null}

      {snapshot ? (
        <>
          <JobHeroTimeline snapshot={snapshot} logs={logs} />
          <section
            aria-label="Job status"
            aria-busy={!terminal || undefined}
            className="space-y-4 border border-(--line) bg-(--paper-deep)/60 px-4 py-5"
          >
            <div className="flex flex-wrap items-center gap-3">
              <StatusBadge status={snapshot.status} />
              {!terminal ? (
                <span className="inline-flex items-center gap-1.5 font-mono text-xs tracking-wide text-(--accent)">
                  <span className="job-live-dot" aria-hidden />
                  Live
                </span>
              ) : null}
              <p className="text-sm text-(--muted)">
                {snapshot.current_step ||
                  (terminal ? "Finished." : "Waiting for next step…")}
              </p>
            </div>
            <ProgressBar progress={snapshot.progress} active={!terminal} />
            <p className="font-mono text-xs text-(--muted)">
              cursor {snapshot.event_cursor ?? "—"}
            </p>
          </section>
        </>
      ) : (
        <LoadingPanel
          label="Loading job snapshot…"
          detail="Fetching status, then connecting to the live event stream."
        />
      )}

      <ScreenshotTimeline jobId={jobId} shots={shots} />

      {snapshot?.receipt?.containment ? (
        <ContainmentPanel containment={snapshot.receipt.containment} />
      ) : null}

      {snapshot && (snapshot.vuln_report || terminal) ? (
        <FindingsSummary snapshot={snapshot} />
      ) : null}

      {error ? <ErrorBanner message={error.message} code={error.code} /> : null}

      {!vision ? <ProgressLog entries={logs} /> : null}

      {showReport && snapshot ? (
        <div className="border-t border-(--line) pt-8">
          <JobReport snapshot={snapshot} />
        </div>
      ) : null}
    </div>
  );
}
