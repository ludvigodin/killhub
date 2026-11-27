# Killhub — Product fixes and completion checklist

Review date: 2026-11-27. Rechecked at local commit `85edddb`.

Scope: `/Users/ludvigodinhestvik/git/killhub`, automated checks, and existing public reports on [killhub.pro](https://killhub.pro). Checked items below have supporting code or test evidence. This investigation did not submit new sandbox jobs or independently inspect the sandbox host. Existing public receipts are deployment evidence, not a fresh host audit.

## Current assessment

Killhub has a working sandbox-verification MVP, with meaningful improvements since the earlier review. Failed readiness now routes to finalization, advisory records are enriched before severity is displayed, and install activity / MCP tool-description checks are retained in reports. Existing live reports demonstrate readiness, screenshots, findings, durable receipts, and recorded removal.

The general autonomous Environment Agent remains incomplete. Discovery primarily uses heuristics and fixture rules, and repair retries largely repeat unchanged commands. Cleanup on unexpected worker exceptions, executable profile support, and containment proof also remain incomplete. New reporting and acceptance-test gaps are described below.

## Priorities

| Priority | Work | Completion condition |
|---|---|---|
| P1 | Unexpected-exception finalization | Unexpected stage errors also scan, attempt cleanup, persist the receipt, and release capacity |
| P1 | Adaptive discovery and repair | Unfamiliar repositories receive evidence-based plans and bounded revisions |
| P2 | Executable profile support | Accepted fields are honored or explicitly rejected |
| P2 | Containment evidence | Claims demonstrate guest-process termination and identify unverified targets |
| P2 | Advisory alias normalization | One vulnerability is not counted twice under different advisory IDs |
| P2 | Canary outcome classification | An attempted transmission is distinct from a confirmed isolation bypass |
| P2 | Acceptance-suite reliability | Failed host inventory cannot pass the no-leaks check |
| Release validation | Reproducible checks and fresh live runs | Python 3.12 checks and real sandbox lifecycle scenarios are verified |

## 1. P1 — Finalize failed readiness before terminal status

References: [explore/verify.py](explore/verify.py), [explore/worker.py](explore/worker.py), [explore/finalize.py](explore/finalize.py), [explore/ledger/store.py](explore/ledger/store.py).

**Progress:** the original premature-terminal defect is fixed in code. `verify_readiness` leaves failed readiness in `verifying`; the worker skips post-readiness stages and calls finalization. `test_verify_fail_skips_to_finalize_scan_and_destroy` passes and checks scan, receipt, failed status, and recorded destruction.

**Remaining finding:** `worker._run_claimed_job` catches a fixed list of domain exceptions. An unexpected `RuntimeError` escapes to the outer worker loop, which only logs it. A controlled local reproduction with a temporary ledger and simulated running generation left the job `installing`, called the finalizer zero times, and wrote no receipt or `destroyed_at`. The reaper remains a fallback; prompt finalization is missing. This establishes a control-flow defect, not a fresh live VM leak.

- [x] Record failed readiness without making the job terminal immediately.
- [x] Route ordinary readiness failure through finalization, skipping screenshot and containment stages.
- [x] Add a pipeline regression test covering verify failure through scan, receipt, and cleanup.
- [x] Add defensive reclaim for an already-terminal job with a recorded live sandbox.
- [ ] Route unexpected pipeline exceptions through bounded finalization without interfering with cancellation ownership.
- [ ] Ensure best-effort SCA, destruction evidence, receipt, and admission release on every failure path.
- [ ] Add a worker-boundary regression test for an unexpected exception after sandbox creation.

**Acceptance:** a deliberately broken application's readiness fails, its finalizer executes, its report or explicit scan failure is retained, and the final receipt records cleanup before the final SSE status. Ordinary terminal-write errors must not interrupt this path.

## 2. P1 — Resolve and score vulnerability severity correctly

References: [explore/vulnscan.py](explore/vulnscan.py), [explore/safety.py](explore/safety.py), [frontend/lib/findings.ts](frontend/lib/findings.ts).

**Progress:** the earlier ID-only batch / invented-medium defect is fixed for supported severity formats. The scanner fetches bounded full advisory records, caches lookups within the scan, parses CVSS v3 vectors, retains aliases, and uses `unknown` when severity is unavailable. Regression tests pass. The existing live Vultr MCP report displays distinct critical/high/medium/low bands.

Source: [OSV querybatch contract](https://google.github.io/osv.dev/post-v1-querybatch/).

- [x] Fetch and cache full records for matched advisory IDs within a bounded lookup budget.
- [x] Parse supported CVSS vectors and authoritative severity fields.
- [x] Represent missing or unavailable severity as unknown rather than inventing `medium`.
- [x] Preserve advisory IDs, aliases, lockfile provenance, and incomplete-lookup status.
- [x] Use unknown severity in backend safety classifications and frontend risk displays.
- [x] Test realistic ID-only batch responses, full advisory enrichment, critical/high vectors, and unavailable details.

**New finding:** aliased records are still separate findings. In existing live job [`13242cd9-2665-460b-893a-91fe2119baf8`](https://killhub.pro/jobs/13242cd9-2665-460b-893a-91fe2119baf8), `GHSA-7vr2-2fgp-9w7p` and `PYSEC-2026-4355` both describe the same `authlib@1.7.2` issue and share `CVE-2026-114615`. One is displayed as high and the other critical. The scan creates a new finding for every OSV result and never groups by aliases, inflating counts and showing conflicting severity for one vulnerability.

- [ ] Group records for the same ecosystem/package/version by overlapping advisory IDs and aliases.
- [ ] Retain all source records, lockfile locations, and severity provenance under the grouped finding.
- [ ] Define an explicit policy for conflicting source severities and expose the disagreement.
- [ ] Test reciprocal aliases and the same package appearing in multiple lockfiles.

**Acceptance:** a known high/critical advisory retains its supported severity through the report and UI; incomplete enrichment is visible. Multiple IDs for the same affected package vulnerability contribute one grouped issue to severity counts, with source disagreements explained.

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

**Finding:** the timeout probe still treats a local CLI/SSH timeout followed by a successful guest `echo alive` as evidence that the busy-loop was killed. That does not establish that the guest process stopped. The existing live Vultr MCP report still displays `4/4 axes proven`, `CLAIM · PROVEN`, and a killed-loop claim alongside unverified `host_internal` / `host_gateway_ip` targets. The exclusions are visible, but the overall claim still overstates the measured evidence.

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
- [x] Isolate unit tests from deployment `.env` files and deployment object storage settings.
- [ ] Make tests independent of ambient proxy settings, or explicitly install/document the required proxy support.
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
| Python tests with deployment settings isolated, inherited proxy unchanged | 306 passed, 2 failed, 1 skipped |
| Remaining two failures in that invocation | HTTPX operator-MCP tests encounter inherited SOCKS proxy settings without `socksio` |
| Python tests with proxy environment variables removed for the process | 308 passed, 1 skipped |
| Python runtime used | 3.9.6; the documented Python 3.12 release gate remains unverified |
| Unexpected worker exception reproduction | Finalizer not called; job remained installing; no receipt or destruction timestamp |
| Host cleanup acceptance negative reproduction | Test passed despite a simulated SSH exit code of 255 |
| Existing live reports inspected | Vultr MCP readiness / severity / tool review; leaky-install canary / persistence findings / cleanup receipt |
| Fresh real-VM lifecycle, cancel/restart/reaper scenarios | No new jobs submitted; host inventory not independently checked |

The earlier `tomllib` compatibility failure is resolved. Passing local tests after removing proxy settings should not be presented as a fully passing Python 3.12 release gate or as live lifecycle acceptance.

## 7. P2 — Make the acceptance suite fail when evidence collection fails

References: [acceptance/test_invariants.py](acceptance/test_invariants.py), [acceptance/test_cancel.py](acceptance/test_cancel.py), [acceptance/conftest.py](acceptance/conftest.py).

**Finding:** `test_no_sandboxes_left_running_on_host` reads only SSH stdout and ignores its return code. SSH authentication failure or a failed inventory command can return empty stdout and pass the no-leaks assertion. A local negative reproduction returned exit code 255 / empty stdout and the test passed. Without `KILLHUB_SSH_HOST`, the test skips entirely.

The check also only tracks the eight scenario job IDs, excluding the separate cancellation test. `test_receipt_written_before_terminal` examines a final snapshot rather than proving event ordering. `test_stream_resumes_after_cursor` resumes after the final cursor, so an empty event list satisfies its assertion without exercising a mid-run reconnect.

- [ ] Require successful SSH execution and validate the inventory output before asserting no leaks.
- [ ] Treat unavailable host evidence as failed/incomplete release validation, rather than successful cleanup proof.
- [ ] Track cancellation jobs, all sandbox generations, and containment probe VMs in host cleanup verification.
- [ ] Verify receipt / terminal ordering from persisted events or an observed transition.
- [ ] Exercise SSE reconnection from a cursor with later events and check for loss or duplication.
- [ ] Exercise cancellation at explicit create/install/verify/finalize boundaries, plus restart and host-expiry recovery.
- [ ] Record executed acceptance results, deployed commit, job IDs, and host cleanup evidence.

**Acceptance:** a simulated failed SSH command fails the cleanup test; an intentionally retained test VM is detected. A green release result cannot silently mean that critical host checks were skipped or never observed.

## 8. P2 — Separate malicious attempts from confirmed containment bypasses

References: [explore/activity.py](explore/activity.py), [explore/finalize.py](explore/finalize.py), [frontend/lib/findings.ts](frontend/lib/findings.ts).

**Finding:** any canary match in an outgoing network attempt is assigned `classification=policy_bypass`. Finalization consumes that classification as a bypass reason, and the UI says a sandbox isolation check recorded a policy bypass. The trace match does not establish delivery or successful boundary crossing.

Existing live job [`6f79f695-3a86-42a4-8fa0-b3573bbd5236`](https://killhub.pro/jobs/6f79f695-3a86-42a4-8fa0-b3573bbd5236) demonstrates the mismatch: the finding accurately says an outgoing attempt matched a test secret, while the outcome says isolation was bypassed and the containment matrix simultaneously says proven. This does not establish that exfiltration succeeded or that isolation actually failed.

- [ ] Record attempted, blocked, successful, and unknown transmission outcomes separately where evidence supports them.
- [ ] Give dangerous repository behavior a dedicated gate reason; retain a hard-fail policy for the attempt if desired.
- [ ] Reserve confirmed isolation-bypass wording for evidence that the configured boundary was crossed.
- [ ] Keep the finding, gate reasons, security summary, and containment panel consistent about what was observed.
- [ ] Test blocked/failed sends containing canaries and confirmed delivery as different cases.

**Acceptance:** a canary-bearing attempt can remain a critical security finding and fail the job without being presented as proven sandbox escape or confirmed exfiltration.

## Suggested order

1. Close unexpected-exception finalization and acceptance-test false passes.
2. Align accepted profile fields with actual harness behavior.
3. Tighten containment proof, canary classifications, and advisory grouping.
4. Complete adaptive discovery/repair, or narrow the product promise explicitly.
5. Run Python 3.12 quality gates and fresh live lifecycle validation before calling the original product goal complete.
