import { connection } from "next/server";
import { checkPostJobsRateLimitAsync } from "@/lib/admission";
import { exploreFetch, mapExploreError } from "@/lib/explore";
import { validateGithubUrl } from "@/lib/github";

function clientIp(request: Request): string {
  const forwarded = request.headers.get("x-forwarded-for");
  if (forwarded) {
    return forwarded.split(",")[0]?.trim() || "unknown";
  }
  return request.headers.get("x-real-ip") || "unknown";
}

export async function GET(request: Request) {
  await connection();
  const url = new URL(request.url);
  const limit = url.searchParams.get("limit");
  const path =
    limit != null && limit.length > 0
      ? `/internal/jobs?limit=${encodeURIComponent(limit)}`
      : "/internal/jobs";
  const upstream = await exploreFetch(path, {
    method: "GET",
  });
  if (!upstream.ok) {
    return mapExploreError(upstream);
  }
  return Response.json(await upstream.json());
}

export async function POST(request: Request) {
  await connection();

  const limited = await checkPostJobsRateLimitAsync(clientIp(request));
  if (limited) {
    return Response.json(limited.body, { status: limited.status });
  }

  let body: { github_url?: string };
  try {
    body = (await request.json()) as { github_url?: string };
  } catch {
    return Response.json(
      { error: "Invalid JSON body", code: "invalid_url" },
      { status: 400 },
    );
  }

  let githubUrl: string;
  try {
    githubUrl = validateGithubUrl(body.github_url ?? "");
  } catch (error) {
    return Response.json(
      {
        error: error instanceof Error ? error.message : "Invalid URL",
        code: "invalid_url",
      },
      { status: 400 },
    );
  }

  const upstream = await exploreFetch("/internal/jobs", {
    method: "POST",
    body: JSON.stringify({ github_url: githubUrl }),
    headers: {
      "X-Client-IP": clientIp(request),
    },
  });

  if (!upstream.ok) {
    return mapExploreError(upstream);
  }

  const data = await upstream.json();
  return Response.json(data, { status: 201 });
}
