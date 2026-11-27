import type { JobSnapshot, SafetyOutcome, VulnFinding } from "@/lib/api";
import { parseContainment } from "./containment";

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
  unknown: number;
};

export const SEVERITY_TONE: Record<SeverityLevel, { bg: string; fg: string }> =
  {
    critical: { bg: "var(--danger-soft)", fg: "var(--danger)" },
    high: { bg: "var(--danger-soft)", fg: "var(--danger)" },
    medium: { bg: "var(--warn-soft)", fg: "var(--warn)" },
    low: { bg: "var(--paper-deep)", fg: "var(--muted)" },
    info: { bg: "var(--paper-deep)", fg: "var(--muted)" },
  };

export function normalizeSeverity(raw: string | undefined): string {
  const severity = (raw || "unknown").toLowerCase();
  if (severity === "moderate") return "medium";
  return severity;
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
    unknown: 0,
  };
  if (!Array.isArray(findings)) return counts;
  for (const f of findings) {
    counts.total += 1;
    const sev = normalizeSeverity(f.severity);
    if (sev in SEVERITY_TONE) {
      counts[sev as SeverityLevel] += 1;
    } else if (sev === "unknown") {
      counts.unknown += 1;
    } else {
      counts.other += 1;
    }
  }
  return counts;
}

const legacyClean =
  "No scan findings. Clean bill for this job's scanned surfaces.";

export function readerSummary(report: JobSnapshot["vuln_report"]) {
  if (!report?.summary || report.summary === legacyClean) return null;
  if (report.summary.includes("[github_api_limited]")) {
    // Older reviews led with metadata availability. Keep independent scan evidence.
    const sentences = report.summary
      .split(/(?<=[.!?])\s+/)
      .filter((sentence) => {
        const citations = [...sentence.matchAll(/\[([^\]]+)\]/g)];
        return (
          !citations.length ||
          citations.some((match) => match[1] !== "github_api_limited")
        );
      });
    return (
      sentences.join(" ") ||
      "GitHub repository metadata was unavailable during preflight."
    );
  }
  if (!report.summary.includes("Cite-checked review —")) return report.summary;

  // Older receipts stored a list of titles. Rebuild the reader-facing sentence
  // from the saved evidence without rewriting the receipt.
  const findings = report.findings ?? [];
  for (const severity of SEVERITY_ORDER) {
    const finding = findings.find(
      (f) => normalizeSeverity(f.severity) === severity,
    );
    if (!finding) continue;
    if (severity === "info") break;
    if (finding.source === "sca" && finding.package)
      return `A security advisory lists ${finding.package} as affected. Its effect on this application is unknown. Check the advisory for a fixed version before running the project.`;
    return finding.title || null;
  }
  if (
    findings.some(
      (f) =>
        f.source === "network" &&
        typeof f.detail === "object" &&
        f.detail !== null &&
        "classification" in f.detail &&
        f.detail.classification === "policy_denied",
    )
  )
    return "The sandbox blocked a network connection as expected.";
  return null;
}

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

export function securityVerdict(job: JobSnapshot) {
  const report = job.vuln_report;
  const counts = countSeverities(report?.findings);
  const reasons = job.receipt?.dossier?.gates?.reasons;
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
    report.summary === legacyClean
  ) {
    gaps.push("Dependency scan coverage is incomplete or unknown.");
  }
  if (target === "generated_demo")
    gaps.push(
      "Killhub tested a generated demo. The original application still needs verification.",
    );
  else if (
    target !== "original_application" &&
    ["failed", "cancelled"].includes(job.status)
  ) {
    gaps.push(
      "The run ended before Killhub could verify the original application.",
    );
  } else if (target !== "original_application") {
    gaps.push("Verification of the original application is incomplete.");
  }
  if (target === "original_application" && job.status !== "completed")
    gaps.push("The application started, but the job did not complete.");
  const isolation = parseContainment(job.receipt?.containment);
  if (isolation?.unverifiedHostTargets.length)
    gaps.push(
      `Unverified host targets: ${isolation.unverifiedHostTargets.join(", ")}.`,
    );
  if (job.receipt?.containment?.claim !== "proven")
    gaps.push("Sandbox isolation was not fully verified.");

  if (bypass || counts.critical || counts.high)
    return {
      label: "High risk",
      color: "var(--danger)",
      reason: bypass
        ? "A sandbox isolation check recorded a policy bypass."
        : "The scan reported a high or critical finding. Review it before running this code.",
      gaps,
    };
  if (
    counts.medium ||
    counts.low ||
    counts.other ||
    counts.unknown ||
    report?.findings?.some(
      (f) => !f.severity || normalizeSeverity(f.severity) === "unknown",
    )
  )
    return {
      label: "Review before use",
      color: "var(--warn)",
      reason: "Review the detailed findings before using this project.",
      gaps,
    };
  if (gaps.length)
    return { label: "Safety unknown", color: "var(--warn)", reason: "", gaps };
  return {
    label: "No risks flagged by these checks",
    color: "var(--ok)",
    reason:
      "The dependency scan and sandbox checks raised no warnings for this run. Other risks may still exist.",
    gaps,
  };
}

/**
 * Slim feed/detail stamp matching explore `summary_safety`.
 * Null while running or before a receipt exists.
 */
export function snapshotSafety(job: JobSnapshot): SafetyOutcome | null {
  if (!TERMINAL.has(job.status) || !job.receipt) return null;
  const verdict = securityVerdict(job);
  if (verdict.label === "High risk") return "high_risk";
  if (verdict.label === "Review before use") return "review";
  if (verdict.label === "Safety unknown") return "unknown";
  return "safe";
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
  if (s === "ok") return { label: s, fg: "var(--ok)" };
  if (s === "partial") return { label: s, fg: "var(--warn)" };
  if (s === "failed") return { label: s, fg: "var(--danger)" };
  return { label: status || "unknown", fg: "var(--muted)" };
}
