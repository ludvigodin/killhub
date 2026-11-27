import { connection } from "next/server";

type ExploreHealth = {
  ok: boolean;
  status?: number;
  error?: string;
};

async function probeExplore(): Promise<ExploreHealth> {
  const base = process.env.EXPLORE_BASE_URL?.replace(/\/$/, "");
  if (!base) {
    return { ok: false, error: "EXPLORE_BASE_URL unset" };
  }

  try {
    const response = await fetch(`${base}/internal/health`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3_000),
    });
    const body = await response.json();
    return { ok: response.ok && body?.ok === true, status: response.status };
  } catch (error) {
    const message = error instanceof Error ? error.message : "unreachable";
    return { ok: false, error: message };
  }
}

export async function GET() {
  await connection();
  const explore = await probeExplore();
  const ok = explore.ok;

  return Response.json(
    {
      ok,
      frontend: true,
      explore,
    },
    { status: ok ? 200 : 503 },
  );
}
