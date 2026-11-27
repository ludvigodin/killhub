import type { JobSnapshot } from "@/lib/api";
import { snapshotSafety } from "@/lib/findings";
import { DetonationVerdictView } from "./DetonationVerdictView";
import { EnvStatus } from "./EnvStatus";
import { ResultStamp } from "./ResultStamp";
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

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asList(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function JobReport({ snapshot }: JobReportProps) {
  const receipt = snapshot.receipt;
  const dossier = receipt?.dossier ?? {};
  const gates = asRecord(dossier.gates);
  const lifecycle = asRecord(receipt?.lifecycle);
  const revisions = asList(dossier.profile_revisions);
  const generations = asList(dossier.sandbox_generations);
  const outcome = typeof dossier.outcome === "string" ? dossier.outcome : null;
  const dossierCode =
    typeof dossier.code === "string" && dossier.code.trim().length > 0
      ? dossier.code.trim()
      : null;
  const scanError =
    typeof dossier.scan_error === "string" ? dossier.scan_error : null;
  const vulnReportStatus =
    typeof dossier.vuln_report_status === "string"
      ? dossier.vuln_report_status
      : null;
  const vulnReview =
    typeof dossier.vuln_review === "string" ? dossier.vuln_review : null;
  const findingIds = asList(dossier.finding_ids).filter(
    (id): id is string => typeof id === "string" && id.length > 0,
  );
  const destroyError =
    typeof lifecycle?.destroy_error === "string"
      ? lifecycle.destroy_error
      : null;
  const destroyConfirmed = lifecycle?.confirmed;
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
  const safety = snapshotSafety(snapshot);

  return (
    <section className="space-y-8" aria-label="Intake receipt">
      <div>
        <div className="flex flex-wrap items-center gap-3">
          <h2
            className="text-2xl font-semibold tracking-tight"
            style={{
              fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
            }}
          >
            Receipt
          </h2>
          {safety ? <ResultStamp safety={safety} /> : null}
        </div>
        <p className="mt-1 text-sm text-(--muted)">
          Review the evidence and cleanup status for this job.
        </p>
        {(() => {
          const parts = [
            dossierCode ? `code ${dossierCode}` : null,
            outcome ? `outcome ${outcome}` : null,
            vulnReportStatus ? `vuln ${vulnReportStatus}` : null,
          ].filter(Boolean);
          return parts.length > 0 ? (
            <p className="mt-2 font-mono text-xs text-(--muted)">
              {parts.join(" · ")}
            </p>
          ) : null;
        })()}
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
                {Array.isArray(gates.reasons) ? gates.reasons.join(", ") : "-"}
              </dd>
            </div>
          </dl>
        ) : (
          <p className="text-sm text-(--muted)">
            Gates appear when the receipt is written at finalize.
          </p>
        )}
        {scanError ? (
          <p className="mt-3 text-sm" style={{ color: "var(--danger)" }}>
            Scan error: {scanError}
          </p>
        ) : null}
        {vulnReview ? (
          <p className="mt-2 text-sm text-(--muted)">{vulnReview}</p>
        ) : null}
        {findingIds.length > 0 ? (
          <p className="mt-2 font-mono text-xs text-(--muted)">
            findings {findingIds.join(", ")}
          </p>
        ) : null}
      </section>

      <VulnReport
        report={snapshot.vuln_report}
        verdictFindings={verdict?.findings}
      />

      <section aria-label="Profile revisions">
        <p className="mb-2 text-sm uppercase tracking-wide text-(--muted)">
          Profile revisions
        </p>
        {revisions.length > 0 ? (
          <ul className="space-y-1.5 text-sm">
            {revisions.map((item, index) => {
              const rev = asRecord(item);
              const key =
                rev && typeof rev.revision === "number"
                  ? `rev-${rev.revision}`
                  : `rev-i-${index}`;
              return (
                <li
                  key={key}
                  className="flex flex-wrap gap-x-3 gap-y-1 border border-(--line) bg-(--paper-deep)/40 px-3 py-2 font-mono text-xs"
                >
                  <span>
                    rev{" "}
                    {rev && typeof rev.revision === "number"
                      ? rev.revision
                      : "?"}
                  </span>
                  <span className="text-(--muted)">
                    {rev && typeof rev.phase === "string"
                      ? rev.phase
                      : "phase?"}
                  </span>
                  <span className="text-(--muted)">
                    {rev && typeof rev.schema_version === "string"
                      ? rev.schema_version
                      : ""}
                  </span>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="text-sm text-(--muted)">
            No profile revision history on this receipt yet.
          </p>
        )}
      </section>

      <section aria-label="Sandbox generations">
        <p className="mb-2 text-sm uppercase tracking-wide text-(--muted)">
          Sandbox generations
        </p>
        {generations.length > 0 ? (
          <ul className="space-y-1.5 text-sm">
            {generations.map((item, index) => {
              const gen = asRecord(item);
              const key =
                gen && typeof gen.generation === "number"
                  ? `gen-${gen.generation}`
                  : `gen-i-${index}`;
              return (
                <li
                  key={key}
                  className="space-y-1 border border-(--line) bg-(--paper-deep)/40 px-3 py-2 font-mono text-xs"
                >
                  <p>
                    gen{" "}
                    {gen && typeof gen.generation === "number"
                      ? gen.generation
                      : "?"}
                    {gen && typeof gen.state === "string"
                      ? ` · ${gen.state}`
                      : ""}
                  </p>
                  {gen && typeof gen.environment_id === "string" ? (
                    <p className="break-all text-(--muted)">
                      {gen.environment_id}
                    </p>
                  ) : null}
                  {gen && typeof gen.image === "string" ? (
                    <p className="break-all text-(--muted)">{gen.image}</p>
                  ) : null}
                  {gen && typeof gen.destroyed_at === "string" ? (
                    <p className="text-(--muted)">
                      destroyed {gen.destroyed_at}
                    </p>
                  ) : null}
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="text-sm text-(--muted)">
            No sandbox generation history on this receipt yet.
          </p>
        )}
      </section>

      <section aria-label="Lifecycle evidence">
        <p className="mb-2 text-sm uppercase tracking-wide text-(--muted)">
          Lifecycle
        </p>
        {lifecycle ? (
          <div className="space-y-2">
            <dl className="grid gap-2 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-(--muted)">Cleanup</dt>
                <dd className="font-medium">
                  {typeof lifecycle.cleanup === "string"
                    ? lifecycle.cleanup
                    : "-"}
                </dd>
              </div>
              <div>
                <dt className="text-(--muted)">Destroy confirmed</dt>
                <dd className="font-medium">
                  {destroyConfirmed === true
                    ? "yes"
                    : destroyConfirmed === false
                      ? "no"
                      : "-"}
                </dd>
              </div>
              <div>
                <dt className="text-(--muted)">Destroyed at</dt>
                <dd className="font-mono text-xs">
                  {typeof lifecycle.destroyed_at === "string"
                    ? lifecycle.destroyed_at
                    : "-"}
                </dd>
              </div>
              <div>
                <dt className="text-(--muted)">Destroy error</dt>
                <dd
                  className="font-mono text-xs"
                  style={destroyError ? { color: "var(--danger)" } : undefined}
                >
                  {destroyError || "-"}
                </dd>
              </div>
            </dl>
            <pre className="max-h-48 overflow-auto border border-(--line) bg-(--paper-deep)/50 p-3 font-mono text-xs">
              {prettyJson(lifecycle)}
            </pre>
          </div>
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
