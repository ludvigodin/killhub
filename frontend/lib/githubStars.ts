/** Killhub GitHub repo used for the nav star count. */
export const KILLHUB_GITHUB_OWNER = "ludvigodin";
export const KILLHUB_GITHUB_REPO = "killhub";
export const KILLHUB_GITHUB_URL = `https://github.com/${KILLHUB_GITHUB_OWNER}/${KILLHUB_GITHUB_REPO}`;

export async function fetchGithubStars(
  signal?: AbortSignal,
): Promise<number | null> {
  const res = await fetch("/api/github-stars", {
    method: "GET",
    signal,
    headers: { Accept: "application/json" },
  });
  if (!res.ok) return null;
  const body = (await res.json()) as { stars?: unknown };
  return typeof body.stars === "number" && Number.isFinite(body.stars)
    ? Math.max(0, Math.floor(body.stars))
    : null;
}
