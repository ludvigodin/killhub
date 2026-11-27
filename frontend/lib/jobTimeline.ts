import type { JobSnapshot } from "@/lib/api";

type TimelineStageId =
  | "plan"
  | "sandbox"
  | "execute"
  | "containment"
  | "receipt"
  | "destroy";

/** "6:11 PM" for a timeline caption; falls back to the raw value if unparsable. */
function clockTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

export type TimelineStageState =
  | "pending"
  | "active"
  | "done"
  | "failed"
  | "skipped";

export type TimelineStage = {
  id: TimelineStageId;
  label: string;
  state: TimelineStageState;
  detail: string | null;
};

export type TimelineEvidence = {
  sawContainmentEvent?: boolean;
  sawLifecycleCreate?: boolean;
  sawLifecycleDestroy?: boolean;
};

const STATUS_RANK: Record<string, number> = {
  pending: 0,
  queued: 1,
  analyzing: 2,
  planning: 3,
  provisioning: 4,
  installing: 5,
  verifying: 6,
  repairing: 6,
  scanning: 7,
  finalizing: 8,
  completed: 9,
  failed: 9,
  cancelled: 9,
};

const STAGE_DEFS: { id: TimelineStageId; label: string }[] = [
  { id: "plan", label: "Plan" },
  { id: "sandbox", label: "Sandbox create" },
  { id: "execute", label: "Execute" },
  { id: "containment", label: "Containment hit" },
  { id: "receipt", label: "Receipt" },
  { id: "destroy", label: "Destroy" },
];

