import type { ActiveChecks } from "@/lib/api";

export function ActiveCheckSummary({
  checks,
}: {
  checks?: ActiveChecks | null;
}) {
  if (!checks) return null;
  const trace = {
    full: "All install steps traced",
    partial: "Some install steps traced",
    none: "No install commands were traced",
  };
  const tools = checks.mcp_tools_reviewed;
  const meta = [
    checks.install_trace ? trace[checks.install_trace] : null,
    tools == null ? null : `${tools} MCP tool descriptions reviewed`,
    checks.finding_count > 0
      ? `${checks.finding_count} active-check ${checks.finding_count === 1 ? "finding" : "findings"}`
      : null,
  ].filter(Boolean);
  const hasGroups = Boolean(checks.by_check && checks.by_check.length > 0);
  if (!checks.leading_finding && !hasGroups && meta.length === 0) return null;
  return (
    <section className="space-y-1 text-sm" aria-label="Active security checks">
      {checks.leading_finding && (
        <p className="font-medium wrap-anywhere">
          {checks.leading_finding.title}
        </p>
      )}
      {checks.by_check && checks.by_check.length > 0 && (
        <ul
          aria-label="Findings by check"
          className="flex flex-wrap gap-x-3 text-xs"
        >
          {checks.by_check.map((group) => (
            <li key={group.check}>
              {group.label} ({group.count})
            </li>
          ))}
        </ul>
      )}
      {meta.length > 0 ? (
        <p className="text-xs text-(--muted)">{meta.join(" · ")}</p>
      ) : null}
    </section>
  );
}
