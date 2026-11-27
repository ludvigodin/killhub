"""GET /internal/jobs recent feed list (D69)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_jobs_newest_first(client: TestClient, auth_header: dict[str, str]) -> None:
    first = client.post(
        "/internal/jobs",
        headers=auth_header,
        json={"github_url": "https://github.com/heroku/node-js-getting-started"},
    )
    assert first.status_code == 201
    second = client.post(
        "/internal/jobs",
        headers=auth_header,
        json={"github_url": "https://github.com/octocat/Hello-World"},
    )
    assert second.status_code == 201

    listed = client.get("/internal/jobs?limit=10", headers=auth_header)
    assert listed.status_code == 200
    body = listed.json()
    assert "jobs" in body
    assert len(body["jobs"]) >= 2
    ids = [j["job_id"] for j in body["jobs"]]
    assert second.json()["job_id"] in ids
    assert first.json()["job_id"] in ids
    # Newest first
    assert ids.index(second.json()["job_id"]) < ids.index(first.json()["job_id"])
    row = body["jobs"][0]
    assert set(row.keys()) >= {
        "job_id",
        "github_url",
        "status",
        "progress",
        "current_step",
        "created_at",
        "screenshot_id",
    }


def test_list_jobs_limit(client: TestClient, auth_header: dict[str, str]) -> None:
    a = client.post(
        "/internal/jobs",
        headers=auth_header,
        json={"github_url": "https://github.com/heroku/node-js-getting-started"},
    )
    b = client.post(
        "/internal/jobs",
        headers=auth_header,
        json={"github_url": "https://github.com/octocat/Hello-World"},
    )
    assert a.status_code == 201 and b.status_code == 201
    listed = client.get("/internal/jobs?limit=1", headers=auth_header)
    assert listed.status_code == 200
    assert len(listed.json()["jobs"]) == 1
