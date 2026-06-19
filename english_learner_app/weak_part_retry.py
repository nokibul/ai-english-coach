from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from .database import Database
from .roadmap import mapLanguageAssetToRoadmapSkill, roadmap_skill_name
from .utils import normalize_answer, to_iso, utc_now


def getWeakPartRetry(db: Database, userId: int, sessionId: int) -> dict[str, Any]:
    session = db.get_session(user_id=userId, session_id=sessionId)
    if not session:
        raise ValueError("Session was not found.")
    assets = db.list_session_reusable_language_assets(user_id=userId, session_id=sessionId)
    if not assets:
        return _empty_retry(sessionId)

    summary = _json_load(session.get("summary_json"), {})
    focuses = summary.get("coverageFocuses") or summary.get("coverage_focuses") or []
    candidates = [
        _focus_candidate(focus, assets)
        for focus in focuses
        if isinstance(focus, dict)
    ]
    candidates = [candidate for candidate in candidates if candidate["targetAssets"]]

    if not candidates:
        weak_assets = [asset for asset in assets if _asset_is_weak(asset)]
        if not weak_assets:
            return _empty_retry(sessionId)
        weakest = sorted(weak_assets, key=_asset_weak_key)[0]
        skill = mapLanguageAssetToRoadmapSkill(weakest)
        return _retry_payload(
            session=session,
            session_id=sessionId,
            focus_name=skill["skillName"],
            question_text=_question_for_assets(skill["skillName"], [weakest]),
            previous_help_level=3 if str(weakest.get("source") or "") == "guided_coverage_hint" else 1,
            target_assets=[weakest],
            support_levels=_fallback_support_levels(skill["skillName"], [weakest]),
        )

    best = sorted(candidates, key=lambda item: item["score"], reverse=True)[0]
    return _retry_payload(
        session=session,
        session_id=sessionId,
        focus_name=best["focusName"],
        question_text=best["questionText"],
        previous_help_level=best["previousHelpLevelUsed"],
        target_assets=best["targetAssets"],
        support_levels=best["supportLevels"],
    )


