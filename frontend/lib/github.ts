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
