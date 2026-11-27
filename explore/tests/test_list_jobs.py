"""GET /internal/jobs recent feed list (D69 / D77)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_jobs_newest_first(client: TestClient, auth_header: dict[str, str]) -> None:
    first = client.post(
        "/internal/jobs",
        headers=auth_header,
        json={"git_url": "https://github.com/heroku/node-js-getting-started"},
    )
    assert first.status_code == 201
    second = client.post(
        "/internal/jobs",
        headers=auth_header,
        json={"git_url": "https://github.com/octocat/Hello-World"},
    )
    assert second.status_code == 201

    listed = client.get("/internal/jobs?limit=10", headers=auth_header)
    assert listed.status_code == 200
    body = listed.json()
    assert "jobs" in body
    assert body["limit"] == 10
    assert body["offset"] == 0
    assert body["total"] >= 2
    assert len(body["jobs"]) >= 2
    ids = [j["job_id"] for j in body["jobs"]]
    assert second.json()["job_id"] in ids
    assert first.json()["job_id"] in ids
    # Newest first
    assert ids.index(second.json()["job_id"]) < ids.index(first.json()["job_id"])
    row = body["jobs"][0]
    assert set(row.keys()) >= {
        "job_id",
        "git_url",
        "status",
        "progress",
        "current_step",
        "created_at",
        "screenshot_id",
        "screenshot_url",
        "safety",
    }
    assert row["safety"] is None


def test_list_jobs_limit(client: TestClient, auth_header: dict[str, str]) -> None:
    a = client.post(
        "/internal/jobs",
        headers=auth_header,
        json={"git_url": "https://github.com/heroku/node-js-getting-started"},
    )
    b = client.post(
        "/internal/jobs",
        headers=auth_header,
        json={"git_url": "https://github.com/octocat/Hello-World"},
    )
    assert a.status_code == 201 and b.status_code == 201
    listed = client.get("/internal/jobs?limit=1", headers=auth_header)
    assert listed.status_code == 200
    body = listed.json()
    assert len(body["jobs"]) == 1
    assert body["limit"] == 1
    assert body["offset"] == 0
    assert body["total"] >= 2


def test_list_jobs_offset_page(client: TestClient, auth_header: dict[str, str]) -> None:
    created: list[str] = []
    for slug in ("alpha", "beta", "gamma"):
        res = client.post(
            "/internal/jobs",
            headers=auth_header,
            json={"git_url": f"https://github.com/octocat/{slug}"},
        )
        assert res.status_code == 201
        created.append(res.json()["job_id"])

    page0 = client.get("/internal/jobs?limit=2&offset=0", headers=auth_header)
    assert page0.status_code == 200
    body0 = page0.json()
    assert body0["limit"] == 2
    assert body0["offset"] == 0
    assert body0["total"] >= 3
    assert len(body0["jobs"]) == 2

    page1 = client.get("/internal/jobs?limit=2&offset=2", headers=auth_header)
    assert page1.status_code == 200
    body1 = page1.json()
    assert body1["offset"] == 2
    assert len(body1["jobs"]) >= 1

    ids0 = {j["job_id"] for j in body0["jobs"]}
    ids1 = {j["job_id"] for j in body1["jobs"]}
    assert ids0.isdisjoint(ids1)

    # Newest page should start with the last create
    assert body0["jobs"][0]["job_id"] == created[-1]
