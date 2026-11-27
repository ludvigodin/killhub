"""Vultr Container Registry image ref + host-cred gate (D74)."""

from __future__ import annotations

import pytest

from errors import HarnessError
from harness import default_bootstrap_plan, plan_for_image
from paths import FORBIDDEN_ENV_KEYS, guest_env_has_forbidden_keys
from registry import (
    has_digest_pin,
    is_vultr_cr_ref,
    parse_oci_image_ref,
    require_host_registry_pull_ready,
    validate_oci_image_ref,
)

DIGEST = "sha256:" + ("a" * 64)
CR_IMAGE = f"ewr.vultrcr.com/killhub/bootstrap@{DIGEST}"


def test_is_vultr_cr_ref_and_digest() -> None:
    assert is_vultr_cr_ref(CR_IMAGE)
    assert is_vultr_cr_ref("fra.vultrcr.com/killhub/runtime:v1")
    assert not is_vultr_cr_ref("debian")
    assert not is_vultr_cr_ref("ghcr.io/org/img:1")
    assert has_digest_pin(CR_IMAGE)
    assert not has_digest_pin("ewr.vultrcr.com/killhub/bootstrap:latest")


def test_parse_vultr_cr_digest_and_tag() -> None:
    pinned = parse_oci_image_ref(CR_IMAGE)
    assert pinned.is_vultr_cr
    assert pinned.host == "ewr.vultrcr.com"
    assert pinned.path == "killhub/bootstrap"
    assert pinned.digest == DIGEST
    assert pinned.tag is None

    tagged = validate_oci_image_ref("ams.vultrcr.com/killhub/bootstrap:v2")
    assert tagged.tag == "v2"
    assert tagged.digest is None


def test_public_image_skips_cred_gate(monkeypatch) -> None:
    monkeypatch.setenv("MSB_DEFAULT_IMAGE", "debian")
    monkeypatch.delenv("VULTR_CR_ROBOT_USERNAME", raising=False)
    monkeypatch.delenv("VULTR_CR_ROBOT_PASSWORD", raising=False)
    from config import get_settings

    get_settings.cache_clear()
    cfg = get_settings()
    assert require_host_registry_pull_ready("debian", cfg).is_vultr_cr is False
    plan = default_bootstrap_plan(cfg)
    assert plan.image == "debian"


def test_vultr_cr_fail_closed_without_robot(monkeypatch) -> None:
    monkeypatch.setenv("MSB_DEFAULT_IMAGE", CR_IMAGE)
    monkeypatch.setenv("VULTR_CR_REQUIRE_CREDS", "true")
    monkeypatch.delenv("VULTR_CR_ROBOT_USERNAME", raising=False)
    monkeypatch.delenv("VULTR_CR_ROBOT_PASSWORD", raising=False)
    from config import get_settings

    get_settings.cache_clear()
    cfg = get_settings()
    with pytest.raises(HarnessError) as err:
        require_host_registry_pull_ready(CR_IMAGE, cfg)
    assert err.value.code == "registry_creds_missing"

    with pytest.raises(HarnessError) as err2:
        default_bootstrap_plan(cfg)
    assert err2.value.code == "registry_creds_missing"


def test_vultr_cr_ok_with_robot_creds(monkeypatch) -> None:
    monkeypatch.setenv("MSB_DEFAULT_IMAGE", CR_IMAGE)
    monkeypatch.setenv("VULTR_CR_REQUIRE_CREDS", "true")
    monkeypatch.setenv("VULTR_CR_ROBOT_USERNAME", "robot$killhub+pull")
    monkeypatch.setenv("VULTR_CR_ROBOT_PASSWORD", "not-a-real-secret")
    from config import get_settings

    get_settings.cache_clear()
    cfg = get_settings()
    parsed = require_host_registry_pull_ready(CR_IMAGE, cfg)
    assert parsed.digest == DIGEST
    plan = default_bootstrap_plan(cfg)
    assert plan.image == CR_IMAGE
    # Guest plan must not carry registry secrets.
    assert plan.env == ()


def test_vultr_cr_require_creds_opt_out(monkeypatch) -> None:
    monkeypatch.setenv("MSB_DEFAULT_IMAGE", "ewr.vultrcr.com/killhub/bootstrap:dev")
    monkeypatch.setenv("VULTR_CR_REQUIRE_CREDS", "false")
    monkeypatch.delenv("VULTR_CR_ROBOT_USERNAME", raising=False)
    monkeypatch.delenv("VULTR_CR_ROBOT_PASSWORD", raising=False)
    from config import get_settings

    get_settings.cache_clear()
    cfg = get_settings()
    plan = default_bootstrap_plan(cfg)
    assert "vultrcr.com" in plan.image


def test_plan_for_image_gates_runtime_replace(monkeypatch) -> None:
    monkeypatch.setenv("MSB_DEFAULT_IMAGE", "debian")
    monkeypatch.setenv("VULTR_CR_REQUIRE_CREDS", "true")
    monkeypatch.delenv("VULTR_CR_ROBOT_USERNAME", raising=False)
    monkeypatch.delenv("VULTR_CR_ROBOT_PASSWORD", raising=False)
    from config import get_settings

    get_settings.cache_clear()
    cfg = get_settings()
    with pytest.raises(HarnessError) as err:
        plan_for_image(CR_IMAGE, settings=cfg, replace=True)
    assert err.value.code == "registry_creds_missing"


def test_guest_env_forbids_registry_robot_keys() -> None:
    assert "VULTR_CR_ROBOT_PASSWORD" in FORBIDDEN_ENV_KEYS
    assert "VULTR_CR_ROBOT_USERNAME" in FORBIDDEN_ENV_KEYS
    blob = "PATH=/bin\nVULTR_CR_ROBOT_PASSWORD=leak\nHOME=/root\n"
    found = guest_env_has_forbidden_keys(blob)
    assert "VULTR_CR_ROBOT_PASSWORD" in found
