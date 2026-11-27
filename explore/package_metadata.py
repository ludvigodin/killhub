"""Plane 1 read-only metadata lookup for exact public npm and PyPI releases.

Only fixed registry origins are contacted. The result describes published
artifact digests and carries no launch commands or provisionable job state.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from time import monotonic
from urllib.parse import quote

import httpx

_NPM_NAME = r"(?:@[a-z0-9][a-z0-9_.-]*/)?[a-z0-9][a-z0-9_.-]*"
_NPM_VERSION = r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?"
_PYPI_NAME = r"[a-zA-Z0-9](?:[a-zA-Z0-9._-]*[a-zA-Z0-9])?"
_PYPI_VERSION = r"[0-9][0-9A-Za-z.!+_-]{0,95}"
_MAX_METADATA_BYTES = 2_000_000
_MAX_ARTIFACTS = 256


class PackageMetadataError(ValueError):
    def __init__(self, message: str, status: int, code: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class RegistryTarget:
    registry: str
    package: str
    version: str

    @property
    def metadata_url(self) -> str:
        package = quote(self.package, safe="")
        version = quote(self.version, safe="")
        if self.registry == "npm":
            return f"https://registry.npmjs.org/{package}/{version}"
        return f"https://pypi.org/pypi/{package}/{version}/json"


def _normalized_python_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_target(locator: str) -> RegistryTarget:
    # Reject tags, ranges, URLs and shell syntax before building an outbound URL.
    if len(locator) <= 320:
        npm = re.fullmatch(rf"npm:({_NPM_NAME})@({_NPM_VERSION})", locator)
        if npm is not None:
            return RegistryTarget("npm", npm[1], npm[2])
        pypi = re.fullmatch(rf"pypi:({_PYPI_NAME})==({_PYPI_VERSION})", locator)
        if pypi is not None:
            return RegistryTarget("pypi", _normalized_python_name(pypi[1]), pypi[2])
    raise PackageMetadataError(
        "Provide an exact npm or PyPI package version", 400, "invalid_target"
    )


def _invalid_metadata() -> PackageMetadataError:
    return PackageMetadataError(
        "Registry returned incomplete release metadata", 502, "registry_error"
    )


def _npm_artifacts(target: RegistryTarget, payload: dict) -> list[dict[str, str]]:
    dist = payload.get("dist")
    integrity = dist.get("integrity") if isinstance(dist, dict) else None
    if (
        payload.get("name") != target.package
        or payload.get("version") != target.version
        or not isinstance(integrity, str)
        or not integrity.startswith("sha512-")
    ):
        raise _invalid_metadata()
    try:
        digest = base64.b64decode(integrity.removeprefix("sha512-"), validate=True)
    except ValueError as exc:
        raise _invalid_metadata() from exc
    if len(digest) != 64:
        raise _invalid_metadata()
    return [{"algorithm": "sha512", "digest": digest.hex()}]


def _pypi_artifacts(target: RegistryTarget, payload: dict) -> list[dict[str, str]]:
    info = payload.get("info")
    files = payload.get("urls")
    if (
        not isinstance(info, dict)
        or not isinstance(info.get("name"), str)
        or _normalized_python_name(info["name"]) != target.package
        or info.get("version") != target.version
        or not isinstance(files, list)
        or not 0 < len(files) <= _MAX_ARTIFACTS
    ):
        raise _invalid_metadata()
    artifacts = {}
    for artifact in files:
        digests = artifact.get("digests") if isinstance(artifact, dict) else None
        digest = digests.get("sha256") if isinstance(digests, dict) else None
        filename = artifact.get("filename") if isinstance(artifact, dict) else None
        if (
            not isinstance(filename, str)
            or not re.fullmatch(r"[a-zA-Z0-9_.+!-]{1,255}", filename)
            or filename in artifacts
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise _invalid_metadata()
        if artifact.get("yanked") is True:
            continue
        artifacts[filename] = {"filename": filename, "algorithm": "sha256", "digest": digest}
    if not artifacts:
        raise PackageMetadataError("Release has no available artifacts", 404, "release_not_found")
    return [artifacts[filename] for filename in sorted(artifacts)]


def resolve_package_metadata(locator: str, *, client: httpx.Client) -> dict:
    """Resolve artifact identity without downloading any package contents."""
    target = _parse_target(locator)
    try:
        deadline = monotonic() + 8
        with client.stream("GET", target.metadata_url, follow_redirects=False) as response:
            if response.status_code == 404:
                raise PackageMetadataError("Package release not found", 404, "release_not_found")
            response.raise_for_status()
            raw = bytearray()
            for chunk in response.iter_bytes():
                raw.extend(chunk)
                if len(raw) > _MAX_METADATA_BYTES or monotonic() > deadline:
                    raise _invalid_metadata()
        payload = json.loads(raw)
    except (httpx.HTTPError, json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
        raise _invalid_metadata() from exc
    if not isinstance(payload, dict):
        raise _invalid_metadata()
    artifacts = (
        _npm_artifacts(target, payload)
        if target.registry == "npm"
        else _pypi_artifacts(target, payload)
    )
    return {
        "registry": target.registry,
        "package": target.package,
        "version": target.version,
        "artifacts": artifacts,
    }
