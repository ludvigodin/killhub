import type { JobSnapshot, VulnFinding } from "@/lib/api";

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

export function securityVerdict(job: JobSnapshot) {
  const report = job.vuln_report;
  const counts = countSeverities(report?.findings);
  const gates = job.receipt?.dossier?.gates as
    | { reasons?: unknown }
    | undefined;
  const reasons = gates?.reasons;
  const bypass =
    Array.isArray(reasons) &&
    reasons.some(
      (r) => r === "policy_bypass" || r === "containment_policy_bypass",
    );
  const target = (job.verification ?? job.receipt?.verification)?.kind;
  const gaps: string[] = [];
  if (!report) gaps.push("No vulnerability report is available for this run.");
  else if (
    report.status !== "ok" ||
    !Array.isArray(report.findings) ||
    report.summary ===
      "No scan findings. Clean bill for this job's scanned surfaces."
  ) {
    gaps.push("Dependency scan coverage is incomplete or unknown.");
  }
  if (target === "generated_demo")
    gaps.push("Only a generated demo was verified.");
  else if (target !== "original_application" || job.status !== "completed") {
    gaps.push("Verification of the original application is incomplete.");
  }
  if (job.receipt?.containment?.claim !== "proven")
    gaps.push("Sandbox isolation was not fully verified.");

  if (bypass || counts.critical || counts.high)
    return {
      label: "High risk",
      color: "#9b2c2c",
      reason: bypass
        ? "A sandbox isolation check recorded a policy bypass."
        : "The scan reported a high or critical finding. Review it before running this code.",
      gaps,
    };
  if (
    counts.medium ||
    counts.low ||
    counts.other ||
    report?.findings?.some((f) => !f.severity)
  )
    return {
      label: "Review before use",
      color: "#805015",
      reason:
        "The scan flagged issues that need a closer look. See the findings in the receipt.",
      gaps,
    };
  if (gaps.length)
    return { label: "Safety unknown", color: "#805015", reason: "", gaps };
  return {
    label: "No risks flagged by these checks",
    color: "#226442",
    reason:
      "The dependency scan and sandbox checks raised no warnings for this run. Other risks may still exist.",
    gaps,
  };
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
