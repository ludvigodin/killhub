# How to review a Killhub security receipt

Hackbus #37 · Research and test plan · 27 November 2026

An operator should be able to answer three questions independently. Which commit ran? Which behavior did Killhub actually observe? Which dependency advisories apply to the versions it scanned? A job can answer one question and leave another open. This plan uses all 36 Markdown files at the [pinned OWASP MCP Security Testing Guide revision](https://github.com/OWASP/MCP-Security-Testing-Guide/tree/ffb9c6ac307adb553c95f47748130127f6b8f15f). The guide describes itself as community guidance.

## What production already demonstrates

| Observation | Evidence and interpretation |
|---|---|
| A pinned filesystem server answered over stdio and listed 16 tools. | The handshake proves discovery. Tool names alone give no evidence that calls respected a workspace boundary. [MCP receipt](https://killhub.pro/api/jobs/3f15fadd-0f57-419e-86ef-cb6c6fe14582) |
| An affected npm version and an affected Python version yielded the expected advisory IDs. The patched npm control yielded zero SCA findings with report status `ok`. | Match package, version, lockfile and advisory ID. Count only findings with `source=sca`. A partial scan with zero findings leaves coverage open. [npm affected](https://killhub.pro/api/jobs/f1d58cd2-2d4a-442d-96da-b2a9aa962316) · [npm patched](https://killhub.pro/api/jobs/24d35da8-172b-411c-962c-3395b251ee76) · [Python affected](https://killhub.pro/api/jobs/c1537f7b-e5a1-4cde-82c7-d483a49d924e) |
| The Heroku app served HTTP 200. The same job reported partial advisory coverage and incomplete containment. | Preserve each verdict. The host-internal and gateway checks lacked positive controls. The sibling check recorded an infrastructure error. [Webapp receipt](https://killhub.pro/api/jobs/480c2b63-76e4-4172-bbc3-c2498832bff2) |

Before the implementation of this plan, the optional assessment checked for a helper file on stdio and recorded a note for other transports. Its `ok` field alone supports no tool-behavior verdict. The readiness path separately records protocol evidence. [Assessment implementation](explore/vulnscan.py) · [Readiness implementation](explore/verify.py)

## Review sequence and acceptance criteria

1. **Identify the subject.** Start with the job snapshot at `GET /api/jobs/{id}`. Compare the profile source commit with `resolved_commit`, declared intent, transport and verification kind. For a generated demo, attribute runtime observations to the demo and dependency observations to the scanned checkout. An absent SHA leaves provenance unverified.
2. **Establish the baseline.** For a repository, compare declared services and working directory with launch and readiness events. For MCP, compare transport, initialization outcome and tool inventory against the pinned fixture manifest. For a webapp, record the probe target, accepted status and actual response. Record the source event or receipt field for every conclusion.
3. **Measure one ordinary behavior on an owned fixture.** For the pinned D35 check, predeclare one read-only tool and a synthetic input file with a known digest. After readiness, in the same offline guest, invoke only that fixture operation once. Compare the response digest, fixture file digests before and after, and observed completion time against the declared bound. Record tool name, schema revision, duration and outcome. Missing instrumentation yields an unknown result for the affected observation. For arbitrary submitted repos, retain discovery evidence and route unfamiliar operations for human review.
4. **Check dependency coverage.** Replay the three pinned controls above when changing the scanner. The two affected controls must return their expected IDs and the patched control must have complete coverage and zero matching advisories. Include an unavailable-advisory-service case in a local scanner test and require an explicit partial result. Compare IDs and package versions rather than total finding count.
5. **Reconcile the receipt.** Read recent durable events alongside the snapshot. Check the install and verify network phases, each containment dimension and its positive control, redacted canary outcomes, final cleanup confirmation and terminal event. A missing positive control leaves that dimension inconclusive. Preserve readiness if an optional assessment is skipped or fails. Every review claim should resolve to its finding or observation.
6. **Retest drift.** Compare like-for-like fixtures at the same source revision. Record the scanner date, runtime image and tool inventory when available. A changed schema or image calls for a new baseline. A new advisory against an unchanged lockfile can be a database update. Assign the discrepancy to the worker, scanner or control-plane reviewer according to the evidence.

For a demonstration, present six independently scored cases: MCP discovery, the synthetic read, original webapp readiness, affected npm, patched npm and affected Python. Label the synthetic read as planned until a receipt records it. A dynamic prompt may summarize observed schema changes or ask a reviewer to classify a capability. Runtime permissions and fixture operations come from the trusted profile.

## Guide coverage and review decisions

The chapter 3 index and its 19 category files span the following control questions. Each row identifies an observation an operator can use or the boundary that limits the conclusion. Section numbers refer to the [pinned chapter directory](https://github.com/OWASP/MCP-Security-Testing-Guide/tree/ffb9c6ac307adb553c95f47748130127f6b8f15f/03.%20MCP%20Threats%20and%20Attack%20Patterns).

| Section | Killhub review decision |
|---|---|
| 3.01 Inventory | Capture declared transport and returned tool names. Record whether resources and prompts were inventoried separately. |
| 3.02 Configuration | Compare declared and effective server entrypoint, working directory and image. Record how the effective values were observed. |
| 3.03 Identity | Mark user identity and token lifecycle outside the anonymous public demo. A stdio handshake says nothing about identity enforcement. |
| 3.04 Permissions | Review fixture scope and trusted harness grants. A tool's read-only annotation is a declaration requiring corroboration. |
| 3.05 Tools | Compare the pinned schema and the ordinary synthetic read with the manifest; flag drift for review. |
| 3.06 Resources | For an owned fixture with declared resources, compare its inventory and ordinary read digest to the expected fixture inventory. |
| 3.07 Instructions | Inspect provenance of repository text and server descriptions in the planner input. Only trusted managed configuration may grant actions. |
| 3.08 Context | Review the boundaries between two existing job records, including artifact ownership, job IDs and retained fields. Shared user-memory behavior is outside v1. |
| 3.09 Workflow | Trace a repair or cancellation through its attempt budget, finalizer and terminal event. Record missing transitions. |
| 3.10 Inputs | Check fixture schema and harmless type-validation cases in component tests. Record structured validation errors and whether a handler ran. |
| 3.11 Outputs | Review output size bounds, escaping and redaction on synthetic records through the public snapshot and rendered view. |
| 3.12 Detection | Trace one finding ID from event to report and cited review. Record gaps in event or receipt correlation. |
| 3.13 Supply chain | Pin the checkout, identify copied lockfiles, record advisory coverage and compare affected/patched controls. |
| 3.14 Governance | Identify who owns the runtime profile and the evidence review. Enterprise registry approval and tenant policy require a separate deployment context. |
| 3.15 Transport | Report the transport actually exercised. Stdio results provide no coverage for HTTP authentication or TLS configuration. |
| 3.16 Egress | Review existing phase-specific controls, positive controls and host liveness together. Record infrastructure errors separately. |
| 3.17 Secrets | Review synthetic canary outcomes and redacted event fields. Store only marker identifiers and outcomes in the assessment. |
| 3.18 Resilience | Compare existing admission, timeout and retry evidence with configured bounds. Distinguish a timeout from successful recovery. |
| 3.19 Privacy | Compare retained screenshots, logs and receipts against documented purpose and retention. Sandbox removal proves only guest cleanup. |

The other 17 Markdown files inform the review as follows.

| Source files at the pinned revision | Application |
|---|---|
| README, CONTRIBUTING, 01 Project Overview, 02 MCP Fundamentals | Establish scope, protocol roles and reproducible evidence requirements. |
| Chapter 3 index, about-docs-tests, how-to-run, taxonomy, test-case-format | Map categories to an owner, baseline, expected result, observed result and retest. Preserve upstream identifiers when citing individual cases. |
| 04 Secure MCP Development, 05 MCP Security Taxonomy | Review schema boundaries and assign a control category after evidence is available. |
| 06 Hacks, News, and Public Incidents | Use incident reports to prioritize review topics. Attribute a finding to a submitted repo only with job-specific evidence. |
| 07 Glossary, 08 Suggested Reading | Align host, client and server terminology. Record protocol and source versions. |
| 09 Security Review, 10 Safe Lab Fixtures, 11 Testing Tools | Structure the review record, select reproducible synthetic inputs and choose tooling available before the offline phase. |

## Implementation and verification

The runtime profile for the pinned filesystem fixture opts into `filesystem_read_v1`. The worker records the result in the vulnerability report, terminal receipt and operator receipt. The job view labels historical helper checks separately. Regression tests cover mismatched digests, changed files, elapsed-time overruns, incomplete measurements, an unmatched revision and missing offline evidence.

On 27 November 2026 the staged helper ran inside the offline guest for [job d7f513ef](https://killhub.pro/api/jobs/d7f513ef-078d-4be5-8aa1-8ba6e21bf919). The filesystem server listed 16 tools. Its synthetic read took 462 ms against a 15,000 ms bound. Expected and returned SHA-256 were both `7c945284a459aaccc08847e8f885d56deaac11a204be40b6efb7cdd31b3c69f8`; the fixture contents and directory inventory matched after the call. That job used the existing production worker. The measurement came from the staged runner. New workers built from this checkout will persist the measurement when the trusted fixture is eligible.
