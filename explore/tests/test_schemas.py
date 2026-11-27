"""Canonical JSON schema validity and directory parity tests.

What this module does:
    Validates that every JSON Schema file under ``schemas/`` and
    ``explore/schemas/`` conforms to JSON Schema Draft 2020-12 and that both
    directories stay synchronized with the exact canonical set of 4 schemas.

Plane & trust-zone responsibility:
    Plane 1 (control-plane) static schema validation test suite; executes no
    Plane 2 microVM workloads or external network calls.

Key contracts / invariants:
    - ``schemas/`` and ``explore/schemas/`` must contain the exact same 4
      schema filenames (``environment_profile.v1.json``,
      ``dynamic_install_spec.v1.json``, ``test_scenario_plan.v1.json``,
      ``detonation_verdict.v1.json``) with byte-for-byte identical contents.
    - Every file under ``explore/schemas/`` must be a regular file (never a
      symlink escaping ``./explore``) so ``docker-compose.yml`` builds with
      ``context: ./explore`` remain self-contained.
    - All schemas must pass ``Draft202012Validator.check_schema``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_DIR = REPO_ROOT / "schemas"
EXPLORE_DIR = REPO_ROOT / "explore" / "schemas"
EXPECTED_SCHEMA_NAMES = (
    "detonation_verdict.v1.json",
    "dynamic_install_spec.v1.json",
    "environment_profile.v1.json",
    "test_scenario_plan.v1.json",
)


def test_schema_directories_match_exact_canonical_set_and_bytes() -> None:
    canonical_files = sorted(path.name for path in CANONICAL_DIR.glob("*.json"))
    explore_files = sorted(path.name for path in EXPLORE_DIR.glob("*.json"))

    assert canonical_files == sorted(EXPECTED_SCHEMA_NAMES)
    assert explore_files == sorted(EXPECTED_SCHEMA_NAMES)

    for name in EXPECTED_SCHEMA_NAMES:
        canonical_path = CANONICAL_DIR / name
        explore_path = EXPLORE_DIR / name

        # Docker builds with context ./explore; symlinks out of explore/ would dangle.
        assert not explore_path.is_symlink(), f"{explore_path} must be a regular file"
        assert explore_path.is_file()
        assert canonical_path.read_bytes() == explore_path.read_bytes(), (
            f"Schema mismatch between {canonical_path} and {explore_path}"
        )


@pytest.mark.parametrize(
    "schema_path",
    [
        *(CANONICAL_DIR / name for name in EXPECTED_SCHEMA_NAMES),
        *(EXPLORE_DIR / name for name in EXPECTED_SCHEMA_NAMES),
    ],
    ids=lambda path: f"{path.parent.name}/{path.name}",
)
def test_schema_passes_draft_2020_12_validation(schema_path: Path) -> None:
    # Ensure every canonical and mirrored schema parses cleanly as Draft 2020-12.
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
