"use client";

import { useEffect, useEffectEvent, useState } from "react";
import {
  cancelJob,
  getJob,
  type JobSnapshot,
  jobEventsUrl,
  listScreenshots,
  type ScreenshotMeta,
} from "@/lib/api";
import { ErrorBanner } from "./ErrorBanner";
import { JobReport } from "./JobReport";
import { ProgressBar } from "./ProgressBar";
import {
  isProgressLogType,
  ProgressLog,
  type ProgressLogEntry,
} from "./ProgressLog";
import { type ScreenshotItem, ScreenshotTimeline } from "./ScreenshotTimeline";
import { StatusBadge } from "./StatusBadge";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

type JobLiveViewProps = {
  jobId: string;
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

export function JobLiveView({ jobId }: JobLiveViewProps) {
  const [snapshot, setSnapshot] = useState<JobSnapshot | null>(null);
  const [logs, setLogs] = useState<ProgressLogEntry[]>([]);
  const [shots, setShots] = useState<ScreenshotItem[]>([]);
  const [error, setError] = useState<{ message: string; code?: string } | null>(
    null,
  );
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

        if (isProgressLogType(type)) {
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

  return (
    <div className="space-y-8">
      <p className="font-mono text-sm text-[var(--muted)]">{jobId}</p>
      {snapshot?.github_url ? (
        <p className="text-sm text-[var(--muted)]">
          <a href={snapshot.github_url} target="_blank" rel="noreferrer">
            {snapshot.github_url}
          </a>
        </p>
      ) : null}

      {snapshot ? (
        <section
          aria-label="Job status"
          className="space-y-4 border border-[var(--line)] bg-white/55 px-4 py-5"
        >
          <div className="flex flex-wrap items-center gap-3">
            <StatusBadge status={snapshot.status} />
            <p className="text-sm text-[var(--muted)]">
              {snapshot.current_step || "Waiting for next step…"}
            </p>
          </div>
          <ProgressBar progress={snapshot.progress} />
          <p className="font-mono text-xs text-[var(--muted)]">
            cursor {snapshot.event_cursor ?? "—"}
          </p>
        </section>
      ) : (
        <p className="text-[var(--muted)]">Loading snapshot…</p>
      )}

      {error ? <ErrorBanner message={error.message} code={error.code} /> : null}

      <div>
        <button
          type="button"
          onClick={() => void onCancel()}
          disabled={busy || terminal}
          className="rounded-md border border-[var(--line)] bg-white px-4 py-2 text-sm transition-opacity disabled:opacity-50"
        >
          Cancel job
        </button>
      </div>

      <ProgressLog entries={logs} />

      <ScreenshotTimeline jobId={jobId} shots={shots} />

      {showReport && snapshot ? (
        <div className="border-t border-[var(--line)] pt-8">
          <JobReport snapshot={snapshot} />
        </div>
      ) : null}
    </div>
  );
}
