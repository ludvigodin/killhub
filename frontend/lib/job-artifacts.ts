/**
 * Plane 1 browser views of the versioned artifacts in the repository's schemas/.
 * Runtime validation belongs to Plane 1 workers. These declarations describe
 * JSON on the wire, including commands that the frontend only displays.
 */

type TargetType = "github_repo" | "npm_package" | "pypi_package" | "fixture";
type McpTransport = "stdio" | "streamable_http";
type DiscoveryMethod = "mcp_inspector_cli" | "python_mcp_sdk_fallback";
type NetworkMode = "install" | "monitored_detonation" | "offline_verify";
type CgroupLimits = {
  memory_max: string;
  memory_swap_max: "0";
  pids_max: number;
  cpu_max: string;
};

// Both command schemas require exactly one of argv or shell.
type CommandSpec = {
  cwd?: string;
  env?: Record<string, string>;
  timeout_seconds: number;
} & (
  | { argv: [string, ...string[]]; shell?: never }
  | { argv?: never; shell: string }
);

export type EnvironmentProfile = {
  schema_version: "1";
  oci_image: string;
  os_image?: string;
  runtime?: string;
  workdir?: string;
  summary?: string;
  verification_target?: "original_application" | "generated_demo";
  source: {
    type: TargetType;
    url?: string;
    locator?: string;
    ref?: string;
    commit: string;
    package_name?: string | null;
    entrypoint?: string | null;
  };
  services: ServiceSpec[];
  packages?: string[];
  commands: {
    install: CommandSpec[];
    run: CommandSpec[];
  };
  processes: ProcessSpec[];
  probes: ProbeSpec[];
  ports?: number[];
  security_assessment?: SecurityAssessmentConfig;
  network_mode: NetworkMode;
  cgroup_limits: CgroupLimits;
} & (
  | { intent: "git_mcp"; mcp: McpConfig }
  | { intent: "webapp" | "demo"; mcp?: McpConfig }
);

type ServiceSpec = {
  name: string;
  kind: "postgres" | "redis" | "mongodb" | "custom";
  ports: number[];
  env?: Record<string, string>;
  healthcheck: ProbeSpec;
  depends_on?: string[];
  optional?: boolean;
} & ({ image: string; package?: string } | { image?: string; package: string });
type McpConfig = {
  launch_command: CommandSpec;
  cwd?: string;
  entrypoint?: string;
  readiness: {
    type: "mcp_handshake";
    transport: McpTransport;
    timeout_seconds: number;
    allow_empty_tools?: boolean;
  };
  security_assessment?: SecurityAssessmentConfig;
} & (
  | { transport: "stdio"; url?: string }
  | { transport: "streamable_http"; url: string }
);

