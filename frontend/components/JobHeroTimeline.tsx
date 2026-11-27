"use client";

import type { JobSnapshot } from "@/lib/api";
import {
  buildJobTimeline,
  evidenceFromLogs,
  type TimelineStage,
  type TimelineStageState,
} from "@/lib/jobTimeline";
import { SectionHeader } from "./SectionHeader";
import { SECTION_SCROLL_MT } from "./SectionNav";

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
          className="type-display text-xs font-semibold tracking-tight sm:text-sm"
          style={{
            color:
              stage.state === "pending" || stage.state === "skipped"
                ? "var(--muted)"
                : "var(--ink)",
          }}
        >
          {stage.label}
        </p>
        <p className="type-eyebrow text-(--muted)">{stateLabel(stage.state)}</p>
        {stage.detail ? (
          <p className="line-clamp-2 text-xs leading-snug text-(--muted)">
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
      id="section-timeline"
      aria-label="Job timeline"
      className={`job-timeline ${SECTION_SCROLL_MT}`}
    >
      <SectionHeader
        className="mb-3"
        eyebrow="Pattern A loop"
        title="Plan → execute → prove → destroy"
      />

      <ol className="flex flex-col gap-5 border border-(--line) bg-(--paper-deep)/55 px-3 py-5 sm:flex-row sm:items-start sm:gap-0 sm:px-5">
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
