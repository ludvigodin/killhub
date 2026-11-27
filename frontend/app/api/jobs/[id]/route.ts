import { connection } from "next/server";
import { exploreFetch, mapExploreError } from "@/lib/explore";

export async function GET(
  _request: Request,
  ctx: RouteContext<"/api/jobs/[id]">,
) {
  await connection();
  const { id } = await ctx.params;
  const upstream = await exploreFetch(
    `/internal/jobs/${encodeURIComponent(id)}`,
  );
  if (!upstream.ok) {
    return mapExploreError(upstream);
  }
  return Response.json(await upstream.json());
}

export async function DELETE(
  _request: Request,
  ctx: RouteContext<"/api/jobs/[id]">,
) {
  await connection();
  const { id } = await ctx.params;
  const upstream = await exploreFetch(
    `/internal/jobs/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  );
  if (!upstream.ok) {
    return mapExploreError(upstream);
  }
  return Response.json(await upstream.json());
}
