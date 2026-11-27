import { connection } from "next/server";
import { exploreFetch, mapExploreError } from "@/lib/explore";

export async function GET(
  request: Request,
  ctx: RouteContext<"/api/jobs/[id]/events">,
) {
  await connection();
  const { id } = await ctx.params;
  const url = new URL(request.url);
  const after = url.searchParams.get("after");
  const lastEventId = request.headers.get("Last-Event-ID");

  const qs = after && !lastEventId ? `?after=${encodeURIComponent(after)}` : "";
  const headers: HeadersInit = {};
  if (lastEventId) {
    headers["Last-Event-ID"] = lastEventId;
  }

  const upstream = await exploreFetch(
    `/internal/jobs/${encodeURIComponent(id)}/events${qs}`,
    { headers, signal: request.signal },
  );

  if (!upstream.ok) {
    return mapExploreError(upstream);
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
