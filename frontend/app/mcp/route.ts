import { connection } from "next/server";
import { exploreFetch, mapExploreError } from "@/lib/explore";

/** Public operator MCP JSON-RPC proxy → explore `/internal/mcp` (D81). */

export async function GET() {
  await connection();
  const upstream = await exploreFetch("/internal/mcp", { method: "GET" });
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

export async function POST(request: Request) {
  await connection();
  let body: string;
  try {
    body = await request.text();
  } catch {
    return Response.json(
      { error: "Invalid request body", code: "invalid_rpc" },
      { status: 400 },
    );
  }

  const upstream = await exploreFetch("/internal/mcp", {
    method: "POST",
    body,
    headers: {
      "Content-Type": request.headers.get("content-type") || "application/json",
    },
  });

  if (upstream.status === 204) {
    return new Response(null, { status: 204 });
  }
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
