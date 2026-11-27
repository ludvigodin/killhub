"""Edge, API contract and boundary checks (fast, no sandboxes)."""

from __future__ import annotations

import uuid

import pytest
from conftest import post_job


def test_home_page_serves(client) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


def test_health_reports_ok(client) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True, body


def test_tls_and_security_headers(client) -> None:
    r = client.get("/")
    assert str(r.url).startswith("https://") or not client.base_url.scheme == "https"
    if client.base_url.scheme == "https":
        assert "max-age" in r.headers.get("strict-transport-security", ""), r.headers


@pytest.mark.parametrize(
    "bad_url",
    [
        "",
        "not a url",
        "http://github.com/octocat/Hello-World",  # not HTTPS
        "https://example.com/owner/repo",  # host not allowlisted
        "https://github.com/octocat",  # no repo
        "https://user:pw@github.com/octocat/Hello-World",  # credentials in URL
        "https://127.0.0.1/owner/repo",  # private address
        "file:///etc/passwd",
    ],
)
def test_job_create_rejects_invalid_urls(client, bad_url: str) -> None:
    r = post_job(client, {"git_url": bad_url}, budget=180)
    assert r.status_code == 400, f"{bad_url!r} → {r.status_code} {r.text[:200]}"
    body = r.json()
    assert body.get("code") in {"invalid_url", "preflight_blocked"}, body
    assert "error" in body


def test_job_create_rejects_missing_body(client) -> None:
    r = post_job(client, {}, budget=180)
    assert r.status_code in (400, 422), r.text[:200]


def test_unknown_job_is_404(client) -> None:
    r = client.get(f"/api/jobs/{uuid.uuid4()}")
    assert r.status_code == 404


def test_job_list_shape(client) -> None:
    r = client.get("/api/jobs?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body.get("jobs"), list)
    for job in body["jobs"]:
        assert {"job_id", "git_url", "status"} <= set(job), job.keys()


@pytest.mark.parametrize("path", ["/internal/jobs", "/internal/health", "/internal/mcp"])
def test_internal_api_not_exposed_publicly(client, path: str) -> None:
    """Plane-1 internal API (token-guarded sidecar) must never answer through the edge."""
    for method in ("GET", "POST"):
        r = client.request(
            method, path, json={"git_url": "https://github.com/octocat/Hello-World"}
        )
        ctype = r.headers.get("content-type", "")
        assert "application/json" not in ctype or "job_id" not in r.text, (
            method,
            path,
            r.text[:200],
        )
        assert '"service":"explore"' not in r.text.replace(" ", "")


def test_snapshot_never_contains_control_plane_secret_names_with_values(client) -> None:
    jobs = client.get("/api/jobs?limit=20").json()["jobs"]
    for job in jobs[:10]:
        text = client.get(f"/api/jobs/{job['job_id']}").text
        for name in ("VULTR_API_KEY", "VULTR_INFERENCE_API_KEY", "INTERNAL_API_TOKEN"):
            assert f"{name}=" not in text and f'"{name}":"' not in text.replace(" ", ""), name
