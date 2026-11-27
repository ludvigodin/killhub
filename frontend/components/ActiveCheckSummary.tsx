import type { ActiveChecks } from "@/lib/api";

export function ActiveCheckSummary({
  checks,
}: {
  checks?: ActiveChecks | null;
}) {
  if (!checks)
    return (
      <p className="text-xs text-(--muted)">
        Active check results unavailable.
      </p>
    );
  const trace = {
    full: "All install steps traced",
    partial: "Some install steps traced",
    none: "No install trace available",
  }[checks.install_trace ?? "none"];
  const tools = checks.mcp_tools_reviewed;
  return (
    <section className="space-y-1 text-sm" aria-label="Active security checks">
      {checks.leading_finding && (
        <p className="font-medium wrap-anywhere">
          {checks.leading_finding.title}
        </p>
      )}
      <p className="text-xs text-(--muted)">
        {trace} ·{" "}
        {tools == null
          ? "MCP tool review unavailable"
          : `${tools} MCP tool descriptions reviewed`}
        {checks.finding_count > 0
          ? ` · ${checks.finding_count} active-check ${checks.finding_count === 1 ? "finding" : "findings"}`
          : ""}
      </p>
    </section>
  );
}
