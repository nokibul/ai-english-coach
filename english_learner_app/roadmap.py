from __future__ import annotations

import re
from typing import Any

from .utils import normalize_answer


BASE_ROADMAP_SKILLS: dict[str, str] = {
    "basic_description": "Basic Description",
    "positioning": "Positioning",
    "actions": "Actions",
    "descriptive_language": "Descriptive Language",
    "atmosphere": "Atmosphere",
    "sentence_patterns": "Sentence Patterns",
    "natural_english": "Natural English",
}

ROADMAP_SKILL_DESCRIPTIONS: dict[str, str] = {
    "basic_description": "Practice core words and simple phrases for describing what you see.",
    "positioning": "Practice phrases that describe where things are.",
    "actions": "Practice language for describing what people or things are doing.",
    "descriptive_language": "Practice richer phrases that make visual details more specific.",
    "atmosphere": "Practice language for describing the mood and feeling of a scene.",
    "sentence_patterns": "Practice reusable sentence frames for image descriptions.",
    "natural_english": "Practice phrases that make descriptions sound natural and fluent.",
}

ROADMAP_ASSET_STATUSES = {
    "new",
    "learning",
    "familiar",
    "strong",
    "mastered",
    "weak",
}

POSITIONING_ASSETS = {
    "covered with",
    "surrounded by",
    "visible in the background",
    "standing near",
    "attached to",
    "resting on",
    "in front of",
    "behind",
    "next to",
    "beside",
    "above",
    "below",
    "placed near",
    "located near",
}

ACTION_ASSETS = {
    "firmly holding",
    "walking through",
    "gathered together",
    "looking toward",
    "sitting beside",
    "standing beside",
    "leaning against",
    "carrying",
    "pointing at",
    "reaching for",
}

DESCRIPTIVE_ASSETS = {
    "dense greenery",
    "compact digital stopwatch",
    "climbing vines",
    "modern building",
    "bright blue sky",
    "leafy branches",
    "wooden table",
    "narrow road",
}

ATMOSPHERE_ASSETS = {
    "calm atmosphere",
    "peaceful surroundings",
    "lively environment",
    "relaxed mood",
    "busy street",
    "quiet setting",
    "warm feeling",
    "natural feel",
}

SENTENCE_PATTERN_ASSETS = {
    "the image shows",
    "a is visible",
    "in the background",
    "in the foreground",
    "the scene shows",
    "there is a",
    "there are",
}

NATURAL_ENGLISH_ASSETS = {
    "it appears to be",
    "it seems to",
    "gives the impression of",
    "looks like",
    "appears as if",
    "seems as though",
}


def mapLanguageAssetToRoadmapSkill(asset: dict[str, Any]) -> dict[str, str]:
    value = str(asset.get("value") or asset.get("text") or asset.get("phrase") or "").strip()
    asset_type = str(asset.get("type") or "").strip()
    normalized = _roadmap_normalize(value)

    if asset_type == "sentence_pattern":
        return _skill("sentence_patterns")
    if asset_type == "positioning_language" or _contains_any(normalized, POSITIONING_ASSETS):
        return _skill("positioning")
    if asset_type == "action_language" or _contains_any(normalized, ACTION_ASSETS):
        return _skill("actions")
    if asset_type == "atmosphere_language" or _contains_any(normalized, ATMOSPHERE_ASSETS):
        return _skill("atmosphere")
    if _contains_any(normalized, NATURAL_ENGLISH_ASSETS):
        return _skill("natural_english")
    if _contains_any(normalized, SENTENCE_PATTERN_ASSETS):
        return _skill("sentence_patterns")
    if asset_type == "descriptive_language" or _contains_any(normalized, DESCRIPTIVE_ASSETS):
        return _skill("descriptive_language")
    if asset_type == "vocabulary" and len(normalized.split()) <= 1:
        return _skill("basic_description")
    return _skill("descriptive_language")


def roadmap_skill_name(skill_key: str) -> str:
    return BASE_ROADMAP_SKILLS.get(str(skill_key or ""), BASE_ROADMAP_SKILLS["descriptive_language"])


def roadmap_skill_description(skill_key: str) -> str:
    return ROADMAP_SKILL_DESCRIPTIONS.get(
        str(skill_key or ""),
        ROADMAP_SKILL_DESCRIPTIONS["descriptive_language"],
    )


def normalize_roadmap_status(status: Any, *, fallback: str = "new") -> str:
    cleaned = str(status or "").strip().casefold().replace(" ", "_")
    return cleaned if cleaned in ROADMAP_ASSET_STATUSES else fallback


def _skill(skill_key: str) -> dict[str, str]:
    return {"skillKey": skill_key, "skillName": roadmap_skill_name(skill_key)}


def _roadmap_normalize(value: str) -> str:
    normalized = normalize_answer(value.replace("...", "").replace("___", " "))
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _contains_any(normalized_value: str, candidates: set[str]) -> bool:
    if not normalized_value:
        return False
    for candidate in candidates:
        normalized_candidate = _roadmap_normalize(candidate)
        if normalized_value == normalized_candidate or normalized_candidate in normalized_value:
            return True
    return False
