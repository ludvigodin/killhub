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
