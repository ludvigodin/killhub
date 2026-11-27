"""Plane-1 pre-flight (D45) — hard-fail skips msb create."""

from __future__ import annotations

import io
import json
from typing import Any
from urllib.error import HTTPError

import fakeredis
import pytest
from fastapi.testclient import TestClient

from errors import HarnessError
from harness import EnvironmentPlan, MsbCli, create_environment
from jobs import get_ledger
from preflight import run_preflight
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
    # A rejected target never acquired a VM and cannot have a removal timestamp.
    assert snap["destroyed_at"] is None
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


@pytest.mark.parametrize("private", [False, True])
def test_preflight_finishes_before_job_publication(
    client: TestClient, auth_header, monkeypatch, private: bool
) -> None:
    _ = client, auth_header
    monkeypatch.setenv("PREFLIGHT_ENABLED", "true")
    from config import get_settings

    get_settings.cache_clear()

    from admission import reset_admission_store_for_tests
    from admission.valkey import ValkeyAdmissionStore

    # Exercise the reservation with a real Valkey admission store over fakeredis.
    fake = fakeredis.FakeRedis(decode_responses=True)
    store = ValkeyAdmissionStore(fake)
    reset_admission_store_for_tests()
    monkeypatch.setenv("ADMISSION_STORE", "valkey")
    monkeypatch.setenv("VALKEY_URL", "redis://localhost:6379")
    monkeypatch.setattr("admission.factory._connect_valkey", lambda _url: fake)

    def fake_urlopen(req: object, timeout: float = 0) -> _FakeResp:
        _ = timeout
        # Simulate a second ledger reader while the metadata request is in flight.
        assert get_ledger().list_jobs() == []
        assert store.gauges() == {"running": 0, "queued": 1}
        return _FakeResp(
            {
                "private": private,
                "archived": True,
                "disabled": False,
                "size": 10,
                "default_branch": "main",
                "visibility": "private" if private else "public",
            }
        )

    monkeypatch.setattr("preflight.urllib.request.urlopen", fake_urlopen)
    job = create_job("https://github.com/heroku/node-js-getting-started")
    ledger = get_ledger()
    events = ledger.list_events(job.job_id)
    if private:
        assert job.status == "failed"
        assert store.gauges() == {"running": 0, "queued": 0}
        assert job.sandbox_id is None
        assert ledger.try_claim_pending_job(job.job_id) is None
        assert ledger.list_sandbox_generations(job.job_id) == []
        receipt = ledger.get_receipt(job.job_id)
        assert receipt is not None
        assert receipt["lifecycle"]["sandbox_created"] is False
        assert any(e.payload.get("code") == "repo_private" for e in events)
    else:
        assert job.status == "pending"
        assert store.gauges() == {"running": 0, "queued": 1}
        assert any(e.payload.get("code") == "repo_archived" for e in events)
        claimed = ledger.try_claim_pending_job(job.job_id)
        assert claimed is not None and claimed.status == "analyzing"
    get_settings.cache_clear()


def test_gitlab_not_found_hard_fail(monkeypatch) -> None:
    monkeypatch.setenv("PREFLIGHT_ENABLED", "true")
    from config import get_settings

    get_settings.cache_clear()

    def fake_urlopen(req: object, timeout: float = 0) -> Any:
        _ = timeout
        raise HTTPError(
            url="https://gitlab.com/missing/project",
            code=404,
            msg="Not Found",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(b"{}"),
        )

    monkeypatch.setattr("preflight.urllib.request.urlopen", fake_urlopen)

    # build_opener().open also needs the same failure path
    class _Opener:
        def open(self, req: object, timeout: float = 0) -> Any:
            return fake_urlopen(req, timeout)

    monkeypatch.setattr(
        "preflight.urllib.request.build_opener",
        lambda *_a, **_k: _Opener(),
    )
    result = run_preflight("https://gitlab.com/missing/project")
    assert result.ok_to_bootstrap is False
    assert any(f.code == "repo_not_found" and f.hard for f in result.findings)
    get_settings.cache_clear()


def test_gitlab_unreachable_is_soft(monkeypatch) -> None:
    monkeypatch.setenv("PREFLIGHT_ENABLED", "true")
    from urllib.error import URLError

    from config import get_settings

    get_settings.cache_clear()

    class _Opener:
        def open(self, req: object, timeout: float = 0) -> Any:
            _ = req, timeout
            raise URLError("timed out")

    monkeypatch.setattr(
        "preflight.urllib.request.build_opener",
        lambda *_a, **_k: _Opener(),
    )
    result = run_preflight("https://gitlab.com/org/repo")
    assert result.ok_to_bootstrap is True
    assert any(f.code == "host_unreachable" and not f.hard for f in result.findings)
    get_settings.cache_clear()


def test_ledger_records_preflight_rejection_with_job(client, auth_header, monkeypatch) -> None:
    _ = client, auth_header
    monkeypatch.setenv("PREFLIGHT_ENABLED", "true")
    from config import get_settings
    from preflight import PreflightFinding, PreflightResult

    get_settings.cache_clear()
    ledger = get_ledger()
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
    # A rejected job and its receipt should already be terminal when first visible.
    job = ledger.create_job(
        "https://github.com/heroku/node-js-getting-started",
        env_ttl_seconds=600,
        preflight=result,
    )
    assert job.status == "failed"
    refreshed = ledger.get_job(job.job_id)
    assert refreshed is not None
    assert refreshed.status == "failed"
    snap = ledger.get_snapshot(job.job_id)
    assert snap is not None
    assert snap["receipt"] is not None
    get_settings.cache_clear()
