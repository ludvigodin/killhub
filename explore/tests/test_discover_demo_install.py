"""Demo-intent repos still run (and so trace) their own dependency install."""

from __future__ import annotations

from discover import demo_install_plan, infer_runtime_profile

SHA = "b" * 40


def _inspect(*files: str) -> dict:
    return {"raw": "---TREE---\n" + "\n".join(files) + "\n---PACKAGE_JSON---\n"}


def test_npm_repo_installs_with_npm() -> None:
    packages, cmds = demo_install_plan(_inspect("./package.json", "./package-lock.json"))
    assert {"nodejs", "npm"} <= set(packages)
    assert cmds == [
        {
            "argv": ["npm", "install", "--no-audit", "--no-fund"],
            "timeout_seconds": 600,
            "cwd": "/tmp/killhub/repo",
        }
    ]


def test_uv_lock_repo_uses_frozen_sync_after_trusted_installer() -> None:
    _, cmds = demo_install_plan(_inspect("./pyproject.toml", "./uv.lock"))
    assert cmds[0]["killhub_tooling"] is True  # uv installer is Killhub's, not the repo's
    assert cmds[1]["argv"] == ["uv", "sync", "--frozen", "--no-dev"]


def test_requirements_repo_installs_requirements() -> None:
    _, cmds = demo_install_plan(_inspect("./requirements.txt"))
    assert "-r requirements.txt" in cmds[1]["shell"]


def test_repo_without_manifests_installs_nothing() -> None:
    assert demo_install_plan(_inspect("./README.md", "./index.html")) == ([], [])


def test_demo_profile_carries_repo_install_and_keeps_honest_label() -> None:
    profile = infer_runtime_profile(
        github_url="https://github.com/example/lib",
        commit=SHA,
        inspect={"has_package_json": True, **_inspect("./package.json")},
        fixture=None,
        oci_image="debian",
    )
    assert profile["intent"] == "demo"
    assert profile["verification_target"] == "generated_demo"
    assert profile["install_commands"][0]["argv"][:2] == ["npm", "install"]
    assert "npm" in profile["packages"] and "python3" in profile["packages"]
