"""P2: every accepted environment_profile field is honored or rejected before provision."""

from __future__ import annotations

import copy
import json
import shlex
from profile import (
    PROBE_TYPES,
    STOP_SIGNALS,
    SUPERVISE_MODES,
    ProfileError,
    assert_runtime_ready_for_provision,
    effective_processes,
    load_schema,
    service_launch_order,
    validate_profile,
)
from typing import Any

import pytest

from config import get_settings
from errors import HarnessError
from harness import ExecResult
from install import run_install_commands
from jobs import get_ledger, reset_ledger_for_tests
from service import create_job
from verify import (
    VerifyError,
    launch_supervised_process,
    probe_command,
    probe_http,
    probe_tcp,
    run_probe,
    start_services,
    stop_supervised_process,
    verify_mcp_stdio,
    verify_readiness,
)

COMMIT = "d33649d5edae61fc766fe6d47e530c475c05a7a0"
WORKDIR = "/tmp/killhub/repo"

BASE: dict[str, Any] = {
    "schema_version": "1",
    "intent": "webapp",
    "oci_image": "debian",
    "os_image": "linux",
    "runtime": "node",
    "workdir": WORKDIR,
    "source": {"type": "git", "url": "https://github.com/o/r", "commit": COMMIT, "ref": "main"},
    "packages": [],
    "install_commands": [],
    "run_commands": [],
    "services": [],
    "processes": [],
    "ports": [5000],
    "probes": [{"name": "root", "type": "http", "url": "http://127.0.0.1:5000/"}],
    "summary": "contract test",
    "verification_target": "original_application",
}

MCP_STDIO: dict[str, Any] = {
    **BASE,
    "intent": "git_mcp",
    "ports": [],
    "probes": [],
    "mcp": {
        "transport": "stdio",
        "launch_command": {"argv": ["node", "dist/index.js"], "timeout_seconds": 30},
        "readiness": {"type": "mcp_handshake", "transport": "stdio", "timeout_seconds": 30},
    },
}


def _profile(**over: Any) -> dict[str, Any]:
    out = copy.deepcopy(BASE)
    out.update(copy.deepcopy(over))
    return out


def _cmd(argv: list[str], **extra: Any) -> dict[str, Any]:
    return {"argv": argv, "timeout_seconds": 60, **extra}


def _svc(name: str, **over: Any) -> dict[str, Any]:
    svc: dict[str, Any] = {
        "name": name,
        "kind": "custom",
        "command": _cmd([f"{name}d"]),
        "ports": [{"db": 5432, "cache": 6379, "queue": 5672}.get(name, 7000)],
        "healthcheck": {"type": "command", "command": _cmd(["true"])},
    }
    svc.update(over)
    return svc


# --- validation: unsupported fields and modes are rejected before provision -------------


def _rejected(profile: dict[str, Any], *fragments: str, code: str | None = None) -> None:
    with pytest.raises(ProfileError) as err:
        validate_profile(profile, phase="runtime")
    for frag in fragments:
        assert frag in err.value.message, err.value.message
    if code:
        assert err.value.code == code
    with pytest.raises(HarnessError) as blocked:  # provision/verify entry point
        assert_runtime_ready_for_provision(profile)
    assert blocked.value.code == "profile_blocks_provision"


def test_base_profiles_validate() -> None:
    validate_profile(_profile(), phase="runtime")
    validate_profile(MCP_STDIO, phase="runtime")


def test_unknown_top_level_field_rejected() -> None:
    _rejected(_profile(policy={"x": 1}), "policy", code="profile_unsupported")
    _rejected(_profile(restart_policy="always"), "restart_policy", code="profile_unsupported")


def test_unsupported_supervise_mode_rejected() -> None:
    proc = {"name": "web", "command": _cmd(["npm", "start"]), "supervise": "systemd"}
    _rejected(_profile(processes=[proc]), "supervise", code="profile_unsupported")
    del proc["supervise"]
    _rejected(_profile(processes=[proc]), "supervise")


