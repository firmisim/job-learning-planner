from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import unicodedata
from uuid import UUID

from schemas.core import CapabilityCatalogDocument


RECALL_TOP_K = 5
RECALL_THRESHOLD = 0.68
RECALL_HISTORY_LIMIT = 3
CAPABILITY_SEARCH_LIMIT = 10

_WRAPPER_PUNCTUATION = re.compile(r"[\(\)\[\]\{\}<>,;:，；：、'\"“”‘’]+")
_SPACING_SEPARATORS = re.compile(r"[\s\-_–—]+")


@dataclass(frozen=True)
class RecalledCapability:
    capability_id: UUID
    canonical_name: str
    historical_expressions: tuple[str, ...]


def normalize_recall_text(value: str) -> str:
    """Normalize recall text without stripping technical operators."""

    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    normalized = _WRAPPER_PUNCTUATION.sub(" ", normalized)
    normalized = _SPACING_SEPARATORS.sub(" ", normalized)
    return " ".join(normalized.split())


def _compact(value: str) -> str:
    return value.replace(" ", "")


def _character_ngrams(value: str, size: int = 3) -> set[str]:
    if len(value) < size:
        return set()
    return {value[index : index + size] for index in range(len(value) - size + 1)}


def recall_similarity(left: str, right: str) -> float:
    first = normalize_recall_text(left)
    second = normalize_recall_text(right)
    if not first or not second:
        return 0.0
    first_compact = _compact(first)
    second_compact = _compact(second)
    if first_compact == second_compact:
        return 1.0

    score = 0.0
    first_tokens = set(first.split())
    second_tokens = set(second.split())
    if first_tokens and second_tokens:
        overlap = 2 * len(first_tokens & second_tokens) / (
            len(first_tokens) + len(second_tokens)
        )
        score = max(score, 0.45 + 0.4 * overlap)

    shorter, longer = sorted((first_compact, second_compact), key=len)
    if len(shorter) >= 5 and shorter in longer:
        score = max(score, 0.72 + 0.18 * (len(shorter) / len(longer)))

    score = max(
        score,
        0.82 * SequenceMatcher(None, first_compact, second_compact).ratio(),
    )
    first_ngrams = _character_ngrams(first_compact)
    second_ngrams = _character_ngrams(second_compact)
    if first_ngrams and second_ngrams:
        ngram_overlap = 2 * len(first_ngrams & second_ngrams) / (
            len(first_ngrams) + len(second_ngrams)
        )
        score = max(score, 0.75 * ngram_overlap)
    return min(score, 1.0)


def _history_by_capability(
    catalog: CapabilityCatalogDocument,
) -> dict[UUID, list[str]]:
    result: dict[UUID, list[str]] = {}
    for mapping in catalog.source_mappings:
        result.setdefault(mapping.capability_id, []).append(mapping.source_expression)
    return result


def _representative_history(
    expression: str, historical: list[str]
) -> tuple[str, ...]:
    return tuple(
        sorted(
            historical,
            key=lambda value: (-recall_similarity(expression, value), value.casefold()),
        )[:RECALL_HISTORY_LIMIT]
    )


def recall_merge_candidates(
    expression: str,
    catalog: CapabilityCatalogDocument,
    *,
    top_k: int = RECALL_TOP_K,
    threshold: float = RECALL_THRESHOLD,
) -> tuple[RecalledCapability, ...]:
    if top_k < 1:
        return ()
    history = _history_by_capability(catalog)
    ranked: list[tuple[float, str, str, RecalledCapability]] = []
    for capability in catalog.capabilities:
        historical = history.get(capability.capability_id, [])
        score = max(
            recall_similarity(expression, value)
            for value in (capability.name, *historical)
        )
        if score < threshold:
            continue
        ranked.append(
            (
                -score,
                capability.name.casefold(),
                str(capability.capability_id),
                RecalledCapability(
                    capability.capability_id,
                    capability.name,
                    _representative_history(expression, historical),
                ),
            )
        )
    ranked.sort(key=lambda item: item[:3])
    return tuple(item[3] for item in ranked[:top_k])


def search_capabilities(
    query: str,
    catalog: CapabilityCatalogDocument,
    *,
    limit: int = CAPABILITY_SEARCH_LIMIT,
) -> tuple[RecalledCapability, ...]:
    normalized_query = normalize_recall_text(query)
    if not normalized_query or limit < 1:
        return ()
    compact_query = _compact(normalized_query)
    history = _history_by_capability(catalog)
    ranked: list[tuple[float, str, str, RecalledCapability]] = []
    for capability in catalog.capabilities:
        historical = history.get(capability.capability_id, [])
        representations = (capability.name, *historical)
        normalized_values = [normalize_recall_text(value) for value in representations]
        substring_match = any(
            normalized_query in value or compact_query in _compact(value)
            for value in normalized_values
        )
        score = max(recall_similarity(query, value) for value in representations)
        if not substring_match and score < RECALL_THRESHOLD:
            continue
        ranked.append(
            (
                -score,
                capability.name.casefold(),
                str(capability.capability_id),
                RecalledCapability(
                    capability.capability_id,
                    capability.name,
                    _representative_history(query, historical),
                ),
            )
        )
    ranked.sort(key=lambda item: item[:3])
    return tuple(item[3] for item in ranked[:limit])
