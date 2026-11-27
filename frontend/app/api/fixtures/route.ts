import { exploreFetch, mapExploreError } from "@/lib/explore";

export async function GET() {
  const upstream = await exploreFetch("/internal/fixtures");
  if (!upstream.ok) return mapExploreError(upstream);
  return Response.json(await upstream.json(), {
    headers: { "Cache-Control": "no-store" },
  });
}
