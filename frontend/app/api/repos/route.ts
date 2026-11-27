import { connection } from "next/server";
import { exploreFetch, mapExploreError } from "@/lib/explore";

export async function GET(request: Request) {
  await connection();
  const url = new URL(request.url);
  const params = new URLSearchParams();
  const limit = url.searchParams.get("limit");
  const offset = url.searchParams.get("offset");
  const q = url.searchParams.get("q");
  if (limit != null && limit.length > 0) {
    params.set("limit", limit);
  }
  if (offset != null && offset.length > 0) {
    params.set("offset", offset);
  }
  if (q != null && q.trim().length > 0) {
    params.set("q", q.trim().slice(0, 200));
  }
  const qs = params.toString();
  const path = qs.length > 0 ? `/internal/repos?${qs}` : "/internal/repos";
  const upstream = await exploreFetch(path, {
    method: "GET",
  });
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
