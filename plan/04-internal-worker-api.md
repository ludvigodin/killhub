# Step 04 — Internal Worker API (D52)

**Goal:** Loopback Internal Worker API is the sole job-state owner; Next.js will only proxy.

## Prerequisites

- [03-ledger-core.md](03-ledger-core.md)

## Read first

- [API.md](../API.md) — Jobs shapes (public contract)
- [DECISIONS.md](../DECISIONS.md) D52, D55, D61, D67
- [IMPLEMENTATION_EXPLORE_SANDBOX.md](../IMPLEMENTATION_EXPLORE_SANDBOX.md) § E1

## Do

- [ ] Freeze Internal API: `POST/GET/DELETE /internal/jobs…`, `GET …/events` (SSE), auth via `INTERNAL_API_TOKEN`
- [ ] Bind explore API to localhost / compose-internal only
- [ ] Snapshot includes `event_cursor`; SSE supports `Last-Event-ID` / `?after=`; contiguous prune + `gap` (D67)
- [ ] Cancel: `cancel_requested_at` → freeze ordinary writers → finalizer allowlist (receipt + cleanup) → terminal `cancelled` (D61)
- [ ] Background worker stub that can pick up a job (no sandbox yet)

## Do not

- Implement Microsandbox harness
- Put job dictionary in Next.js

## Lint gate (required before Done when)

Run Biome + Knip and fix all findings before marking this step done (see [LINT.md](LINT.md)):

```bash
cd frontend
pnpm lint:fix && pnpm lint && pnpm knip
```

Must exit **0**. Do **not** start the next step while either tool fails. Python-only changes still require a green gate.

## Done when

curl/internal client can create → snapshot → SSE → cancel against explore; Next still has no local store. Biome + Knip lint gate passes ([LINT.md](LINT.md)).

## Next

[05-jobs-proxy-admission.md](05-jobs-proxy-admission.md)
