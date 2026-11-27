"""Plane-1 pre-flight (D45) — hard-fail skips msb create."""

from __future__ import annotations

import io
import json
from typing import Any
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

from errors import HarnessError
from harness import EnvironmentPlan, MsbCli, create_environment
from jobs import get_ledger
from preflight import apply_preflight_to_job, run_preflight
from service import create_job


class _FakeResp:
    def __init__(self, payload: dict[str, Any], code: int = 200) -> None:
        self._payload = payload
        self.status = code

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_deny_list_hard_fail_no_msb(client: TestClient, auth_header, monkeypatch) -> None:
    monkeypatch.setenv("PREFLIGHT_ENABLED", "true")
    monkeypatch.setenv("PREFLIGHT_DENY_REPOS", "evil/malware,badorg/*")
    from config import get_settings

    get_settings.cache_clear()

    # Avoid live GitHub — deny list alone is enough for hard-fail.
    def boom(*args: object, **kwargs: object) -> Any:
        raise AssertionError("GitHub should not be required for deny-list hit")

    monkeypatch.setattr("preflight.urllib.request.urlopen", boom)

    res = client.post(
        "/internal/jobs",
        headers=auth_header,
        json={"github_url": "https://github.com/evil/malware"},
    )
    assert res.status_code == 201
    job_id = res.json()["job_id"]
    snap = client.get(f"/internal/jobs/{job_id}", headers=auth_header).json()
    assert snap["status"] == "failed"
    assert snap["destroyed_at"] is not None
    assert snap["sandbox_id"] is None

    events = get_ledger().list_events(job_id)
    assert any(e.type == "log" and e.payload.get("kind") == "preflight" for e in events)
    assert any(
        e.type == "finding"
        and e.payload.get("source") == "preflight"
        and e.payload.get("hard") is True
        for e in events
    )

    # Guard: create_environment must refuse.
    cfg = get_settings()
    cli = MsbCli(cfg, runner=lambda *a, **k: (_ for _ in ()).throw(AssertionError("msb")))
    with pytest.raises(HarnessError) as err:
        create_environment(
            job_id,
            EnvironmentPlan(
                image="debian",
                cpus=1,
                memory="512M",
                net_profiles=("public",),
                net_rules=("deny@host",),
            ),
            settings=cfg,
            cli=cli,
        )
    assert err.value.code == "preflight_blocked"
    get_settings.cache_clear()


def test_clean_repo_proceeds(monkeypatch) -> None:
    monkeypatch.setenv("PREFLIGHT_ENABLED", "true")
    monkeypatch.setenv("PREFLIGHT_DENY_REPOS", "")
    from config import get_settings

    get_settings.cache_clear()

    def fake_urlopen(req: object, timeout: float = 0) -> _FakeResp:
        _ = timeout
        return _FakeResp(
            {
                "private": False,
                "archived": False,
                "disabled": False,
                "fork": False,
                "size": 100,
                "default_branch": "main",
                "visibility": "public",
            }
        )

    monkeypatch.setattr("preflight.urllib.request.urlopen", fake_urlopen)
    result = run_preflight("https://github.com/heroku/node-js-getting-started")
    assert result.ok_to_bootstrap is True
    assert result.hard_findings == []
    get_settings.cache_clear()


def test_not_found_hard_fail(monkeypatch) -> None:
    monkeypatch.setenv("PREFLIGHT_ENABLED", "true")
    from config import get_settings

    get_settings.cache_clear()

    def fake_urlopen(req: object, timeout: float = 0) -> Any:
        _ = timeout
        raise HTTPError(
            url="https://api.github.com/repos/no/such",
            code=404,
            msg="Not Found",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(b"{}"),
        )

    monkeypatch.setattr("preflight.urllib.request.urlopen", fake_urlopen)
    result = run_preflight("https://github.com/no/such")
    assert result.ok_to_bootstrap is False
    assert any(f.code == "repo_not_found" and f.hard for f in result.findings)
    get_settings.cache_clear()


def test_archived_is_soft(client: TestClient, auth_header, monkeypatch) -> None:
    _ = client, auth_header
    monkeypatch.setenv("PREFLIGHT_ENABLED", "true")
    from config import get_settings

    get_settings.cache_clear()

    def fake_urlopen(req: object, timeout: float = 0) -> _FakeResp:
        _ = timeout
        return _FakeResp(
            {
                "private": False,
                "archived": True,
                "disabled": False,
                "size": 10,
                "default_branch": "main",
                "visibility": "public",
            }
        )

    monkeypatch.setattr("preflight.urllib.request.urlopen", fake_urlopen)
    result = run_preflight("https://github.com/heroku/node-js-getting-started")
    assert result.ok_to_bootstrap is True
    assert any(f.code == "repo_archived" and not f.hard for f in result.findings)

    # Soft findings still emit on a real job (isolated ledger via client fixture).
    job = create_job("https://github.com/heroku/node-js-getting-started")
    assert job.status == "pending"
    events = get_ledger().list_events(job.job_id)
    assert any(e.type == "finding" and e.payload.get("code") == "repo_archived" for e in events)
    get_settings.cache_clear()


def test_apply_hard_fail_marks_terminal(client, auth_header, monkeypatch) -> None:
    _ = client, auth_header
    monkeypatch.setenv("PREFLIGHT_ENABLED", "true")
    from config import get_settings
    from preflight import PreflightFinding, PreflightResult

    get_settings.cache_clear()
    ledger = get_ledger()
    job = ledger.create_job(
        "https://github.com/heroku/node-js-getting-started",
        env_ttl_seconds=600,
    )
    result = PreflightResult(
        ok_to_bootstrap=False,
        findings=[
            PreflightFinding(
                code="deny_list",
                message="blocked",
                severity="critical",
                hard=True,
            )
        ],
    )
    apply_preflight_to_job(job.job_id, result)
    refreshed = ledger.get_job(job.job_id)
    assert refreshed is not None
    assert refreshed.status == "failed"
    snap = ledger.get_snapshot(job.job_id)
    assert snap is not None
    assert snap["receipt"] is not None
    get_settings.cache_clear()
