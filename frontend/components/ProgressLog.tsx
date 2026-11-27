import { SectionHeader } from "./SectionHeader";
import { SECTION_SCROLL_MT } from "./SectionNav";

export type ProgressLogEntry = {
  id: string;
  type: string;
  message: string;
  timestamp?: string;
  /** Structured log kind from SSE payload (sandbox_replace, repair_attempt, …). */
  kind?: string;
  /** Extra detail for findings / structured evidence. */
  detail?: string;
};

const EVIDENCE_TYPES = new Set([
  "log",
  "span",
  "finding",
  "containment",
  "lifecycle",
  "gap",
  "error",
  "status",
  "progress",
]);

type ProgressLogProps = {
  entries: ProgressLogEntry[];
};

export function isProgressLogType(type: string): boolean {
  return EVIDENCE_TYPES.has(type);
}

export function ProgressLog({ entries }: ProgressLogProps) {
  // Show status/progress steps, but hide D81 liveness pulses (kind=heartbeat).
  const lines = entries.filter(
    (e) =>
      isProgressLogType(e.type) &&
      !(e.type === "progress" && e.kind === "heartbeat"),
  );
  return (
    <section
      id="section-activity"
      aria-label="Job event log"
      className={SECTION_SCROLL_MT}
    >
      <SectionHeader className="mb-3" eyebrow="Event stream" title="Activity" />
      <ul className="max-h-96 space-y-1.5 overflow-y-auto border border-(--line) bg-(--paper-deep)/50 p-3 font-mono text-xs leading-relaxed">
        {lines.length === 0 ? (
          <li className="text-(--muted)">Waiting for events…</li>
        ) : (
          lines.map((line) => (
            <li key={line.id} className="flex gap-2">
              <span
                className="shrink-0 uppercase tracking-wide"
                style={{ color: typeColor(line.type) }}
              >
                {line.type}
              </span>
              <span className="min-w-0 wrap-break-word text-(--ink)">
                {line.kind ? (
                  <span className="mr-1.5 text-(--muted)">[{line.kind}]</span>
                ) : null}
                {line.message}
                {line.detail ? (
                  <span className="mt-0.5 block text-(--muted)">
                    {line.detail}
                  </span>
                ) : null}
              </span>
            </li>
          ))
        )}
      </ul>
    </section>
  );
}

function typeColor(type: string): string {
  switch (type) {
    case "finding":
      return "var(--danger)";
    case "containment":
      return "var(--accent)";
    case "lifecycle":
      return "var(--muted)";
    case "error":
      return "var(--danger)";
    case "span":
      return "var(--muted)";
    case "gap":
      return "var(--warn)";
    case "status":
    case "progress":
      return "var(--ink)";
    default:
      return "var(--accent)";
  }
}
