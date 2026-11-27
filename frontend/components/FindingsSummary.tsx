import type { JobSnapshot } from "@/lib/api";
import { parseContainment } from "@/lib/containment";
import {
  countSeverities,
  readerSummary,
  reportStatusTone,
  SEVERITY_ORDER,
  SEVERITY_TONE,
  type SeverityLevel,
  securityVerdict,
} from "@/lib/findings";
import { ActiveCheckSummary } from "./ActiveCheckSummary";
import { SectionHeader } from "./SectionHeader";
import { SECTION_SCROLL_MT } from "./SectionNav";

export function FindingsSummary({
  snapshot,
  finished = false,
}: {
  snapshot: JobSnapshot;
  finished?: boolean;
}) {
  const report = snapshot.vuln_report;
  const verdict = securityVerdict(snapshot);
  const counts = countSeverities(report?.findings);
  const summary = readerSummary(report);
  const statusTone = report ? reportStatusTone(report.status) : null;

  const kind = (snapshot.verification ?? snapshot.receipt?.verification)?.kind;
  const verified = snapshot.readiness?.passed === true;
  let outcome = "The original app could not be verified.";
  if (verified && kind === "original_application")
    outcome = "The original app ran.";
  else if (verified && kind === "generated_demo")
    outcome =
      "A generated demo ran. The original app still needs verification.";
  else if (snapshot.status === "cancelled")
    outcome = "The run was cancelled before the original app was verified.";
  const isolation = parseContainment(snapshot.receipt?.containment);
  const sandbox = [
    snapshot.screenshot_ids?.length ? "Killhub captured a screenshot." : "",
    isolation?.absorption?.absorbed
      ? "The sandbox stopped a runaway loop."
      : "",
    snapshot.destroyed_at
      ? "Killhub confirmed the sandbox was destroyed."
      : snapshot.sandbox_id
        ? "Sandbox removal is unconfirmed."
        : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <section
      id="section-findings"
      aria-label="Findings summary"
      className={SECTION_SCROLL_MT}
    >
      <SectionHeader
        className="mb-3"
        eyebrow={finished ? "Run summary" : "Security assessment"}
        title={finished ? outcome : "Findings"}
        meta={
          !finished && statusTone ? (
            <p className="type-mono" style={{ color: statusTone.fg }}>
              Scan status: {statusTone.label}
            </p>
          ) : null
        }
      />

      <div className="space-y-3 border border-(--line) bg-(--paper-deep)/60 px-4 py-4">
        {finished && sandbox && (
          <p className="text-sm leading-relaxed">{sandbox}</p>
        )}
        <p
          className="type-display text-base font-medium tracking-tight"
          style={{ color: verdict.color }}
        >
          {verdict.label}
        </p>

        {summary ? (
          <p className="text-sm leading-relaxed wrap-anywhere">{summary}</p>
        ) : null}

        <ActiveCheckSummary checks={snapshot.receipt?.dossier?.active_checks} />
        {counts.total > 0 ? (
          <ul className="flex flex-wrap gap-2" aria-label="Severity counts">
            {SEVERITY_ORDER.filter((sev) => counts[sev] > 0).map((sev) => (
              <SeverityChip key={sev} severity={sev} count={counts[sev]} />
            ))}
            {counts.unknown > 0 ? (
              <li className="inline-flex items-center rounded-md bg-(--paper-deep) px-2 py-0.5 font-mono text-xs text-(--muted)">
                {counts.unknown} unknown
              </li>
            ) : null}
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
      </div>
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