def test_unsupported_process_fields_rejected() -> None:
    proc = {"name": "web", "command": _cmd(["x"]), "supervise": "restart", "depends_on": ["db"]}
    _rejected(_profile(processes=[proc]), "depends_on", code="profile_unsupported")
    proc = {"name": "web", "command": _cmd(["x"]), "supervise": "oneshot", "max_restarts": 2}
    _rejected(_profile(processes=[proc]), "max_restarts")
    proc = {"name": "web", "command": _cmd(["x"]), "supervise": "restart", "stop_signal": "SIGFOO"}
    _rejected(_profile(processes=[proc]), "stop_signal")
    proc = {"name": "../etc", "command": _cmd(["x"]), "supervise": "restart"}
    _rejected(_profile(processes=[proc]), "name")


def test_ready_probe_must_name_declared_probe() -> None:
    proc = {"name": "web", "command": _cmd(["x"]), "supervise": "restart", "ready_probe": "nope"}
    _rejected(_profile(processes=[proc]), "ready_probe")


def test_image_services_and_unknown_service_fields_rejected() -> None:
    _rejected(_profile(services=[_svc("db", image="postgres:16")]), "image", "not supported")
    _rejected(_profile(services=[_svc("db", volumes=["/data"])]), "volumes")
    _rejected(_profile(services=[_svc("db", depends_on=["ghost"])]), "ghost")


def test_service_cycle_and_required_on_optional_rejected() -> None:
    cyc = [_svc("db", depends_on=["cache"]), _svc("cache", depends_on=["db"])]
    _rejected(_profile(services=cyc), "cycle", code="service_cycle")
    chain = [_svc("db", optional=True), _svc("cache", depends_on=["db"])]
    _rejected(_profile(services=chain), "optional")


def test_service_requires_healthcheck_command_ports() -> None:
    for key in ("healthcheck", "command", "ports"):
        svc = _svc("db")
        del svc[key]
        _rejected(_profile(services=[svc]), key)


def test_unsupported_probe_types_and_fields_rejected() -> None:
    _rejected(_profile(probes=[{"type": "udp", "port": 1}]), "udp", code="profile_unsupported")
    _rejected(
        _profile(probes=[{"type": "mcp_handshake"}]), "mcp.readiness", code="profile_unsupported"
    )
    _rejected(_profile(probes=[{"type": "http", "url": "http://x/", "port": 1}]), "port")
    _rejected(_profile(probes=[{"type": "http", "url": "ftp://x/"}]), "http(s)")
    _rejected(_profile(probes=[{"type": "tcp"}]), "port")
    _rejected(_profile(probes=[{"type": "tcp", "port": 99999}]), "port")
    _rejected(_profile(probes=[{"type": "command", "command": {"argv": ["x"]}}]), "timeout")
    _rejected(_profile(probes=[{"type": "http", "url": "http://x/", "retries": 0}]), "retries")


def test_probes_and_healthcheck_cannot_both_be_set() -> None:
    both = _profile(healthcheck={"type": "tcp", "port": 5000})
    _rejected(both, "not both")


def test_command_env_policy() -> None:
    for bad in ("VULTR_API_KEY", "OPENCODE_TOKEN", "LD_PRELOAD", "KH_CMD", "BASH_ENV", "MSB_X"):
        _rejected(
            _profile(install_commands=[_cmd(["x"], env={bad: "1"})]),
            bad,
            code="profile_unsupported",
        )
    _rejected(_profile(install_commands=[_cmd(["x"], env={"A B": "1"})]), "invalid variable")
    _rejected(_profile(install_commands=[_cmd(["x"], env={"A": 1})]), "must be a string")
    validate_profile(
        _profile(install_commands=[_cmd(["x"], env={"NODE_ENV": "production"})]), phase="runtime"
    )


def test_command_spec_shape() -> None:
    _rejected(
        _profile(install_commands=[{"argv": ["x"], "shell": "y", "timeout_seconds": 1}]), "exactly"
    )
    _rejected(_profile(install_commands=[_cmd(["x"], user="root")]), "user")
    _rejected(_profile(install_commands=[{"argv": [], "timeout_seconds": 1}]), "argv")


