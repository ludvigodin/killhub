import type { VulnFinding, VulnReportData } from "@/lib/api";
import {
  countSeverities,
  formatFindingDetail,
  normalizeSeverity,
  reportStatusTone,
  SEVERITY_ORDER,
  SEVERITY_TONE,
  type SeverityLevel,
} from "@/lib/findings";
import { SectionHeader } from "./SectionHeader";

type VulnReportProps = {
  report: VulnReportData | null | undefined;
};

const SOURCE_ORDER = [
  "sca",
  "mcp_assessment",
  "canary",
  "network",
  "containment",
  "preflight",
  "intentional_app",
] as const;

const SOURCE_LABEL: Record<string, string> = {
  sca: "SCA / advisories",
  mcp_assessment: "MCP assessment (planned)",
  canary: "Canary hits",
  network: "Network probes",
  containment: "Containment",
  preflight: "Pre-flight",
  intentional_app: "Intentional app patterns",
};

function groupBySource(findings: VulnFinding[]): Record<string, VulnFinding[]> {
  const out: Record<string, VulnFinding[]> = {};
  for (const f of findings) {
    const src = (f.source || "unknown").toLowerCase();
    if (!out[src]) out[src] = [];
    out[src].push(f);
  }
  for (const list of Object.values(out)) {
    list.sort((a, b) => {
      const ai = SEVERITY_ORDER.indexOf(
        normalizeSeverity(a.severity) as SeverityLevel,
      );
      const bi = SEVERITY_ORDER.indexOf(
        normalizeSeverity(b.severity) as SeverityLevel,
      );
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
    });
  }
  return out;
}

function severityTone(raw: string | undefined): { bg: string; fg: string } {
  const sev = normalizeSeverity(raw);
  if (sev in SEVERITY_TONE) {
    return SEVERITY_TONE[sev as SeverityLevel];
  }
  return { bg: "var(--paper-deep)", fg: "var(--muted)" };
}

export function VulnReport({ report }: VulnReportProps) {
  if (!report) {
    return (
      <section aria-label="Vulnerability report" className="space-y-3">
        <SectionHeader size="sm" eyebrow="Scan" title="Vulnerability report" />
        <p className="text-sm text-(--muted)">
          Scan not available yet - report appears after finalize.
        </p>
      </section>
    );
  }

  const findings = Array.isArray(report.findings) ? report.findings : [];
  const counts = countSeverities(findings);
  const statusTone = reportStatusTone(report.status);
  const bySource = groupBySource(findings);
  const sources = [
    ...SOURCE_ORDER.filter((s) => bySource[s]?.length),
    ...Object.keys(bySource).filter(
      (s) => !(SOURCE_ORDER as readonly string[]).includes(s),
    ),
  ];

  return (
    <section
      aria-label="Vulnerability report"
      className="min-w-0 space-y-4 wrap-anywhere"
    >
      <SectionHeader
        size="sm"
        eyebrow="Scan"
        title="Vulnerability report"
        description="Default report is scan-based (SCA / advisories). This is not a generic app pentest. Findings do not erase readiness evidence."
      />

      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
        <p>
          Status:{" "}
          <span className="font-medium" style={{ color: statusTone.fg }}>
            {statusTone.label}
          </span>
        </p>
        {counts.total > 0 ? (
          <p className="text-(--muted)">
            {counts.total} {counts.total === 1 ? "finding" : "findings"}
          </p>
        ) : null}
      </div>

      {counts.total > 0 ? (
        <ul className="flex flex-wrap gap-2" aria-label="Severity breakdown">
          {SEVERITY_ORDER.filter((sev) => counts[sev] > 0).map((sev) => {
            const tone = SEVERITY_TONE[sev];
            return (
              <li
                key={sev}
                className="inline-flex items-center rounded-md px-2 py-0.5 font-mono text-xs uppercase"
                style={{ background: tone.bg, color: tone.fg }}
              >
                {counts[sev]} {sev}
              </li>
            );
          })}
          {counts.other > 0 ? (
            <li className="inline-flex items-center rounded-md bg-(--paper-deep) px-2 py-0.5 font-mono text-xs text-(--muted)">
              {counts.other} other
            </li>
          ) : null}
        </ul>
      ) : null}

      {report.summary ? (
        <p className="border border-(--line) bg-(--paper-deep)/50 px-3 py-2 text-sm leading-relaxed">
          {report.summary ===
          "No scan findings. Clean bill for this job's scanned surfaces."
            ? "No findings recorded. This historical summary does not establish scan coverage."
            : report.summary}
        </p>
      ) : null}

      {report.mcp_assessment ? (
        <div className="border border-(--line) bg-(--paper-deep)/50 px-3 py-2 text-sm">
          <p className="text-xs uppercase tracking-wide text-(--muted)">
            MCP assessment (agent-planned)
          </p>
          <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-xs">
            {JSON.stringify(report.mcp_assessment, null, 2)}
          </pre>
          <p className="mt-2 text-xs text-(--muted)">
            Shown only when the profile enabled assessment - separate from SCA.
          </p>
        </div>
      ) : null}

      {sources.length === 0 ? (
        <p className="text-sm text-(--muted)">No findings to list.</p>
      ) : (
        sources.map((source) => (
          <div key={source}>
            <p className="mb-2 text-sm font-medium text-(--ink)">
              {SOURCE_LABEL[source] || source}
            </p>
            <ul className="space-y-2">
              {(bySource[source] || []).map((f, i) => {
                const tone = severityTone(f.severity);
                const detail = formatFindingDetail(f.detail);
                return (
                  <li
                    key={f.id || `${source}-${i}`}
                    className="border-b border-(--line) pb-2 text-sm last:border-0"
                  >
                    <div className="flex flex-wrap items-baseline gap-2">
                      <span
                        className="inline-flex items-center rounded-md px-1.5 py-0.5 font-mono text-xs uppercase"
                        style={{ background: tone.bg, color: tone.fg }}
                      >
                        {f.severity || "info"}
                      </span>
                      {f.id ? (
                        <span className="font-mono text-xs text-(--muted)">
                          [{f.id}]
                        </span>
                      ) : null}
                    </div>
                    <p className="mt-0.5">{f.title || "Finding"}</p>
                    {f.package ? (
                      <p className="font-mono text-xs text-(--muted)">
                        {f.package}
                      </p>
                    ) : null}
                    {detail ? (
                      <p className="mt-1 font-mono text-xs leading-relaxed text-(--muted)">
                        {detail}
                      </p>
                    ) : null}
                    {f.advisory_url ? (
                      <a
                        href={f.advisory_url}
                        className="text-xs text-(--accent)"
                        target="_blank"
                        rel="noreferrer"
                      >
                        Advisory
                      </a>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </div>
        ))
      )}
    </section>
  );
}
