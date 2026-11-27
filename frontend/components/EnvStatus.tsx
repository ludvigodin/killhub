import type { JobSnapshot } from "@/lib/api";
import { SectionHeader } from "./SectionHeader";

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

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function formatUsage(usage: JobSnapshot["inference_usage"]): string | null {
  if (!usage) return null;
  const parts: string[] = [];
  if (typeof usage.total_tokens === "number") {
    parts.push(`${usage.total_tokens} tokens`);
  } else {
    const prompt =
      typeof usage.prompt_tokens === "number" ? usage.prompt_tokens : null;
    const completion =
      typeof usage.completion_tokens === "number"
        ? usage.completion_tokens
        : null;
    if (prompt != null || completion != null) {
      parts.push(`${prompt ?? 0}+${completion ?? 0} tokens`);
    }
  }
  if (typeof usage.wall_ms === "number") {
    parts.push(`${Math.round(usage.wall_ms)}ms`);
  }
  return parts.length ? parts.join(" · ") : null;
}

function verificationLabel(kind: string | undefined): string {
  if (!kind) return "-";
  if (kind === "original_application") return "original application";
  if (kind === "generated_demo") return "fallback target";
  if (kind === "setup_failed") return "setup failed";
  return kind;
}

function failureCallout(
  kind: string | undefined,
  originalFailure: unknown,
): { title: string; body: string } | null {
  if (originalFailure == null) return null;
  const body =
    typeof originalFailure === "string"
      ? originalFailure
      : prettyJson(originalFailure);
  if (kind === "generated_demo") {
    return { title: "Original setup failure", body };
  }
  if (kind === "setup_failed") {
    return { title: "Setup failure", body };
  }
  return null;
}

export function EnvStatus({ snapshot }: EnvStatusProps) {
  const envId =
    snapshot.environment?.environment_id || snapshot.sandbox_id || "-";
  const readiness = snapshot.readiness;
  const verification = snapshot.verification;
  const kind = verification?.kind;
  const verifyResult = snapshot.verify_result;
  const usageLine = formatUsage(snapshot.inference_usage);
  const failure = failureCallout(kind, verification?.original_failure);
  const profilePhase =
    typeof snapshot.profile?.phase === "string" ? snapshot.profile.phase : null;
  const cleanupAttempts =
    typeof snapshot.cleanup?.attempts === "number"
      ? snapshot.cleanup.attempts
      : null;

  return (
    <section aria-label="Environment status" className="space-y-3">
      <SectionHeader size="sm" eyebrow="Sandbox" title="Environment" />
      <dl className="grid gap-2 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-(--muted)">Lifecycle</dt>
          <dd className="font-medium text-(--ink)">{labelFor(snapshot)}</dd>
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
          <dt className="text-(--muted)">Generation</dt>
          <dd className="font-mono text-xs">
            {snapshot.current_sandbox_generation ??
              snapshot.environment?.generation ??
              "-"}
            {snapshot.environment?.image
              ? ` · ${snapshot.environment.image}`
              : ""}
          </dd>
        </div>
        <div>
          <dt className="text-(--muted)">Profile revision</dt>
          <dd className="font-mono text-xs">
            {snapshot.current_profile_revision ?? "-"}
            {profilePhase ? ` · ${profilePhase}` : ""}
          </dd>
        </div>
        <div>
          <dt className="text-(--muted)">Expires</dt>
          <dd className="font-mono text-xs">
            {snapshot.expires_at || snapshot.environment?.expires_at || "-"}
          </dd>
        </div>
        <div>
          <dt className="text-(--muted)">Cleanup</dt>
          <dd className="font-medium">
            {snapshot.cleanup?.status || "pending"}
            {cleanupAttempts != null ? ` · ${cleanupAttempts} attempt(s)` : ""}
            {snapshot.cleanup?.last_error
              ? ` - ${snapshot.cleanup.last_error}`
              : null}
          </dd>
        </div>
        <div>
          <dt className="text-(--muted)">Destroyed at</dt>
          <dd className="font-mono text-xs">{snapshot.destroyed_at || "-"}</dd>
        </div>
        <div>
          <dt className="text-(--muted)">Inference</dt>
          <dd className="font-mono text-xs break-all">
            {snapshot.inference_model || "-"}
            {usageLine ? (
              <span className="mt-1 block text-(--muted)">{usageLine}</span>
            ) : null}
          </dd>
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
          <dt className="text-(--muted)">Verification</dt>
          <dd className="font-medium">
            {verificationLabel(kind)}
            {kind === "generated_demo" ? (
              <span className="mt-1 block text-xs font-normal text-(--muted)">
                Does not prove the original application works.
              </span>
            ) : null}
            {kind === "setup_failed" ? (
              <span className="mt-1 block text-xs font-normal text-(--muted)">
                Original setup did not become ready.
              </span>
            ) : null}
          </dd>
        </div>
      </dl>

      {failure ? (
        <div className="border border-(--line) bg-(--paper-deep)/50 px-3 py-2 text-sm">
          <p className="text-xs uppercase tracking-wide text-(--muted)">
            {failure.title}
          </p>
          <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-xs">
            {failure.body}
          </pre>
        </div>
      ) : null}

      {readiness?.detail != null ? (
        <div className="border border-(--line) bg-(--paper-deep)/50 px-3 py-2 text-sm">
          <p className="text-xs uppercase tracking-wide text-(--muted)">
            Readiness detail
          </p>
          <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap font-mono text-xs">
            {typeof readiness.detail === "string"
              ? readiness.detail
              : prettyJson(readiness.detail)}
          </pre>
        </div>
      ) : null}

      {verifyResult ? (
        <div className="border border-(--line) bg-(--paper-deep)/50 px-3 py-2 text-sm">
          <p className="text-xs uppercase tracking-wide text-(--muted)">
            Verify result
          </p>
          <pre className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap font-mono text-xs">
            {prettyJson(verifyResult)}
          </pre>
        </div>
      ) : null}

      <p className="text-xs text-(--muted)">
        Readiness is probe evidence only - it is not job completion, and it does
        not destroy the sandbox by itself.
      </p>
    </section>
  );
}
