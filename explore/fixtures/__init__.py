"""Pinned M7 fixture configuration (D53)."""

from __future__ import annotations

import json
import re
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


def normalize_github_url(url: str) -> str:
    cleaned = url.strip().rstrip("/")
    parsed = urlparse(cleaned)
    if parsed.hostname and parsed.hostname.lower() == "github.com":
        return f"https://github.com{parsed.path.rstrip('/')}"
    return cleaned


def _fixture_urls(fixture: dict[str, Any]) -> list[str]:
    urls = [str(fixture.get("github_url") or "")]
    aliases = fixture.get("aliases") or []
    if isinstance(aliases, list):
        urls.extend(str(a) for a in aliases)
    return [u for u in urls if u]


def match_fixture(github_url: str) -> dict[str, Any] | None:
    """Match a public URL to a URL-facing fixture (skips match_by_url=false)."""
    target = normalize_github_url(github_url).lower()
    for fixture in list_fixtures().values():
        if fixture.get("match_by_url") is False:
            continue
        for candidate in _fixture_urls(fixture):
            if normalize_github_url(candidate).lower() == target:
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
        try:
            resolve_intake_fixture(fixture["id"], restricted=restricted)
        except ValueError:
            continue
        catalog.append(
            {
                key: fixture.get(key)
                for key in ("id", "github_url", "expected_intent", "verification_kind")
            }
        )
    return {"restricted": restricted, "fixtures": catalog}


def resolve_intake_fixture(fixture_id: str, *, restricted: bool) -> str:
    """Resolve only catalog fixtures whose URL also selects the same discovery pin."""
    fixture = list_fixtures().get(fixture_id)
    if (
        fixture is None
        or fixture.get("id") != fixture_id
        or fixture.get("match_by_url") is False
        or (restricted and not fixture.get("public_demo"))
        or not re.fullmatch(r"[0-9a-f]{40}", str(fixture.get("commit") or ""))
    ):
        raise ValueError("Fixture is unavailable for intake")
    url = str(fixture.get("github_url") or "")
    matched = match_fixture(url)
    # Hidden variants can share a URL with public fixtures. Never switch variants.
    if not matched or matched.get("id") != fixture_id:
        raise ValueError("Fixture is unavailable for intake")
    return url
