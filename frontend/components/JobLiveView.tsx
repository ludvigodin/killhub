"use client";

import { type ReactNode, useEffect, useEffectEvent, useState } from "react";
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
import { formatQueueLine, isInQueue } from "@/lib/queue";
import { resolveScreenshotSrc } from "@/lib/screenshots";
import { formatJobWhen, isJobStalled } from "@/lib/time";
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
import { SectionHeader } from "./SectionHeader";
import {
  SECTION_SCROLL_MT,
  SectionNav,
  type SectionNavItem,
} from "./SectionNav";
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
  /** Extra TOC entries (e.g. Earlier runs on the repo page). */
  extraNavItems?: SectionNavItem[];
  /** Content after live-run sections (same column as the TOC). */
  after?: ReactNode;
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

function activityMessage(type: string, data: SsePayload): string {
  const payload = data.payload;
  const stepCandidate = [
    data.current_step,
    data.step,
    typeof payload?.step === "string" ? payload.step : null,
    typeof payload?.current_step === "string" ? payload.current_step : null,
  ].find((v): v is string => typeof v === "string" && v.length > 0);
  const pct =
    typeof data.progress === "number"
      ? data.progress
      : typeof payload?.progress === "number"
        ? payload.progress
        : null;

  if (type === "status") {
    if (stepCandidate) return stepCandidate;
    return data.message || data.status || "status";
  }
  if (type === "progress") {
    if (stepCandidate && pct != null) return `${stepCandidate} (${pct}%)`;
    if (stepCandidate) return stepCandidate;
    if (pct != null) return `${pct}%`;
    return data.message || "progress";
  }
  return data.message || type;
}

