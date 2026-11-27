import { connection } from "next/server";
import { exploreFetch, mapExploreError } from "@/lib/explore";

export async function GET(
  request: Request,
  ctx: RouteContext<"/api/jobs/[id]/events/recent">,
) {
  await connection();
  const { id } = await ctx.params;
  const url = new URL(request.url);
  const limit = url.searchParams.get("limit");
  const qs =
    limit != null && limit.length > 0
      ? `?limit=${encodeURIComponent(limit)}`
      : "";
  const upstream = await exploreFetch(
    `/internal/jobs/${encodeURIComponent(id)}/events/recent${qs}`,
    { method: "GET" },
  );
  if (!upstream.ok) {
    return mapExploreError(upstream);
  }
  try {
    return Response.json(await upstream.json());
  } catch {
    return Response.json(
      { error: "Invalid upstream response", code: "upstream_error" },
      { status: 502 },
    );
  }
}