function statusRank(status: string): number {
  return STATUS_RANK[status] ?? 0;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function containmentHitDetail(
  containment: Record<string, unknown> | null | undefined,
): string | null {
  if (!containment) return null;
  const dims = asRecord(containment.dimensions);
  const timeout = asRecord(dims?.timeout_enforcement);
  const absorption = asRecord(timeout?.absorption);
  if (absorption?.absorbed === true || timeout?.ok === true) {
    return "∞ loop absorbed · guest still alive";
  }
  if (timeout?.timed_out === true) {
    return "loop timed out - check guest liveness";
  }
  const claim = containment.claim;
  if (typeof claim === "string" && claim.length > 0) {
    return `claim: ${claim}`;
  }
  return "matrix recorded";
}

function stageCompletion(
  snapshot: JobSnapshot,
  evidence: TimelineEvidence,
): Record<TimelineStageId, boolean> {
  const rank = statusRank(snapshot.status);
  const containment = snapshot.receipt?.containment;
  const hasContainment =
    evidence.sawContainmentEvent === true ||
    containment != null ||
    (typeof snapshot.current_step === "string" &&
      /containment/i.test(snapshot.current_step));

  const destroyed =
    Boolean(snapshot.destroyed_at) ||
    snapshot.cleanup?.status === "destroyed" ||
    evidence.sawLifecycleDestroy === true;

  const sandboxPresent =
    Boolean(snapshot.sandbox_id) ||
    Boolean(snapshot.environment?.environment_id) ||
    evidence.sawLifecycleCreate === true ||
    rank >= 5;

  const executed =
    snapshot.readiness?.passed === true ||
    Boolean(snapshot.verify_result) ||
    Boolean(snapshot.verification) ||
    rank >= 7;

  return {
    plan: Boolean(snapshot.profile) || rank >= 4,
    sandbox: sandboxPresent,
    execute: executed,
    containment: hasContainment,
    receipt: snapshot.receipt != null,
    destroy: destroyed,
  };
}

function stageDetails(
  snapshot: JobSnapshot,
  done: Record<TimelineStageId, boolean>,
): Record<TimelineStageId, string | null> {
  const sandboxId = snapshot.sandbox_id || snapshot.environment?.environment_id;
  const shortSandbox =
    typeof sandboxId === "string" && sandboxId.length > 18
      ? `${sandboxId.slice(0, 16)}…`
      : sandboxId || null;

  return {
    plan: done.plan
      ? snapshot.profile
        ? "environment profile ready"
        : snapshot.current_step || "planned"
      : null,
    sandbox: done.sandbox
      ? shortSandbox
        ? `microVM ${shortSandbox}`
        : "sandbox live"
      : null,
    execute: done.execute
      ? snapshot.readiness?.passed
        ? "readiness verified"
        : snapshot.verification?.kind
          ? `verify: ${snapshot.verification.kind}`
          : snapshot.current_step || "executed"
      : null,
    containment: done.containment
      ? containmentHitDetail(snapshot.receipt?.containment) ||
        "probe stream active"
      : null,
    receipt: done.receipt
      ? snapshot.receipt?.containment &&
        typeof snapshot.receipt.containment.claim === "string"
        ? `dossier · containment ${snapshot.receipt.containment.claim}`
        : "intake dossier persisted"
      : null,
    destroy: done.destroy
      ? snapshot.destroyed_at
        ? `destroyed ${clockTime(snapshot.destroyed_at)}`
        : "sandbox removed"
      : snapshot.cleanup?.status === "destroy_failed"
        ? snapshot.cleanup.last_error || "destroy not confirmed"
        : snapshot.cleanup?.status === "destroying"
          ? "removing sandbox"
          : null,
  };
}

/** Map job snapshot (+ optional SSE hints) to the hero timeline stages. */
export function buildJobTimeline(
  snapshot: JobSnapshot,
  evidence: TimelineEvidence = {},
): TimelineStage[] {
  const done = stageCompletion(snapshot, evidence);
  const details = stageDetails(snapshot, done);
  const terminalFail =
    snapshot.status === "failed" || snapshot.status === "cancelled";
  const terminalOk = snapshot.status === "completed";
  const destroyFailed = snapshot.cleanup?.status === "destroy_failed";
  const destroyRequired =
    terminalFail ||
    terminalOk ||
    snapshot.status === "finalizing" ||
    snapshot.cleanup?.status === "destroying";

  let foundActive = false;
  return STAGE_DEFS.map((def) => {
    const isDone = done[def.id];
    let state: TimelineStageState;

    if (isDone) {
      state = "done";
    } else if (def.id === "destroy") {
      // Destroy is mandatory on every job path (D37/D57) — never skip.
      if (destroyFailed) {
        state = "failed";
      } else if (destroyRequired || !foundActive) {
        state = "active";
        foundActive = true;
      } else {
        state = "pending";
      }
    } else if (terminalOk) {
      // Completed without every marker (e.g. no containment event yet) -
      // leave unfinished stages visible as pending, not fake-done.
      state = "pending";
    } else if (terminalFail) {
      if (!foundActive) {
        state = "failed";
        foundActive = true;
      } else {
        state = "skipped";
      }
    } else if (!foundActive) {
      state = "active";
      foundActive = true;
    } else {
      state = "pending";
    }

    return {
      id: def.id,
      label: def.label,
      state,
      detail: details[def.id],
    };
  });
}

/** Fold SSE log lines into timeline evidence flags. */
export function evidenceFromLogs(
  entries: { type: string; message: string }[],
): TimelineEvidence {
  let sawContainmentEvent = false;
  let sawLifecycleCreate = false;
  let sawLifecycleDestroy = false;

  for (const entry of entries) {
    const msg = entry.message.toLowerCase();
    if (entry.type === "containment" || msg.includes("containment")) {
      sawContainmentEvent = true;
    }
    if (
      entry.type === "lifecycle" ||
      msg.includes("sandbox_create") ||
      msg.includes("sandbox create") ||
      msg.includes("created sandbox")
    ) {
      if (
        msg.includes("create") ||
        msg.includes("boot") ||
        msg.includes("replace")
      ) {
        sawLifecycleCreate = true;
      }
      if (msg.includes("destroy") || msg.includes("destroyed")) {
        sawLifecycleDestroy = true;
      }
    }
    if (
      msg.includes("sandbox_destroy") ||
      msg.includes("sandbox destroy") ||
      msg.includes("destroyed_at")
    ) {
      sawLifecycleDestroy = true;
    }
  }

  return { sawContainmentEvent, sawLifecycleCreate, sawLifecycleDestroy };
}
