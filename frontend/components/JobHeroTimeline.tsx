"use client";

import type { JobSnapshot } from "@/lib/api";
import {
  buildJobTimeline,
  evidenceFromLogs,
  type TimelineStage,
  type TimelineStageState,
} from "@/lib/jobTimeline";

type LogHint = { type: string; message: string };

type JobHeroTimelineProps = {
  snapshot: JobSnapshot;
  logs?: LogHint[];
};

function stateLabel(state: TimelineStageState): string {
  switch (state) {
    case "done":
      return "done";
    case "active":
      return "now";
    case "failed":
      return "failed";
    case "skipped":
      return "skipped";
    default:
      return "queued";
  }
}

function nodeStyle(state: TimelineStageState): {
  bg: string;
  fg: string;
  ring: string;
} {
  switch (state) {
    case "done":
      return { bg: "var(--ok)", fg: "var(--paper)", ring: "var(--ok-soft)" };
    case "active":
      return {
        bg: "var(--accent)",
        fg: "var(--paper)",
        ring: "var(--accent-soft)",
      };
    case "failed":
      return {
        bg: "var(--danger)",
        fg: "var(--paper)",
        ring: "var(--danger-soft)",
      };
    case "skipped":
      return { bg: "var(--line)", fg: "var(--muted)", ring: "transparent" };
    default:
      return {
        bg: "var(--paper-deep)",
        fg: "var(--muted)",
        ring: "var(--line)",
      };
  }
}

function connectorTone(prev: TimelineStageState): string {
  if (prev === "done") return "var(--ok)";
  if (prev === "active") return "var(--accent)";
  if (prev === "failed") return "var(--danger)";
  return "var(--line)";
}

function StageNode({
  stage,
  index,
  prevState,
}: {
  stage: TimelineStage;
  index: number;
  prevState: TimelineStageState | null;
}) {
  const tone = nodeStyle(stage.state);
  const pulse = stage.state === "active";

  return (
    <li
      className="job-timeline-stage relative flex min-w-0 flex-1 flex-col items-center gap-2 text-center"
      style={{ animationDelay: `${index * 55}ms` }}
    >
      {prevState ? (
        <span
          aria-hidden
          className="pointer-events-none absolute top-4 right-1/2 hidden h-px w-full sm:block"
          style={{ background: connectorTone(prevState), opacity: 0.75 }}
        />
      ) : null}
      <span
        className={`relative z-10 flex size-8 items-center justify-center rounded-full text-xs font-semibold tabular-nums transition-colors duration-500 ${pulse ? "job-timeline-pulse" : ""}`}
        style={{
          background: tone.bg,
          color: tone.fg,
          boxShadow:
            stage.state === "pending" || stage.state === "skipped"
              ? `inset 0 0 0 1px ${tone.ring}`
              : `0 0 0 4px ${tone.ring}`,
        }}
        aria-hidden
      >
        {stage.state === "done" ? "✓" : index + 1}
      </span>
      <div className="min-w-0 space-y-0.5 px-0.5">
        <p
          className="text-xs font-semibold tracking-tight sm:text-sm"
          style={{
            fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
            color:
              stage.state === "pending" || stage.state === "skipped"
                ? "var(--muted)"
                : "var(--ink)",
          }}
        >
          {stage.label}
        </p>
        <p className="font-mono text-[10px] uppercase tracking-wide text-(--muted)">
          {stateLabel(stage.state)}
        </p>
        {stage.detail ? (
          <p className="line-clamp-2 text-[11px] leading-snug text-(--muted) sm:text-xs">
            {stage.detail}
          </p>
        ) : null}
      </div>
    </li>
  );
}

export function JobHeroTimeline({ snapshot, logs = [] }: JobHeroTimelineProps) {
  const stages = buildJobTimeline(snapshot, evidenceFromLogs(logs));

  return (
    <section
      aria-label="Job timeline"
      className="job-timeline space-y-4 border border-(--line) bg-(--paper-deep)/55 px-3 py-5 sm:px-5"
    >
      <div>
        <p className="text-xs uppercase tracking-[0.14em] text-(--muted)">
          Pattern A loop
        </p>
        <h2
          className="mt-1 text-lg font-semibold tracking-tight sm:text-xl"
          style={{
            fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
          }}
        >
          Plan → execute → prove → destroy
        </h2>
      </div>

      <ol className="flex flex-col gap-5 sm:flex-row sm:items-start sm:gap-0">
        {stages.map((stage, index) => (
          <StageNode
            key={stage.id}
            stage={stage}
            index={index}
            prevState={index > 0 ? stages[index - 1].state : null}
          />
        ))}
      </ol>
    </section>
  );
}
