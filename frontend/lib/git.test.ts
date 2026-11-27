import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  githubUrlFromOwnerRepo,
  hostFromGitUrl,
  hostLabelFromGitUrl,
  isReservedAppSegment,
  validateGitUrl,
} from "./git.ts";

describe("isReservedAppSegment", () => {
  it("blocks Killhub app routes", () => {
    for (const seg of [
      "jobs",
      "repos",
      "features",
      "hubs",
      "mcp",
      "health",
      "api",
      "_next",
      "JOBS",
      "  repos  ",
    ]) {
      assert.equal(isReservedAppSegment(seg), true, seg);
    }
  });

  it("allows ordinary GitHub owners", () => {
    assert.equal(isReservedAppSegment("heroku"), false);
    assert.equal(isReservedAppSegment("vercel"), false);
  });
});

describe("githubUrlFromOwnerRepo", () => {
  it("builds canonical github.com URLs", () => {
    assert.equal(
      githubUrlFromOwnerRepo("heroku", "node-js-getting-started"),
      "https://github.com/heroku/node-js-getting-started",
    );
  });

  it("strips optional .git on the repo segment", () => {
    assert.equal(
      githubUrlFromOwnerRepo("heroku", "node-js-getting-started.git"),
      "https://github.com/heroku/node-js-getting-started",
    );
  });

  it("rejects reserved first segments", () => {
    assert.equal(githubUrlFromOwnerRepo("jobs", "abc"), null);
    assert.equal(githubUrlFromOwnerRepo("mcp", "tools"), null);
  });

  it("rejects forbidden path junk", () => {
    assert.equal(githubUrlFromOwnerRepo("heroku", "tree"), null);
    assert.equal(githubUrlFromOwnerRepo("blob", "repo"), null);
    assert.equal(githubUrlFromOwnerRepo("heroku", "issues"), null);
  });

  it("rejects empty or illegal characters", () => {
    assert.equal(githubUrlFromOwnerRepo("", "repo"), null);
    assert.equal(githubUrlFromOwnerRepo("own er", "repo"), null);
    assert.equal(githubUrlFromOwnerRepo("owner", ""), null);
  });

  it("produces URLs that pass D78 validateGitUrl", () => {
    const url = githubUrlFromOwnerRepo("heroku", "node-js-getting-started");
    assert.ok(url);
    assert.equal(validateGitUrl(url), url);
  });
});

describe("hostFromGitUrl / hostLabelFromGitUrl", () => {
  it("extracts allowlisted hosts", () => {
    assert.equal(hostFromGitUrl("https://github.com/org/repo"), "github.com");
    assert.equal(
      hostFromGitUrl("https://gitlab.com/group/project"),
      "gitlab.com",
    );
    assert.equal(hostFromGitUrl("not-a-url"), null);
  });

  it("labels hosts for UI chrome", () => {
    assert.equal(hostLabelFromGitUrl("https://github.com/org/repo"), "GitHub");
    assert.equal(
      hostLabelFromGitUrl("https://gitlab.com/group/project"),
      "GitLab",
    );
    assert.equal(
      hostLabelFromGitUrl("https://bitbucket.org/team/repo"),
      "Bitbucket",
    );
    assert.equal(
      hostLabelFromGitUrl("https://codeberg.org/user/repo"),
      "Codeberg",
    );
  });
});
