"""public_screenshot_url prefers CDN when s3 + CDN base (D76)."""

from __future__ import annotations

from pathlib import Path

import pytest

from screenshots import public_screenshot_url


@pytest.fixture(autouse=True)
def _clear_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OBJECT_STORAGE_CDN_BASE_URL", raising=False)
    from config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_public_url_api_fallback() -> None:
    assert public_screenshot_url("job-1", "shot-a") == "/api/jobs/job-1/screenshots/shot-a"
    assert (
        public_screenshot_url(
            "job-1",
            "shot-a",
            storage_path="./storage/screenshots/job-1/shot-a.png",
        )
        == "/api/jobs/job-1/screenshots/shot-a"
    )


def test_public_url_cdn_when_s3_and_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "OBJECT_STORAGE_CDN_BASE_URL",
        "https://cdn-example.vultrcdn.com",
    )
    from config import get_settings

    get_settings.cache_clear()
    assert (
        public_screenshot_url(
            "job-1",
            "shot-a",
            storage_path="s3://killhub/killhub/screenshots/job-1/shot-a.png",
        )
        == "https://cdn-example.vultrcdn.com/killhub/screenshots/job-1/shot-a.png"
    )


def test_public_screenshot_rows_enrich_cdn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from screenshots import public_screenshot_rows

    monkeypatch.setenv(
        "OBJECT_STORAGE_CDN_BASE_URL",
        "https://cdn-example.vultrcdn.com",
    )
    from config import get_settings

    get_settings.cache_clear()
    rows = public_screenshot_rows(
        [
            {
                "job_id": "job-1",
                "screenshot_id": "shot-a",
                "storage_path": "s3://bucket/killhub/screenshots/job-1/shot-a.png",
                "step": "verify",
            },
        ],
    )
    assert "storage_path" not in rows[0]
    assert rows[0]["url"] == (
        "https://cdn-example.vultrcdn.com/killhub/screenshots/job-1/shot-a.png"
    )


def test_list_summaries_include_screenshot_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from config import get_settings
    from ledger.store import Ledger
    from service import list_job_summaries

    db = tmp_path / "ledger.db"
    monkeypatch.setenv("LEDGER_URL", f"sqlite:///{db}")
    monkeypatch.setenv(
        "OBJECT_STORAGE_CDN_BASE_URL",
        "https://cdn-example.vultrcdn.com",
    )
    get_settings.cache_clear()

    with Ledger(db) as ledger:
        job = ledger.create_job(
            "https://github.com/heroku/nodejs-getting-started",
            env_ttl_seconds=60,
        )
        ledger.insert_screenshot(
            job.job_id,
            screenshot_id="shot-1",
            step="verify",
            caption="still",
            storage_path=(f"s3://bucket/killhub/screenshots/{job.job_id}/shot-1.png"),
        )

    rows = list_job_summaries(limit=10)
    assert len(rows) >= 1
    row = next(r for r in rows if r["job_id"] == job.job_id)
    assert row["screenshot_id"] == "shot-1"
    assert (
        row["screenshot_url"]
        == f"https://cdn-example.vultrcdn.com/killhub/screenshots/{job.job_id}/shot-1.png"
    )
