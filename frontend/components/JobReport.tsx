import type { JobSnapshot } from "@/lib/api";
import { DetonationVerdictView } from "./DetonationVerdictView";
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

function containmentClaimLabel(
  containment: Record<string, unknown> | null | undefined,
): string | null {
  if (!containment || !("claim" in containment)) return null;
  return String(containment.claim);
}

export function JobReport({ snapshot }: JobReportProps) {
  const receipt = snapshot.receipt;
  // Gate evidence is optional for jobs that exit before normal finalization.
  const gates = receipt?.dossier?.gates;
  const containment = receipt?.containment;
  const lifecycle = receipt?.lifecycle;
  const claim = containmentClaimLabel(containment);
  // Older workers store the verdict inside the receipt dossier.
  const verdict =
    snapshot.detonation_verdict ??
    receipt?.detonation_verdict ??
    receipt?.dossier?.detonation_verdict;
  const setupArtifacts = [
    ["Environment profile", snapshot.profile],
    ["Install specification", snapshot.install_spec],
    ["Scenario plan", snapshot.scenario_plan],
  ] as const;

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
        <p className="mt-1 text-sm text-(--muted)">
          Review the evidence and cleanup status for this job.
        </p>
      </div>

      <EnvStatus snapshot={snapshot} />

      {verdict ? <DetonationVerdictView report={verdict} /> : null}

      <section aria-label="Outcome gates">
        <p className="mb-2 text-sm uppercase tracking-wide text-(--muted)">
          Gates
        </p>
        {gates ? (
          <dl className="grid gap-2 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-(--muted)">Terminal</dt>
              <dd className="font-medium">
                {String(gates.terminal || snapshot.status)}
              </dd>
            </div>
            <div>
              <dt className="text-(--muted)">Readiness at gate</dt>
              <dd>{gates.readiness_passed ? "passed" : "not passed"}</dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-(--muted)">Reasons</dt>
              <dd className="font-mono text-xs">
                {Array.isArray(gates.reasons) ? gates.reasons.join(", ") : "—"}
              </dd>
            </div>
          </dl>
        ) : (
          <p className="text-sm text-(--muted)">
            Gates appear when the receipt is written at finalize.
          </p>
        )}
      </section>

      <VulnReport
        report={snapshot.vuln_report}
        verdictFindings={verdict?.findings}
      />

      <details className="space-y-2">
        <summary className="cursor-pointer text-sm font-medium">
          Containment probe details
        </summary>
        {containment ? (
          <div className="space-y-2 text-sm">
            {claim ? (
              <p>
                Claim: <span className="font-medium">{claim}</span>
              </p>
            ) : (
              <p className="text-(--muted)">
                Matrix recorded (see JSON below).
              </p>
            )}
            <pre className="max-h-48 overflow-auto border border-(--line) bg-white/50 p-3 font-mono text-xs">
              {prettyJson(containment)}
            </pre>
          </div>
        ) : (
          <p className="text-sm text-(--muted)">
            No containment matrix on this receipt.
          </p>
        )}
      </details>

      <section aria-label="Lifecycle evidence">
        <p className="mb-2 text-sm uppercase tracking-wide text-(--muted)">
          Lifecycle
        </p>
        {lifecycle ? (
          <pre className="max-h-48 overflow-auto border border-(--line) bg-white/50 p-3 font-mono text-xs">
            {prettyJson(lifecycle)}
          </pre>
        ) : (
          <p className="text-sm text-(--muted)">No lifecycle receipt yet.</p>
        )}
      </section>

      <section aria-labelledby="setup-artifacts" className="space-y-3">
        <h3
          id="setup-artifacts"
          className="text-sm uppercase tracking-wide text-(--muted)"
        >
          Setup artifacts
        </h3>
        {setupArtifacts.map(([label, artifact]) => (
          <details
            key={label}
            className="space-y-2 border border-(--line) bg-white/50 px-4 py-3"
          >
            <summary className="cursor-pointer text-sm font-medium">
              {label}
            </summary>
            {artifact ? (
              <pre className="max-h-80 overflow-auto font-mono text-xs leading-relaxed">
                {prettyJson(artifact)}
              </pre>
            ) : (
              <p className="text-sm text-(--muted)">
                Not recorded for this job.
              </p>
            )}
          </details>
        ))}
      </section>
    </section>
  );
}
