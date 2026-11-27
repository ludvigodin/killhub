"""GET /internal/repos + github_url filter on GET /internal/jobs (D79)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_repos_groups_same_url(client: TestClient, auth_header: dict[str, str]) -> None:
    url = "https://github.com/octocat/Hello-World"
    other = "https://github.com/heroku/node-js-getting-started"
    first = client.post("/internal/jobs", headers=auth_header, json={"github_url": url})
    second = client.post("/internal/jobs", headers=auth_header, json={"github_url": url})
    third = client.post("/internal/jobs", headers=auth_header, json={"github_url": other})
    assert first.status_code == 201
    assert second.status_code == 201
    assert third.status_code == 201
    latest_same = second.json()["job_id"]
    latest_other = third.json()["job_id"]

    listed = client.get("/internal/repos?limit=20", headers=auth_header)
    assert listed.status_code == 200
    body = listed.json()
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert body["total"] >= 2
    assert "repos" in body

    by_url = {r["github_url"]: r for r in body["repos"]}
    assert url in by_url
    assert other in by_url
    assert by_url[url]["run_count"] >= 2
    assert by_url[url]["latest"]["job_id"] == latest_same
    assert by_url[other]["run_count"] >= 1
    assert by_url[other]["latest"]["job_id"] == latest_other

    # Newest activity first — other was created last
    assert body["repos"][0]["github_url"] == other


def test_list_jobs_filter_by_github_url(client: TestClient, auth_header: dict[str, str]) -> None:
    url = "https://github.com/octocat/Spoon-Knife"
    other = "https://github.com/octocat/Hello-World"
    a = client.post("/internal/jobs", headers=auth_header, json={"github_url": url})
    b = client.post("/internal/jobs", headers=auth_header, json={"github_url": url})
    c = client.post("/internal/jobs", headers=auth_header, json={"github_url": other})
    assert a.status_code == 201 and b.status_code == 201 and c.status_code == 201

    listed = client.get(
        "/internal/jobs",
        headers=auth_header,
        params={"github_url": url, "limit": 10},
    )
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] >= 2
    assert all(j["github_url"] == url for j in body["jobs"])
    ids = [j["job_id"] for j in body["jobs"]]
    assert b.json()["job_id"] in ids
    assert a.json()["job_id"] in ids
    assert c.json()["job_id"] not in ids
    assert ids.index(b.json()["job_id"]) < ids.index(a.json()["job_id"])


def test_list_jobs_filter_invalid_url(client: TestClient, auth_header: dict[str, str]) -> None:
    bad = client.get(
        "/internal/jobs?github_url=not-a-url&limit=5",
        headers=auth_header,
    )
    assert bad.status_code == 400
    detail = bad.json()["detail"]
    assert detail["code"] == "invalid_url"