def test_stdio_mcp_rejects_fields_it_would_ignore() -> None:
    launch = MCP_STDIO["mcp"]["launch_command"]
    _rejected(
        {**MCP_STDIO, "processes": [{"name": "a", "command": launch, "supervise": "restart"}]},
        "stdio MCP: processes",
    )
    _rejected({**MCP_STDIO, "ports": [3000]}, "stdio MCP: ports")
    _rejected({**MCP_STDIO, "probes": BASE["probes"]}, "stdio MCP: probes")
    _rejected({**MCP_STDIO, "run_commands": [_cmd(["other"])]}, "run_commands must equal")
    # Mirroring mcp.launch_command is fine: the handshake helper launches it.
    validate_profile({**MCP_STDIO, "run_commands": [dict(launch)]}, phase="runtime")


def test_mcp_block_unknown_fields_and_non_mcp_rejected() -> None:
    mcp = {**MCP_STDIO["mcp"], "sandbox": True}
    _rejected({**MCP_STDIO, "mcp": mcp}, "sandbox")
    _rejected(_profile(mcp=MCP_STDIO["mcp"]), "only supported for git_mcp")


def test_bootstrap_profile_cannot_declare_services() -> None:
    boot = {
        "schema_version": "1",
        "intent": "bootstrap",
        "oci_image": "debian",
        "workdir": WORKDIR,
        "services": [_svc("db")],
    }
    with pytest.raises(ProfileError):
        validate_profile(boot, phase="bootstrap")


def test_full_featured_profile_is_accepted() -> None:
    profile = _profile(
        services=[
            _svc("cache", depends_on=["db"], package="redis-server"),
            _svc("db", package=["postgresql"], env={"PGDATA": "/tmp/pg"}),
        ],
        processes=[
            {
                "name": "web",
                "command": _cmd(["npm", "start"], env={"NODE_ENV": "production"}),
                "supervise": "restart",
                "max_restarts": 5,
                "stop_signal": "SIGINT",
                "ready_after_seconds": 0,
                "ready_probe": "root",
            }
        ],
        probes=[
            {
                "name": "root",
                "type": "http",
                "url": "http://127.0.0.1:5000/",
                "body_contains": "ok",
            },
            {"name": "port", "type": "tcp", "port": 5000, "retries": 3},
            {"name": "cmd", "type": "command", "command": _cmd(["true"]), "expect_exit": 0},
        ],
    )
    validate_profile(profile, phase="runtime")
    assert [s["name"] for s in service_launch_order(profile["services"])] == ["db", "cache"]


def test_schema_enums_match_enforced_contract() -> None:
    schema = load_schema()
    defs = schema["$defs"]
    assert set(defs["process"]["properties"]["supervise"]["enum"]) == SUPERVISE_MODES
    assert set(defs["process"]["properties"]["stop_signal"]["enum"]) == STOP_SIGNALS
    assert set(defs["probe"]["properties"]["type"]["enum"]) == PROBE_TYPES
    assert set(schema["properties"]) >= {"services", "processes", "probes", "healthcheck"}
    assert "policy" not in schema["properties"]


def test_run_commands_not_mirrored_become_implied_oneshot_processes() -> None:
    mirrored = _cmd(["npm", "start"], cwd=WORKDIR)
    proc = {"name": "web", "command": {**mirrored, "timeout_seconds": 3600}, "supervise": "restart"}
    profile = _profile(processes=[proc], run_commands=[mirrored, _cmd(["worker"])])
    names = [p["name"] for p in effective_processes(profile)]
    assert names == ["web", "run-1"]
    assert effective_processes(profile)[1]["supervise"] == "oneshot"


# --- execution: fake guest ---------------------------------------------------------------


