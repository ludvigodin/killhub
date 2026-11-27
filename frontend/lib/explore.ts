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

export async function exploreFetch(
  path: string,
  init: ExploreProxyInit = {},
): Promise<Response> {
  await connection();
  const url = `${exploreBase()}${path.startsWith("/") ? path : `/${path}`}`;
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${internalToken()}`);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return fetch(url, {
    method: init.method ?? "GET",
    headers,
    body: init.body,
    signal: init.signal,
    cache: "no-store",
  });
}

/** Map explore FastAPI `{detail:{error,code}}` into the public error body. */
export async function mapExploreError(res: Response): Promise<Response> {
  const contentType = res.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    return new Response(res.body, {
      status: res.status,
      headers: {
        "Content-Type": contentType || "application/json",
      },
    });
  }
  const data = (await res.json()) as {
    detail?: { error?: string; code?: string } | string;
    error?: string;
    code?: string;
  };
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
