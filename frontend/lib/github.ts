/** Public github.com HTTPS URL validation (D15). */

const GITHUB_RE =
  /^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/?$/;

function normalizeGithubUrl(raw: string): string {
  return raw.trim().replace(/\/+$/, "");
}

export function isPublicGithubUrl(raw: string): boolean {
  return GITHUB_RE.test(normalizeGithubUrl(raw));
}

export function validateGithubUrl(raw: string): string {
  const cleaned = normalizeGithubUrl(raw);
  if (!isPublicGithubUrl(cleaned)) {
    throw new Error("URL must be a public https://github.com/org/repo link");
  }
  return cleaned;
}

/** `owner/repo` from a public github.com URL, or null if unparseable. */
export function ownerRepoFromGithubUrl(raw: string): string | null {
  try {
    const cleaned = validateGithubUrl(raw);
    const path = new URL(cleaned).pathname.replace(/^\/+|\/+$/g, "");
    const parts = path.split("/");
    if (parts.length >= 2 && parts[0] && parts[1]) {
      return `${parts[0]}/${parts[1]}`;
    }
  } catch {
    return null;
  }
  return null;
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