class FakeGuest:
    """Records every guest script; answers like a guest with configurable behavior."""

    def __init__(self) -> None:
        self.scripts: list[str] = []
        self.alive = True
        self.exit_code = ""
        self.state = ""
        self.fail_substrings: dict[str, ExecResult] = {}
        self.sequences: dict[str, list[ExecResult]] = {}

    def __call__(self, environment_id: str, cmd: Any, **kwargs: Any) -> ExecResult:
        script = cmd[-1] if isinstance(cmd, (list, tuple)) else str(cmd)
        self.scripts.append(script)
        for needle, seq in self.sequences.items():
            if needle in script:
                return seq.pop(0) if len(seq) > 1 else seq[0]
        for needle, result in self.fail_substrings.items():
            if needle in script:
                return result
        if "kh_alive" in script:
            return ExecResult(
                f"kh_alive:{int(self.alive)}\nkh_state:{self.state}\n"
                f"kh_exit:{self.exit_code}\nkh_restarts:\n",
                "",
                0,
            )
        if "nohup" in script:
            return ExecResult("4242\n", "", 0)
        if "http_code" in script:
            return ExecResult("http_code:200\nbody_match:1\n", "", 0)
        return ExecResult("", "", 0)

    def matching(self, needle: str) -> list[str]:
        return [s for s in self.scripts if needle in s]


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LEDGER_URL", f"sqlite:///{(tmp_path / 'l.db').as_posix()}")
    monkeypatch.setenv("REAPER_ENABLED", "false")
    monkeypatch.setenv("PREFLIGHT_ENABLED", "false")
    monkeypatch.setenv("MSB_AUTO_CREATE", "false")
    monkeypatch.setenv("VERIFY_ON_CLAIM", "false")
    monkeypatch.setenv("MAX_REPAIR_ATTEMPTS", "2")
    monkeypatch.setenv("PROFILE_STORAGE", str(tmp_path / "profiles"))
    get_settings.cache_clear()
    reset_ledger_for_tests()
    yield
    reset_ledger_for_tests()
    get_settings.cache_clear()


@pytest.fixture
def guest(monkeypatch: pytest.MonkeyPatch) -> FakeGuest:
    fake = FakeGuest()
    monkeypatch.setattr("verify.exec_command", fake)
    monkeypatch.setattr("install.exec_command", fake)
    monkeypatch.setattr("verify.time.sleep", lambda *_a, **_k: None)
    return fake


def _job(profile: dict[str, Any] | None = None) -> str:
    job = create_job("https://github.com/o/r")
    ledger = get_ledger()
    ledger.append_sandbox_generation(
        job.job_id,
        environment_id="env-x",
        image="debian",
        expires_at=job.expires_at,
        state="running",
    )
    ledger.update_job_fields(job.job_id, resolved_commit=COMMIT)
    if profile is not None:
        ledger.append_profile_revision(
            job.job_id, phase="runtime", schema_version="1", profile=profile, storage_path=None
        )
    return job.job_id


# install: env, cwd, service packages


def test_install_applies_env_and_resolves_relative_cwd(guest: FakeGuest) -> None:
    profile = _profile(
        install_commands=[
            _cmd(["npm", "ci"], env={"NODE_ENV": "production", "MSG": "it's"}, cwd="web"),
            {"shell": "make", "timeout_seconds": 5},
        ]
    )
    steps = run_install_commands("env-x", profile, job_id=_job(), settings=get_settings())
    assert all(s.ok for s in steps)
    first = guest.matching("npm")[0]
    assert "export NODE_ENV='production';" in first
    assert "export MSG='it'\"'\"'s';" in first  # quoting survives hostile values
    assert f"cd '{WORKDIR}/web' || exit 1" in first  # relative cwd -> under workdir
    # Order: cd, then env, then the (possibly tracer-wrapped) command.
    assert first.index("cd ") < first.index("export ") < first.index("npm")
    plain = guest.matching("make")[0]
    assert "export" not in plain and f"cd '{WORKDIR}'" in plain


def test_install_provisions_service_packages_in_dependency_order(guest: FakeGuest) -> None:
    profile = _profile(
        packages=["git"],
        services=[
            _svc("cache", depends_on=["db"], package="redis-server"),
            _svc("db", package=["postgresql", "git"]),
        ],
    )
    run_install_commands("env-x", profile, job_id=_job(), settings=get_settings())
    (pkg_script,) = guest.matching("apt-get install")
    assert "'git' 'postgresql' 'redis-server'" in pkg_script  # deduped, db before cache


# launch: supervision


