import { connection } from "next/server";
import { exploreFetch, mapExploreError } from "@/lib/explore";

export async function GET(
  _request: Request,
  ctx: RouteContext<"/api/jobs/[id]/screenshots/[shot_id]">,
) {
  await connection();
  const { id, shot_id } = await ctx.params;
  const upstream = await exploreFetch(
    `/internal/jobs/${encodeURIComponent(id)}/screenshots/${encodeURIComponent(shot_id)}`,
  );
  if (!upstream.ok) {
    return mapExploreError(upstream);
  }
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("Content-Type") || "image/png",
      "Cache-Control": "private, max-age=60",
    },
  });
}
