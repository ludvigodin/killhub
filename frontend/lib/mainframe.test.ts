import assert from "node:assert/strict";
import test from "node:test";
import { mapEvents } from "./mainframe.ts";

test("route events and distinguish danger evidence from operational waits and expected denials", () => {
  const data = [
    { type: "status", telemetry: { status: "installing" } },
    { type: "log", telemetry: { kind: "wait", elapsed_seconds: 20 } },
    {
      type: "finding",
      telemetry: {
        source: "network",
        classification: "policy_denied",
        severity: "info",
      },
    },
    { type: "containment", telemetry: { classification: "inconclusive" } },
    {
      type: "finding",
      telemetry: { source: "sca", finding: { severity: "high" } },
    },
    {
      type: "finding",
      telemetry: { source: "canary", code: "canary_unexpected_hit" },
    },
    { type: "containment", telemetry: { classification: "policy_bypass" } },
    {
      type: "finding",
      telemetry: {
        source: "activity",
        classification: "canary_exfiltration_attempt",
        severity: "critical",
      },
    },
    { type: "status", telemetry: { status: "completed" } },
  ];
  const items = mapEvents(
    data.map((e, i) => ({ ...e, id: String(i), message: "fixture" })),
  );
  assert.deepEqual(
    items.map((i) => i.station),
    [2, 2, 4, 4, 3, 4, 4, 3, 5],
  );
  assert.deepEqual(
    items.map((i) => i.alert),
    [
      null,
      null,
      null,
      null,
      "High-severity finding",
      "Unexpected canary exposure",
      "Containment policy bypass",
      "Canary send attempt",
      null,
    ],
  );
});