def _proc(**over: Any) -> dict[str, Any]:
    proc = {
        "name": "web",
        "command": _cmd(["npm", "start"], env={"FOO": "bar"}),
        "supervise": "restart",
        "ready_after_seconds": 0,
    }
    proc.update(over)
    return proc


def test_restart_supervision_is_in_the_launch_script(guest: FakeGuest) -> None:
    launch_supervised_process(
        "env-x",
        _proc(max_restarts=5, stop_signal="SIGHUP"),
        job_id=_job(),
        settings=get_settings(),
        default_cwd=WORKDIR,
        extra_env={"PORT": "5000"},
    )
    script = guest.matching("nohup")[0]
    assert "KH_MODE=restart" in script and "KH_MAX=5" in script and "KH_TIMEOUT=60" in script
    inner = _inner(script)
    assert "export PORT='5000'" in inner and "export FOO='bar'" in inner
    assert "gave_up" in script and "restart" in script  # supervisor loop is shipped, not nohup-only


def test_oneshot_does_not_restart_and_defaults_apply(guest: FakeGuest) -> None:
    launch_supervised_process(
        "env-x",
        _proc(supervise="oneshot"),
        job_id=_job(),
        settings=get_settings(),
        default_cwd=WORKDIR,
    )
    script = guest.matching("nohup")[0]
    assert "KH_MODE=oneshot" in script
    restart = _proc()
    launch_supervised_process(
        "env-x", restart, job_id=_job(), settings=get_settings(), default_cwd=WORKDIR
    )
    assert "KH_MAX=3" in guest.matching("nohup")[1]  # documented default


def test_command_env_wins_over_profile_default_env(guest: FakeGuest) -> None:
    launch_supervised_process(
        "env-x",
        _proc(command=_cmd(["x"], env={"PORT": "9999"})),
        job_id=_job(),
        settings=get_settings(),
        default_cwd=WORKDIR,
        extra_env={"PORT": "5000"},
    )
    inner = _inner(guest.matching("nohup")[0])
    assert "PORT='9999'" in inner and "PORT='5000'" not in inner


def test_dead_process_fails_launch(guest: FakeGuest) -> None:
    guest.alive = False
    guest.state = "gave_up"
    guest.exit_code = "1"
    with pytest.raises(VerifyError) as err:
        launch_supervised_process(
            "env-x", _proc(), job_id=_job(), settings=get_settings(), default_cwd=WORKDIR
        )
    assert err.value.code == "process_exited"
    # A oneshot that exited 0 is fine (migration-style launch).
    guest.state, guest.exit_code = "exited", "0"
    handle = launch_supervised_process(
        "env-x",
        _proc(supervise="oneshot"),
        job_id=_job(),
        settings=get_settings(),
        default_cwd=WORKDIR,
    )
    assert handle["state"]["exit_code"] == 0


def test_stop_uses_declared_signal_then_kill(guest: FakeGuest) -> None:
    handle = launch_supervised_process(
        "env-x",
        _proc(stop_signal="SIGINT"),
        job_id=_job(),
        settings=get_settings(),
        default_cwd=WORKDIR,
    )
    stop_supervised_process("env-x", handle, job_id=_job(), settings=get_settings())
    stop = guest.matching("kh_kill_tree")[0]
    assert 'kh_kill_tree "$child" INT' in stop
    assert 'kh_kill_tree "$child" KILL' in stop  # escalation after the grace period
    assert "kill -s TERM 4242" in stop  # supervisor itself
    assert "web.stop" in stop  # stop flag prevents a restart


# probes: pass criteria


