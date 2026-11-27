/** Parse receipt / SSE containment payloads into axis verdicts (D58 / D65). */

export type AxisVerdict = "pass" | "fail" | "inconclusive" | "missing";

export type ContainmentAxis = {
  id: string;
  label: string;
  blurb: string;
  verdict: AxisVerdict;
  classification: string | null;
  detail: string | null;
  probes: ContainmentProbe[];
};

type ContainmentProbe = {
  name: string;
  verdict: AxisVerdict;
  classification: string | null;
  detail: string | null;
};

export type AbsorptionMoment = {
  absorbed: boolean;
  kind: string;
  command: string | null;
  summary: string;
};

export type ContainmentView = {
  claim: string | null;
  at: string | null;
  axes: ContainmentAxis[];
  absorption: AbsorptionMoment | null;
  canary: {
    status: string | null;
    hitCount: number;
    unexpected: boolean;
  } | null;
  unverifiedHostTargets: string[];
  passed: number;
  total: number;
};

const AXIS_ORDER = [
  "timeout_enforcement",
  "host_access_denied",
  "sibling_access_denied",
  "host_liveness",
] as const;

const AXIS_META: Record<
  (typeof AXIS_ORDER)[number],
  { label: string; blurb: string }
> = {
  timeout_enforcement: {
    label: "∞ loop absorption",
    blurb: "Adversarial busy-loop killed by sandbox timeout; guest still alive",
  },
  host_access_denied: {
    label: "Host access denied",
    blurb: "Checks reachability of each configured host destination",
  },
  sibling_access_denied: {
    label: "Sibling access denied",
    blurb: "Guest cannot reach another job’s sandbox",
  },
  host_liveness: {
    label: "Host liveness",
    blurb: "Control plane stayed healthy during probes",
  },
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function probeVerdict(probe: Record<string, unknown>): AxisVerdict {
  const classification = str(probe.classification);
  if (classification === "policy_denied") return "pass";
  if (classification === "policy_bypass") return "fail";
  if (classification === "inconclusive" || classification === "infra_error") {
    return "inconclusive";
  }
  if (probe.ok === true) return "pass";
  if (probe.ok === false) return "fail";
  return "inconclusive";
}

function dimensionVerdict(
  id: string,
  dim: Record<string, unknown> | null,
): AxisVerdict {
  if (!dim) return "missing";
  const classification = str(dim.classification);

  if (id === "host_liveness" || id === "timeout_enforcement") {
    if (dim.ok === true) return "pass";
    if (classification === "inconclusive" || classification === "infra_error") {
      return "inconclusive";
    }
    return "fail";
  }

  // Deny dimensions require policy_denied + ok (matches explore/_dimension_proven).
  if (classification === "policy_denied" && dim.ok === true) return "pass";
  if (classification === "policy_bypass") return "fail";
  if (
    classification === "inconclusive" ||
    classification === "infra_error" ||
    classification === "tooling_missing"
  ) {
    return "inconclusive";
  }
  if (dim.ok === true) return "pass";
  if (dim.ok === false) return "fail";
  return "inconclusive";
}

function dimensionDetail(
  id: string,
  dim: Record<string, unknown>,
): string | null {
  if (id === "timeout_enforcement") {
    const absorption = asRecord(dim.absorption);
    const summary = str(absorption?.summary);
    if (summary) return summary;
    const parts: string[] = [];
    if (dim.timed_out === true) parts.push("loop timed out");
    if (dim.guest_alive === true) parts.push("guest alive");
    if (parts.length) return parts.join(" · ");
  }
  if (id === "host_liveness") {
    const checks = Array.isArray(dim.checks) ? dim.checks : [];
    const okCount = checks.filter((c) => asRecord(c)?.ok === true).length;
    if (checks.length) return `${okCount}/${checks.length} checks healthy`;
  }
  if (id === "sibling_access_denied") {
    const target = str(dim.target);
    if (target) return `probe → ${target}`;
  }
  const detail = str(dim.detail);
  if (detail) return detail.length > 120 ? `${detail.slice(0, 118)}…` : detail;
  return str(dim.classification);
}

function parseProbes(dim: Record<string, unknown>): ContainmentProbe[] {
  const raw = Array.isArray(dim.probes) ? dim.probes : [];
  return raw
    .map((item) => asRecord(item))
    .filter((p): p is Record<string, unknown> => p != null)
    .map((p) => {
      const name = str(p.name) || "probe";
      const classification = str(p.classification);
      const guest = str(p.guest_detail);
      const host = str(p.host_detail);
      const url = str(p.url);
      const bits = [url, guest && `guest ${guest}`, host && `host ${host}`]
        .filter(Boolean)
        .join(" · ");
      return {
        name,
        verdict: probeVerdict(p),
        classification,
        detail: bits || classification,
      };
    });
}

export function parseContainment(
  containment: Record<string, unknown> | null | undefined,
): ContainmentView | null {
  if (!containment) return null;

  const dims = asRecord(containment.dimensions) || {};
  const axes: ContainmentAxis[] = AXIS_ORDER.map((id) => {
    const dim = asRecord(dims[id]);
    const meta = AXIS_META[id];
    return {
      id,
      label: meta.label,
      blurb: meta.blurb,
      verdict: dimensionVerdict(id, dim),
      classification: dim ? str(dim.classification) : null,
      detail: dim ? dimensionDetail(id, dim) : null,
      probes: dim ? parseProbes(dim) : [],
    };
  });

  const canaryRaw = asRecord(containment.canary_scan);
  const hitCount =
    typeof canaryRaw?.hit_count === "number" ? canaryRaw.hit_count : 0;
  const canary = canaryRaw
    ? {
        status: str(canaryRaw.status),
        hitCount,
        unexpected: hitCount > 0,
      }
    : null;

  const timeoutDim = asRecord(dims.timeout_enforcement);
  const absorptionRaw = asRecord(timeoutDim?.absorption);
  let absorption: AbsorptionMoment | null = null;
  if (absorptionRaw) {
    absorption = {
      absorbed: absorptionRaw.absorbed === true,
      kind: str(absorptionRaw.kind) || "infinite_loop",
      command: str(absorptionRaw.command),
      summary:
        str(absorptionRaw.summary) ||
        (absorptionRaw.absorbed === true
          ? "Adversarial busy-loop absorbed by exec timeout; guest still alive"
          : "Busy-loop was not cleanly absorbed"),
    };
  } else if (timeoutDim?.ok === true || timeoutDim?.timed_out === true) {
    absorption = {
      absorbed: timeoutDim.ok === true,
      kind: "infinite_loop",
      command: "while true; do :; done",
      summary:
        timeoutDim.ok === true
          ? "Adversarial busy-loop absorbed by exec timeout; guest still alive"
          : "Busy-loop timed out without confirmed guest liveness",
    };
  }

  const scored = axes.filter((a) => a.verdict !== "missing");
  const passed = scored.filter((a) => a.verdict === "pass").length;

  return {
    claim: str(containment.claim),
    at: str(containment.at),
    axes,
    absorption,
    canary,
    unverifiedHostTargets:
      axes
        .find((axis) => axis.id === "host_access_denied")
        ?.probes.filter((probe) => probe.verdict === "inconclusive")
        .map((probe) => probe.name) ?? [],
    passed,
    total: AXIS_ORDER.length,
  };
}

export const VERDICT_TONE: Record<
  AxisVerdict,
  { bg: string; fg: string; label: string }
> = {
  pass: { bg: "var(--ok-soft)", fg: "var(--ok)", label: "pass" },
  fail: { bg: "var(--danger-soft)", fg: "var(--danger)", label: "fail" },
  inconclusive: {
    bg: "var(--warn-soft)",
    fg: "var(--warn)",
    label: "inconclusive",
  },
  missing: { bg: "var(--paper-deep)", fg: "var(--muted)", label: "missing" },
};

export function claimTone(
  claim: string | null,
  unverifiedTargets: number,
): {
  bg: string;
  fg: string;
  label: string;
} {
  if (claim === "proven") {
    return {
      bg: "var(--ok-soft)",
      fg: "var(--ok)",
      label: unverifiedTargets ? "proven for tested targets" : "proven",
    };
  }
  if (claim === "incomplete") {
    return {
      bg: "var(--warn-soft)",
      fg: "var(--warn)",
      label: "incomplete",
    };
  }
  return {
    bg: "var(--paper-deep)",
    fg: "var(--muted)",
    label: claim || "unknown",
  };
}
