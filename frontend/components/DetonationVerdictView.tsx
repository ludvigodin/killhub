/**
 * Plane 1 receipt view for the worker's validated verdict. Evidence labels
 * track recorded observations, including partial and untested coverage.
 */

import type { ReactNode } from "react";
import type { DetonationVerdict } from "@/lib/job-artifacts";

const CONTAINMENT_AXES = [
  ["timeout_enforcement", "Timeout enforcement"],
  ["host_access_denied", "Control-plane access"],
  ["sibling_access_denied", "Sibling access"],
  ["host_liveness", "Host liveness"],
] as const;

const KILL_SWITCH_LAYERS = {
  layer1_llm_proxy: "Layer 1 · LLM proxy",
  layer2_cgroup_v2: "Layer 2 · Guest cgroup",
  layer3_watchdog: "Layer 3 · Host watchdog",
} as const;

const DISCOVERY_METHODS = {
  mcp_inspector_cli: "MCP Inspector",
  python_mcp_sdk_fallback: "Python MCP SDK",
  none: "No discovery recorded",
} as const;

type CoverageRow = {
  id: string;
  name: string;
  monitored: boolean;
  triggered: boolean;
  sensors: string[];
  finding_ids: string[];
};

function EvidenceValues({ values }: { values: [string, ReactNode][] }) {
  return (
    <dl className="grid gap-3 text-sm sm:grid-cols-2">
      {values.map(([label, value]) => (
        <div className="min-w-0" key={label}>
          <dt className="text-(--muted)">{label}</dt>
          <dd className="mt-0.5 wrap-anywhere font-medium">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function displayDigest(value: string | null | undefined) {
  return value ? (
    <code className="break-all font-mono text-xs">{value}</code>
  ) : (
    "Not recorded"
  );
}

function CoverageTable({
  title,
  entries,
  knownFindings,
}: {
  title: string;
  entries: CoverageRow[];
  knownFindings: ReadonlySet<string>;
}) {
  return (
    <table className="w-full table-fixed border-collapse text-left text-sm">
      <caption className="mb-2 text-left font-medium">{title}</caption>
      <thead className="text-xs text-(--muted)">
        <tr className="border-b border-(--line)">
          <th scope="col" className="w-23 py-2 pr-2 font-normal">
            ID
          </th>
          <th scope="col" className="py-2 pr-2 font-normal">
            Category
          </th>
          <th scope="col" className="w-23 py-2 font-normal">
            Evidence
          </th>
        </tr>
      </thead>
      <tbody>
        {entries.map((entry) => (
          <tr
            className="border-b border-(--line) align-top last:border-0"
            key={entry.id}
          >
            <th
              scope="row"
              className="py-2.5 pr-2 font-mono text-xs font-normal"
            >
              {entry.id}
            </th>
            <td className="py-2.5 pr-2">
              {entry.name}
              {entry.sensors.length ? (
                <p className="mt-1 wrap-anywhere font-mono text-xs text-(--muted)">
                  {entry.sensors.join(", ")}
                </p>
              ) : null}
              {entry.finding_ids.length ? (
                <ul className="mt-1 flex flex-wrap gap-x-2 text-xs">
                  {entry.finding_ids.map((id) => (
                    <li className="wrap-anywhere" key={id}>
                      {knownFindings.has(id) ? (
                        <a
                          className="text-(--accent) underline"
                          href={`#${encodeURIComponent(`finding-${id}`)}`}
                        >
                          {id}
                        </a>
                      ) : (
                        id
                      )}
                    </li>
                  ))}
                </ul>
              ) : null}
            </td>
            <td className="py-2.5 text-xs">
              {entry.triggered
                ? "Finding recorded"
                : entry.monitored
                  ? "Monitored"
                  : "Not monitored"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function DetonationVerdictView({
  report,
}: {
  report: DetonationVerdict;
}) {
  const {
    target,
    verdict,
    containment_proof: proof,
    mcp_capabilities: mcp,
    telemetry,
  } = report;
  const killSwitch = verdict.kill_switch_triggered;
  const findingIds = new Set(report.findings.map((finding) => finding.id));
  // Zero counts are measurements only when their collection ran.
  const discoveryRecorded = mcp.discovery_method !== "none";
  // Git measurements cover paths in the pinned commit. Package targets use artifact digests.
  const integrityScope =
    target.source_type === "github_repo" || target.source_type === "git_repo"
      ? "Tracked checkout"
      : "Package";
  const integrity =
    target.integrity_tampered === null
      ? "Insufficient evidence"
      : target.integrity_tampered
        ? "Change detected"
        : "No change detected";

  return (
    <section
      aria-label="Detonation verdict"
      className="min-w-0 space-y-5 border border-(--line) bg-white/60 p-4 sm:p-6"
    >
      <div className="space-y-2">
        <h3 className="text-lg font-semibold">Detonation verdict</h3>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <span className="rounded bg-(--accent-soft) px-2 py-1 font-mono text-xs font-semibold text-(--accent)">
            {verdict.status}
          </span>
          <p className="text-sm text-(--muted)">
            {verdict.risk_score === null
              ? "Risk score unavailable"
              : `Risk score ${verdict.risk_score}/100`}
          </p>
        </div>
        <p className="text-sm">{verdict.summary}</p>
      </div>

      <section
        aria-labelledby="containment-proof-heading"
        className="space-y-3 border-t border-(--line) pt-4"
      >
        <h4 id="containment-proof-heading" className="font-medium">
          Containment proof
        </h4>
        <EvidenceValues
          values={[
            ["Claim", proof.claim],
            ...CONTAINMENT_AXES.map(([axis, label]): [string, ReactNode] => [
              label,
              <>
                <span>{proof[axis].status.replaceAll("_", " ")}</span>
                <span className="block text-xs font-normal text-(--muted)">
                  {proof[axis].detail}
                </span>
                {proof[axis].positive_control_passed != null ? (
                  <span className="block text-xs font-normal text-(--muted)">
                    {proof[axis].positive_control_passed
                      ? "Positive control passed"
                      : "Positive control failed"}
                  </span>
                ) : null}
              </>,
            ]),
            [
              "Key isolation",
              proof.key_isolation_verified ? "Verified" : "Unverified",
            ],
            [
              "Canary blocking",
              proof.canary_blocking_verified ? "Verified" : "Unverified",
            ],
            [
              "DoH, DoT and QUIC drops",
              proof.doh_dot_quic_dropped ? "Verified" : "Unverified",
            ],
          ]}
        />
      </section>

      <details className="space-y-4 border-t border-(--line) pt-4">
        <summary className="cursor-pointer font-medium">
          Artifact and MCP integrity
        </summary>
        <EvidenceValues
          values={[
            [`${integrityScope} integrity`, integrity],
            [
              `${integrityScope} SHA-256 before`,
              displayDigest(target.package_sha256_before),
            ],
            [
              `${integrityScope} SHA-256 after`,
              displayDigest(target.package_sha256_after),
            ],
            ["Discovery method", DISCOVERY_METHODS[mcp.discovery_method]],
            // A missing inventory has no meaningful tool or resource count.
            ...(discoveryRecorded
              ? ([
                  ["Tools at discovery", mcp.tools_count_t0],
                  [
                    "Tools at final check",
                    mcp.final_tools_sha256
                      ? mcp.tools_count_final
                      : "Not recorded",
                  ],
                  ["Resources", mcp.resources_count],
                  ["Prompts", mcp.prompts_count],
                ] satisfies [string, ReactNode][])
              : []),
            ["Tool SHA-256 at discovery", displayDigest(mcp.t0_tools_sha256)],
            [
              "Tool SHA-256 at final check",
              displayDigest(mcp.final_tools_sha256),
            ],
          ]}
        />
        {mcp.tool_diffs.length ? (
          <ul aria-label="Tool changes" className="space-y-2">
            {mcp.tool_diffs.map((diff) => (
              <li
                className="border-t border-(--line) py-2 text-sm"
                key={`${diff.tool_name}-${diff.change_type}`}
              >
                <p className="wrap-anywhere font-medium">
                  {diff.tool_name}{" "}
                  <span className="font-normal text-(--muted)">
                    {diff.change_type.replaceAll("_", " ")}
                  </span>
                </p>
                {diff.detail ? (
                  <p className="wrap-anywhere text-xs">{diff.detail}</p>
                ) : null}
                {diff.t0_sha256 || diff.final_sha256 ? (
                  <EvidenceValues
                    values={[
                      ["Previous SHA-256", displayDigest(diff.t0_sha256)],
                      ["Final SHA-256", displayDigest(diff.final_sha256)],
                    ]}
                  />
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-(--muted)">
            {mcp.t0_tools_sha256 && mcp.final_tools_sha256
              ? "No tool changes recorded."
              : "No tool comparison recorded."}
          </p>
        )}
      </details>

      <details className="space-y-4 border-t border-(--line) pt-4">
        <summary className="cursor-pointer font-medium">
          MITRE ATLAS and OWASP MCP coverage
        </summary>
        <CoverageTable
          title="MITRE ATLAS"
          knownFindings={findingIds}
          entries={Object.values(report.atlas_coverage_matrix).map((entry) => ({
            ...entry,
            id: entry.tactic_id,
            name: entry.tactic_name,
          }))}
        />
        <CoverageTable
          title="OWASP MCP Top 10"
          knownFindings={findingIds}
          entries={Object.values(report.owasp_mcp_coverage).map((entry) => ({
            ...entry,
            id: entry.category_id,
          }))}
        />
      </details>

      <details className="space-y-4 border-t border-(--line) pt-4">
        <summary className="cursor-pointer font-medium">
          Kill switch and recorded telemetry
        </summary>
        <EvidenceValues
          values={[
            [
              "Kill switch",
              killSwitch.triggered
                ? KILL_SWITCH_LAYERS[killSwitch.layer]
                : "No trigger recorded",
            ],
            ...(killSwitch.reason
              ? [["Reason", killSwitch.reason] satisfies [string, ReactNode]]
              : []),
            ...(killSwitch.timestamp
              ? [
                  ["Triggered at", killSwitch.timestamp] satisfies [
                    string,
                    ReactNode,
                  ],
                ]
              : []),
            ["Telemetry events", telemetry.ndjson_events_count],
            ["HTTP requests", telemetry.http_requests],
            ["HTTPS interceptions", telemetry.https_intercepted],
            ["DNS queries", telemetry.dns_queries],
            ["DoH, DoT and QUIC blocks", telemetry.doh_dot_quic_blocked],
            ["Canary blocks", telemetry.canary_blocks],
            ["Flagged syscalls", telemetry.strace_syscalls_flagged],
            ["MCP messages", telemetry.mcp_wire_messages],
            ["cgroup out-of-memory events", telemetry.cgroup_events.oom],
            ["cgroup PID limit events", telemetry.cgroup_events.pid_max],
            [
              "cgroup CPU throttling events",
              telemetry.cgroup_events.cpu_throttled,
            ],
            ["LLM proxy turns", telemetry.llm_proxy_turns],
            ["LLM proxy tokens", telemetry.llm_proxy_tokens],
            ["LLM proxy blocks", telemetry.llm_proxy_429_blocks],
            [
              "Packet capture",
              telemetry.pcap_artifact_path ? "Recorded" : "Not recorded",
            ],
          ]}
        />
        {telemetry.overlayfs_modified_paths.length ? (
          <div className="text-sm">
            <h5 className="font-medium">Modified guest paths</h5>
            <ul className="mt-1 space-y-1 wrap-anywhere font-mono text-xs">
              {telemetry.overlayfs_modified_paths.map((path) => (
                <li key={path}>{path}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </details>
    </section>
  );
}
