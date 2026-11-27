# Killhub acceptance suite (pre-demo final check)

Black-box tests against a **live** Killhub deployment. They submit real repos
through the public API, wait for the real sandboxes to finish, and check the
product promises in [PRODUCT.md](../PRODUCT.md) and [API.md](../API.md): plan →
sandboxed execution → verifiable output → destroy, with honest labels, cited
SCA, containment evidence, active install checks, secrecy and a receipt.

These are not the unit tests (`explore/tests`). They are slow (≈15–30 min),
create real microVMs, and need network access to the deployment.

## Run

```sh
# everything, against https://killhub.pro, plus the host leak check
KILLHUB_SSH_HOST=killhub-vx1 explore/.venv/bin/python -m pytest acceptance

# fast edge/contract checks only (no sandboxes, < 1 min)
explore/.venv/bin/python -m pytest acceptance -m "not slow"

# another deployment
KILLHUB_BASE_URL=http://127.0.0.1:3000 explore/.venv/bin/python -m pytest acceptance
```

| Variable | Default | Meaning |
|---|---|---|
| `KILLHUB_BASE_URL` | `https://killhub.pro` | Deployment under test |
| `KILLHUB_JOB_TIMEOUT` | `2400` | Seconds to wait for all scenario jobs |
| `KILLHUB_SSH_HOST` | unset | SSH alias of the sandbox host; enables the "no leaked sandboxes" check |

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
| `leaky_install` | mokafari/killhub-leaky-install-20261127 | `failed` hard-fail `policy_bypass`, `canary_exfiltration` (critical, redacted) + `persistence_write` |

Plus: vulnerability summaries cite only real finding IDs.

**Invariants on every job** (`test_invariants.py`): receipt with dossier;
sandbox removal confirmed (`cleanup.status=destroyed`, `destroyed_at` before
`expires_at`); source pinned to a full commit SHA; containment matrix
(timeout, host, sibling, liveness) + control-plane and offline egress denials
for every job that ran; vuln report with id/severity/source on each finding;
no canary key or secret values in the snapshot or event stream; poll and SSE
agree on the terminal status; SSE resumes strictly after `event_cursor`; no
scenario sandbox left running on the host.

**Cancel** (`test_cancel.py`): `DELETE` mid-run → `cancelled`, receipt
written, sandbox destroyed, second `DELETE` idempotent.

## Fixture repos

`mokafari/killhub-sca-*` and `mokafari/killhub-leaky-install-20261127` are
harmless test fixtures owned by the team. The leaky one only acts inside a
Killhub sandbox: it sends the planted *fake* canary to a never-resolving
`.invalid` DNS name and appends a comment to `~/.bashrc`.
