/** Public allowlisted HTTPS git URL validation (D78). Field name remains github_url. */

const ALLOWED_HOSTS = new Set([
  "github.com",
  "gitlab.com",
  "bitbucket.org",
  "codeberg.org",
]);

const TWO_SEGMENT_HOSTS = new Set([
  "github.com",
  "bitbucket.org",
  "codeberg.org",
]);

const SEGMENT_RE = /^[A-Za-z0-9_.-]+$/;

const FORBIDDEN_SEGMENTS = new Set([
  "-",
  "tree",
  "blob",
  "src",
  "raw",
  "commit",
  "commits",
  "issues",
  "pull",
  "pulls",
  "wiki",
  "releases",
  "tags",
  "branch",
  "branches",
  "settings",
  "actions",
  "pipelines",
  "merge_requests",
]);

function normalizePathSegments(pathname: string): string[] | null {
  const parts = pathname.split("/").filter(Boolean);
  if (parts.length === 0) return null;
  const last = parts[parts.length - 1];
  if (!last) return null;
  if (last.endsWith(".git")) {
    const stripped = last.slice(0, -".git".length);
    if (!stripped) return null;
    parts[parts.length - 1] = stripped;
  }
  return parts;
}

function parsePublicGitUrl(raw: string): {
  url: string;
  host: string;
  owner: string;
  repo: string;
  pathSegments: string[];
} | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return null;
  }
  if (parsed.protocol !== "https:") return null;
  if (parsed.username || parsed.password) return null;
  if (parsed.search || parsed.hash) return null;
  if (parsed.port) return null;

  const host = parsed.hostname.toLowerCase();
  if (!ALLOWED_HOSTS.has(host)) return null;

  const segments = normalizePathSegments(parsed.pathname);
  if (!segments) return null;
  if (TWO_SEGMENT_HOSTS.has(host)) {
    if (segments.length !== 2) return null;
  } else if (segments.length < 2) {
    return null;
  }

  for (const seg of segments) {
    if (!SEGMENT_RE.test(seg)) return null;
    if (FORBIDDEN_SEGMENTS.has(seg.toLowerCase())) return null;
  }

  const owner = segments[0];
  const repo = segments[segments.length - 1];
  if (!owner || !repo) return null;
  return {
    url: `https://${host}/${segments.join("/")}`,
    host,
    owner,
    repo,
    pathSegments: segments,
  };
}

export function isPublicGithubUrl(raw: string): boolean {
  return parsePublicGitUrl(raw) !== null;
}

export function validateGithubUrl(raw: string): string {
  const parsed = parsePublicGitUrl(raw);
  if (!parsed) {
    throw new Error(
      "URL must be a public HTTPS git link on github.com, gitlab.com, bitbucket.org, or codeberg.org",
    );
  }
  return parsed.url;
}

/** `owner/repo` (or nested GitLab path) from a public git URL, or null. */
export function ownerRepoFromGithubUrl(raw: string): string | null {
  const parsed = parsePublicGitUrl(raw);
  if (!parsed) return null;
  return parsed.pathSegments.join("/");
}

/** Allowlisted host from a public git URL, or null. */
export function hostFromGithubUrl(raw: string): string | null {
  return parsePublicGitUrl(raw)?.host ?? null;
}

/** Short host label for UI chrome (GitHub / GitLab / Bitbucket / Codeberg). */
export function hostLabelFromGithubUrl(raw: string): string {
  const host = hostFromGithubUrl(raw);
  switch (host) {
    case "github.com":
      return "GitHub";
    case "gitlab.com":
      return "GitLab";
    case "bitbucket.org":
      return "Bitbucket";
    case "codeberg.org":
      return "Codeberg";
    default:
      return host ?? "git";
  }
}

/** App path for the repo history page, e.g. `/repos/github.com/org/repo`. */
export function repoPathFromGithubUrl(raw: string): string | null {
  const parsed = parsePublicGitUrl(raw);
  if (!parsed) return null;
  return `/repos/${parsed.host}/${parsed.pathSegments.join("/")}`;
}

/** Reconstruct canonical git URL from `/repos/[...slug]` segments. */
export function githubUrlFromRepoSlug(slug: string[]): string | null {
  if (slug.length < 3) return null;
  const joined = slug.map((s) => s.trim()).filter(Boolean);
  if (joined.length < 3) return null;
  return parsePublicGitUrl(`https://${joined.join("/")}`)?.url ?? null;
}

/** App route first segments that must never be treated as a GitHub owner (D82). */
const RESERVED_APP_SEGMENTS = new Set([
  "jobs",
  "repos",
  "features",
  "hubs",
  "mcp",
  "health",
  "api",
  "_next",
]);

/** True when a path segment collides with a Killhub app route. */
export function isReservedAppSegment(segment: string): boolean {
  const cleaned = segment.trim().toLowerCase();
  if (!cleaned) return true;
  return RESERVED_APP_SEGMENTS.has(cleaned);
}

function normalizeOwnerRepoSegment(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  let seg = trimmed;
  if (seg.endsWith(".git")) {
    seg = seg.slice(0, -".git".length);
  }
  if (!seg || !SEGMENT_RE.test(seg)) return null;
  if (FORBIDDEN_SEGMENTS.has(seg.toLowerCase())) return null;
  return seg;
}

/**
 * Build a canonical github.com URL from a short-path `/{owner}/{repo}` pair (D82).
 * Returns null for reserved app segments or invalid GitHub path junk.
 */
export function githubUrlFromOwnerRepo(
  owner: string,
  repo: string,
): string | null {
  if (isReservedAppSegment(owner)) return null;
  const ownerSeg = normalizeOwnerRepoSegment(owner);
  const repoSeg = normalizeOwnerRepoSegment(repo);
  if (!ownerSeg || !repoSeg) return null;
  return (
    parsePublicGitUrl(`https://github.com/${ownerSeg}/${repoSeg}`)?.url ?? null
  );
}

/** Split textarea / paste input into candidate URL lines (trim, drop blanks). */
export function parseGithubUrlLines(raw: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const line of raw.split(/\r?\n/)) {
    const cleaned = line.trim();
    if (!cleaned || seen.has(cleaned)) continue;
    seen.add(cleaned);
    out.push(cleaned);
  }
  return out;
}
