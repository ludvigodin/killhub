/** Server-only proxy to the explore Internal Worker API (D52). */

import { connection } from "next/server";

function exploreBase(): string {
  const base = process.env.EXPLORE_BASE_URL?.replace(/\/$/, "");
  if (!base) {
    throw new Error("EXPLORE_BASE_URL is not configured");
  }
  return base;
}

function internalToken(): string {
  const token = process.env.INTERNAL_API_TOKEN;
  if (!token) {
    throw new Error("INTERNAL_API_TOKEN is not configured");
  }
  return token;
}

export type ExploreProxyInit = {
  method?: string;
  body?: BodyInit | null;
  headers?: HeadersInit;
  signal?: AbortSignal;
};

function exploreFailureResponse(
  error: unknown,
  code: string,
  status = 503,
): Response {
  const message =
    error instanceof Error ? error.message : "explore unavailable";
  return Response.json({ error: message, code }, { status });
}

export async function exploreFetch(
  path: string,
  init: ExploreProxyInit = {},
): Promise<Response> {
  await connection();

  let base: string;
  let token: string;
  try {
    base = exploreBase();
    token = internalToken();
  } catch (error) {
    return exploreFailureResponse(error, "explore_misconfigured");
  }

  const url = `${base}${path.startsWith("/") ? path : `/${path}`}`;
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  try {
    return await fetch(url, {
      method: init.method ?? "GET",
      headers,
      body: init.body,
      signal: init.signal,
      cache: "no-store",
    });
  } catch (error) {
    const cause =
      error instanceof Error && "cause" in error
        ? (error as Error & { cause?: unknown }).cause
        : undefined;
    const detail =
      cause instanceof Error
        ? cause.message
        : error instanceof Error
          ? error.message
          : "unreachable";
    return exploreFailureResponse(
      new Error(`Explore sidecar unreachable (${detail})`),
      "explore_unreachable",
    );
  }
}

/** Map explore FastAPI `{detail:{error,code}}` into the public error body. */
export async function mapExploreError(res: Response): Promise<Response> {
  const contentType = res.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    const text = await res.text().catch(() => "");
    return Response.json(
      {
        error: text.trim() || "upstream error",
        code: "upstream_error",
      },
      { status: res.status || 502 },
    );
  }
  let data: {
    detail?: { error?: string; code?: string } | string;
    error?: string;
    code?: string;
  };
  try {
    data = (await res.json()) as typeof data;
  } catch {
    return Response.json(
      { error: "upstream error", code: "upstream_error" },
      { status: res.status || 502 },
    );
  }
  if (typeof data.detail === "object" && data.detail) {
    return Response.json(
      {
        error: data.detail.error ?? "request failed",
        code: data.detail.code ?? "error",
      },
      { status: res.status },
    );
  }
  if (data.error && data.code) {
    return Response.json(
      { error: data.error, code: data.code },
      { status: res.status },
    );
  }
  return Response.json(
    { error: "upstream error", code: "upstream_error" },
    { status: res.status },
  );
}
