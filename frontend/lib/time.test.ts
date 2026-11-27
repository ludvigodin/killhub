import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  absoluteTime,
  formatJobWhen,
  isJobStalled,
  relativeTime,
} from "./time.ts";

describe("relativeTime", () => {
  it("formats seconds, minutes, hours, and days", () => {
    const now = Date.parse("2026-11-27T16:00:00.000Z");
    assert.equal(relativeTime("2026-11-27T15:59:30.000Z", now), "30s ago");
    assert.equal(relativeTime("2026-11-27T15:40:00.000Z", now), "20m ago");
    assert.equal(relativeTime("2026-11-27T11:00:00.000Z", now), "5h ago");
    assert.equal(relativeTime("2026-11-24T16:00:00.000Z", now), "3d ago");
  });

  it("returns empty string for invalid input", () => {
    assert.equal(relativeTime("not-a-date"), "");
  });
});

describe("formatJobWhen", () => {
  it("returns relative and absolute together", () => {
    const now = Date.parse("2026-11-27T16:00:00.000Z");
    const iso = "2026-11-27T11:00:00.000Z";
    const when = formatJobWhen(iso, now);
    assert.equal(when.iso, iso);
    assert.equal(when.relative, "5h ago");
    assert.equal(when.absolute, absoluteTime(iso));
    assert.ok(when.absolute.length > 0);
  });
});

describe("isJobStalled", () => {
  it("is false within the stall window and true after", () => {
    const now = Date.parse("2026-11-27T16:00:00.000Z");
    assert.equal(isJobStalled("2026-11-27T15:55:00.000Z", { now }), false);
    assert.equal(isJobStalled("2026-11-27T15:50:00.000Z", { now }), true);
    assert.equal(isJobStalled(null, { now }), false);
    assert.equal(isJobStalled("bad", { now }), false);
  });
});
