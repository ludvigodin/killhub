"""Exercise the Plane 2 digest on a trusted Git fixture and Plane 1 verdict persistence."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from helpers.pkg_hash import MAX_FILE_BYTES, digest_checkout
from ledger import Ledger

URL = "https://github.com/example/fixture"


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], text=True, stderr=subprocess.PIPE
    ).strip()


def test_checkout_digest_covers_pinned_paths_without_following_symlinks(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    source = repo / "src" / "fixture.txt"
    source.write_text("original", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = repo / "tracked-link"
    link.symlink_to(outside)
    _git(repo, "init")
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.test",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        "test fixture",
    )
    commit = _git(repo, "rev-parse", "HEAD")

    before = digest_checkout(str(repo), commit)
    # Exercise the same isolated program invocation and one-line output as the worker.
    helper = Path(__file__).resolve().parents[1] / "helpers" / "pkg_hash.py"
    output = subprocess.check_output(
        ["/usr/bin/python3", "-I", "-S", str(helper), str(repo), commit], text=True
    )
    assert output == f"{before}\n"
    (repo / "build-output").write_text("generated", encoding="utf-8")
    outside.write_text("changed outside checkout", encoding="utf-8")
    assert digest_checkout(str(repo), commit) == before

    source.write_text("different", encoding="utf-8")
    assert digest_checkout(str(repo), commit) != before
    source.write_text("original", encoding="utf-8")
    source.chmod(0o755)
    assert digest_checkout(str(repo), commit) != before
    # A sparse oversized file exceeds the budget without allocating those bytes.
    with source.open("r+b") as stream:
        stream.truncate(MAX_FILE_BYTES + 1)
    with pytest.raises(ValueError, match="read budget"):
        digest_checkout(str(repo), commit)
    source.unlink()
    source.parent.rmdir()
    (tmp_path / "fixture.txt").write_text("original", encoding="utf-8")
    source.parent.symlink_to(tmp_path, target_is_directory=True)
    # A symlinked parent is never traversed, even when the target exists.
    assert digest_checkout(str(repo), commit) != before


@pytest.mark.parametrize("after", ["a" * 64, "b" * 64, None])
def test_verdict_compares_only_current_generation(tmp_path: Path, after: str | None) -> None:
    database = tmp_path / "ledger.db"
    before = "a" * 64
    with Ledger(database) as ledger:
        job = ledger.create_job(URL, env_ttl_seconds=60)
        first = ledger.append_sandbox_generation(
            job.job_id, environment_id="first", image="debian", expires_at=job.expires_at
        )
        assert ledger.record_checkout_digest(
            job.job_id, first.generation, before_install=True, digest="c" * 64
        )
        second = ledger.append_sandbox_generation(
            job.job_id, environment_id="second", image="debian", expires_at=job.expires_at
        )
        assert not ledger.record_checkout_digest(
            job.job_id, first.generation, before_install=False, digest="d" * 64
        )
        assert ledger.record_checkout_digest(
            job.job_id, second.generation, before_install=True, digest=before
        )
        # The first baseline survives retries, even after another capture attempt.
        assert ledger.record_checkout_digest(
            job.job_id, second.generation, before_install=True, digest="e" * 64
        )
        assert ledger.record_checkout_digest(
            job.job_id, second.generation, before_install=False, digest=after
        )

    with Ledger(database) as ledger:
        ledger.finalize_job(job.job_id, status="failed", receipt={}, include_verdict=True)
        verdict = ledger.get_receipt(job.job_id)["dossier"]["detonation_verdict"]
        target = verdict["target"]
        coverage = verdict["owasp_mcp_coverage"]["MCP04:2025"]
        assert target["package_sha256_before"] == before
        assert target["package_sha256_after"] == after
        assert target["integrity_tampered"] is (None if after is None else before != after)
        assert ("checkout_sha256" in coverage["sensors"]) is (after is not None)
        assert ("checkout-changed-after-install" in coverage["finding_ids"]) is (
            after is not None and before != after
        )
        assert not ledger.record_checkout_digest(
            job.job_id, second.generation, before_install=False, digest="f" * 64
        )