def submitWeakPartRetry(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    user_id = int(payload.get("userId") or payload.get("user_id") or 0)
    session_id = int(payload.get("sessionId") or payload.get("session_id") or 0)
    answer = str(payload.get("answer") or "").strip()
    used_support_level = int(payload.get("usedSupportLevel") or payload.get("used_support_level") or 1)
    target_asset_ids = [
        int(item)
        for item in (payload.get("targetAssetIds") or payload.get("target_asset_ids") or [])
        if str(item).isdigit()
    ]
    if not user_id or not session_id:
        raise ValueError("userId and sessionId are required.")
    if not answer:
        raise ValueError("Answer is required.")

    now = utc_now()
    reviewed_at = to_iso(now)
    used_assets: list[dict[str, Any]] = []
    missing_assets: list[dict[str, Any]] = []
    affected_skills: dict[str, str] = {}
    normalized_answer = normalize_answer(answer)

    for asset_id in target_asset_ids:
        asset = db.get_reusable_language_asset(user_id=user_id, asset_id=asset_id)
        if not asset:
            continue
        normalized_asset = normalize_answer(str(asset.get("value") or ""))
        used = bool(normalized_asset and normalized_asset in normalized_answer)
        public_asset = {"id": str(asset_id), "value": asset.get("value") or ""}
        if used:
            gain = _weak_retry_gain(used_support_level)
            old_mastery = float(asset.get("mastery_score") or 0.0)
            new_mastery = max(0.0, min(1.0, old_mastery + gain))
            status = _status_for_mastery(new_mastery)
            updated = db.update_language_asset_mastery_for_roadmap_practice(
                user_id=user_id,
                asset_id=asset_id,
                is_correct=True,
                mastery_delta=gain,
                status=status,
                reviewed_at=reviewed_at,
                next_review_at=to_iso(now + _review_delay_for_mastery(new_mastery)),
            )
            if updated and updated.get("roadmap_skill_key"):
                affected_skills[str(updated["roadmap_skill_key"])] = roadmap_skill_name(str(updated["roadmap_skill_key"]))
            used_assets.append(public_asset)
        else:
            missing_assets.append(public_asset)

    for skill_key, skill_name in affected_skills.items():
        db.recalculate_roadmap_skill_progress(
            user_id=user_id,
            skill_key=skill_key,
            skill_name=skill_name,
            calculated_at=reviewed_at,
        )

    success = bool(used_assets)
    improved_answer = answer if success and answer.endswith((".", "!", "?")) else f"{answer}." if success else ""
    return {
        "success": success,
        "usedAssets": used_assets,
        "missingAssets": missing_assets,
        "feedback": (
            "Nice retry. You used the target language clearly."
            if success
            else "Try again using one of the target phrases."
        ),
        "improvedAnswer": improved_answer,
        "xpEarned": 15 if success else 0,
    }


def _focus_candidate(focus: dict[str, Any], assets: list[dict[str, Any]]) -> dict[str, Any]:
    focus_name = _focus_name(focus)
    support_levels = _support_levels(focus, focus_name)
    linked_assets = _linked_focus_assets(focus, assets)
    hint_assets = [asset for asset in linked_assets if str(asset.get("source") or "") == "guided_coverage_hint"]
    weak_assets = [asset for asset in linked_assets if _asset_is_weak(asset)]
    previous_help_level = 3 if hint_assets else max([int(level.get("level") or 1) for level in support_levels] or [1])
    score = previous_help_level * 10
    score += len(hint_assets) * 8
    score += sum(20 - min(20, round(float(asset.get("mastery_score") or 0.0) * 20)) for asset in linked_assets)
    score += sum(int(asset.get("wrong_count") or 0) * 6 for asset in linked_assets)
    score += len(weak_assets) * 12
    return {
        "focusName": focus_name,
        "questionText": str(support_levels[0].get("prompt") or _question_for_assets(focus_name, linked_assets)),
        "previousHelpLevelUsed": previous_help_level,
        "targetAssets": linked_assets[:4],
        "supportLevels": support_levels,
        "score": score,
    }


def _linked_focus_assets(focus: dict[str, Any], assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    goal_terms = _clean_list(focus.get("reusableLanguageGoal") or focus.get("reusable_language_goal"))
    normalized_goals = {normalize_answer(term) for term in goal_terms if normalize_answer(term)}
    terms = [
        *goal_terms,
        str(focus.get("title") or ""),
        str(focus.get("sourceText") or focus.get("source_text") or ""),
    ]
    for support in focus.get("supportLevels") or focus.get("support_levels") or []:
        if isinstance(support, dict):
            terms.append(str(support.get("prompt") or ""))
            terms.extend(_clean_list(support.get("hints")))
    normalized_terms = [normalize_answer(term) for term in terms if normalize_answer(term)]
    linked: list[dict[str, Any]] = []
    for asset in assets:
        value = normalize_answer(str(asset.get("value") or ""))
        if value and any(value in term or term in value for term in normalized_terms):
            linked.append(asset)
    linked.sort(key=lambda asset: (0 if normalize_answer(str(asset.get("value") or "")) in normalized_goals else 1, *_asset_weak_key(asset)))
    return linked


def _retry_payload(
    *,
    session: dict[str, Any],
    session_id: int,
    focus_name: str,
    question_text: str,
    previous_help_level: int,
    target_assets: list[dict[str, Any]],
    support_levels: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "sessionId": str(session_id),
        "hasWeakPart": True,
        "focusName": focus_name,
        "imageUrl": f"/api/sessions/{session_id}/image",
        "questionText": question_text,
        "previousHelpLevelUsed": previous_help_level,
        "targetAssets": [
            {"id": str(asset.get("id") or ""), "value": asset.get("value") or ""}
            for asset in target_assets
        ],
        "supportLevels": support_levels,
    }


def _empty_retry(session_id: int) -> dict[str, Any]:
    return {
        "sessionId": str(session_id),
        "hasWeakPart": False,
        "message": "No weak part found for this session.",
    }


def _support_levels(focus: dict[str, Any], focus_name: str) -> list[dict[str, Any]]:
    raw_levels = focus.get("supportLevels") or focus.get("support_levels") or []
    levels: list[dict[str, Any]] = []
    for item in raw_levels:
        if not isinstance(item, dict):
            continue
        level = int(item.get("level") or len(levels) + 1)
        levels.append(
            {
                "level": level,
                "prompt": str(item.get("prompt") or _default_prompt(focus_name, level)),
                "hints": _clean_list(item.get("hints")),
            }
        )
    if levels:
        return sorted(levels, key=lambda item: int(item.get("level") or 0))[:3]
    return _fallback_support_levels(focus_name, [])


def _fallback_support_levels(focus_name: str, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    asset = str((assets[0] if assets else {}).get("value") or "").strip()
    return [
        {"level": 1, "prompt": _default_prompt(focus_name, 1)},
        {"level": 2, "prompt": _default_prompt(focus_name, 2)},
        {
            "level": 3,
            "prompt": f"Try using: {asset or 'the target phrase'}.",
            "hints": [asset] if asset else [],
        },
    ]


def _focus_name(focus: dict[str, Any]) -> str:
    return str(
        focus.get("skillName")
        or focus.get("category")
        or focus.get("title")
        or focus.get("label")
        or "Weak Part"
    ).strip().replace("_", " ").title()


def _question_for_assets(focus_name: str, assets: list[dict[str, Any]]) -> str:
    value = str((assets[0] if assets else {}).get("value") or "").strip()
    if "position" in focus_name.casefold() or value in {"covered with", "surrounded by"}:
        return "Where is it, or how is it positioned?"
    if "background" in focus_name.casefold():
        return "What can you describe in the background?"
    if "atmosphere" in focus_name.casefold():
        return "How does the scene feel?"
    return f"What can you add about {focus_name.lower()}?"


def _default_prompt(focus_name: str, level: int) -> str:
    if level == 1:
        return _question_for_assets(focus_name, [])
    if level == 2:
        return f"Can you add one clearer detail about {focus_name.lower()}?"
    return f"Use a sentence frame for {focus_name.lower()}."


def _asset_is_weak(asset: dict[str, Any]) -> bool:
    return (
        str(asset.get("status") or "") == "weak"
        or float(asset.get("mastery_score") or 0.0) <= 0.35
        or int(asset.get("wrong_count") or 0) > int(asset.get("correct_count") or 0)
        or bool(asset.get("recently_answered_wrong"))
        or str(asset.get("source") or "") == "guided_coverage_hint"
    )


def _asset_weak_key(asset: dict[str, Any]) -> tuple[int, float, int, str]:
    return (
        0 if str(asset.get("source") or "") == "guided_coverage_hint" else 1,
        float(asset.get("mastery_score") or 0.0),
        -int(asset.get("wrong_count") or 0),
        str(asset.get("value") or ""),
    )


def _weak_retry_gain(used_support_level: int) -> float:
    gain = 0.12
    if int(used_support_level or 1) <= 1:
        gain += 0.05
    if int(used_support_level or 1) >= 3:
        gain *= 0.5
    return gain


def _status_for_mastery(mastery: float) -> str:
    percent = round(max(0.0, min(1.0, mastery)) * 100)
    if percent <= 25:
        return "new"
    if percent <= 50:
        return "learning"
    if percent <= 70:
        return "familiar"
    if percent <= 90:
        return "strong"
    return "mastered"


def _review_delay_for_mastery(mastery: float) -> timedelta:
    percent = round(max(0.0, min(1.0, mastery)) * 100)
    if percent <= 25:
        return timedelta(days=1)
    if percent <= 50:
        return timedelta(days=2)
    if percent <= 70:
        return timedelta(days=4)
    if percent <= 90:
        return timedelta(days=7)
    return timedelta(days=14)


def _json_load(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return fallback
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return fallback


def _clean_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value or "").strip()]
