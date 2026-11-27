"""Network policy + canary helpers (D39, D44)."""

from __future__ import annotations

import pytest

from canaries import generate_canaries, network_probe, persist_canaries, scan_canaries
from errors import HarnessError
from harness import EnvironmentPlan, MsbCli, apply_killhub_net_policy
from net_policy import install_phase_policy, verify_phase_policy


def test_install_policy_always_denies_host_private_meta(monkeypatch) -> None:
    monkeypatch.setenv("CONTROL_PLANE_DENY_HOSTS", "jobs.example.com,203.0.113.10")
    monkeypatch.setenv("MSB_HOST", "root@203.0.113.50")
    monkeypatch.setenv("MSB_NET_POLICY", "")
    from config import get_settings

    get_settings.cache_clear()
    policy = install_phase_policy(get_settings())
    assert policy.profiles == ("public",)
    assert policy.rules[0] == "allow@dns"
    assert "deny@host" in policy.rules
    assert "deny@private" in policy.rules
    assert policy.rules.index("allow@dns") < policy.rules.index("deny@private")
    assert "deny@meta" in policy.rules
    assert "deny@jobs.example.com" in policy.rules
    assert "deny@203.0.113.10" in policy.rules
    assert "deny@203.0.113.50" in policy.rules
    get_settings.cache_clear()


def test_verify_phase_is_no_net() -> None:
    policy = verify_phase_policy()
    assert policy.no_net is True
    assert "--no-net" in policy.as_msb_args()


def test_create_refuses_empty_net_policy(monkeypatch) -> None:
    from config import get_settings

    get_settings.cache_clear()
    cfg = get_settings()
    cli = MsbCli(cfg, runner=lambda argv, timeout: (_ for _ in ()).throw(AssertionError()))
    plan = EnvironmentPlan(image="debian", cpus=1, memory="512M")
    with pytest.raises(HarnessError) as err:
        cli.create(name="x", plan=plan, labels={})
    assert err.value.code == "net_policy_required"
    get_settings.cache_clear()


def test_apply_killhub_net_policy_merges(monkeypatch) -> None:
    monkeypatch.setenv("CONTROL_PLANE_DENY_HOSTS", "")
    monkeypatch.setenv("MSB_HOST", "local")
    from config import get_settings

    get_settings.cache_clear()
    plan = EnvironmentPlan(
        image="debian",
        cpus=1,
        memory="512M",
        net_rules=("allow@example.com",),
    )
    merged = apply_killhub_net_policy(plan, get_settings())
    assert "public" in merged.net_profiles
    assert "deny@host" in merged.net_rules
    assert "allow@example.com" in merged.net_rules
    get_settings.cache_clear()


def test_canary_persist_and_stubs(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CANARY_STORAGE", str(tmp_path / "canaries"))
    from config import get_settings

    get_settings.cache_clear()
    cans = generate_canaries("job-abc")
    path = persist_canaries(cans)
    assert path.exists()
    text = path.read_text()
    assert "KILLHUB_CANARY_TOKEN" in text
    summary = cans.public_summary()
    assert "fingerprints" in summary
    assert cans.env["KILLHUB_CANARY_TOKEN"] not in str(summary)

    # No sandbox — install-phase network_probe returns retained/missing summary.
    probe = network_probe("env", job_id="job-abc", phase="install")
    assert probe["phase"] == "install"
    assert probe["claim"] in {"incomplete", "proven"}
    # scan without guest exec would fail; plant-only record still loads.
    from canaries import load_canaries

    assert load_canaries("job-abc") is not None
    get_settings.cache_clear()
    _ = scan_canaries  # imported for module surface stability
