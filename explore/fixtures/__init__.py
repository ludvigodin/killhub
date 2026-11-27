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


def normalize_github_url(url: str) -> str:
    cleaned = url.strip().rstrip("/")
    parsed = urlparse(cleaned)
    if parsed.hostname and parsed.hostname.lower() == "github.com":
        return f"https://github.com{parsed.path.rstrip('/')}"
    return cleaned


def match_fixture(github_url: str) -> dict[str, Any] | None:
    target = normalize_github_url(github_url).lower()
    for fixture in list_fixtures().values():
        if normalize_github_url(str(fixture["github_url"])).lower() == target:
            return fixture
    return None


def require_fixture(fixture_id: str) -> dict[str, Any]:
    fixtures = list_fixtures()
    if fixture_id not in fixtures:
        raise KeyError(f"unknown fixture id: {fixture_id}")
    return fixtures[fixture_id]
