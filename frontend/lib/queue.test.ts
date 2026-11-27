/** Plane 1 queue display checks using synthetic worker values. */

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { formatExpectedWait, formatQueueLine, isInQueue } from "./queue.ts";

describe("queue helpers", () => {
  it("detects in-queue statuses", () => {
    assert.equal(isInQueue("pending"), true);
    assert.equal(isInQueue("queued"), true);
    assert.equal(isInQueue("analyzing"), false);
  });

  it("formats wait estimates", () => {
    assert.equal(formatExpectedWait(20), "~under 1m");
    assert.equal(formatExpectedWait(90), "~2m");
    assert.equal(formatExpectedWait(3600), "~1h");
    assert.equal(formatExpectedWait(5400), "~1h 30m");
    assert.equal(formatExpectedWait(null), null);
  });

  it("builds queue subtitle", () => {
    assert.equal(
      formatQueueLine({
        status: "queued",
        queue_position: 3,
        expected_wait_seconds: 720,
      }),
      "In queue · #3 · ~12m",
    );
    assert.equal(formatQueueLine({ status: "analyzing" }), null);
  });
});
