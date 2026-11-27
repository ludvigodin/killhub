# Killhub acceptance suite (pre-demo final check)

Black-box tests against a **live** Killhub deployment. They submit real repos
through the public API, wait for the real sandboxes to finish, and check the
product promises in [PRODUCT.md](../PRODUCT.md) and [API.md](../API.md): plan →
sandboxed execution → verifiable output → destroy, with honest labels, cited
SCA, containment evidence, active install checks, secrecy and a receipt.

These are not the unit tests (`explore/tests`). They are slow (≈15–30 min),
create real microVMs, and need network access to the deployment.

## Run

Use the Python 3.12 venv from [SETUP.md](../SETUP.md) (`explore/.venv`, built with `python3.12`).

```sh
# unit tests for the evidence helpers (no deployment, no SSH, seconds)
explore/.venv/bin/python -m pytest acceptance/test_evidence_helpers.py

# everything, against https://killhub.pro, plus the host cleanup check
KILLHUB_SSH_HOST=killhub-vx1 explore/.venv/bin/python -m pytest acceptance

# RELEASE validation: missing evidence fails instead of skipping
KILLHUB_RELEASE=1 KILLHUB_SSH_HOST=killhub-vx1 \
  KILLHUB_OPERATOR_EVIDENCE=operator-evidence.json \
  explore/.venv/bin/python -m pytest acceptance

# fast edge/contract checks only (no sandboxes, < 1 min)
explore/.venv/bin/python -m pytest acceptance -m "not slow"

# another deployment
KILLHUB_BASE_URL=http://127.0.0.1:3000 explore/.venv/bin/python -m pytest acceptance
```

| Variable | Default | Meaning |
|---|---|---|
| `KILLHUB_BASE_URL` | `https://killhub.pro` | Deployment under test |
| `KILLHUB_JOB_TIMEOUT` | `2400` | Seconds to wait for all scenario jobs |
| `KILLHUB_SSH_HOST` | unset | SSH alias of the sandbox host; enables the independent host cleanup check |
| `KILLHUB_INVENTORY_COMMAND` | `/opt/killhub-msb/bin/killhub-msb list --format json` | Remote inventory command (must print the JSON list `msb list --format json` prints) |
| `KILLHUB_RELEASE` | unset | `1` = release validation (see below) |
| `KILLHUB_DEPLOYED_COMMIT` | unset | Deployed commit SHA to record; otherwise read from `/health` (`commit`, `git_sha`, `version`) or from `git -C $KILLHUB_DEPLOY_DIR rev-parse HEAD` over `KILLHUB_SSH_HOST` |
| `KILLHUB_DEPLOY_DIR` | unset | Checkout directory on the host (for the commit lookup above) |
| `KILLHUB_OPERATOR_EVIDENCE` | unset | JSON file with the operator-gated scenarios (see below) |
| `KILLHUB_ARTIFACT_DIR` | `acceptance/artifacts/<UTC timestamp>` | Where the evidence bundle is written (git-ignored) |
| `KILLHUB_REUSE_JOBS` | unset | JSON `{"scenario": "<job id>"}` to re-check finished jobs |

The suite uses `httpx` with the ambient `HTTP(S)_PROXY` / `ALL_PROXY` settings on
purpose (the deployment may only be reachable through one). It does **not**
scrub them, unlike `explore/tests`. A `socks5://` proxy needs `pip install socksio`
in the venv you run it from.

## Release validation vs developer runs

A developer run that cannot collect some evidence **skips** that check. That is
fine for iterating, but it is **not** release evidence. With `KILLHUB_RELEASE=1`
each of these **fails** instead of skipping, and `results.json` says why:

- no `KILLHUB_SSH_HOST`, a failed SSH run (non-zero exit, timeout, no `ssh`),
  empty or non-JSON inventory, or any test VM still on the host;
- no operator evidence file (restart recovery, host expiry with the CP stopped);
- no scenario that replaced its sandbox image (replacement unproven);
- a cancel boundary the job outran (create, install, verify or finalize);
- deployed commit unknown (recorded as a gap in `release_validation.reasons`).

Tests carrying release evidence are marked `@pytest.mark.release`. The final
verdict is `release_validation.valid` in `results.json`: true only for a
`KILLHUB_RELEASE=1` run with no failures, no skips and complete host evidence.

## What it proves

**Edge / contract** (`test_edge.py`): home page and `/health`, HSTS, invalid
URLs rejected with `400 invalid_url` (non-HTTPS, non-allowlisted host,
credentials, private IPs, `file://`), unknown job `404`, job-list shape, the
token-guarded internal API never answers through the public edge, no
control-plane secret names with values in snapshots.

**Golden scenarios** (`test_scenarios.py`), all submitted at once (concurrency):

| Scenario | Repo | Must end as |
|---|---|---|
| `webapp` | heroku/nodejs-getting-started | `completed`, `original_application`, HTTP readiness |
| `node_mcp_filesystem` | modelcontextprotocol/servers | `completed`, `original_application`, MCP handshake, no poisoning/exfil |
| `python_mcp_vultr` | vultr/vultr-mcp | `completed`, `original_application`, ≥50 tools, `uv.lock` scanned, no false positives |
| `setup_failed` | octocat/Hello-World | `failed`, `setup_failed` (never labelled as working) |
| `sca_npm_affected` | mokafari/killhub-sca-npm-affected-20261127 | `completed`, `minimist` advisory |
| `sca_npm_control` | mokafari/killhub-sca-npm-control-20261127 | `completed`, no advisories |
| `sca_python_affected` | mokafari/killhub-sca-python-affected-20261127 | `completed`, `PyYAML` advisory |
| `leaky_install` | mokafari/killhub-leaky-install-20261127 | `failed` hard-fail `canary_exfiltration_attempt`, `canary_exfiltration` (critical, redacted) + `persistence_write` |

