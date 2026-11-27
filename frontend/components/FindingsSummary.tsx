import type { JobSnapshot } from "@/lib/api";
import {
  countSeverities,
  reportStatusTone,
  SEVERITY_ORDER,
  SEVERITY_TONE,
  type SeverityLevel,
  securityVerdict,
} from "@/lib/findings";

export function FindingsSummary({ snapshot }: { snapshot: JobSnapshot }) {
  const report = snapshot.vuln_report;
  const verdict = securityVerdict(snapshot);
  const counts = countSeverities(report?.findings);
  const statusTone = report ? reportStatusTone(report.status) : null;

  return (
    <section
      aria-label="Findings summary"
      className="space-y-3 border border-(--line) bg-(--paper-deep)/60 px-4 py-4"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm uppercase tracking-wide text-(--muted)">
          Security assessment
        </p>
        {statusTone ? (
          <p className="font-mono text-xs" style={{ color: statusTone.fg }}>
            report {statusTone.label}
          </p>
        ) : null}
      </div>

      <p
        className="text-base font-medium tracking-tight"
        style={{
          fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
          color: verdict.color,
        }}
      >
        {verdict.label}
      </p>

      {counts.total > 0 ? (
        <ul className="flex flex-wrap gap-2" aria-label="Severity counts">
          {SEVERITY_ORDER.filter((sev) => counts[sev] > 0).map((sev) => (
            <SeverityChip key={sev} severity={sev} count={counts[sev]} />
          ))}
          {counts.other > 0 ? (
            <li className="inline-flex items-center rounded-md bg-(--paper-deep) px-2 py-0.5 font-mono text-xs text-(--muted)">
              {counts.other} other
            </li>
          ) : null}
        </ul>
      ) : null}

      <p className="text-sm text-(--muted)">
        {[verdict.reason, ...verdict.gaps].filter(Boolean).join(" ")}
      </p>
    </section>
  );
}

function SeverityChip({
  severity,
  count,
}: {
  severity: SeverityLevel;
  count: number;
}) {
  const tone = SEVERITY_TONE[severity];
  return (
    <li
      className="inline-flex items-center rounded-md px-2 py-0.5 font-mono text-xs uppercase"
      style={{ background: tone.bg, color: tone.fg }}
    >
      {count} {severity}
    </li>
  );
}
