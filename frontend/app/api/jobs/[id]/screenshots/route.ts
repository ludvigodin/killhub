import { connection } from "next/server";
import { exploreFetch, mapExploreError } from "@/lib/explore";

export async function GET(
  _request: Request,
  ctx: RouteContext<"/api/jobs/[id]/screenshots">,
) {
  await connection();
  const { id } = await ctx.params;
  const upstream = await exploreFetch(
    `/internal/jobs/${encodeURIComponent(id)}/screenshots`,
  );
  if (!upstream.ok) {
    return mapExploreError(upstream);
  }
  return Response.json(await upstream.json());
}
