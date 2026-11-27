import type { ProgressLogEntry } from "../components/ProgressLog";

export const stations = [
  "Intake",
  "Provision",
  "Build",
  "Execute",
  "Containment",
  "Receipt",
] as const;

function stationFor(event: ProgressLogEntry, previous: number) {
  const p = event.telemetry ?? {};
  const step = [p.current_step, p.step, p.phase, event.kind, p.status]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  if (
    event.type === "containment" ||
    p.source === "canary" ||
    p.source === "network"
  )
    return 4;
  if (/finaliz|destroy|cleanup|receipt|terminal|completed|cancelled/.test(step))
    return 5;
  if (/containment|canary/.test(step)) return 4;
  if (
    event.type === "finding" ||
    event.type === "screenshot" ||
    /verif|readiness|launch|assessment|scan/.test(step)
  )
    return 3;
  if (/install|build|dependenc/.test(step)) return 2;
  if (/provision|bootstrap|sandbox_create|clone|planning|analyzing/.test(step))
    return 1;
  if (/preflight|queued|pending|admission/.test(step)) return 0;
  return previous;
}

function alertReason(event: ProgressLogEntry): string | null {
  const p = event.telemetry ?? {};
  if (event.type !== "finding" && event.type !== "containment") return null;
  if (p.classification === "policy_bypass") return "Containment policy bypass";
  if (p.classification === "canary_exfiltration_attempt")
    return "Canary send attempt";
  if (p.code === "canary_unexpected_hit") return "Unexpected canary exposure";
  const finding =
    p.finding && typeof p.finding === "object"
      ? (p.finding as Record<string, unknown>)
      : p;
  if (
    event.type === "finding" &&
    (finding.severity === "high" || finding.severity === "critical")
  ) {
    return finding.severity === "critical"
      ? "Critical finding"
      : "High-severity finding";
  }
  return null;
}

export function mapEvents(events: ProgressLogEntry[]) {
  let station = 0;
  return events.map((event) => {
    station = stationFor(event, station);
    const evidence = [
      "error",
      "finding",
      "containment",
      "gap",
      "screenshot",
    ].includes(event.type);
    return {
      event,
      station,
      bank: station * 2 + Number(evidence),
      alert: alertReason(event),
    };
  });
}

export type FrameEvent = ReturnType<typeof mapEvents>[number];
