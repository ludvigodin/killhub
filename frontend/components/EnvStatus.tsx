import type { JobSnapshot } from "@/lib/api";

type EnvStatusProps = {
  snapshot: JobSnapshot;
};

function labelFor(snapshot: JobSnapshot): string {
  const cleanup = snapshot.cleanup?.status;
  if (snapshot.destroyed_at) return "destroyed";
  if (cleanup === "destroy_failed") return "destroy_failed";
  if (cleanup === "destroying") return "destroying";
  if (snapshot.status === "completed")
    return "completed (sandbox cleanup pending?)";
  if (snapshot.readiness?.passed) return "readiness passed";
  if (snapshot.readiness && snapshot.readiness.passed === false) {
    return "readiness failed";
  }
  if (snapshot.sandbox_id || snapshot.environment?.environment_id) {
    return snapshot.environment?.state || "running";
  }
  if (snapshot.status === "provisioning" || snapshot.status === "installing") {
    return "provisioning";
  }
  return snapshot.status || "unknown";
}

export function EnvStatus({ snapshot }: EnvStatusProps) {
  const envId =
    snapshot.environment?.environment_id || snapshot.sandbox_id || "—";
  const readiness = snapshot.readiness;
  const verification = snapshot.verification;
  const kind = verification?.kind;

  return (
    <section aria-label="Environment status" className="space-y-3">
      <p className="text-sm uppercase tracking-wide text-(--muted)">
        Environment
      </p>
      <dl className="grid gap-2 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-(--muted)">Lifecycle</dt>
          <dd className="font-medium text-(--ink)">
            {labelFor(snapshot)}
          </dd>
        </div>
        <div>
          <dt className="text-(--muted)">Job status</dt>
          <dd className="font-medium text-(--ink)">{snapshot.status}</dd>
        </div>
        <div>
          <dt className="text-(--muted)">Sandbox</dt>
          <dd className="font-mono text-xs break-all">{envId}</dd>
        </div>
        <div>
          <dt className="text-(--muted)">Expires</dt>
          <dd className="font-mono text-xs">
            {snapshot.expires_at || snapshot.environment?.expires_at || "—"}
          </dd>
        </div>
        <div>
          <dt className="text-(--muted)">Cleanup</dt>
          <dd className="font-medium">
            {snapshot.cleanup?.status || "pending"}
            {snapshot.cleanup?.last_error
              ? ` — ${snapshot.cleanup.last_error}`
              : null}
          </dd>
        </div>
        <div>
          <dt className="text-(--muted)">Destroyed at</dt>
          <dd className="font-mono text-xs">{snapshot.destroyed_at || "—"}</dd>
        </div>
        <div>
          <dt className="text-(--muted)">Readiness</dt>
          <dd>
            {readiness?.passed === true
              ? `passed (${readiness.probe || "probe"})`
              : readiness?.passed === false
                ? `failed (${readiness.probe || "probe"})`
                : "not set"}
          </dd>
        </div>
        <div>
          <dt className="text-(--muted)">Verification kind</dt>
          <dd className="font-medium">
            {kind || "—"}
            {kind === "generated_demo" ? (
              <span className="mt-1 block text-xs font-normal text-(--muted)">
                Generated demo — does not prove the original application works.
              </span>
            ) : null}
          </dd>
        </div>
      </dl>
      {kind === "generated_demo" && verification?.original_failure != null ? (
        <div className="border border-(--line) bg-white/50 px-3 py-2 text-sm">
          <p className="text-xs uppercase tracking-wide text-(--muted)">
            Original setup failure
          </p>
          <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-xs">
            {typeof verification.original_failure === "string"
              ? verification.original_failure
              : JSON.stringify(verification.original_failure, null, 2)}
          </pre>
        </div>
      ) : null}
      <p className="text-xs text-(--muted)">
        Readiness is probe evidence only — it is not job completion, and it does
        not destroy the sandbox by itself.
      </p>
    </section>
  );
}
