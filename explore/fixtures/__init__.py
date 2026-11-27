"""Pinned M7 fixture configuration (D53)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

FIXTURES_PATH = Path(__file__).resolve().parent / "m7.json"


@lru_cache
def load_m7_fixtures() -> dict[str, Any]:
    data = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "fixtures" not in data:
        raise ValueError("m7.json must contain a fixtures object")
    return data


def list_fixtures() -> dict[str, dict[str, Any]]:
    return dict(load_m7_fixtures()["fixtures"])


def normalize_git_url(url: str) -> str:
    cleaned = url.strip().rstrip("/")
    parsed = urlparse(cleaned)
    if parsed.hostname and parsed.hostname.lower() == "github.com":
        return f"https://github.com{parsed.path.rstrip('/')}"
    return cleaned


def _fixture_urls(fixture: dict[str, Any]) -> list[str]:
    urls = [str(fixture.get("git_url") or "")]
    aliases = fixture.get("aliases") or []
    if isinstance(aliases, list):
        urls.extend(str(a) for a in aliases)
    return [u for u in urls if u]


def match_fixture(git_url: str) -> dict[str, Any] | None:
    """Match a public URL to a URL-facing fixture (skips match_by_url=false)."""
    target = normalize_git_url(git_url).lower()
    for fixture in list_fixtures().values():
        if fixture.get("match_by_url") is False:
            continue
        for candidate in _fixture_urls(fixture):
            if normalize_git_url(candidate).lower() == target:
                return fixture
    return None


def require_fixture(fixture_id: str) -> dict[str, Any]:
    fixtures = list_fixtures()
    if fixture_id not in fixtures:
        raise KeyError(f"unknown fixture id: {fixture_id}")
    return fixtures[fixture_id]


def intake_catalog(*, restricted: bool) -> dict[str, Any]:
    catalog = []
    for fixture in sorted(list_fixtures().values(), key=lambda f: f["id"]):
        if fixture.get("match_by_url") is False or not fixture.get("commit"):
            continue
        if restricted and not fixture.get("public_demo"):
            continue
        catalog.append(
            {
                key: fixture.get(key)
                for key in ("id", "git_url", "expected_intent", "verification_kind")
            }
        )
    return {"restricted": restricted, "fixtures": catalog}
