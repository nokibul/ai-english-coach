from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from .database import Database
from .roadmap import roadmap_skill_name
from .utils import normalize_answer, to_iso, utc_now


DESCRIBE_AGAIN_PHRASE_COUNT = 3
SIMPLE_NOUN_TYPES = {"word", "noun", "vocabulary", "vocab"}


def startDescribeAgain(db: Database, userId: int, sessionId: int, phraseCount: int = DESCRIBE_AGAIN_PHRASE_COUNT) -> dict[str, Any]:
    session = db.get_session(user_id=userId, session_id=sessionId)
    if not session:
        raise ValueError("Session was not found.")
    assets = db.list_session_reusable_language_assets(user_id=userId, session_id=sessionId)
    selected = _select_describe_again_assets(assets, phraseCount)
    if not selected:
        raise ValueError("No reusable phrases were found for this session.")

    return {
        "sessionId": str(sessionId),
        "imageUrl": f"/api/sessions/{sessionId}/image",
        "selectedPhrases": [
            {"assetId": str(asset.get("id") or ""), "value": asset.get("value") or ""}
            for asset in selected
        ],
        "prompt": f"Describe this image again using all {len(selected)} phrases.",
    }


def submitDescribeAgain(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    user_id = int(payload.get("userId") or payload.get("user_id") or 0)
    session_id = int(payload.get("sessionId") or payload.get("session_id") or 0)
    description = str(payload.get("description") or "").strip()
    selected_asset_ids = [
        int(item)
        for item in (payload.get("selectedAssetIds") or payload.get("selected_asset_ids") or [])
        if str(item).isdigit()
    ]
    if not user_id or not session_id:
        raise ValueError("userId and sessionId are required.")
    if not description:
        raise ValueError("Description is required.")
    if not selected_asset_ids:
        raise ValueError("Select at least one phrase.")

    session = db.get_session(user_id=user_id, session_id=session_id)
    if not session:
        raise ValueError("Session was not found.")

    assets = [
        asset
        for asset_id in selected_asset_ids
        if (asset := db.get_reusable_language_asset(user_id=user_id, asset_id=asset_id))
    ]
    if not assets:
        raise ValueError("Selected phrases were not found.")

    now = utc_now()
    reviewed_at = to_iso(now)
    normalized_description = normalize_answer(description)
    used_assets: list[dict[str, Any]] = []
    missing_assets: list[dict[str, Any]] = []
    affected_skills: dict[str, str] = {}

    for asset in assets:
        asset_id = int(asset["id"])
        value = str(asset.get("value") or "").strip()
        used = _phrase_used(normalized_description, value)
        public_asset = {"id": str(asset_id), "value": value}
        if used:
            updated = db.update_language_asset_mastery_for_roadmap_practice(
                user_id=user_id,
                asset_id=asset_id,
                is_correct=True,
                mastery_delta=0.15,
                status=_status_for_mastery(min(1.0, float(asset.get("mastery_score") or 0.0) + 0.15)),
                reviewed_at=reviewed_at,
                next_review_at=to_iso(now + timedelta(days=7)),
            )
            if updated and updated.get("roadmap_skill_key"):
                affected_skills[str(updated["roadmap_skill_key"])] = roadmap_skill_name(str(updated["roadmap_skill_key"]))
            used_assets.append(public_asset)
        else:
            updated = db.update_language_asset_mastery_for_roadmap_practice(
                user_id=user_id,
                asset_id=asset_id,
                is_correct=False,
                mastery_delta=-0.03,
                status="weak",
                reviewed_at=reviewed_at,
                next_review_at=to_iso(now + timedelta(hours=6)),
            )
            if updated and updated.get("roadmap_skill_key"):
                affected_skills[str(updated["roadmap_skill_key"])] = roadmap_skill_name(str(updated["roadmap_skill_key"]))
            missing_assets.append(public_asset)

    for skill_key, skill_name in affected_skills.items():
        db.recalculate_roadmap_skill_progress(
            user_id=user_id,
            skill_key=skill_key,
            skill_name=skill_name,
            calculated_at=reviewed_at,
        )

    used_all = len(used_assets) == len(assets)
    score = _describe_again_score(description, used_count=len(used_assets), total_count=len(assets))
    feedback = _feedback(used_assets, missing_assets, score)
    improved_description = _improved_description(session, assets, description)
    xp_earned = _xp_for_describe_again(score, used_all)
    db.create_describe_again_attempt(
        user_id=user_id,
        session_id=session_id,
        selected_asset_ids=[int(asset["id"]) for asset in assets],
        description=description,
        used_asset_ids=[int(asset["id"]) for asset in used_assets],
        missing_asset_ids=[int(asset["id"]) for asset in missing_assets],
        score=score,
        feedback=feedback,
        improved_description=improved_description,
        xp_earned=xp_earned,
        created_at=reviewed_at,
    )

    return {
        "usedAllPhrases": used_all,
        "usedPhrases": [asset["value"] for asset in used_assets],
        "missingPhrases": [asset["value"] for asset in missing_assets],
        "score": score,
        "feedback": feedback,
        "improvedDescription": improved_description,
        "xpEarned": xp_earned,
    }


def _select_describe_again_assets(assets: list[dict[str, Any]], phrase_count: int) -> list[dict[str, Any]]:
    useful_assets = [asset for asset in assets if _is_good_describe_again_phrase(asset)]
    fallback_assets = [asset for asset in assets if asset not in useful_assets]
    ranked = sorted(useful_assets, key=_describe_again_asset_key)
    if len(ranked) < phrase_count:
        ranked.extend(sorted(fallback_assets, key=_describe_again_asset_key))
    return ranked[: max(1, int(phrase_count or DESCRIBE_AGAIN_PHRASE_COUNT))]


def _is_good_describe_again_phrase(asset: dict[str, Any]) -> bool:
    value = str(asset.get("value") or "").strip()
    if not value:
        return False
    asset_type = str(asset.get("type") or "").strip().lower()
    if asset_type in SIMPLE_NOUN_TYPES and len(value.split()) <= 1:
        return False
    normalized = normalize_answer(value)
    if len(normalized.split()) <= 1:
        return False
    return True


def _describe_again_asset_key(asset: dict[str, Any]) -> tuple[int, int, float, int, int, int]:
    source = str(asset.get("source") or "")
    status = str(asset.get("status") or "")
    mastery = float(asset.get("mastery_score") or 0.0)
    value = str(asset.get("value") or "")
    learned_from_hint = source == "guided_coverage_hint" or "hint" in source.lower()
    weak = status == "weak" or int(asset.get("wrong_count") or 0) > int(asset.get("correct_count") or 0)
    high_value = int(asset.get("usefulness_score") or 0) + int(asset.get("transferability_score") or 0)
    return (
        0 if weak else 1,
        0 if learned_from_hint else 1,
        mastery,
        -high_value,
        0 if len(value.split()) > 1 else 1,
        int(asset.get("id") or 0),
    )


def _phrase_used(normalized_description: str, phrase: str) -> bool:
    normalized_phrase = normalize_answer(phrase)
    return bool(normalized_phrase and normalized_phrase in normalized_description)


def _describe_again_score(description: str, *, used_count: int, total_count: int) -> int:
    if total_count <= 0:
        return 0
    usage_score = round((used_count / total_count) * 80)
    sentences = [item for item in re.split(r"[.!?]+", description) if item.strip()]
    word_count = len(normalize_answer(description).split())
    natural_score = 0
    if 2 <= len(sentences) <= 4:
        natural_score += 12
    elif len(sentences) >= 1:
        natural_score += 6
    if word_count >= 8:
        natural_score += 8
    return max(0, min(100, usage_score + natural_score))


def _feedback(used_assets: list[dict[str, Any]], missing_assets: list[dict[str, Any]], score: int) -> str:
    if not missing_assets and score >= 80:
        return "Great job. You used all the target phrases in a natural description."
    if used_assets and missing_assets:
        return f"Good start. You used {len(used_assets)} phrase{'s' if len(used_assets) != 1 else ''}; add the missing phrase to make it stronger."
    return "Try again using the selected phrases in your image description."


def _improved_description(session: dict[str, Any], assets: list[dict[str, Any]], original: str) -> str:
    examples = [str(asset.get("example_sentence") or "").strip() for asset in assets if str(asset.get("example_sentence") or "").strip()]
    if examples:
        return " ".join(_sentence_clean(example) for example in examples[:2])
    natural = str(session.get("natural_explanation") or session.get("simple_explanation") or "").strip()
    if natural:
        return natural
    phrases = [str(asset.get("value") or "").strip() for asset in assets if str(asset.get("value") or "").strip()]
    if phrases:
        return f"The image shows a scene with {', '.join(phrases[:-1])} and {phrases[-1]}." if len(phrases) > 1 else f"The image shows {phrases[0]}."
    return original


def _sentence_clean(value: str) -> str:
    value = value.strip()
    if not value:
        return value
    return value if value.endswith((".", "!", "?")) else f"{value}."


def _xp_for_describe_again(score: int, used_all: bool) -> int:
    if score <= 0:
        return 0
    xp = 10 if score < 70 else 20
    if used_all:
        xp += 10
    return xp


def _status_for_mastery(mastery: float) -> str:
    if mastery <= 0.25:
        return "new"
    if mastery <= 0.5:
        return "learning"
    if mastery <= 0.7:
        return "familiar"
    if mastery <= 0.9:
        return "strong"
    return "mastered"
