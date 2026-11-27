"use client";

import { useEffect, useEffectEvent, useState } from "react";
import { cancelJob, getJob, type JobSnapshot, jobEventsUrl } from "@/lib/api";
import { ErrorBanner } from "./ErrorBanner";

type JobLiveViewProps = {
  jobId: string;
};

type LogLine = { id: string; type: string; message: string };

export function JobLiveView({ jobId }: JobLiveViewProps) {
  const [snapshot, setSnapshot] = useState<JobSnapshot | null>(null);
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [error, setError] = useState<{ message: string; code?: string } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);

  const onEvent = useEffectEvent((line: LogLine) => {
    setLogs((prev) => {
      if (prev.some((p) => p.id === line.id)) return prev;
      return [...prev, line].slice(-200);
    });
  });

  const onSnapshot = useEffectEvent((snap: JobSnapshot) => {
    setSnapshot(snap);
  });

  useEffect(() => {
    let cancelled = false;
    let source: EventSource | null = null;
    let cursor: string | null = null;

    async function hydrateAndSubscribe() {
      try {
        const snap = await getJob(jobId);
        if (cancelled) return;
        onSnapshot(snap);
        cursor = snap.event_cursor;
        openSse(cursor);
      } catch (err) {
        if (cancelled) return;
        const e = err as Error & { code?: string };
        setError({ message: e.message, code: e.code });
      }
    }

    function openSse(after: string | null) {
      source?.close();
      source = new EventSource(jobEventsUrl(jobId, after));

      const handlePayload = (event: MessageEvent, type: string) => {
        let data: {
          event_id?: string;
          message?: string;
          status?: string;
          progress?: number;
          current_step?: string;
          code?: string;
          payload?: Record<string, unknown>;
        };
        try {
          data = JSON.parse(String(event.data)) as typeof data;
        } catch {
          return;
        }

        if (type === "error" && data.code === "cursor_expired") {
          source?.close();
          void resnapshot();
          return;
        }

        const id = data.event_id || event.lastEventId || String(Date.now());
        onEvent({
          id,
          type,
          message: data.message || type,
        });

        if (data.event_id) {
          cursor = data.event_id;
        }

        setSnapshot((prev) => {
          if (!prev) return prev;
          const next = { ...prev };
          if (typeof data.status === "string") next.status = data.status;
          if (typeof data.progress === "number") next.progress = data.progress;
          if (typeof data.current_step === "string") {
            next.current_step = data.current_step;
          }
          if (data.event_id) next.event_cursor = data.event_id;
          return next;
        });
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
        // Browser reconnects EventSource; on persistent failure re-hydrate.
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
        openSse(snap.event_cursor);
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

  return (
    <div className="space-y-6">
      <p className="font-mono text-sm text-[var(--muted)]">{jobId}</p>

      {snapshot ? (
        <div className="rounded-md border border-[var(--line)] bg-white/60 px-4 py-4">
          <p className="text-sm uppercase tracking-wide text-[var(--muted)]">
            Status
          </p>
          <p className="mt-1 text-xl font-medium">{snapshot.status}</p>
          <p className="mt-2 text-sm text-[var(--muted)]">
            {snapshot.current_step || "—"} · {snapshot.progress}%
          </p>
          <p className="mt-1 font-mono text-xs text-[var(--muted)]">
            cursor {snapshot.event_cursor ?? "—"}
          </p>
        </div>
      ) : (
        <p className="text-[var(--muted)]">Loading snapshot…</p>
      )}

      {error ? <ErrorBanner message={error.message} code={error.code} /> : null}

      <div>
        <button
          type="button"
          onClick={() => void onCancel()}
          disabled={
            busy ||
            snapshot?.status === "cancelled" ||
            snapshot?.status === "completed" ||
            snapshot?.status === "failed"
          }
          className="rounded-md border border-[var(--line)] bg-white px-4 py-2 text-sm disabled:opacity-50"
        >
          Cancel job
        </button>
      </div>

      <div>
        <p className="mb-2 text-sm uppercase tracking-wide text-[var(--muted)]">
          Events
        </p>
        <ul className="max-h-80 space-y-1 overflow-y-auto rounded-md border border-[var(--line)] bg-white/50 p-3 font-mono text-xs">
          {logs.length === 0 ? (
            <li className="text-[var(--muted)]">Waiting for SSE…</li>
          ) : (
            logs.map((line) => (
              <li key={line.id}>
                <span className="text-[var(--accent)]">{line.type}</span>{" "}
                {line.message}
              </li>
            ))
          )}
        </ul>
      </div>
    </div>
  );
}
