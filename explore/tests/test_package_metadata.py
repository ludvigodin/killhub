"""Exercise Plane 1 package identity lookup against synthetic registry responses."""

import base64

import httpx
import pytest

from package_metadata import PackageMetadataError, resolve_package_metadata


def test_npm_scoped_release_returns_digest_without_downloading_artifact() -> None:
    def registry(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://registry.npmjs.org/%40scope%2Fdemo/1.2.3"
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={
                "name": "@scope/demo",
                "version": "1.2.3",
                "dist": {
                    "integrity": "sha512-" + base64.b64encode(b"x" * 64).decode(),
                    "tarball": "https://example.invalid/package.tgz",
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(registry)) as client:
        result = resolve_package_metadata("npm:@scope/demo@1.2.3", client=client)
    assert result["artifacts"] == [{"algorithm": "sha512", "digest": (b"x" * 64).hex()}]


def test_pypi_lists_only_available_artifact_digests() -> None:
    def registry(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://pypi.org/pypi/my-demo/2.0/json"
        return httpx.Response(
            200,
            json={
                "info": {"name": "My_Demo", "version": "2.0"},
                "urls": [
                    {"filename": "old.whl", "digests": {"sha256": "a" * 64}, "yanked": True},
                    {"filename": "demo.whl", "digests": {"sha256": "b" * 64}, "yanked": False},
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(registry)) as client:
        result = resolve_package_metadata("pypi:My_Demo==2.0", client=client)
    assert result["package"] == "my-demo"
    assert result["artifacts"] == [
        {"filename": "demo.whl", "algorithm": "sha256", "digest": "b" * 64}
    ]


@pytest.mark.parametrize(
    "locator", ["npm:demo@latest", "npm:demo@^1.2.3", "pypi:demo>=2", "https://example.org"]
)
def test_non_exact_targets_never_contact_registry(locator: str) -> None:
    def unexpected(request: httpx.Request) -> httpx.Response:
        pytest.fail("Invalid targets must not send an HTTP request")

    with httpx.Client(transport=httpx.MockTransport(unexpected)) as client:
        with pytest.raises(PackageMetadataError) as error:
            resolve_package_metadata(locator, client=client)
    assert error.value.status == 400


def test_registry_redirect_fails_closed() -> None:
    def redirect(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "registry.npmjs.org"
        return httpx.Response(302, headers={"Location": "http://example.invalid/"})

    with httpx.Client(transport=httpx.MockTransport(redirect)) as client:
        with pytest.raises(PackageMetadataError) as error:
            resolve_package_metadata("npm:demo@1.2.3", client=client)
    assert error.value.status == 502