interface ProbeSpec {
  name?: string;
  type: "http" | "tcp" | "command" | "mcp_handshake";
  url?: string;
  host?: string;
  port?: number;
  expected_statuses?: number[];
  body_contains?: string;
  command?: CommandSpec;
  timeout_seconds?: number;
}
interface ProcessSpec {
  name: string;
  command: CommandSpec;
  supervise: "oneshot" | "restart";
  stop_signal?: string;
  ready_after_seconds?: number;
  ready_probe?: string;
}
interface SecurityAssessmentConfig {
  enabled: boolean;
  discovery_method?: DiscoveryMethod;
  run_detonation_scenarios?: boolean;
  allow_empty_tools?: boolean;
  max_scenarios?: number;
}
export interface DynamicInstallSpec {
  schema_version: "1";
  spec_id: string;
  target: {
    source_type: TargetType;
    locator: string;
    resolved_ref: string;
    package_name?: string | null;
    entrypoint: string;
  };
  base_image: "ubuntu-24.04-killhub";
  dependencies: {
    python: {
      enabled: boolean;
      version?: string;
      packages?: string[];
    };
    uv: {
      enabled: boolean;
      version?: string;
      tool_installs?: string[];
    };
    node: {
      enabled: boolean;
      version?: string;
      packages?: string[];
    };
    system_packages: string[];
  };
  install_commands: (CommandSpec & { cache_dir?: "/run/mcp-package-cache" })[];
  launch: {
    cwd: string;
    argv: [string, ...string[]];
    env_overrides: Record<string, string>;
    mcp_transport: McpTransport | "none";
    http_port?: number | null;
  };
  mounts_and_seeds: {
    rootfs_readonly: true;
    overlayfs: {
      enabled: true;
      lowerdir: string;
      upperdir: string;
      workdir: string;
      merged: string;
    };
    workspace_size_cap_mb: number;
    canary_paths: {
      workspace_env: "/workspace/.env";
      ssh_dir: "/home/agent/.ssh";
      aws_dir: "/home/agent/.aws";
      extra_paths?: string[];
    };
    opencode_seeds: {
      db_path: "/home/agent/.local/share/opencode/opencode.db";
      config_dir: "/home/agent/.config/opencode";
      gitconfig_path: "/home/agent/.gitconfig";
      llm_proxy_url: string;
    };
    package_cache_tmpfs: {
      mount_path: "/run/mcp-package-cache";
      size_cap_mb: number;
    };
    tls_ca: {
      ca_cert_path: string;
      env_vars: {
        SSL_CERT_FILE: string;
        REQUESTS_CA_BUNDLE: string;
        NODE_EXTRA_CA_CERTS: string;
      };
    };
    ipc: {
      transport: "af_vsock" | "uds" | "mgmt0";
      vsock_device?: string;
      vsock_cid?: number;
      control_port?: number;
      telemetry_port?: number;
      uds_path?: string;
      mgmt_iface?: string;
    };
  };
  network_policy: {
    mode: NetworkMode;
    tap_mitmdump: {
      enabled: boolean;
      tap_interface?: string;
      listen_port?: number;
      transparent_http_https: boolean;
      transparent_dns: boolean;
    };
    drop_doh_dot_quic: true;
    pcap_enabled: boolean;
    canary_blocking: {
      enabled: boolean;
      block_http: boolean;
      block_dns: boolean;
    };
    deny_control_plane: true;
    deny_siblings: true;
  };
  kill_switch_limits: {
    layer1_llm_proxy: {
      max_turns: number;
      max_tokens: number;
      oscillation_detection: boolean;
      repeated_call_threshold?: number;
      http_status_on_trip: 429;
    };
    layer2_cgroup_v2: CgroupLimits & { monitor_events: true };
    layer3_watchdog: {
      wall_clock_seconds: number;
      flush_telemetry_before_kill: true;
      flush_grace_seconds?: number;
      teardown_tap_iptables_overlay: true;
    };
  };
}
export interface TestScenarioPlan {
  schema_version: "1";
  scan_id: string;
  discovery: {
    inspector_method: DiscoveryMethod;
    protocol_version: string;
    server_info: {
      name: string;
      version?: string;
      [k: string]: unknown;
    };
    t0_tools_sha256: string;
    tools: {
      name: string;
      description?: string;
      input_schema?: Record<string, unknown>;
      [k: string]: unknown;
    }[];
    resources: {
      uri: string;
      name?: string;
      description?: string;
      mime_type?: string;
      [k: string]: unknown;
    }[];
    prompts: {
      name: string;
      description?: string;
      arguments?: unknown[];
      [k: string]: unknown;
    }[];
  };
  target_atlas_tactics: AtlasTacticId[];
  target_owasp_mcp: OwaspMcpId[];
  scenarios: TestScenario[];
}
interface TestScenario {
  scenario_id: string;
  title: string;
  demo_fixture_id: string | null;
  category:
    | "indirect_prompt_injection"
    | "tool_rug_pull"
    | "supply_chain_backdoor"
    | "credential_exfiltration"
    | "tool_drift_shadowing"
    | "resource_exhaustion"
    | "command_injection"
    | "auth_bypass"
    | "custom";
  atlas_tactics: AtlasTacticId[];
  owasp_mcp: OwaspMcpId[];
  trigger_steps: TriggerStep[];
  expected_invariants: string[];
  catching_sensors: RuntimeSensorId[];
  max_turns: number;
}
interface TriggerStep {
  step_index: number;
  action: string;
  tool_name?: string;
  arguments?: Record<string, unknown>;
  prompt?: string;
  expected_observation?: string;
}
type AtlasTacticId =
  | "AML.TA0000"
  | "AML.TA0001"
  | "AML.TA0002"
  | "AML.TA0003"
  | "AML.TA0004"
  | "AML.TA0005"
  | "AML.TA0006"
  | "AML.TA0007"
  | "AML.TA0008"
  | "AML.TA0009"
  | "AML.TA0010"
  | "AML.TA0011"
  | "AML.TA0012"
  | "AML.TA0013"
  | "AML.TA0014"
  | "AML.TA0015";
type OwaspMcpId =
  | "MCP01:2025"
  | "MCP02:2025"
  | "MCP03:2025"
  | "MCP04:2025"
  | "MCP05:2025"
  | "MCP06:2025"
  | "MCP07:2025"
  | "MCP08:2025"
  | "MCP09:2025"
  | "MCP10:2025";
