"""Pure evidence helpers for the acceptance suite (no network, unit-testable).

Everything here is deterministic given its inputs so ``test_evidence_helpers.py``
can prove the negative cases (failed SSH, retained VM, malformed inventory,
receipt after terminal, duplicated or missing SSE events) without a live host.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Sequence

TERMINAL = frozenset({"completed", "failed", "cancelled"})

# Remote command run over SSH. ``--format json`` is what explore/reaper.py uses on the host.
DEFAULT_INVENTORY_COMMAND = "/opt/killhub-msb/bin/killhub-msb list --format json"

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class HostEvidenceError(AssertionError):
    """Host evidence is unavailable, malformed, or shows a retained test VM."""

    def __init__(self, message: str, evidence: HostEvidence | None = None) -> None:
        super().__init__(message)
        self.evidence = evidence


# --- sandbox names ------------------------------------------------------------------


def compact_job_id(job_id: str) -> str:
    """Mirror ``harness.environment_name_for_job`` (strip to [A-Za-z0-9-])."""
    return re.sub(r"[^a-zA-Z0-9-]", "", job_id)


def job_vm_name(job_id: str) -> str:
    """Primary microVM name for a job (``kh-<compact id>``, 63 chars max)."""
    return f"kh-{compact_job_id(job_id)}"[:63]


def sibling_vm_prefix(job_id: str) -> str:
    """Containment sibling probe VM name (``kh-sib-<first 20 id chars>``)."""
    return f"kh-sib-{job_id.replace('-', '')[:20]}"


def expected_vm_names(job_id: str, snapshot: dict[str, Any] | None = None) -> set[str]:
    """Every exact VM name a job may have owned: base name, sibling probe, every generation."""
    names = {job_vm_name(job_id), sibling_vm_prefix(job_id)}
    snap = snapshot or {}
    if snap.get("sandbox_id"):
        names.add(str(snap["sandbox_id"]))
    env = snap.get("environment") or {}
    if env.get("environment_id"):
        names.add(str(env["environment_id"]))
    dossier = (snap.get("receipt") or {}).get("dossier") or {}
    for gen in dossier.get("sandbox_generations") or []:
        if isinstance(gen, dict) and gen.get("environment_id"):
            names.add(str(gen["environment_id"]))
    return names


def retained_vms(
    inventory: Iterable[str], job_ids: Iterable[str], snapshots: dict[str, Any]
) -> list[str]:
    """Inventory names that belong to any of ``job_ids`` (exact name or sibling/base prefix)."""
    exact: set[str] = set()
    prefixes: set[str] = set()
    for jid in job_ids:
        exact |= expected_vm_names(jid, snapshots.get(jid))
        prefixes.add(sibling_vm_prefix(jid))
        prefixes.add(job_vm_name(jid))
    leaked = []
    for name in sorted(set(inventory)):
        if name in exact or any(name.startswith(p) for p in prefixes):
            leaked.append(name)
    return leaked


# --- host inventory -----------------------------------------------------------------


def parse_inventory(stdout: str) -> set[str]:
    """Parse ``msb list --format json`` output; raise on anything not a valid inventory.

    An empty list (``[]``) is a valid, empty inventory. Empty stdout, prose, or rows
    without a string ``name`` are not.
    """
    text = (stdout or "").strip()
    if not text:
        raise HostEvidenceError("host inventory output is empty")
    try:
        rows = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HostEvidenceError(f"host inventory is not valid JSON: {exc}") from exc
    if isinstance(rows, dict):
        rows = rows.get("sandboxes") or rows.get("items")
    if not isinstance(rows, list):
        raise HostEvidenceError("host inventory JSON is not a list of sandboxes")
    names: set[str] = set()
    for row in rows:
        if not (isinstance(row, dict) and isinstance(row.get("name"), str) and row["name"].strip()):
            raise HostEvidenceError(f"host inventory row has no name: {str(row)[:80]}")
        names.add(row["name"])
    return names


@dataclass
class HostEvidence:
    """What was independently observed on the sandbox host."""

    host: str
    command: str
    returncode: int | None
    observed_at: str
    names: set[str] = field(default_factory=set)
    retained: list[str] = field(default_factory=list)
    error: str | None = None
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.error is None and not self.retained

    def to_json(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "command": self.command,
            "returncode": self.returncode,
            "observed_at": self.observed_at,
            "inventory_size": len(self.names),
            "inventory_names": sorted(self.names),
            "retained": self.retained,
            "error": self.error,
            "stderr": self.stderr[-500:],
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_host_inventory(
    host: str,
    *,
    command: str = DEFAULT_INVENTORY_COMMAND,
    runner: Runner | None = None,
    timeout: float = 60.0,
) -> HostEvidence:
    """Run the inventory over SSH. Never swallows failure: returncode and parse are checked."""
    run = runner or subprocess.run
    ev = HostEvidence(host=host, command=command, returncode=None, observed_at=_now())
    try:
        proc = run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host, command],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        ev.error = f"ssh did not run: {type(exc).__name__}: {exc}"
        return ev
    ev.returncode = proc.returncode
    ev.stderr = proc.stderr or ""
    if proc.returncode != 0:
        ev.error = f"ssh/inventory exited {proc.returncode}: {ev.stderr.strip()[-200:]}"
        return ev
    try:
        ev.names = parse_inventory(proc.stdout)
    except HostEvidenceError as exc:
        ev.error = str(exc)
    return ev


def verify_host_cleanup(
    host: str,
    job_ids: Sequence[str],
    snapshots: dict[str, Any],
    *,
    command: str = DEFAULT_INVENTORY_COMMAND,
    runner: Runner | None = None,
) -> HostEvidence:
    """Fetch inventory then fail unless it was observed AND no job VM remains.

    Covers every given job (scenario, cancel, boundary-cancel), every recorded
    sandbox generation, and containment sibling probe VMs (``kh-sib-*``).
    """
    if not job_ids:
        raise HostEvidenceError("no job ids to verify; cleanup evidence would be vacuous")
    ev = fetch_host_inventory(host, command=command, runner=runner)
    if ev.error is None:
        ev.retained = retained_vms(ev.names, job_ids, snapshots)
    if ev.error:
        raise HostEvidenceError(f"host cleanup evidence unavailable: {ev.error}", ev)
    if ev.retained:
        raise HostEvidenceError(f"test VMs still on host {host}: {ev.retained}", ev)
    return ev


# --- SSE ----------------------------------------------------------------------------


def parse_sse(text: str) -> list[dict[str, Any]]:
    """Parse an SSE body into ``[{id, type, data}]`` (keep-alive comments ignored)."""
    events: list[dict[str, Any]] = []
    for block in re.split(r"\n\n+", text.replace("\r\n", "\n")):
        eid = etype = None
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("id:"):
                eid = line[3:].strip()
            elif line.startswith("event:"):
                etype = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if eid is None and not data_lines:
            continue
        data: Any = None
        if data_lines:
            try:
                data = json.loads("\n".join(data_lines))
            except json.JSONDecodeError:
                data = None
        events.append({"id": eid, "type": etype, "data": data})
    return events


def event_ids(events: Sequence[dict[str, Any]]) -> list[int]:
    return [int(e["id"]) for e in events if e.get("id") is not None]


def check_resume(full_ids: Sequence[int], resumed_ids: Sequence[int], cursor: int) -> list[str]:
    """Problems when reconnecting after ``cursor``: duplicates, early ids, or missing ids."""
    problems: list[str] = []
    dupes = sorted({i for i in resumed_ids if list(resumed_ids).count(i) > 1})
    if dupes:
        problems.append(f"duplicate event ids after reconnect: {dupes[:10]}")
    early = [i for i in resumed_ids if i <= cursor]
    if early:
        problems.append(f"replayed ids at or before cursor {cursor}: {early[:10]}")
    if list(resumed_ids) != sorted(resumed_ids):
        problems.append("resumed event ids are not ascending")
    expected = [i for i in full_ids if i > cursor]
    missing = [i for i in expected if i not in set(resumed_ids)]
    if missing:
        problems.append(f"missing event ids after cursor {cursor}: {missing[:10]}")
    return problems


def check_stitched_stream(
    before: Sequence[int], after: Sequence[int], full: Sequence[int]
) -> list[str]:
    """First connection + resumed connection must equal one full replay, once each."""
    problems: list[str] = []
    stitched = list(before) + list(after)
    if len(stitched) != len(set(stitched)):
        dupes = sorted({i for i in stitched if stitched.count(i) > 1})
        problems.append(f"duplicate ids across reconnect: {dupes[:10]}")
    missing = [i for i in full if i not in set(stitched)]
    if missing:
        problems.append(f"events lost across reconnect: {missing[:10]}")
    return problems


# --- receipt before terminal ----------------------------------------------------------


def _ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def check_receipt_before_terminal(
    snapshot: dict[str, Any], events: Sequence[dict[str, Any]]
) -> list[str]:
    """Persisted-evidence ordering: receipt dossier time <= terminal status event time.

    ``events`` come from the SSE replay (``parse_sse``). The receipt is written
    before terminal status (D61), so the terminal status event cannot predate it.
    """
    problems: list[str] = []
    receipt = snapshot.get("receipt") or {}
    dossier = receipt.get("dossier") or {}
    if snapshot.get("status") in TERMINAL and not dossier:
        problems.append("terminal job has no receipt dossier")
        return problems
    terminal_events = [
        e
        for e in events
        if e.get("type") == "status"
        and isinstance(e.get("data"), dict)
        and e["data"].get("status") in TERMINAL
    ]
    if not terminal_events:
        problems.append("no terminal status event in persisted events")
        return problems
    first = terminal_events[0]
    receipt_at = _ts(dossier.get("at"))
    terminal_at = _ts(first["data"].get("timestamp"))
    if receipt_at is None:
        # The cancel finalizer's dossier carries no 'at'; ordering for those jobs is
        # proven by check_observed_transitions (no terminal poll without a receipt).
        if dossier.get("at") not in (None, ""):
            problems.append("receipt dossier 'at' is not a parseable timestamp")
    elif terminal_at is None:
        problems.append("terminal status event has no parseable timestamp")
    elif receipt_at > terminal_at:
        problems.append(
            f"receipt written at {receipt_at.isoformat()} after terminal status "
            f"{terminal_at.isoformat()}"
        )
    return problems


@dataclass(frozen=True)
class Observation:
    """One polled snapshot: what a client could see at one instant."""

    job_id: str
    status: str
    has_receipt: bool
    at: str = ""


def check_observed_transitions(observations: Sequence[Observation]) -> list[str]:
    """No poll may ever show a terminal status without a receipt (D61)."""
    return [
        f"{o.job_id}: observed {o.status} without a receipt at {o.at}"
        for o in observations
        if o.status in TERMINAL and not o.has_receipt
    ]


# --- sandbox generations (image replacement) -------------------------------------------


def check_generations(
    generations: Sequence[dict[str, Any]], *, destroyed: bool = True
) -> list[str]:
    """One live VM per job (D27/D36): older generations replaced, the last one destroyed."""
    gens = sorted(generations, key=lambda g: int(g.get("generation", 0)))
    if not gens:
        return ["no sandbox generations recorded"]
    problems: list[str] = []
    numbers = [int(g.get("generation", 0)) for g in gens]
    if numbers != list(range(1, len(gens) + 1)):
        problems.append(f"generation numbers are not contiguous from 1: {numbers}")
    for g in gens[:-1]:
        if g.get("state") not in {"replaced", "destroyed"}:
            problems.append(f"generation {g.get('generation')} left {g.get('state')} after replace")
    last = gens[-1]
    if destroyed and (last.get("state") != "destroyed" or not last.get("destroyed_at")):
        problems.append(
            f"last generation {last.get('generation')} not confirmed destroyed: "
            f"{last.get('state')} destroyed_at={last.get('destroyed_at')}"
        )
    return problems


def replaced_lifecycle_events(events: Sequence[dict[str, Any]]) -> list[int]:
    """Generations announced by ``lifecycle phase=replaced`` events."""
    out: list[int] = []
    for e in events:
        data = e.get("data")
        payload = (data or {}).get("payload") if isinstance(data, dict) else None
        if (
            e.get("type") == "lifecycle"
            and isinstance(payload, dict)
            and payload.get("phase") == "replaced"
        ):
            out.append(int(payload.get("generation", 0)))
    return out


# --- operator-gated evidence ------------------------------------------------------------

OPERATOR_SCENARIOS = ("restart_recovery", "host_expiry_cp_stopped")
_OPERATOR_FIELDS = ("operator", "observed_at", "result", "job_ids", "host_evidence")


def validate_operator_evidence(doc: Any) -> list[str]:
    """Problems with an operator evidence file (see acceptance/README.md)."""
    if not isinstance(doc, dict):
        return ["operator evidence must be a JSON object"]
    problems: list[str] = []
    for scenario in OPERATOR_SCENARIOS:
        entry = doc.get(scenario)
        if not isinstance(entry, dict):
            problems.append(f"{scenario}: missing")
            continue
        for key in _OPERATOR_FIELDS:
            if not entry.get(key):
                problems.append(f"{scenario}: missing {key}")
        if entry.get("result") not in (None, "", "pass"):
            problems.append(f"{scenario}: result is {entry.get('result')!r}, not 'pass'")
    return problems
