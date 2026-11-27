"""GET /internal/repos + git_url filter on GET /internal/jobs (D79)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_repos_groups_same_url(client: TestClient, auth_header: dict[str, str]) -> None:
    url = "https://github.com/octocat/Hello-World"
    other = "https://github.com/heroku/node-js-getting-started"
    first = client.post("/internal/jobs", headers=auth_header, json={"git_url": url})
    second = client.post("/internal/jobs", headers=auth_header, json={"git_url": url})
    third = client.post("/internal/jobs", headers=auth_header, json={"git_url": other})
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

    by_url = {r["git_url"]: r for r in body["repos"]}
    assert url in by_url
    assert other in by_url
    assert by_url[url]["run_count"] >= 2
    assert by_url[url]["latest"]["job_id"] == latest_same
    assert by_url[other]["run_count"] >= 1
    assert by_url[other]["latest"]["job_id"] == latest_other

    # Newest activity first — other was created last
    assert body["repos"][0]["git_url"] == other


def test_list_jobs_filter_by_git_url(client: TestClient, auth_header: dict[str, str]) -> None:
    url = "https://github.com/octocat/Spoon-Knife"
    other = "https://github.com/octocat/Hello-World"
    a = client.post("/internal/jobs", headers=auth_header, json={"git_url": url})
    b = client.post("/internal/jobs", headers=auth_header, json={"git_url": url})
    c = client.post("/internal/jobs", headers=auth_header, json={"git_url": other})
    assert a.status_code == 201 and b.status_code == 201 and c.status_code == 201

    listed = client.get(
        "/internal/jobs",
        headers=auth_header,
        params={"git_url": url, "limit": 10},
    )
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] >= 2
    assert all(j["git_url"] == url for j in body["jobs"])
    ids = [j["job_id"] for j in body["jobs"]]
    assert b.json()["job_id"] in ids
    assert a.json()["job_id"] in ids
    assert c.json()["job_id"] not in ids
    assert ids.index(b.json()["job_id"]) < ids.index(a.json()["job_id"])


def test_list_jobs_filter_invalid_url(client: TestClient, auth_header: dict[str, str]) -> None:
    bad = client.get(
        "/internal/jobs?git_url=not-a-url&limit=5",
        headers=auth_header,
    )
    assert bad.status_code == 400
    detail = bad.json()["detail"]
    assert detail["code"] == "invalid_url"


def test_list_repos_q_filters_by_url_substring(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    keep = "https://github.com/octocat/Hello-World"
    drop = "https://github.com/heroku/node-js-getting-started"
    a = client.post("/internal/jobs", headers=auth_header, json={"git_url": keep})
    b = client.post("/internal/jobs", headers=auth_header, json={"git_url": keep})
    c = client.post("/internal/jobs", headers=auth_header, json={"git_url": drop})
    assert a.status_code == 201 and b.status_code == 201 and c.status_code == 201

    listed = client.get(
        "/internal/repos",
        headers=auth_header,
        params={"q": "Hello-World", "limit": 50},
    )
    assert listed.status_code == 200
    body = listed.json()
    urls = [r["git_url"] for r in body["repos"]]
    assert keep in urls
    assert drop not in urls
    assert body["total"] == len(urls)
    by_url = {r["git_url"]: r for r in body["repos"]}
    assert by_url[keep]["run_count"] >= 2
    assert by_url[keep]["latest"]["job_id"] == b.json()["job_id"]


def test_list_repos_q_filters_by_job_id(client: TestClient, auth_header: dict[str, str]) -> None:
    url = "https://github.com/octocat/Spoon-Knife"
    other = "https://github.com/octocat/Hello-World"
    first = client.post("/internal/jobs", headers=auth_header, json={"git_url": url})
    second = client.post("/internal/jobs", headers=auth_header, json={"git_url": url})
    third = client.post("/internal/jobs", headers=auth_header, json={"git_url": other})
    assert first.status_code == 201 and second.status_code == 201 and third.status_code == 201
    target_id = first.json()["job_id"]

    listed = client.get(
        "/internal/repos",
        headers=auth_header,
        params={"q": target_id, "limit": 50},
    )
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 1
    assert len(body["repos"]) == 1
    row = body["repos"][0]
    assert row["git_url"] == url
    # Full run_count, not shrunk to the single matching job_id row.
    assert row["run_count"] >= 2
    assert row["latest"]["job_id"] == second.json()["job_id"]


def test_list_repos_empty_q_unfiltered(client: TestClient, auth_header: dict[str, str]) -> None:
    url = "https://github.com/octocat/Hello-World"
    other = "https://gitlab.com/gitlab-org/gitlab-test"
    assert (
        client.post("/internal/jobs", headers=auth_header, json={"git_url": url}).status_code == 201
    )
    assert (
        client.post("/internal/jobs", headers=auth_header, json={"git_url": other}).status_code
        == 201
    )

    blank = client.get(
        "/internal/repos",
        headers=auth_header,
        params={"q": "   ", "limit": 50},
    )
    full = client.get("/internal/repos?limit=50", headers=auth_header)
    assert blank.status_code == 200 and full.status_code == 200
    assert blank.json()["total"] == full.json()["total"]
    assert {r["git_url"] for r in blank.json()["repos"]} == {
        r["git_url"] for r in full.json()["repos"]
    }


def test_list_repos_q_escapes_like_wildcards(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    url = "https://github.com/octocat/Hello-World"
    assert (
        client.post("/internal/jobs", headers=auth_header, json={"git_url": url}).status_code == 201
    )

    listed = client.get(
        "/internal/repos",
        headers=auth_header,
        params={"q": "%Hello%", "limit": 50},
    )
    assert listed.status_code == 200
    # Literal % wildcards must not match everything; only an exact substring with %.
    assert listed.json()["total"] == 0
    assert listed.json()["repos"] == []