function toShot(meta: ScreenshotMeta, jobId: string): ScreenshotItem {
  return {
    screenshot_id: meta.screenshot_id,
    step: meta.step,
    caption: meta.caption,
    created_at: meta.created_at,
    url: resolveScreenshotSrc(jobId, meta.screenshot_id, meta.url),
  };
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function formatFindingDetail(
  payload: Record<string, unknown> | undefined,
): string | undefined {
  if (!payload) return undefined;
  const parts: string[] = [];
  if (typeof payload.source === "string") parts.push(payload.source);
  if (typeof payload.severity === "string") parts.push(payload.severity);
  if (typeof payload.package === "string") parts.push(payload.package);
  if (typeof payload.id === "string") parts.push(payload.id);
  if (typeof payload.classification === "string") {
    parts.push(payload.classification);
  }
  if (typeof payload.title === "string") parts.push(payload.title);
  return parts.length ? parts.join(" · ") : undefined;
}

function formatLogKind(
  payload: Record<string, unknown> | undefined,
): string | undefined {
  if (!payload) return undefined;
  if (typeof payload.kind === "string" && payload.kind.length > 0) {
    return payload.kind;
  }
  if (typeof payload.phase === "string" && payload.phase.length > 0) {
    return payload.phase;
  }
  return undefined;
}

function isContainmentMatrix(
  payload: Record<string, unknown> | undefined,
): payload is Record<string, unknown> {
  if (!payload) return false;
  return (
    typeof payload.claim === "string" ||
    asRecord(payload.dimensions) != null ||
    asRecord(payload.canary_scan) != null
  );
}

export function JobLiveView({
  jobId,
  embedded = false,
  actionsHost = null,
  extraNavItems = [],
  after = null,
}: JobLiveViewProps) {
  const [snapshot, setSnapshot] = useState<JobSnapshot | null>(null);
  const [logs, setLogs] = useState<ProgressLogEntry[]>([]);
  const [shots, setShots] = useState<ScreenshotItem[]>([]);
  const [liveContainment, setLiveContainment] = useState<Record<
    string,
    unknown
  > | null>(null);
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
    const receiptContainment = asRecord(snap.receipt?.containment);
    if (receiptContainment) {
      setLiveContainment(receiptContainment);
    }
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
      // EventSource ignores SSE comment keep-alives (`: keepalive`) - no flicker (D50).
      source = new EventSource(jobEventsUrl(jobId, after));

      const handlePayload = (event: MessageEvent, type: string) => {
        let data: SsePayload;
        try {
          data = JSON.parse(String(event.data)) as SsePayload;
        } catch {
          // Malformed or empty frames - ignore (keep-alive comments never reach here).
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
            message: activityMessage(type, data),
            timestamp: data.timestamp,
            telemetry: {
              ...data.payload,
              ...(data.status !== undefined && { status: data.status }),
              ...(data.progress !== undefined && { progress: data.progress }),
              ...(data.current_step !== undefined && {
                current_step: data.current_step,
              }),
            },
            kind: formatLogKind(data.payload),
            detail:
              type === "finding"
                ? formatFindingDetail(data.payload)
                : undefined,
          });
        }

        if (type === "containment" && isContainmentMatrix(data.payload)) {
          setLiveContainment(data.payload);
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
              url: resolveScreenshotSrc(
                jobId,
                shotId,
                data.url ||
                  (typeof data.payload?.url === "string"
                    ? data.payload.url
                    : undefined),
              ),
            });
          }
        }

        setSnapshot((prev) => {
          if (!prev) return prev;
          const next = { ...prev };
          if (typeof data.status === "string") next.status = data.status;
          if (typeof data.progress === "number") next.progress = data.progress;
          if (typeof data.current_step === "string") {
            next.current_step = data.current_step;
          }
          // Nested progress fields on status/log/wait payloads.
          const payload = data.payload;
          if (payload) {
            if (typeof payload.status === "string") {
              next.status = payload.status;
            }
            if (typeof payload.progress === "number") {
              next.progress = payload.progress;
            }
            // Status events use `step`; wait heartbeats use `current_step`.
            const step =
              (typeof payload.current_step === "string" &&
                payload.current_step) ||
              (typeof payload.step === "string" && payload.step) ||
              null;
            if (step) next.current_step = step;
            if (typeof payload.cancel_requested_at === "string") {
              next.cancel_requested_at = payload.cancel_requested_at;
            }
          }
          if (data.event_id) next.event_cursor = data.event_id;
          // Meaningful SSE frames refresh last-activity (keep-alives never arrive).
          if (typeof data.timestamp === "string" && data.timestamp.length > 0) {
            next.updated_at = data.timestamp;
          } else {
            next.updated_at = new Date().toISOString();
          }
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

  // Queue position/ETA change when peers claim — SSE alone won't refresh them.
  const queueStatus = snapshot?.status;
  useEffect(() => {
    if (!queueStatus || !isInQueue(queueStatus)) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const snap = await getJob(jobId);
        if (!cancelled) onSnapshot(snap);
      } catch {
        // Keep last known queue fields if poll fails.
      }
    };
    const id = window.setInterval(() => {
      void tick();
    }, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [jobId, queueStatus]);

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
  const stalled =
    Boolean(snapshot) && !terminal && isJobStalled(snapshot?.updated_at);
  const cancelling = Boolean(snapshot?.cancel_requested_at && !terminal);
  const queueLine = snapshot
    ? formatQueueLine({
        status: snapshot.status,
        queue_position:
          typeof snapshot.queue_position === "number"
            ? snapshot.queue_position
            : null,
        expected_wait_seconds:
          typeof snapshot.expected_wait_seconds === "number"
            ? snapshot.expected_wait_seconds
            : null,
        fallback: snapshot.current_step || null,
      })
    : null;
  const showReport = Boolean(
    snapshot &&
      (terminal ||
        snapshot.receipt ||
        snapshot.vuln_report ||
        snapshot.profile),
  );
  const containment =
    asRecord(snapshot?.receipt?.containment) || liveContainment;
  const stepsCompleted = Array.isArray(snapshot?.steps_completed)
    ? snapshot.steps_completed.filter(
        (step): step is string => typeof step === "string" && step.length > 0,
      )
    : [];
  const jobError =
    typeof snapshot?.error === "string" && snapshot.error.trim().length > 0
      ? snapshot.error.trim()
      : null;
  const dossierCode =
    typeof snapshot?.receipt?.dossier?.code === "string" &&
    snapshot.receipt.dossier.code.trim().length > 0
      ? snapshot.receipt.dossier.code.trim()
      : null;
  const errorItems: { message: string; code?: string }[] = [];
  if (jobError) {
    errorItems.push({ message: jobError, code: dossierCode || "job_error" });
  } else if (dossierCode) {
    errorItems.push({
      message: `Job ended with ${dossierCode.replaceAll("_", " ")}.`,
      code: dossierCode,
    });
  }
  if (error) {
    errorItems.push({ message: error.message, code: error.code });
  }

  const canCancel = Boolean(snapshot) && !terminal && !cancelling;
  const actions = (
    <div className="flex flex-wrap items-center justify-end gap-2">
      {canCancel ? (
        <button
          type="button"
          onClick={() => void onCancel()}
          disabled={busy}
          className="min-h-9 rounded px-2.5 text-sm font-medium text-(--muted) transition-colors enabled:hover:bg-(--danger-soft) enabled:hover:text-(--danger) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--accent) disabled:text-(--muted)/65"
        >
          Cancel job
        </button>
      ) : null}
      <button
        type="button"
        aria-pressed={vision}
        onClick={() => setVision(!vision)}
        className="inline-flex min-h-9 items-center rounded-md border border-(--line) bg-(--paper-deep) px-3 text-sm font-medium text-(--ink) transition-colors hover:border-(--muted) aria-pressed:border-(--accent) aria-pressed:bg-(--accent-soft) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--accent)"
      >
        HackerVision
      </button>
    </div>
  );

  const githubUrl = snapshot?.github_url;
  const repoTitle = githubUrl
    ? (ownerRepoFromGithubUrl(githubUrl) ?? null)
    : null;
  const started = snapshot?.created_at
    ? formatJobWhen(snapshot.created_at)
    : null;
  const updated = snapshot?.updated_at
    ? formatJobWhen(snapshot.updated_at)
    : null;

  const showFindings = Boolean(snapshot && (snapshot.vuln_report || terminal));
  const navItems: SectionNavItem[] = [];
  if (terminal && snapshot)
    navItems.push({ id: "section-findings", label: "Run summary" });
  if (errorItems.length > 0) {
    navItems.push({ id: "section-errors", label: "Errors" });
  }
  if (snapshot) {
    navItems.push(
      { id: "section-timeline", label: "Timeline" },
      { id: "section-status", label: "Status" },
    );
  }
  if (shots.length > 0) {
    navItems.push({ id: "section-screenshots", label: "Screenshots" });
  }
  if (containment) {
    navItems.push({ id: "section-containment", label: "Containment" });
  }
  if (showFindings && !terminal) {
    navItems.push({ id: "section-findings", label: "Findings" });
  }
  navItems.push({ id: "section-activity", label: "Activity" });
  if (showReport) {
    navItems.push({ id: "section-receipt", label: "Receipt" });
  }
  for (const item of extraNavItems) {
    if (!navItems.some((existing) => existing.id === item.id)) {
      navItems.push(item);
    }
  }

  const sections = (
    <div className="flex flex-col gap-8">
      {terminal && snapshot && <FindingsSummary snapshot={snapshot} finished />}
      {errorItems.length > 0 ? (
        <section
          id="section-errors"
          aria-label="Errors"
          className={SECTION_SCROLL_MT}
        >
          <SectionHeader className="mb-3" eyebrow="Problems" title="Errors" />
          <div className="space-y-3">
            {errorItems.map((item) => (
              <ErrorBanner
                key={`${item.code ?? "error"}:${item.message}`}
                message={item.message}
                code={item.code}
              />
            ))}
          </div>
        </section>
      ) : null}

      {snapshot ? (
        <>
          <JobHeroTimeline snapshot={snapshot} logs={logs} />
          <section
            id="section-status"
            aria-label="Job status"
            aria-busy={!terminal || undefined}
            className={SECTION_SCROLL_MT}
          >
            <SectionHeader
              className="mb-3"
              eyebrow="Live status"
              title="Job status"
              meta={
                <div className="flex flex-wrap items-center justify-end gap-3">
                  <StatusBadge status={snapshot.status} />
                  {cancelling ? (
                    <span className="type-mono inline-flex items-center gap-1.5 tracking-wide text-(--warn)">
                      <span className="job-live-dot" aria-hidden />
                      Cancelling
                    </span>
                  ) : stalled ? (
                    <span className="type-mono inline-flex items-center gap-1.5 tracking-wide text-(--muted)">
                      May be stalled
                    </span>
                  ) : queueLine ? (
                    <span className="type-mono inline-flex items-center gap-1.5 tracking-wide text-(--muted)">
                      <span className="job-live-dot" aria-hidden />
                      Waiting
                    </span>
                  ) : !terminal ? (
                    <span className="type-mono inline-flex items-center gap-1.5 tracking-wide text-(--accent)">
                      <span className="job-live-dot" aria-hidden />
                      Live
                    </span>
                  ) : null}
                </div>
              }
            />
            <div className="space-y-4 border border-(--line) bg-(--paper-deep)/60 px-4 py-5">
              <p className="text-sm text-(--muted)">
                {queueLine ||
                  snapshot.current_step ||
                  (terminal ? "Finished." : "Waiting for next step…")}
              </p>
              {stepsCompleted.length > 0 ? (
                <p className="type-mono text-(--muted)">
                  steps {stepsCompleted.join(" → ")}
                </p>
              ) : null}
              {started ? (
                <p className="type-meta flex flex-wrap items-center gap-x-2 gap-y-1 text-(--muted)">
                  <time
                    dateTime={started.iso}
                    title={started.absolute || undefined}
                  >
                    Started {started.relative || started.absolute}
                    {started.absolute ? ` · ${started.absolute}` : ""}
                  </time>
                  {updated && updated.iso !== started.iso ? (
                    <time
                      dateTime={updated.iso}
                      title={updated.absolute || undefined}
                    >
                      · Updated {updated.relative}
                    </time>
                  ) : null}
                </p>
              ) : null}
              <ProgressBar
                progress={snapshot.progress}
                active={!terminal && !stalled}
              />
              <p className="type-mono text-(--muted)">
                cursor {snapshot.event_cursor ?? "-"}
                {snapshot.inference_model
                  ? ` · model ${snapshot.inference_model}`
                  : ""}
                {snapshot.current_profile_revision != null
                  ? ` · profile rev ${snapshot.current_profile_revision}`
                  : ""}
                {snapshot.current_sandbox_generation != null
                  ? ` · sandbox gen ${snapshot.current_sandbox_generation}`
                  : ""}
              </p>
            </div>
          </section>
        </>
      ) : (
        <LoadingPanel
          label="Loading job snapshot…"
          detail="Fetching status, then connecting to the live event stream."
        />
      )}

      <ScreenshotTimeline jobId={jobId} shots={shots} />

      {containment ? <ContainmentPanel containment={containment} /> : null}

      {showFindings && !terminal && snapshot ? (
        <FindingsSummary snapshot={snapshot} />
      ) : null}

      <ProgressLog entries={logs} />

      {showReport && snapshot ? (
        <div id="section-receipt" className={SECTION_SCROLL_MT}>
          <JobReport snapshot={snapshot} />
        </div>
      ) : null}

      {after}
    </div>
  );

  return (
    <div className="space-y-8">
      {!embedded ? (
        <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <Breadcrumbs items={jobBreadcrumbs(jobId, githubUrl)} />
            <h1 className="type-page-title mb-1 wrap-anywhere">
              {repoTitle ?? "Job"}
            </h1>
            {started ? (
              <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-(--muted)">
                <time
                  dateTime={started.iso}
                  className="tabular-nums text-(--ink)"
                  title={started.absolute || undefined}
                >
                  Started {started.relative || started.absolute}
                </time>
                {started.absolute ? (
                  <>
                    <span aria-hidden className="text-(--line)">
                      ·
                    </span>
                    <span className="tabular-nums">{started.absolute}</span>
                  </>
                ) : null}
                {updated && updated.iso !== started.iso ? (
                  <>
                    <span aria-hidden className="text-(--line)">
                      ·
                    </span>
                    <time
                      dateTime={updated.iso}
                      className="tabular-nums"
                      title={updated.absolute || undefined}
                    >
                      Updated {updated.relative}
                    </time>
                  </>
                ) : null}
              </p>
            ) : null}
          </div>
          {actionsHost ? null : (
            <div className="flex w-full shrink-0 justify-start sm:w-auto sm:justify-end sm:self-start sm:pt-1">
              {actions}
            </div>
          )}
        </header>
      ) : actionsHost ? null : (
        actions
      )}
      {actionsHost ? createPortal(actions, actionsHost) : null}

      {navItems.length > 0 ? (
        <div className="lg:grid lg:grid-cols-[10.5rem_minmax(0,1fr)] lg:items-start lg:gap-8">
          <SectionNav items={navItems} />
          {sections}
        </div>
      ) : (
        sections
      )}

      {vision ? (
        <HackerVision entries={logs} onClose={() => setVision(false)} />
      ) : null}
    </div>
  );
}
