import type { VulnFinding, VulnReportData } from "@/lib/api";

export const SEVERITY_ORDER = [
  "critical",
  "high",
  "medium",
  "low",
  "info",
] as const;

export type SeverityLevel = (typeof SEVERITY_ORDER)[number];

export type SeverityCounts = Record<SeverityLevel, number> & {
  total: number;
  other: number;
};

export const SEVERITY_TONE: Record<SeverityLevel, { bg: string; fg: string }> =
  {
    critical: { bg: "#f8d9d6", fg: "#9b2c2c" },
    high: { bg: "#f8d9d6", fg: "#9b2c2c" },
    medium: { bg: "#f3e8d4", fg: "#8a5a1a" },
    low: { bg: "var(--paper-deep)", fg: "var(--muted)" },
    info: { bg: "var(--paper-deep)", fg: "var(--muted)" },
  };

export function normalizeSeverity(raw: string | undefined): string {
  return (raw || "info").toLowerCase();
}

export function countSeverities(
  findings: VulnFinding[] | undefined | null,
): SeverityCounts {
  const counts: SeverityCounts = {
    critical: 0,
    high: 0,
    medium: 0,
    low: 0,
    info: 0,
    total: 0,
    other: 0,
  };
  if (!Array.isArray(findings)) return counts;
  for (const f of findings) {
    counts.total += 1;
    const sev = normalizeSeverity(f.severity);
    if (sev in SEVERITY_TONE) {
      counts[sev as SeverityLevel] += 1;
    } else {
      counts.other += 1;
    }
  }
  return counts;
}

/** Short headline for the above-the-fold findings strip. */
export function findingsHeadline(
  report: VulnReportData | null | undefined,
): string {
  if (!report) return "Scan pending";
  const counts = countSeverities(report.findings);
  if (counts.total === 0) return "No vulnerabilities reported";
  const parts: string[] = [];
  for (const sev of SEVERITY_ORDER) {
    if (counts[sev] > 0) {
      parts.push(`${counts[sev]} ${sev}`);
    }
  }
  if (counts.other > 0) {
    parts.push(`${counts.other} other`);
  }
  const noun = counts.total === 1 ? "finding" : "findings";
  return `${counts.total} ${noun} · ${parts.join(" · ")}`;
}

export function formatFindingDetail(detail: unknown): string | null {
  if (detail == null) return null;
  if (typeof detail === "string") {
    const t = detail.trim();
    return t || null;
  }
  try {
    const s = JSON.stringify(detail);
    if (!s || s === "{}" || s === "[]" || s === "null") return null;
    return s.length > 280 ? `${s.slice(0, 277)}…` : s;
  } catch {
    return String(detail);
  }
}

export function reportStatusTone(status: string | undefined): {
  label: string;
  fg: string;
} {
  const s = (status || "unknown").toLowerCase();
  if (s === "ok") return { label: s, fg: "#1f6b3a" };
  if (s === "partial") return { label: s, fg: "#8a5a1a" };
  if (s === "failed") return { label: s, fg: "#9b2c2c" };
  return { label: status || "unknown", fg: "var(--muted)" };
}
