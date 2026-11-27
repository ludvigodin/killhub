"""Public allowlisted HTTPS git URL validation (D78).

Wire/DB field is ``git_url``; values may be any allowlisted host
(GitHub, GitLab, Bitbucket, Codeberg).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

ALLOWED_GIT_HOSTS = frozenset(
    {
        "github.com",
        "gitlab.com",
        "bitbucket.org",
        "codeberg.org",
    }
)
_TWO_SEGMENT_HOSTS = frozenset({"github.com", "bitbucket.org", "codeberg.org"})
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_FORBIDDEN_SEGMENTS = frozenset(
    {
        "-",
        "tree",
        "blob",
        "src",
        "raw",
        "commit",
        "commits",
        "issues",
        "pull",
        "pulls",
        "wiki",
        "releases",
        "tags",
        "branch",
        "branches",
        "settings",
        "actions",
        "pipelines",
        "merge_requests",
    }
)


@dataclass(frozen=True)
class ParsedGitUrl:
    url: str
    host: str
    owner: str
    repo: str
    path_segments: tuple[str, ...]

    @property
    def owner_repo(self) -> str:
        return f"{self.owner}/{self.repo}"


def _normalize_segments(path: str) -> list[str]:
    parts = [p for p in path.split("/") if p]
    if not parts:
        return []
    last = parts[-1]
    if last.endswith(".git"):
        last = last[: -len(".git")]
        if not last:
            return []
        parts[-1] = last
    return parts


def parse_public_git_url(raw: str) -> ParsedGitUrl:
    """Parse and validate a public allowlisted git HTTPS URL.

    Raises ValueError with a stable message on rejection.
    """
    cleaned = (raw or "").strip()
    if not cleaned:
        raise ValueError("git_url must be a public HTTPS git URL on an allowlisted host")

    parsed = urlparse(cleaned)
    if parsed.scheme != "https":
        raise ValueError("git_url must be a public HTTPS git URL on an allowlisted host")
    if parsed.username or parsed.password:
        raise ValueError("git_url must not include credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("git_url must not include query or fragment")
    if parsed.port is not None:
        raise ValueError("git_url must use the default HTTPS port")

    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_GIT_HOSTS:
        raise ValueError(
            "git_url must be a public HTTPS git URL on github.com, "
            "gitlab.com, bitbucket.org, or codeberg.org"
        )

    segments = _normalize_segments(parsed.path or "")
    if host in _TWO_SEGMENT_HOSTS:
        if len(segments) != 2:
            raise ValueError(
                "git_url must be a public HTTPS git URL on an allowlisted host (owner/repo)"
            )
    elif len(segments) < 2:
        raise ValueError(
            "git_url must be a public HTTPS git URL on an allowlisted host (group/…/project)"
        )

    for seg in segments:
        if not _SEGMENT_RE.match(seg):
            raise ValueError("git_url path segments must be alphanumeric (plus _.-)")
        if seg.lower() in _FORBIDDEN_SEGMENTS:
            raise ValueError("git_url must not include repository UI path segments")

    owner = segments[0]
    repo = segments[-1]
    canonical = f"https://{host}/{'/'.join(segments)}"
    return ParsedGitUrl(
        url=canonical,
        host=host,
        owner=owner,
        repo=repo,
        path_segments=tuple(segments),
    )


def validate_public_git_url(raw: str) -> str:
    """Return the canonical public git URL or raise ValueError."""
    return parse_public_git_url(raw).url


def parse_git_owner_repo(raw: str) -> tuple[str, str]:
    """Return (owner, repo) from a validated public git URL."""
    parsed = parse_public_git_url(raw)
    return parsed.owner, parsed.repo
