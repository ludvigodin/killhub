import { connection } from "next/server";
import { KILLHUB_GITHUB_OWNER, KILLHUB_GITHUB_REPO } from "@/lib/githubStars";

type GithubRepoPayload = {
  stargazers_count?: unknown;
};

export async function GET() {
  await connection();
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
      { headers, cache: "no-store" },
    );
    if (!upstream.ok) {
      return Response.json(
        { stars: null },
        {
          status: 200,
          headers: {
            "Cache-Control": "public, s-maxage=300, stale-while-revalidate=600",
          },
        },
      );
    }
    const body = (await upstream.json()) as GithubRepoPayload;
    const raw = body.stargazers_count;
    const stars =
      typeof raw === "number" && Number.isFinite(raw)
        ? Math.max(0, Math.floor(raw))
        : null;
    return Response.json(
      { stars },
      {
        headers: {
          "Cache-Control":
            "public, s-maxage=3600, stale-while-revalidate=86400",
        },
      },
    );
  } catch {
    return Response.json(
      { stars: null },
      {
        status: 200,
        headers: {
          "Cache-Control": "public, s-maxage=60, stale-while-revalidate=300",
        },
      },
    );
  }
}
