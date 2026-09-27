from __future__ import annotations

from schemas.core import Capability, CapabilityCatalogDocument, SourceMapping
from src.capability_recall import (
    RECALL_HISTORY_LIMIT,
    RECALL_TOP_K,
    normalize_recall_text,
    recall_merge_candidates,
    search_capabilities,
)


def test_recall_normalization_preserves_technical_operators() -> None:
    assert normalize_recall_text("  Fast API  ") == "fast api"
    assert normalize_recall_text("Ｆａｓｔ－ＡＰＩ") == "fast api"
    assert normalize_recall_text("C++") == "c++"
    assert normalize_recall_text("C#") == "c#"
    assert normalize_recall_text(".NET") == ".net"
    assert normalize_recall_text("CI/CD") == "ci/cd"
    assert normalize_recall_text("TCP/IP") == "tcp/ip"
    assert normalize_recall_text("I/O") == "i/o"


def test_recall_uses_canonical_and_historical_text_with_threshold_and_top_k() -> None:
    fastapi = Capability(name="Web Backend Integration")
    docker = Capability(name="Docker")
    unrelated = [Capability(name=f"Payroll Domain {index}") for index in range(8)]
    catalog = CapabilityCatalogDocument(
        capabilities=[fastapi, docker, *unrelated],
        source_mappings=[
            SourceMapping.create("Fast API", fastapi.capability_id),
            SourceMapping.create("ASGI API framework", fastapi.capability_id),
            SourceMapping.create("Python web endpoints", fastapi.capability_id),
            SourceMapping.create("Service routing", fastapi.capability_id),
            SourceMapping.create("Container tooling", docker.capability_id),
        ],
    )

    historical_match = recall_merge_candidates("Fast-API development", catalog)
    canonical_match = recall_merge_candidates("Docker containers", catalog)
    unrelated_match = recall_merge_candidates("Financial forecasting", catalog)

    assert historical_match[0].capability_id == fastapi.capability_id
    assert len(historical_match[0].historical_expressions) == RECALL_HISTORY_LIMIT
    assert canonical_match[0].capability_id == docker.capability_id
    assert unrelated_match == ()
    assert len(historical_match) <= RECALL_TOP_K


def test_recall_never_fills_top_k_with_weak_items() -> None:
    capabilities = [Capability(name=f"Data Platform {index}") for index in range(7)]
    catalog = CapabilityCatalogDocument(capabilities=capabilities)

    recalled = recall_merge_candidates("Data Platform", catalog)

    assert len(recalled) == RECALL_TOP_K
    assert all(item.canonical_name.startswith("Data Platform") for item in recalled)


def test_search_all_is_empty_without_query_and_matches_name_or_history() -> None:
    capability = Capability(name="Web Backend Integration")
    catalog = CapabilityCatalogDocument(
        capabilities=[capability, Capability(name="Unrelated")],
        source_mappings=[SourceMapping.create("Fast API", capability.capability_id)],
    )

    assert search_capabilities("", catalog) == ()
    assert search_capabilities("Web Backend", catalog)[0].capability_id == (
        capability.capability_id
    )
    assert search_capabilities("Fast API", catalog)[0].capability_id == (
        capability.capability_id
    )