def test_http_default_accept_is_200_to_399_and_body_match(guest: FakeGuest) -> None:
    jid = _job()
    guest.fail_substrings["http_code"] = ExecResult("http_code:302\n", "", 0)
    ok = probe_http("env-x", {"url": "http://127.0.0.1/"}, job_id=jid, settings=get_settings())
    assert ok["ok"] is True and ok["accept"] == "200-399"
    guest.fail_substrings["http_code"] = ExecResult("http_code:404\n", "", 0)
    bad = probe_http("env-x", {"url": "http://127.0.0.1/"}, job_id=jid, settings=get_settings())
    assert bad["ok"] is False
    # Status fine but body missing -> fail; the grep for the substring is in the script.
    guest.fail_substrings["http_code"] = ExecResult("http_code:200\nbody_match:0\n", "", 0)
    probe = {"url": "http://127.0.0.1/", "body_contains": "hello", "accept": [200]}
    miss = probe_http("env-x", probe, job_id=jid, settings=get_settings())
    assert miss["ok"] is False and miss["body_matched"] is False
    assert "grep -qF -- 'hello'" in guest.matching("http_code")[-1].replace('"', "")


def test_tcp_probe_passes_on_connect_exit_zero(guest: FakeGuest) -> None:
    jid = _job()
    ok = probe_tcp("env-x", {"port": 5432}, job_id=jid, settings=get_settings())
    assert ok["ok"] is True and ok["port"] == 5432 and ok["host"] == "127.0.0.1"
    assert "create_connection" in guest.matching("5432")[0]
    guest.fail_substrings["create_connection"] = ExecResult("", "refused", 1)
    assert probe_tcp("env-x", {"port": 5432}, job_id=jid, settings=get_settings())["ok"] is False
    guest.fail_substrings["create_connection"] = ExecResult("tooling_missing\n", "", 3)
    res = probe_tcp("env-x", {"port": 5432}, job_id=jid, settings=get_settings())
    assert res["ok"] is False and res["error"] == "tooling_missing"


def test_command_probe_exit_and_stdout_criteria(guest: FakeGuest) -> None:
    jid = _job()
    probe = {
        "name": "db-ready",
        "command": _cmd(["pg_isready"], env={"PGHOST": "127.0.0.1"}),
        "stdout_contains": "accepting",
    }
    guest.fail_substrings["pg_isready"] = ExecResult("accepting connections\n", "", 0)
    ok = probe_command("env-x", probe, job_id=jid, settings=get_settings(), workdir=WORKDIR)
    assert ok["ok"] is True and "accepting" in ok["stdout_tail"]
    assert "export PGHOST='127.0.0.1'" in guest.matching("pg_isready")[0]
    guest.fail_substrings["pg_isready"] = ExecResult("no response\n", "", 0)
    assert probe_command("env-x", probe, job_id=jid, settings=get_settings())["ok"] is False
    guest.fail_substrings["pg_isready"] = ExecResult("accepting\n", "", 2)
    assert probe_command("env-x", probe, job_id=jid, settings=get_settings())["ok"] is False
    # expect_exit overrides the default 0.
    guest.fail_substrings["pg_isready"] = ExecResult("accepting\n", "", 2)
    expecting = {**probe, "expect_exit": 2}
    assert probe_command("env-x", expecting, job_id=jid, settings=get_settings())["ok"] is True


def test_run_probe_retries_until_pass(guest: FakeGuest) -> None:
    guest.sequences["create_connection"] = [
        ExecResult("", "", 1),
        ExecResult("", "", 1),
        ExecResult("", "", 0),
    ]
    probe = {"type": "tcp", "port": 8080, "retries": 5, "interval_seconds": 0}
    res = run_probe("env-x", probe, job_id=_job(), settings=get_settings())
    assert res["ok"] is True and res["attempts"] == 3
    guest.sequences["create_connection"] = [ExecResult("", "", 1)]
    res = run_probe("env-x", {**probe, "retries": 2}, job_id=_job(), settings=get_settings())
    assert res["ok"] is False and res["attempts"] == 2


# services: ordering and health checks


def _inner(script: str) -> str:
    """The command the supervisor runs (KH_CMD is shell-quoted inside the launch script)."""
    head = script.split(" && nohup")[0]
    return next(t[len("KH_CMD=") :] for t in shlex.split(head) if t.startswith("KH_CMD="))


def _launch_order(guest: FakeGuest) -> list[str]:
    names = []
    for script in guest.matching("nohup"):
        names.append(script.split("KH_NAME='")[1].split("'")[0])
    return names


