"""Plane 1 tests for redacted network canary blocking."""

import sys
from types import ModuleType, SimpleNamespace

from net_tap import NetTapAddon


def test_http_request_with_canary_is_blocked_and_redacted(monkeypatch):
    http = ModuleType("mitmproxy.http")
    http.Response = SimpleNamespace(make=lambda status, content: (status, content))
    mitmproxy = ModuleType("mitmproxy")
    mitmproxy.http = http
    monkeypatch.setitem(sys.modules, "mitmproxy", mitmproxy)
    monkeypatch.setitem(sys.modules, "mitmproxy.http", http)
    events = []
    addon = NetTapAddon(
        job_id="job-1",
        generation=3,
        canaries={"env:KILLHUB_CANARY_TOKEN": "secret-value"},
        emit=events.append,
    )
    request = SimpleNamespace(
        pretty_url="https://example.test/upload",
        headers={"Authorization": "secret-value"},
        raw_content=b"",
    )
    flow = SimpleNamespace(request=request, response=None)
    addon.request(flow)

    assert flow.response == (403, b"blocked by egress policy")
    assert events[0]["sensor"] == "canary_block"
    assert events[0]["job_id"] == "job-1"
    assert events[0]["generation"] == 3
    assert "secret-value" not in repr(events)
    assert "secret-value" not in repr(flow.response)


def test_safe_http_request_is_forwarded_unchanged():
    events = []
    addon = NetTapAddon(
        job_id="job-1", generation=3, canaries={"token": "secret"}, emit=events.append
    )
    flow = SimpleNamespace(
        request=SimpleNamespace(pretty_url="https://example.test", headers={}, raw_content=b"ok"),
        response=None,
    )
    addon.request(flow)
    assert flow.response is None
    assert events == []


def test_dns_question_with_canary_is_failed_and_redacted(monkeypatch):
    dns = ModuleType("mitmproxy.dns")
    dns.response_codes = SimpleNamespace(NXDOMAIN=3)
    mitmproxy = ModuleType("mitmproxy")
    mitmproxy.dns = dns
    monkeypatch.setitem(sys.modules, "mitmproxy", mitmproxy)
    monkeypatch.setitem(sys.modules, "mitmproxy.dns", dns)
    events = []
    addon = NetTapAddon(
        job_id="job-1",
        generation=3,
        canaries={"env:KILLHUB_CANARY_TOKEN": "canary-token"},
        emit=events.append,
    )
    request = SimpleNamespace(
        question=SimpleNamespace(name="canary-token.exfil.test"),
        fail=lambda code: ("nxdomain", code),
    )
    flow = SimpleNamespace(request=request, response=None)
    addon.dns_request(flow)

    assert flow.response == ("nxdomain", 3)
    assert "canary-token" not in repr(events)
    assert events[0]["summary"] == "blocked canary-bearing DNS request"
