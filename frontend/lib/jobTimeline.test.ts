import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { buildJobTimeline } from "./jobTimeline.ts";

type Snapshot = Parameters<typeof buildJobTimeline>[0];

function snapshot(partial: Partial<Snapshot>): Snapshot {
  return {
    job_id: "job_test",
    status: "analyzing",
    progress: 10,
    current_step: "working",
    event_cursor: null,
    error: null,
    cancel_requested_at: null,
    updated_at: "2026-11-27T16:00:00.000Z",
    ...partial,
  };
}

describe("buildJobTimeline destroy stage", () => {
  it("never marks destroy as skipped on terminal failure", () => {
    const stages = buildJobTimeline(
      snapshot({
        status: "failed",
        progress: 40,
        current_step: "install failed",
        error: "install failed",
        profile: { schema_version: 1 },
        sandbox_id: "sbx_abc",
        cleanup: { status: "destroying", attempts: 1 },
      }),
    );

    const destroy = stages.find((s) => s.id === "destroy");
    assert.ok(destroy);
    assert.notEqual(destroy.state, "skipped");
    assert.equal(destroy.state, "active");
  });

  it("shows destroy as done when removal is confirmed", () => {
    const stages = buildJobTimeline(
      snapshot({
        status: "failed",
        progress: 100,
        current_step: "failed",
        error: "verify failed",
        profile: { schema_version: 1 },
        sandbox_id: "sbx_abc",
        destroyed_at: "2026-11-27T16:05:00.000Z",
        cleanup: { status: "destroyed", attempts: 1 },
        receipt: { containment: { claim: "incomplete" } },
      }),
    );

    const destroy = stages.find((s) => s.id === "destroy");
    assert.ok(destroy);
    assert.equal(destroy.state, "done");
  });

  it("shows destroy as failed when cleanup is destroy_failed", () => {
    const stages = buildJobTimeline(
      snapshot({
        status: "cancelled",
        progress: 100,
        current_step: "cancelled",
        profile: { schema_version: 1 },
        sandbox_id: "sbx_abc",
        cleanup: {
          status: "destroy_failed",
          attempts: 2,
          last_error: "msb remove timed out",
        },
        receipt: {},
      }),
    );

    const destroy = stages.find((s) => s.id === "destroy");
    assert.ok(destroy);
    assert.equal(destroy.state, "failed");
    assert.equal(destroy.detail, "msb remove timed out");
  });

  it("keeps later non-destroy stages skippable after an earlier failure", () => {
    const stages = buildJobTimeline(
      snapshot({
        status: "failed",
        progress: 30,
        current_step: "planning failed",
        error: "planning failed",
        cleanup: { status: "destroying", attempts: 1 },
      }),
    );

    // Rank marks early stages complete; first unfinished non-destroy fails,
    // subsequent non-destroy stages may skip — destroy must stay required.
    assert.equal(stages.find((s) => s.id === "containment")?.state, "failed");
    assert.equal(stages.find((s) => s.id === "receipt")?.state, "skipped");
    assert.equal(stages.find((s) => s.id === "destroy")?.state, "active");
  });
});
