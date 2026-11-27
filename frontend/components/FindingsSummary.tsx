import type { VulnReportData } from "@/lib/api";
import {
  countSeverities,
  findingsHeadline,
  reportStatusTone,
  SEVERITY_ORDER,
  SEVERITY_TONE,
  type SeverityLevel,
} from "@/lib/findings";

type FindingsSummaryProps = {
  report: VulnReportData | null | undefined;
  /** Show “scan pending” when terminal but report not yet attached. */
  showPending?: boolean;
};

export function FindingsSummary({
  report,
  showPending = false,
}: FindingsSummaryProps) {
  if (!report && !showPending) return null;

  const headline = findingsHeadline(report);
  const counts = countSeverities(report?.findings);
  const statusTone = report ? reportStatusTone(report.status) : null;
  const clean = Boolean(report) && counts.total === 0;
  const hasIssues = counts.total > 0;

  return (
    <section
      aria-label="Findings summary"
      className="space-y-3 border border-(--line) bg-white/55 px-4 py-4"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm uppercase tracking-wide text-(--muted)">
          Security scan
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
          color: hasIssues ? "#9b2c2c" : clean ? "#1f6b3a" : "var(--ink)",
        }}
      >
        {headline}
      </p>

      {hasIssues ? (
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

      <p className="text-xs text-(--muted)">
        Job completion is not a clean bill of health — findings are listed in
        the receipt below.
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
