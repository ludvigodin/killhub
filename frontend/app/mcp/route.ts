import { connection } from "next/server";
import { exploreFetch, mapExploreError } from "@/lib/explore";

/**
 * Public operator MCP JSON-RPC proxy → explore `/internal/mcp` (D81).
 *
 * Streamable HTTP–friendly status codes at the edge:
 * - GET → 405 (no standalone SSE/GET stream on this endpoint)
 * - JSON-RPC notifications → 202 Accepted with empty body
 */

export async function GET() {
  await connection();
  return new Response(null, {
    status: 405,
    headers: { Allow: "POST" },
  });
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

  let isNotification = false;
  try {
    const parsed = JSON.parse(body) as { method?: unknown; id?: unknown };
    isNotification =
      typeof parsed.method === "string" &&
      parsed.method.startsWith("notifications/") &&
      !("id" in parsed && parsed.id !== null && parsed.id !== undefined);
  } catch {
    // Upstream validates JSON; keep proxy thin on parse failures.
  }

  const upstream = await exploreFetch("/internal/mcp", {
    method: "POST",
    body,
    headers: {
      "Content-Type": request.headers.get("content-type") || "application/json",
      "X-Killhub-Mcp-Transport": "http",
    },
  });

  // Explore may still return 204 for notifications; Streamable HTTP wants 202.
  if (
    upstream.status === 204 ||
    (isNotification && upstream.status === 200 && !upstream.body)
  ) {
    return new Response(null, { status: 202 });
  }
  if (isNotification && upstream.ok) {
    // Drop any accidental body on notifications.
    return new Response(null, { status: 202 });
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
