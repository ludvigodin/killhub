import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { resolveScreenshotSrc, screenshotFallbackSrc } from "./screenshots.ts";

describe("resolveScreenshotSrc", () => {
  it("prefers a trimmed public CDN URL", () => {
    assert.equal(
      resolveScreenshotSrc(
        "job-1",
        "shot-a",
        "  https://cdn.example/killhub/screenshots/job-1/shot-a.png  ",
      ),
      "https://cdn.example/killhub/screenshots/job-1/shot-a.png",
    );
  });

  it("falls back to the Plane-1 API path when URL is absent", () => {
    assert.equal(
      resolveScreenshotSrc("job-1", "shot-a"),
      "/api/jobs/job-1/screenshots/shot-a",
    );
    assert.equal(
      resolveScreenshotSrc("job-1", "shot-a", null),
      "/api/jobs/job-1/screenshots/shot-a",
    );
    assert.equal(
      resolveScreenshotSrc("job-1", "shot-a", "   "),
      "/api/jobs/job-1/screenshots/shot-a",
    );
  });

  it("encodes job and screenshot ids in the API path", () => {
    assert.equal(
      resolveScreenshotSrc("job/1", "shot a"),
      "/api/jobs/job%2F1/screenshots/shot%20a",
    );
  });
});

describe("screenshotFallbackSrc", () => {
  it("retries via the API proxy after a CDN failure", () => {
    assert.equal(
      screenshotFallbackSrc(
        "job-1",
        "shot-a",
        "https://cdn.example/killhub/screenshots/job-1/shot-a.png",
      ),
      "/api/jobs/job-1/screenshots/shot-a",
    );
  });

  it("returns null after the API proxy itself fails", () => {
    assert.equal(
      screenshotFallbackSrc(
        "job-1",
        "shot-a",
        "/api/jobs/job-1/screenshots/shot-a",
      ),
      null,
    );
  });
});
