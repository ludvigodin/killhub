import type { JobSnapshot } from "@/lib/api";
import { EnvStatus } from "./EnvStatus";
import { VulnReport } from "./VulnReport";

type JobReportProps = {
  snapshot: JobSnapshot;
};

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function JobReport({ snapshot }: JobReportProps) {
  const receipt = snapshot.receipt;
  const dossier = (receipt?.dossier || {}) as Record<string, unknown>;
  const gates = dossier.gates as Record<string, unknown> | undefined;
  const containment = receipt?.containment;
  const lifecycle = receipt?.lifecycle;
  const profile = snapshot.profile;

  return (
    <section className="space-y-8" aria-label="Intake receipt">
      <div>
        <h2
          className="text-2xl font-semibold tracking-tight"
          style={{
            fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
          }}
        >
          Receipt
        </h2>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Durable intake dossier — outlives the sandbox. Scan-based by default;
          not a pentest suite.
        </p>
      </div>

      <EnvStatus snapshot={snapshot} />

      <section aria-label="Outcome gates">
        <p className="mb-2 text-sm uppercase tracking-wide text-[var(--muted)]">
          Gates
        </p>
        {gates ? (
          <dl className="grid gap-2 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-[var(--muted)]">Terminal</dt>
              <dd className="font-medium">
                {String(gates.terminal || snapshot.status)}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">Readiness at gate</dt>
              <dd>{gates.readiness_passed ? "passed" : "not passed"}</dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-[var(--muted)]">Reasons</dt>
              <dd className="font-mono text-xs">
                {Array.isArray(gates.reasons) ? gates.reasons.join(", ") : "—"}
              </dd>
            </div>
          </dl>
        ) : (
          <p className="text-sm text-[var(--muted)]">
            Gates appear when the receipt is written at finalize.
          </p>
        )}
      </section>

      <section aria-label="Lifecycle evidence">
        <p className="mb-2 text-sm uppercase tracking-wide text-[var(--muted)]">
          Lifecycle
        </p>
        {lifecycle ? (
          <pre className="max-h-48 overflow-auto border border-[var(--line)] bg-white/50 p-3 font-mono text-xs">
            {prettyJson(lifecycle)}
          </pre>
        ) : (
          <p className="text-sm text-[var(--muted)]">
            No lifecycle receipt yet.
          </p>
        )}
      </section>

      <section aria-label="Containment evidence">
        <p className="mb-2 text-sm uppercase tracking-wide text-[var(--muted)]">
          Containment
        </p>
        {containment ? (
          <div className="space-y-2 text-sm">
            {"claim" in containment ? (
              <p>
                Claim:{" "}
                <span className="font-medium">{String(containment.claim)}</span>
              </p>
            ) : null}
            <pre className="max-h-48 overflow-auto border border-[var(--line)] bg-white/50 p-3 font-mono text-xs">
              {prettyJson(containment)}
            </pre>
          </div>
        ) : (
          <p className="text-sm text-[var(--muted)]">
            No containment matrix on this receipt.
          </p>
        )}
      </section>

      <VulnReport report={snapshot.vuln_report} />

      <section aria-label="Environment profile">
        <p className="mb-2 text-sm uppercase tracking-wide text-[var(--muted)]">
          environment_profile.json
        </p>
        {profile ? (
          <pre className="max-h-80 overflow-auto border border-[var(--line)] bg-white/50 p-3 font-mono text-xs leading-relaxed">
            {prettyJson(profile)}
          </pre>
        ) : (
          <p className="text-sm text-[var(--muted)]">
            No runtime profile revision on this job yet.
          </p>
        )}
        {snapshot.resolved_commit ? (
          <p className="mt-2 font-mono text-xs text-[var(--muted)]">
            resolved_commit {snapshot.resolved_commit}
          </p>
        ) : null}
      </section>
    </section>
  );
}
