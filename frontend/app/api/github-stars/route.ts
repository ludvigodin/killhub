import { cacheLife } from "next/cache";
import { connection } from "next/server";
import { KILLHUB_GITHUB_OWNER, KILLHUB_GITHUB_REPO } from "@/lib/githubStars";

type GithubRepoPayload = {
  stargazers_count?: unknown;
};

async function readStarCount(): Promise<number | null> {
  "use cache";
  const headers: Record<string, string> = {
    Accept: "application/vnd.github+json",
    "User-Agent": "killhub-frontend",
    "X-GitHub-Api-Version": "2022-11-28",
  };
  const token = (process.env.GITHUB_TOKEN || "").trim();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  try {
    const upstream = await fetch(
      `https://api.github.com/repos/${KILLHUB_GITHUB_OWNER}/${KILLHUB_GITHUB_REPO}`,
      { headers },
    );
    if (!upstream.ok) {
      cacheLife("minutes");
      return null;
    }
    const body = (await upstream.json()) as GithubRepoPayload;
    const raw = body.stargazers_count;
    cacheLife("hours");
    return typeof raw === "number" && Number.isFinite(raw)
      ? Math.max(0, Math.floor(raw))
      : null;
  } catch {
    cacheLife("minutes");
    return null;
  }
}

export async function GET() {
  await connection();
  const stars = await readStarCount();
  return Response.json(
    { stars },
    {
      headers: {
        "Cache-Control":
          stars === null
            ? "public, s-maxage=300, stale-while-revalidate=600"
            : "public, s-maxage=3600, stale-while-revalidate=86400",
      },
    },
  );
}
