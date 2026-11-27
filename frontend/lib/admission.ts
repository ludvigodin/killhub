/**
 * Edge admission for POST /api/jobs (D40 / D71): per-IP + global rate limits.
 * Concurrency / queue gates live in the explore sidecar.
 *
 * ADMISSION_STORE=memory (default) → in-process buckets.
 * ADMISSION_STORE=valkey|redis + VALKEY_URL|REDIS_URL → shared Valkey counters.
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

function admissionBackend(): "memory" | "valkey" {
  const raw = (process.env.ADMISSION_STORE ?? "memory").trim().toLowerCase();
  if (raw === "valkey" || raw === "redis") {
    return "valkey";
  }
  return "memory";
}

function valkeyUrl(): string {
  return (process.env.VALKEY_URL || process.env.REDIS_URL || "").trim();
}

function prune(bucket: number[], now: number, window: number): number[] {
  return bucket.filter((t) => now - t < window);
}

export type AdmissionReject = {
  status: 429 | 503;
  body: {
    error: string;
    code: "rate_limited" | "admission_unavailable";
  };
};

function memoryRateLimit(ip: string): AdmissionReject | null {
  const now = Date.now();
  const window = windowMs();
  const ipKey = ip || "unknown";

  const ipBucket = perIp.get(ipKey) ?? { timestamps: [] };
  ipBucket.timestamps = prune(ipBucket.timestamps, now, window);
  if (perIpLimit() > 0 && ipBucket.timestamps.length >= perIpLimit()) {
    return {
      status: 429,
      body: {
        error: "Rate limit exceeded for job creation",
        code: "rate_limited",
      },
    };
  }

  globalHits = prune(globalHits, now, window);
  if (globalLimit() > 0 && globalHits.length >= globalLimit()) {
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

function rateKey(kind: "ip" | "global", id: string, bucket: number): string {
  if (kind === "ip") {
    const safe = (id || "unknown").replace(/\s/g, "_").slice(0, 128);
    return `killhub:adm:v1:rl:ip:${safe}:${bucket}`;
  }
  return `killhub:adm:v1:rl:global:${bucket}`;
}

type RedisLike = {
  incr: (key: string) => Promise<number>;
  pExpire: (key: string, ms: number) => Promise<unknown>;
  connect: () => Promise<unknown>;
  isOpen: boolean;
  on: (ev: string, cb: (err: Error) => void) => void;
};

let redisClient: RedisLike | null | undefined;

async function getRedis(): Promise<RedisLike | null> {
  if (redisClient !== undefined) {
    return redisClient;
  }
  const url = valkeyUrl();
  if (!url) {
    redisClient = null;
    return null;
  }
  try {
    // Optional dependency — only required when ADMISSION_STORE=valkey.
    const mod = await import("redis");
    const client = mod.createClient({ url }) as RedisLike;
    client.on("error", () => {
      /* command failures surface to the caller */
    });
    if (!client.isOpen) {
      await client.connect();
    }
    redisClient = client;
    return client;
  } catch {
    redisClient = null;
    return null;
  }
}

async function valkeyRateLimit(ip: string): Promise<AdmissionReject | null> {
  const client = await getRedis();
  if (!client) {
    return {
      status: 503,
      body: {
        error: "Admission store unavailable",
        code: "admission_unavailable",
      },
    };
  }
  const window = Math.max(windowMs(), 1);
  const ttl = window * 2;
  const bucket = Math.floor(Date.now() / window);
  try {
    const ipKey = rateKey("ip", ip, bucket);
    const ipN = await client.incr(ipKey);
    if (ipN === 1) {
      await client.pExpire(ipKey, ttl);
    }
    if (perIpLimit() > 0 && ipN > perIpLimit()) {
      return {
        status: 429,
        body: {
          error: "Rate limit exceeded for job creation",
          code: "rate_limited",
        },
      };
    }
    const gKey = rateKey("global", "", bucket);
    const gN = await client.incr(gKey);
    if (gN === 1) {
      await client.pExpire(gKey, ttl);
    }
    if (globalLimit() > 0 && gN > globalLimit()) {
      return {
        status: 429,
        body: {
          error: "Global job creation rate limit exceeded",
          code: "rate_limited",
        },
      };
    }
    return null;
  } catch {
    return {
      status: 503,
      body: {
        error: "Admission store unavailable",
        code: "admission_unavailable",
      },
    };
  }
}

export async function checkPostJobsRateLimitAsync(
  ip: string,
): Promise<AdmissionReject | null> {
  if (admissionBackend() === "valkey") {
    return valkeyRateLimit(ip);
  }
  return memoryRateLimit(ip);
}
