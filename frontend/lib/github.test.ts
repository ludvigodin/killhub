import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  githubUrlFromOwnerRepo,
  hostFromGithubUrl,
  hostLabelFromGithubUrl,
  isReservedAppSegment,
  validateGithubUrl,
} from "./github.ts";

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

  it("produces URLs that pass D78 validateGithubUrl", () => {
    const url = githubUrlFromOwnerRepo("heroku", "node-js-getting-started");
    assert.ok(url);
    assert.equal(validateGithubUrl(url), url);
  });
});

describe("hostFromGithubUrl / hostLabelFromGithubUrl", () => {
  it("extracts allowlisted hosts", () => {
    assert.equal(
      hostFromGithubUrl("https://github.com/org/repo"),
      "github.com",
    );
    assert.equal(
      hostFromGithubUrl("https://gitlab.com/group/project"),
      "gitlab.com",
    );
    assert.equal(hostFromGithubUrl("not-a-url"), null);
  });

  it("labels hosts for UI chrome", () => {
    assert.equal(
      hostLabelFromGithubUrl("https://github.com/org/repo"),
      "GitHub",
    );
    assert.equal(
      hostLabelFromGithubUrl("https://gitlab.com/group/project"),
      "GitLab",
    );
    assert.equal(
      hostLabelFromGithubUrl("https://bitbucket.org/team/repo"),
      "Bitbucket",
    );
    assert.equal(
      hostLabelFromGithubUrl("https://codeberg.org/user/repo"),
      "Codeberg",
    );
  });
});
