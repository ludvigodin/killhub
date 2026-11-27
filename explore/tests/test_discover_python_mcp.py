"""Python MCP servers (fastmcp / mcp) are discovered as git_mcp, not a demo."""

from __future__ import annotations

from discover import infer_runtime_profile, python_mcp_signal
from vulnscan import extract_packages

SHA = "a" * 40


def _inspect(*, tree: list[str], pyproject: str = "", requirements: str = "") -> str:
    return (
        "---TREE---\n"
        + "\n".join(tree)
        + "\n---PACKAGE_JSON---\n---PYPROJECT---\n"
        + pyproject
        + "\n---REQUIREMENTS---\n"
        + requirements
        + "\n---README---\nhello\n---MCP_FS---\n"
    )


# Shaped like github.com/vultr/vultr-mcp: fastmcp dep, no scripts, src/<pkg>/__main__.py.
VULTR_LIKE = _inspect(
    tree=[
        "./pyproject.toml",
        "./uv.lock",
        "./src/vultr_mcp/__main__.py",
        "./src/vultr_mcp/server.py",
    ],
    pyproject=(
        '[project]\nname = "vultr-mcp"\nrequires-python = ">=3.12"\n'
        'dependencies = [\n    "fastmcp>=2.14",\n    "httpx>=0.28",\n]\n'
        '[tool.hatch.build.targets.wheel]\npackages = ["src/vultr_mcp"]\n'
    ),
)


def test_fastmcp_module_server_is_detected() -> None:
    sig = python_mcp_signal(VULTR_LIKE)
    assert sig == {
        "kind": "module",
        "name": "vultr_mcp",
        "uv_lock": True,
        "pyproject": True,
        "requirements": False,
    }


def test_vultr_like_repo_gets_python_git_mcp_profile() -> None:
    profile = infer_runtime_profile(
        git_url="https://github.com/vultr/vultr-mcp",
        commit=SHA,
        inspect={"python_mcp": python_mcp_signal(VULTR_LIKE)},
        fixture=None,
        oci_image="debian",
    )
    assert profile["intent"] == "git_mcp"
    assert profile["verification_target"] == "original_application"
    assert profile["mcp"]["transport"] == "stdio"
    assert profile["mcp"]["launch_command"]["argv"] == [".venv/bin/python", "-m", "vultr_mcp"]
    assert profile["install_commands"][1]["argv"] == ["uv", "sync", "--frozen", "--no-dev"]
    assert "original_failure" not in profile


def test_console_script_preferred_when_declared() -> None:
    text = _inspect(
        tree=["./pyproject.toml", "./weather/__main__.py"],
        pyproject=(
            '[project]\ndependencies = ["mcp[cli]>=1.2"]\n'
            '[project.scripts]\nweather-mcp = "weather.server:main"\n'
        ),
    )
    sig = python_mcp_signal(text)
    assert sig["kind"] == "script" and sig["name"] == "weather-mcp"
    assert sig["uv_lock"] is False
    profile = infer_runtime_profile(
        git_url="https://github.com/example/weather",
        commit=SHA,
        inspect={"python_mcp": sig},
        fixture=None,
        oci_image="debian",
    )
    assert profile["mcp"]["launch_command"]["argv"] == [".venv/bin/weather-mcp"]
    assert "uv pip install" in profile["install_commands"][1]["shell"]


def test_requirements_only_server() -> None:
    text = _inspect(
        tree=["./requirements.txt", "./srv/__main__.py"], requirements="fastmcp==2.14.0\n"
    )
    assert python_mcp_signal(text)["name"] == "srv"


def test_plain_python_project_is_not_mcp() -> None:
    text = _inspect(
        tree=["./pyproject.toml", "./src/tool/__main__.py"],
        pyproject='[project]\ndependencies = ["httpx", "mcp-utils-not-really>=1"]\n',
    )
    assert python_mcp_signal(text) is None


def test_mcp_dep_without_entrypoint_is_not_launchable() -> None:
    text = _inspect(tree=["./pyproject.toml", "./lib.py"], pyproject='dependencies = ["fastmcp"]\n')
    assert python_mcp_signal(text) is None


def test_unsafe_names_are_ignored() -> None:
    text = _inspect(
        tree=["./pyproject.toml", "./src/bad-name;rm/__main__.py"],
        pyproject='dependencies = ["fastmcp"]\n',
    )
    assert python_mcp_signal(text) is None


def test_uv_lock_registry_packages_only(tmp_path) -> None:
    lock = tmp_path / "00-uv.lock"
    lock.write_text(
        "version = 1\n"
        '[[package]]\nname = "vultr-mcp"\nversion = "2.1.32"\nsource = { editable = "." }\n'
        '[[package]]\nname = "pyyaml"\nversion = "5.3.1"\n'
        'source = { registry = "https://pypi.org/simple" }\n'
        '[[package]]\nname = "vendored"\nversion = "0.1"\n'
        'source = { git = "https://github.com/x/y?rev=1" }\n'
    )
    assert extract_packages(lock) == ("PyPI", [("pyyaml", "5.3.1")])


def test_poetry_lock_is_parsed(tmp_path) -> None:
    lock = tmp_path / "poetry.lock"
    lock.write_text(
        '[[package]]\nname = "requests"\nversion = "2.19.0"\n'
        '[[package]]\nname = "local"\nversion = "0.0.1"\n'
        '[package.source]\ntype = "directory"\nurl = "../local"\n'
    )
    assert extract_packages(lock) == ("PyPI", [("requests", "2.19.0")])