type RuntimeSensorId =
  | "mitmdump_http"
  | "mitmdump_dns"
  | "tcpdump_pcap"
  | "strace"
  | "overlayfs"
  | "checkout_sha256"
  | "mcp_wire_tap"
  | "cgroup_v2"
  | "llm_proxy"
  | "canary_monitor"
  | "inspector_diff"
  | "opencode_db_audit"
  | "hypervisor_watchdog";
type SensorId = RuntimeSensorId | "sca_scanner" | "preflight";

export interface DetonationVerdict {
  schema_version: "1";
  scan_id: string;
  target: {
    source_type: TargetType | "git_repo";
    locator: string;
    resolved_ref: string | null;
    package_sha256_before: string | null;
    package_sha256_after: string | null;
    // A comparison requires both measurements from the same sandbox generation.
    integrity_tampered: boolean | null;
  };
  verdict: {
    status: "CLEAN" | "SUSPICIOUS" | "MALICIOUS" | "ABORTED" | "INCONCLUSIVE";
    risk_score: number | null;
    summary: string;
    kill_switch_triggered: {
      reason: string | null;
      timestamp: string | null;
    } & (
      | { triggered: false; layer: null }
      | {
          triggered: true;
          layer: "layer1_llm_proxy" | "layer2_cgroup_v2" | "layer3_watchdog";
        }
    );
  };
  containment_proof: {
    timeout_enforcement: ContainmentAxisResult;
    host_access_denied: ContainmentAxisResult;
    sibling_access_denied: ContainmentAxisResult;
    host_liveness: ContainmentAxisResult;
    claim: "complete" | "incomplete";
    key_isolation_verified: boolean;
    canary_blocking_verified: boolean;
    doh_dot_quic_dropped: boolean;
  };
  mcp_capabilities: {
    discovery_method: DiscoveryMethod | "none";
    t0_tools_sha256: string | null;
    final_tools_sha256: string | null;
    tool_diffs: {
      tool_name: string;
      change_type:
        | "added"
        | "removed"
        | "modified_schema"
        | "modified_description";
      t0_sha256?: string | null;
      final_sha256?: string | null;
      detail?: string;
    }[];
    tools_count_t0: number;
    tools_count_final: number;
    resources_count: number;
    prompts_count: number;
  };
  findings: DetonationFinding[];
  atlas_coverage_matrix: Record<AtlasTacticId, AtlasCoverageEntry>;
  owasp_mcp_coverage: Record<OwaspMcpId, OwaspMcpCoverageEntry>;
  telemetry: {
    http_requests: number;
    https_intercepted: number;
    dns_queries: number;
    doh_dot_quic_blocked: number;
    canary_blocks: number;
    strace_syscalls_flagged: number;
    overlayfs_modified_paths: string[];
    mcp_wire_messages: number;
    cgroup_events: {
      oom: number;
      pid_max: number;
      cpu_throttled: number;
    };
    llm_proxy_turns: number;
    llm_proxy_tokens: number;
    llm_proxy_429_blocks: number;
    pcap_artifact_path: string | null;
    ndjson_events_count: number;
  };
}
interface ContainmentAxisResult {
  status:
    | "passed"
    | "policy_denied"
    | "failed"
    | "infra_error"
    | "tooling_missing"
    | "inconclusive"
    | "not_tested";
  positive_control_passed?: boolean | null;
  detail: string;
}
interface DetonationFinding {
  id: string;
  severity: "critical" | "high" | "medium" | "low" | "info";
  source:
    | "sca"
    | "mcp_assessment"
    | "intentional_app"
    | "canary"
    | "network"
    | "containment"
    | "preflight"
    | "runtime_sensor"
    | "kill_switch";
  atlas_tactic: AtlasTacticId | null;
  owasp_mcp: OwaspMcpId | null;
  sensor: SensorId | null;
  title: string;
  detail: string;
  evidence: Record<string, unknown>;
  blocked: boolean;
  cited_by_review: boolean;
}
interface AtlasCoverageEntry {
  tactic_id: AtlasTacticId;
  tactic_name: string;
  monitored: boolean;
  sensors: SensorId[];
  triggered: boolean;
  finding_ids: string[];
}
interface OwaspMcpCoverageEntry {
  category_id: OwaspMcpId;
  name: string;
  monitored: boolean;
  sensors: SensorId[];
  triggered: boolean;
  finding_ids: string[];
}
