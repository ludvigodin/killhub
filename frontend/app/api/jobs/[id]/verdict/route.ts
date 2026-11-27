/**
 * Plane 1 public verdict proxy. The worker owns verdicts and keeps
 * the internal bearer token on the server.
 */

import { connection } from "next/server";
import { exploreFetch, mapExploreError } from "@/lib/explore";

export async function GET(
  _request: Request,
  ctx: RouteContext<"/api/jobs/[id]/verdict">,
) {
  await connection();
  const { id } = await ctx.params;
  const upstream = await exploreFetch(
    `/internal/jobs/${encodeURIComponent(id)}/verdict`,
  );
  if (!upstream.ok) {
    return mapExploreError(upstream);
  }
  return Response.json(await upstream.json());
}