def test_services_start_in_dependency_order_and_gate_on_health(guest: FakeGuest) -> None:
    profile = _profile(
        services=[
            _svc("queue", depends_on=["cache"]),
            _svc("cache", depends_on=["db"], env={"CACHE_MODE": "lru"}),
            _svc("db"),
        ]
    )
    handles: list[dict[str, Any]] = []
    out = start_services("env-x", profile, job_id=_job(), settings=get_settings(), handles=handles)
    assert _launch_order(guest) == ["svc-db", "svc-cache", "svc-queue"]
    assert [h["name"] for h in handles] == ["svc-db", "svc-cache", "svc-queue"]
    assert all(e["ok"] for e in out)
    # Port wait + declared healthcheck both ran for each service before its dependents.
    first_cache_launch = next(i for i, s in enumerate(guest.scripts) if "svc-cache" in s)
    db_checks = [i for i, s in enumerate(guest.scripts) if "create_connection" in s and "5432" in s]
    assert db_checks and max(db_checks[:1]) < first_cache_launch
    cache_launch = next(s for s in guest.matching("nohup") if "svc-cache" in s)
    assert "export CACHE_MODE='lru'" in _inner(cache_launch)
    # Services default to restart supervision.
    assert "KH_MODE=restart" in guest.matching("nohup")[0]


def test_required_service_health_failure_stops_the_stack(guest: FakeGuest) -> None:
    profile = _profile(services=[_svc("db"), _svc("cache", depends_on=["db"])])
    guest.fail_substrings["create_connection"] = ExecResult("", "refused", 1)
    with pytest.raises(VerifyError) as err:
        start_services("env-x", profile, job_id=_job(), settings=get_settings(), handles=[])
    assert err.value.code == "service_failed"
    assert _launch_order(guest) == ["svc-db"]  # dependent never started


def test_optional_service_failure_is_flagged_not_fatal(guest: FakeGuest) -> None:
    profile = _profile(
        services=[
            _svc("db", optional=True, healthcheck={"type": "tcp", "port": 5432, "retries": 1}),
            _svc("cache", optional=True, depends_on=["db"]),
            _svc("queue"),
        ]
    )
    guest.fail_substrings["5432"] = ExecResult("", "refused", 1)
    out = start_services("env-x", profile, job_id=_job(), settings=get_settings(), handles=[])
    by_name = {e["service"]: e for e in out}
    assert by_name["db"]["ok"] is False
    assert by_name["cache"]["ok"] is False and "dependency db failed" in by_name["cache"]["error"]
    assert by_name["queue"]["ok"] is True
    assert "svc-cache" not in _launch_order(guest)


# verify_readiness end to end


def test_verify_runs_tcp_and_command_probes_and_gates_on_all(guest: FakeGuest) -> None:
    profile = _profile(
        processes=[_proc(ready_probe="up")],
        probes=[
            {"name": "up", "type": "tcp", "port": 5000},
            {"name": "check", "type": "command", "command": _cmd(["./check.sh"])},
            {"name": "root", "type": "http", "url": "http://127.0.0.1:5000/"},
        ],
    )
    job_id = _job(profile)
    result = verify_readiness(job_id, settings=get_settings())
    assert result.passed is True
    kinds = [p["type"] for p in result.verify_result["probes"]]
    assert kinds == ["tcp", "command", "http"]  # none filtered out
    assert guest.matching("check.sh")
    # Launch order: process, its ready_probe, then the full probe set.
    assert result.verify_result["processes"][0]["ready_probe"]["ok"] is True

    guest.fail_substrings["check.sh"] = ExecResult("", "bad", 1)
    failing = _job(profile)
    res = verify_readiness(failing, settings=get_settings())
    assert res.passed is False
    assert res.verification_kind == "setup_failed"


