"""Unit tests must be isolated from ambient proxy settings."""

from __future__ import annotations

import os

import httpx
import pytest
from conftest import PROXY_ENV_VARS


def test_proxy_env_is_scrubbed() -> None:
    assert [n for n in PROXY_ENV_VARS if n in os.environ] == []


def test_httpx_client_builds_even_if_proxy_is_set_in_the_shell() -> None:
    """Run with ALL_PROXY=socks5://127.0.0.1:1 in the shell: still constructs (no socksio)."""
    with httpx.Client() as client:
        assert client is not None


@pytest.mark.parametrize("name", PROXY_ENV_VARS)
def test_each_proxy_variable_is_cleared(name: str) -> None:
    assert os.environ.get(name) is None