Plus: vulnerability summaries cite only real finding IDs.

**Invariants on every job** (`test_invariants.py`): receipt with dossier and
receipt-before-terminal ordering (persisted receipt time <= terminal status
event, plus no polled snapshot ever shows a terminal status without a receipt,
D61); sandbox removal confirmed (`cleanup.status=destroyed`, `destroyed_at`
before `expires_at`); source pinned to a full commit SHA; containment matrix
(timeout, host, sibling, liveness) + control-plane and offline egress denials
for every job that ran; vuln report with id/severity/source on each finding;
no canary key or secret values in the snapshot or event stream; poll and SSE
agree on the terminal status; SSE resumes strictly after `event_cursor`; SSE
reconnect from a **mid-run** cursor (live job, connection dropped after three
events, resumed with `Last-Event-ID`) loses and duplicates nothing versus the
final replay; resume from a mid cursor of every finished job returns exactly
the later events, once each, for both `?after=` and `Last-Event-ID`; image
replacement keeps one VM per job (older generations `replaced`, last
`destroyed`, `lifecycle replaced` events match); admission capacity is released
(a new create is admitted once all earlier jobs are terminal).

**Host cleanup** (`test_no_sandboxes_left_running_on_host`, runs last, marked
`release` + `host_cleanup`): SSH must exit 0 and the inventory must be valid
JSON (`[]` is valid; empty output, prose or nameless rows are not). The check
covers **every registered job**, not only the scenarios: cancel and
cancel-boundary jobs, the SSE reconnect job and the admission probe, plus, per
job, the `kh-<job>` VM, **every sandbox generation** `environment_id`, and the
containment probe VMs `kh-sib-*` (matched by exact name or prefix). A failed
SSH run, garbage inventory or a retained VM fails the check; the logic is in
`evidence.py` and its negative cases are unit-tested in
`test_evidence_helpers.py` (failed SSH with clean-looking stdout, timeout,
malformed inventory, retained job, sibling, prior-generation and cancel VMs,
no job ids).

**Cancel** (`test_cancel.py`): `DELETE` mid-run, and at the `create`
(`provisioning`), `install` (`installing`), `verify` (`verifying`) and
`finalize` (`finalizing`) boundaries: each ends `cancelled`, with
`cancel_requested_at`, a receipt written before the terminal status, sandbox
destroyed and generations closed out, and an idempotent second `DELETE`. The
boundary is hit by polling once per second and cancelling the instant the
status appears; a job that outruns the poll cannot prove that boundary (skip in
a developer run, failure under `KILLHUB_RELEASE=1`).

## Operator-gated scenarios

Two guarantees cannot be exercised through the public API because they need
the control plane or host to be disturbed. They are **not automated**; for
release validation an operator performs them and records the result.

1. **Restart recovery (D82).** Start a job, wait until it is `installing`,
   restart the explore service on the control plane (`systemctl restart
   killhub-explore` or your unit name). Expect the job to end terminal
   (`failed`, with a receipt and confirmed destroy), the VM gone from
   `msb list --format json` on the host, and a new create to be admitted
   (admission slot released).
2. **Host expiry with the control plane stopped (D41).** Start a job, stop the
   explore service, wait past the job's `expires_at`, and confirm the host
   reaper (`python -m reaper --host`) removed the VM with `msb list` while the
   control plane stayed down. Start explore again and confirm the ledger
   reaches a terminal state with confirmed destroy.

Record each run in one JSON file and pass it as `KILLHUB_OPERATOR_EVIDENCE`:

```json
{
  "restart_recovery": {
    "operator": "name",
    "observed_at": "2026-11-27T20:00:00Z",
    "result": "pass",
    "job_ids": ["<job id>"],
    "host_evidence": "ssh killhub-vx1 'killhub-msb list --format json' -> no kh-<job id>",
    "notes": "free text"
  },
  "host_expiry_cp_stopped": { "operator": "...", "observed_at": "...", "result": "pass",
                              "job_ids": ["..."], "host_evidence": "..." }
}
```

The file is validated (`validate_operator_evidence`: every scenario present,
all fields non-empty, `result` is `pass`) and copied into the artifact bundle.

## Artifact retention

Every run that creates jobs (and every `KILLHUB_RELEASE=1` run) writes a bundle
to `KILLHUB_ARTIFACT_DIR` (default `acceptance/artifacts/<UTC timestamp>/`,
git-ignored). **Archive it with the release record**; do not rely on the working
tree.

| File | Contents |
|---|---|
| `results.json` | `base_url`, `deployed_commit` + `deployed_commit_source`, `local_checkout_commit` (labelled local, never presented as deployed), every job (label, job id, status, resolved commit, cleanup, generations, receipt present), `host_cleanup` (host, command, return code, observation time, inventory names, retained VMs, error), every polled status observation, operator evidence, per-test outcomes, `release_validation` (`valid`, `reasons`) |
| `receipts/<job id>.json` | The full receipt of each job |

## Fixture repos

`mokafari/killhub-sca-*` and `mokafari/killhub-leaky-install-20261127` are
harmless test fixtures owned by the team. The leaky one only acts inside a
Killhub sandbox: it sends the planted *fake* canary to a never-resolving
`.invalid` DNS name and appends a comment to `~/.bashrc`.
