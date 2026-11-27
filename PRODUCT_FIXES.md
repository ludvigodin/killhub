# Killhub — Product fixes and completion checklist

Review date: 2026-11-27.

Scope: the Killhub repository, automated checks, and existing public reports on [killhub.pro](https://killhub.pro). This checklist records the product review findings; it does not claim that any fixes below are implemented or that deployment has been revalidated.

## Current assessment

Killhub has a working sandbox-verification MVP. Existing live reports demonstrate webapp HTTP readiness, an in-guest screenshot, MCP filesystem tool discovery and a synthetic read, vulnerability findings, durable receipts, and recorded sandbox removal. A Flask run was honestly labeled `generated_demo` rather than original-application success.

The general autonomous Environment Agent remains incomplete. Discovery primarily uses heuristics and fixture rules, and repair retries largely repeat unchanged commands.

## Priorities

| Priority | Work | Completion condition |
|---|---|---|
| P1 | Failed-readiness finalization | Failure paths scan, attempt cleanup, persist the receipt, then become terminal |
| P1 | Advisory severity | Full advisory evidence determines severity; missing severity is explicit |
| P1 | Adaptive discovery and repair | Unfamiliar repositories receive evidence-based plans and bounded revisions |
| P2 | Executable profile support | Accepted fields are honored or explicitly rejected |
| P2 | Containment evidence | Claims demonstrate guest-process termination and identify unverified targets |
| Release validation | Reproducible checks and fresh live runs | Python 3.12 checks and real sandbox lifecycle scenarios are verified |

## 1. P1 — Finalize failed readiness before terminal status

References: [explore/verify.py](explore/verify.py), [explore/worker.py](explore/worker.py), [explore/finalize.py](explore/finalize.py), [explore/ledger/store.py](explore/ledger/store.py).

**Finding:** `verify_readiness` can mark a job `failed` before later pipeline stages finish. Those stages encounter terminal-write protection. A focused reproduction ended with `WriterFrozenError`, zero finalizer calls, no vulnerability report, no `destroyed_at`, and a sandbox generation still recorded as running. This reproduction used simulated sandbox commands; it establishes the control-flow defect, not a fresh live VM leak.

- [ ] Record failed readiness without making the job terminal immediately.
- [ ] Route readiness failure and unexpected pipeline exceptions through bounded finalization.
- [ ] Attempt best-effort SCA while the sandbox and dependency files are still available.
- [ ] Attempt sandbox destruction; record confirmed removal or `destroy_failed` honestly.
- [ ] Persist the complete receipt before publishing terminal status.
- [ ] Release admission capacity on every terminal path.
- [ ] Add a worker-level regression test covering verify failure through scan, receipt, and cleanup—not only isolated stage tests.

**Acceptance:** a deliberately broken application's readiness fails, its finalizer executes, its report or explicit scan failure is retained, and the final receipt records cleanup before the final SSE status. Ordinary terminal-write errors must not interrupt this path.

## 2. P1 — Resolve and score vulnerability severity correctly

References: [explore/vulnscan.py](explore/vulnscan.py), [explore/safety.py](explore/safety.py), [frontend/lib/findings.ts](frontend/lib/findings.ts).

**Finding:** OSV's batch endpoint returns vulnerability IDs and modification timestamps, not full advisory severity. The scanner treats absent severity as `medium`. Its later detail lookup enriches only a description. Separately, a critical CVSS vector was classified as `medium` by the current parser.

Source: [OSV querybatch contract](https://google.github.io/osv.dev/post-v1-querybatch/).

- [ ] Fetch and cache full records for matched advisory IDs within a bounded lookup budget.
- [ ] Parse supported CVSS vectors and authoritative severity fields correctly.
- [ ] Represent missing or unavailable severity as unknown rather than inventing `medium`.
- [ ] Preserve advisory IDs, aliases, provenance, and coverage limitations in the report.
- [ ] Ensure backend safety classifications and frontend risk displays use the corrected evidence.
- [ ] Test realistic ID-only batch responses, full advisory enrichment, critical/high vectors, and unavailable details.

**Acceptance:** a known high/critical advisory retains its correct severity through the finding, receipt, feed stamp, and detailed UI. Incomplete enrichment is visibly identified.

## 3. P1 — Complete adaptive discovery and repair

References: [PRODUCT.md](PRODUCT.md), [explore/discover.py](explore/discover.py), [explore/install.py](explore/install.py), [explore/verify.py](explore/verify.py), [explore/agent.py](explore/agent.py), [explore/prompts/](explore/prompts/).

**Finding:** discovery selects predefined profiles from heuristics and fixtures. Discovery prompts are loaded but do not drive planning. The generic webapp profile assumes npm commands and port 5000; unmatched repositories receive a Python directory server. Install and verify retries do not substantially diagnose errors and revise the plan.

- [ ] Connect discovery and repair reasoning to Vultr Inference through the trusted agent boundary.
- [ ] Infer runtimes, build commands, services, working directories, ports, and readiness from inspected repository evidence.
- [ ] Validate proposed profiles before allowing harness mutations.
- [ ] Feed actual install/launch/probe errors into bounded repair and persist accepted profile revisions.
- [ ] Keep inference budgets, job deadlines, and `MAX_REPAIR_ATTEMPTS` enforced.
- [ ] Preserve resolved-commit provenance and keep untrusted execution inside Plane 2.
- [ ] Keep generated demos distinct from original-application verification and retain original failures.
- [ ] Evaluate representative non-fixture repositories with different commands, ports, and service requirements.

**Acceptance:** an unfamiliar repository can receive a suitable plan, and a recoverable failure results in a justified profile change rather than repetition of the same failed command. Fixture success alone is insufficient evidence.

If this capability is intentionally deferred, explicitly narrow the product promise and supported scope in PRODUCT, README, and the public UI instead of describing it as complete.

## 4. P2 — Honor the executable profile contract

References: [DATABASE.md](DATABASE.md), [explore/schemas/environment_profile.v1.json](explore/schemas/environment_profile.v1.json), [explore/profile.py](explore/profile.py), [explore/install.py](explore/install.py), [explore/verify.py](explore/verify.py).

**Finding:** parts of the documented profile are accepted without corresponding execution. The installer does not provision `services[]`; command environment fields are ignored; process launch uses `nohup` without implementing declared restart supervision; TCP and command probes are filtered out of the webapp/demo verification path.

- [ ] Provision declared services and honor dependency ordering and service health checks.
- [ ] Apply permitted command environment settings consistently during install and launch.
- [ ] Implement declared process supervision and cleanup behavior.
- [ ] Implement supported HTTP, TCP, and command probes with explicit pass criteria.
- [ ] Reject unsupported fields or modes during validation until their execution is implemented.
- [ ] Add focused tests proving that accepted profile fields change execution behavior.

**Acceptance:** a schema-valid profile cannot silently depend on behavior the harness ignores. Unsupported profiles fail with a clear explanation before provision or launch.

## 5. P2 — Make containment claims match measured evidence

References: [explore/containment.py](explore/containment.py), [explore/harness.py](explore/harness.py), [frontend/components/ContainmentPanel.tsx](frontend/components/ContainmentPanel.tsx).

**Finding:** the timeout probe treats a local CLI/SSH timeout followed by a successful guest `echo alive` as evidence that the busy-loop was killed. That does not establish that the guest process stopped. Live reports also display `4/4 axes proven` alongside unverified host targets, so claim scope needs to remain explicit.

- [ ] Give the guest probe a tracked PID/process group and an enforced guest-side execution bound.
- [ ] Confirm that the busy-loop and relevant descendants terminated before reporting absorption.
- [ ] Keep host/guest liveness evidence separate from process-termination evidence.
- [ ] Clearly distinguish tested destinations, excluded destinations, and inconclusive results.
- [ ] Keep overall containment wording scoped to evidence actually collected.
- [ ] Add a negative test in which the client times out but the guest process remains alive; this must not count as proven absorption.

**Acceptance:** a reported absorbed loop has verified termination evidence. A client timeout alone cannot produce a positive containment verdict.

## 6. Release validation still required

These are verification tasks, not claims that each capability is broken.

- [ ] Recreate the local Python environment with the documented Python 3.12 runtime.
- [ ] Isolate tests from deployment `.env` files, cloud credentials, and ambient proxy settings.
- [ ] Run the complete frontend and Python quality gates in that clean environment.
- [ ] Exercise fresh real Microsandbox webapp, MCP, generated-demo, and natural readiness-failure runs.
- [ ] Exercise cancellation during create, install, verify, and finalization.
- [ ] Verify restart recovery and host-side expiry with the control-plane process stopped.
- [ ] Verify image replacement preserves the original expiry and never leaves two active job VMs.
- [ ] Verify configured admission limits and that finished/failed/cancelled jobs release capacity.
- [ ] Record the deployed commit, configuration, job IDs, receipts, and observed cleanup evidence for release sign-off.

### Checks recorded during the review

| Check | Result |
|---|---|
| Frontend lint, Knip, type checking, unit tests, production build | Passed |
| Python Ruff lint and format checks | Passed |
| Python tests with deployment settings isolated | 283 passed, 2 failed, 1 skipped |
| Remaining two Python failures | `tomllib` unavailable in the existing Python 3.9 environment; setup specifies Python 3.12 |
| Fresh real-VM lifecycle, cancel/restart/reaper scenarios | Not exercised during this review |

The initial unisolated Python run had additional environment-dependent failures. The isolated results above should not be presented as a fully passing Python 3.12 release gate.

## Suggested order

1. Fix failed-readiness finalization and advisory severity.
2. Align accepted profile fields with actual harness behavior.
3. Complete adaptive discovery/repair and tighten containment evidence.
4. Run clean quality gates and fresh live lifecycle validation before calling the original product goal complete.
