export type ProgressLogEntry = {
  id: string;
  type: string;
  message: string;
  timestamp?: string;
};

const EVIDENCE_TYPES = new Set([
  "log",
  "span",
  "finding",
  "containment",
  "lifecycle",
  "gap",
  "error",
]);

type ProgressLogProps = {
  entries: ProgressLogEntry[];
};

export function isProgressLogType(type: string): boolean {
  return EVIDENCE_TYPES.has(type);
}

export function ProgressLog({ entries }: ProgressLogProps) {
  const lines = entries.filter((e) => isProgressLogType(e.type));
  return (
    <section aria-label="Job event log">
      <p className="mb-2 text-sm uppercase tracking-wide text-(--muted)">
        Activity
      </p>
      <ul className="max-h-96 space-y-1.5 overflow-y-auto border border-(--line) bg-white/50 p-3 font-mono text-xs leading-relaxed">
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
                {line.message}
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
      return "#9b2c2c";
    case "containment":
      return "#0d6e6e";
    case "lifecycle":
      return "#3d5a80";
    case "error":
      return "#9b2c2c";
    case "span":
      return "#5a6a78";
    case "gap":
      return "#8a5a1a";
    default:
      return "var(--accent)";
  }
}