def test_failed_attempt_cleans_up_processes_before_relaunch(guest: FakeGuest) -> None:
    profile = _profile(processes=[_proc()])
    guest.fail_substrings["http_code"] = ExecResult("http_code:500\n", "", 0)
    job_id = _job(profile)
    result = verify_readiness(job_id, settings=get_settings())
    assert result.passed is False
    launches = guest.matching("nohup")
    stops = guest.matching("kh_kill_tree")
    assert len(launches) == 2 and len(stops) == 2  # MAX_REPAIR_ATTEMPTS=2: launch+stop each
    first_stop = next(i for i, s in enumerate(guest.scripts) if "kh_kill_tree" in s)
    second_launch = [i for i, s in enumerate(guest.scripts) if "nohup" in s][1]
    assert first_stop < second_launch


def test_passing_verify_leaves_stack_running(guest: FakeGuest) -> None:
    job_id = _job(_profile(processes=[_proc()]))
    assert verify_readiness(job_id, settings=get_settings()).passed is True
    assert guest.matching("kh_kill_tree") == []  # stills/scans still need the app


def test_process_ready_probe_failure_is_reported(guest: FakeGuest) -> None:
    profile = _profile(
        processes=[_proc(ready_probe="up")],
        probes=[{"name": "up", "type": "tcp", "port": 5000, "retries": 2, "interval_seconds": 0}],
    )
    guest.fail_substrings["create_connection"] = ExecResult("", "refused", 1)
    result = verify_readiness(_job(profile), settings=get_settings())
    assert result.passed is False
    assert result.verify_result["code"] == "process_not_ready"


def test_verify_launches_services_before_processes(guest: FakeGuest) -> None:
    profile = _profile(services=[_svc("db")], processes=[_proc()])
    result = verify_readiness(_job(profile), settings=get_settings())
    assert result.passed is True
    assert _launch_order(guest)[:2] == ["svc-db", "web"]
    assert result.verify_result["services"][0]["service"] == "db"


def test_implied_run_command_is_launched(guest: FakeGuest) -> None:
    profile = _profile(run_commands=[_cmd(["./serve"], cwd="app")])
    result = verify_readiness(_job(profile), settings=get_settings())
    assert result.passed is True
    assert _launch_order(guest) == ["run-0"]
    assert "KH_MODE=oneshot" in guest.matching("nohup")[0]
    assert f"cd '{WORKDIR}/app'" in _inner(guest.matching("nohup")[0])


def test_streamable_http_mcp_launches_server_and_handshakes(
    guest: FakeGuest, monkeypatch: pytest.MonkeyPatch
) -> None:
    mcp = {
        "transport": "streamable_http",
        "url": "http://127.0.0.1:8000/mcp",
        "launch_command": _cmd(["node", "server.js"], env={"MCP_MODE": "http"}),
        "readiness": {"type": "mcp_handshake", "timeout_seconds": 5},
    }
    profile = {**MCP_STDIO, "mcp": mcp, "ports": [8000]}
    validate_profile(profile, phase="runtime")
    tools = json.dumps({"result": {"tools": [{"name": "t"}]}})
    guest.fail_substrings["killhub-mcp-http.out 2>/dev/null"] = ExecResult(tools, "", 0)
    result = verify_readiness(_job(profile), settings=get_settings())
    assert result.passed is True
    launch = guest.matching("nohup")[0]  # launch_command was not left unexecuted
    assert "KH_NAME='mcp-launch'" in launch and "export MCP_MODE='http'" in _inner(launch)
    assert "export PORT='8000'" in _inner(launch)


def test_stdio_mcp_launch_env_and_relative_cwd_applied(guest: FakeGuest, monkeypatch) -> None:
    monkeypatch.setattr("verify.copy_in", lambda *a, **k: None)
    evidence = json.dumps({"ok": True, "tool_count": 1, "tool_names": ["t"]})
    guest.fail_substrings["mcp_stdio_verify"] = ExecResult(evidence + "\n", "", 0)
    profile = copy.deepcopy(MCP_STDIO)
    profile["mcp"]["launch_command"].update(env={"MCP_TOKEN_FILE": "/tmp/x"}, cwd="pkg")
    out = verify_mcp_stdio("env-x", profile, job_id=_job(), settings=get_settings())
    assert out["ok"] is True
    script = guest.matching("mcp_stdio_verify")[0]
    assert f"cd '{WORKDIR}/pkg' || exit 1; export MCP_TOKEN_FILE='/tmp/x';" in script
