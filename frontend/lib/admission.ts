/**
 * Edge admission for POST /api/jobs (D40): per-IP + global rate limits.
 * Concurrency / queue gates live in the explore sidecar.
 */

type Bucket = { timestamps: number[] };

const perIp = new Map<string, Bucket>();
let globalHits: number[] = [];

function windowMs(): number {
  return Number(process.env.RATE_LIMIT_WINDOW_MS ?? 60_000);
}

function perIpLimit(): number {
  return Number(process.env.RATE_LIMIT_POST_JOBS_PER_IP ?? 10);
}

function globalLimit(): number {
  return Number(process.env.RATE_LIMIT_POST_JOBS_GLOBAL ?? 60);
}

function prune(bucket: number[], now: number, window: number): number[] {
  return bucket.filter((t) => now - t < window);
}

export type AdmissionReject = {
  status: 429;
  body: { error: string; code: "rate_limited" };
};

export function checkPostJobsRateLimit(ip: string): AdmissionReject | null {
  const now = Date.now();
  const window = windowMs();
  const ipKey = ip || "unknown";

  const ipBucket = perIp.get(ipKey) ?? { timestamps: [] };
  ipBucket.timestamps = prune(ipBucket.timestamps, now, window);
  if (ipBucket.timestamps.length >= perIpLimit()) {
    return {
      status: 429,
      body: {
        error: "Rate limit exceeded for job creation",
        code: "rate_limited",
      },
    };
  }

  globalHits = prune(globalHits, now, window);
  if (globalHits.length >= globalLimit()) {
    return {
      status: 429,
      body: {
        error: "Global job creation rate limit exceeded",
        code: "rate_limited",
      },
    };
  }

  ipBucket.timestamps.push(now);
  perIp.set(ipKey, ipBucket);
  globalHits.push(now);
  return null;
}
