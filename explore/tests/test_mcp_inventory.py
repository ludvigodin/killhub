"""Verify the Plane 2 read-only inventory projection with synthetic MCP pages."""

import pytest

from helpers.mcp_stdio_verify import collect_inventory
from verify import compare_mcp_inventory


def test_inventory_is_order_independent_and_contains_only_counts_and_digests() -> None:
    alpha = {"name": "alpha", "description": "fixture metadata", "inputSchema": {"type": "object"}}
    beta = {"name": "beta"}

    def no_request(method: str, params: dict) -> dict:
        pytest.fail(f"Unexpected request: {method} {params}")

    first = collect_inventory({}, {"tools": [alpha, beta]}, no_request)
    reordered = collect_inventory({}, {"tools": [beta, alpha]}, no_request)
    changed = collect_inventory(
        {}, {"tools": [beta, {**alpha, "description": "changed"}]}, no_request
    )

    assert first == reordered
    assert set(first["tools"]) == {"status", "count", "sha256"}
    assert first["tools"]["count"] == 2
    assert first["tools"]["sha256"] != changed["tools"]["sha256"]
    assert first["resources"] == first["prompts"] == {"status": "unsupported"}


def test_inventory_lists_advertised_collections_and_follows_cursor() -> None:
    requests = []

    def request(method: str, params: dict) -> dict:
        requests.append((method, params))
        return {
            "tools/list": {"tools": [{"name": "beta"}]},
            "resources/list": {"resources": [{"uri": "file:///trusted"}]},
            "prompts/list": {"prompts": []},
        }[method]

    result = collect_inventory(
        {"resources": {}, "prompts": {}},
        {"tools": [{"name": "alpha"}], "nextCursor": "next"},
        request,
    )
    assert requests == [
        ("tools/list", {"cursor": "next"}),
        ("resources/list", {}),
        ("prompts/list", {}),
    ]
    assert [result[key]["count"] for key in ("tools", "resources", "prompts")] == [2, 1, 0]


def test_incomplete_collection_keeps_other_inventory_evidence() -> None:
    def request(method: str, params: dict) -> dict:
        if method == "tools/list":
            return {"tools": [], "nextCursor": params["cursor"]}
        raise TimeoutError("fixture did not respond")

    result = collect_inventory(
        {"resources": {}}, {"tools": [{"name": "alpha"}], "nextCursor": "repeat"}, request
    )
    assert result == {
        "tools": {"status": "unavailable"},
        "resources": {"status": "unavailable"},
        "prompts": {"status": "unsupported"},
    }


def test_inventory_comparison_requires_two_complete_records() -> None:
    recorded = {"status": "recorded", "count": 1, "sha256": "a" * 64}
    partial = {"status": "unavailable"}
    comparison = compare_mcp_inventory(
        {"tools": recorded, "resources": recorded, "prompts": partial},
        {
            "tools": recorded,
            "resources": {**recorded, "sha256": "b" * 64},
            "prompts": partial,
        },
    )
    assert comparison["tools"]["status"] == "unchanged"
    assert comparison["resources"]["status"] == "changed"
    assert comparison["prompts"] == {"status": "unavailable"}
