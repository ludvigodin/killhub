import type { VulnFinding, VulnReportData } from "@/lib/api";

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

const SEV_ORDER = ["critical", "high", "medium", "low", "info"] as const;

function groupBySource(findings: VulnFinding[]): Record<string, VulnFinding[]> {
  const out: Record<string, VulnFinding[]> = {};
  for (const f of findings) {
    const src = (f.source || "unknown").toLowerCase();
    if (!out[src]) out[src] = [];
    out[src].push(f);
  }
  for (const list of Object.values(out)) {
    list.sort((a, b) => {
      const ai = SEV_ORDER.indexOf(
        (a.severity || "info").toLowerCase() as (typeof SEV_ORDER)[number],
      );
      const bi = SEV_ORDER.indexOf(
        (b.severity || "info").toLowerCase() as (typeof SEV_ORDER)[number],
      );
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
    });
  }
  return out;
}

export function VulnReport({ report }: VulnReportProps) {
  if (!report) {
    return (
      <section aria-label="Vulnerability report">
        <p className="mb-2 text-sm uppercase tracking-wide text-[var(--muted)]">
          Vulnerability report
        </p>
        <p className="text-sm text-[var(--muted)]">
          Scan not available yet — report appears after finalize.
        </p>
      </section>
    );
  }

  const findings = Array.isArray(report.findings) ? report.findings : [];
  const bySource = groupBySource(findings);
  const sources = [
    ...SOURCE_ORDER.filter((s) => bySource[s]?.length),
    ...Object.keys(bySource).filter(
      (s) => !(SOURCE_ORDER as readonly string[]).includes(s),
    ),
  ];

  return (
    <section aria-label="Vulnerability report" className="space-y-4">
      <div>
        <p className="mb-1 text-sm uppercase tracking-wide text-[var(--muted)]">
          Vulnerability report
        </p>
        <p className="text-xs text-[var(--muted)]">
          Default report is scan-based (SCA / advisories). This is not a generic
          app pentest. Findings do not erase readiness evidence.
        </p>
      </div>

      <p className="text-sm">
        Status:{" "}
        <span className="font-medium">{report.status || "unknown"}</span>
        {findings.length === 0 ? " · clean bill / no findings" : null}
      </p>

      {report.summary ? (
        <p className="border border-[var(--line)] bg-white/50 px-3 py-2 text-sm leading-relaxed">
          {report.summary}
        </p>
      ) : null}

      {report.mcp_assessment ? (
        <div className="border border-[var(--line)] bg-white/50 px-3 py-2 text-sm">
          <p className="text-xs uppercase tracking-wide text-[var(--muted)]">
            MCP assessment (agent-planned)
          </p>
          <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-xs">
            {JSON.stringify(report.mcp_assessment, null, 2)}
          </pre>
          <p className="mt-2 text-xs text-[var(--muted)]">
            Shown only when the profile enabled assessment — separate from SCA.
          </p>
        </div>
      ) : null}

      {sources.length === 0 ? (
        <p className="text-sm text-[var(--muted)]">No findings to list.</p>
      ) : (
        sources.map((source) => (
          <div key={source}>
            <p className="mb-2 text-sm font-medium text-[var(--ink)]">
              {SOURCE_LABEL[source] || source}
            </p>
            <ul className="space-y-2">
              {(bySource[source] || []).map((f, i) => (
                <li
                  key={f.id || `${source}-${i}`}
                  className="border-b border-[var(--line)] pb-2 text-sm last:border-0"
                >
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="font-mono text-xs uppercase text-[var(--accent)]">
                      {f.severity || "info"}
                    </span>
                    {f.id ? (
                      <span className="font-mono text-xs text-[var(--muted)]">
                        [{f.id}]
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-0.5">{f.title || "Finding"}</p>
                  {f.package ? (
                    <p className="font-mono text-xs text-[var(--muted)]">
                      {f.package}
                    </p>
                  ) : null}
                  {f.advisory_url ? (
                    <a
                      href={f.advisory_url}
                      className="text-xs text-[var(--accent)]"
                      target="_blank"
                      rel="noreferrer"
                    >
                      Advisory
                    </a>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ))
      )}
    </section>
  );
}
