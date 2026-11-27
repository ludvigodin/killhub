"""Public allowlisted git URL validation (D78)."""

from __future__ import annotations

import pytest

from git_url import parse_public_git_url, validate_public_git_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://github.com/org/repo", "https://github.com/org/repo"),
        ("https://github.com/org/repo.git", "https://github.com/org/repo"),
        ("https://github.com/org/repo/", "https://github.com/org/repo"),
        ("https://gitlab.com/group/project", "https://gitlab.com/group/project"),
        (
            "https://gitlab.com/group/sub/project.git",
            "https://gitlab.com/group/sub/project",
        ),
        ("https://bitbucket.org/team/repo", "https://bitbucket.org/team/repo"),
        ("https://codeberg.org/user/repo.git", "https://codeberg.org/user/repo"),
    ],
)
def test_validate_accepts_allowlisted(raw: str, expected: str) -> None:
    assert validate_public_git_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "http://github.com/org/repo",
        "git@github.com:org/repo.git",
        "https://www.github.com/org/repo",
        "https://example.com/org/repo",
        "https://github.com/org/repo/tree/main",
        "https://github.com/org/repo?foo=1",
        "https://github.com/org",
        "https://gitlab.com/onlyone",
        "https://bitbucket.org/team/repo/src/main",
        "https://user:pass@github.com/org/repo",
        "https://gitea.com/org/repo",
    ],
)
def test_validate_rejects_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        validate_public_git_url(raw)


def test_parse_owner_repo_nested_gitlab() -> None:
    parsed = parse_public_git_url("https://gitlab.com/a/b/c.git")
    assert parsed.host == "gitlab.com"
    assert parsed.owner == "a"
    assert parsed.repo == "c"
    assert parsed.path_segments == ("a", "b", "c")
    assert parsed.owner_repo == "a/c"
