from __future__ import annotations

from collections.abc import Iterable


LEGACY_LEVEL_ALIASES = {
    "easy": "beginner",
    "hard": "developing",
    "extremely hard": "advancing",
}

LEVEL_LABELS = {
    "beginner": "Beginner",
    "developing": "Developing",
    "advancing": "Advancing",
}

LEVEL_ORDER = {
    "beginner": 0,
    "developing": 1,
    "advancing": 2,
}

LEVEL_PROMPT_GUIDANCE = {
    "beginner": (
        "Use short sentences, very common words, strong visual clues, and direct examples "
        "that a new learner can repeat right away."
    ),
    "developing": (
        "Use natural everyday English, common collocations, and a balanced mix of support "
        "plus slightly longer sentence patterns."
    ),
    "advancing": (
        "Use more fluent, native-like English while staying grounded in common real-life "
        "language and reusable phrasing."
    ),
}


def canonical_level(value: str | None) -> str:
    lowered = str(value or "").strip().lower()
    if lowered in LEVEL_LABELS:
        return lowered
    return LEGACY_LEVEL_ALIASES.get(lowered, "beginner")


def level_label(value: str | None) -> str:
    return LEVEL_LABELS[canonical_level(value)]


def level_guidance(value: str | None) -> str:
    return LEVEL_PROMPT_GUIDANCE[canonical_level(value)]


def level_rank(value: str | None) -> int:
    return LEVEL_ORDER[canonical_level(value)]


def adaptive_level(
    *,
    base_level: str | None,
    recent_accuracy: float,
    weak_item_count: int,
    fast_correct_ratio: float,
) -> str:
    rank = level_rank(base_level)
    if recent_accuracy < 0.58 or weak_item_count >= 6:
        rank = max(0, rank - 1)
    elif recent_accuracy > 0.86 and fast_correct_ratio > 0.45:
        rank = min(2, rank + 1)

    for level, index in LEVEL_ORDER.items():
        if index == rank:
            return level
    return canonical_level(base_level)


def unique_texts(values: Iterable[str], *, limit: int | None = None) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        unique.append(cleaned)
        if limit is not None and len(unique) >= limit:
            break
    return unique
