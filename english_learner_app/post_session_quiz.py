from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import Any, TYPE_CHECKING

from .database import Database
from .roadmap import (
    BASE_ROADMAP_SKILLS,
    mapLanguageAssetToRoadmapSkill,
    normalize_roadmap_status,
    roadmap_skill_description,
    roadmap_skill_name,
)
from .utils import normalize_answer, should_surface_term, to_iso, utc_now

if TYPE_CHECKING:
    from .ai_service import AIAnalyzer


ASSET_TYPES = {
    "phrase",
    "descriptive_language",
    "positioning_language",
    "atmosphere_language",
    "action_language",
    "sentence_pattern",
    "vocabulary",
}

QUIZ_TYPES = {
    "meaning_match",
    "fill_blank",
    "multiple_choice",
    "better_sentence",
    "sentence_builder",
    "rewrite_challenge",
    "production_challenge",
    "image_recall",
}

QUIZ_PRIORITY_TYPES = {
    "phrase": 7,
    "sentence_pattern": 7,
    "positioning_language": 6,
    "atmosphere_language": 5,
    "action_language": 5,
    "descriptive_language": 4,
    "vocabulary": 1,
}

QUIZ_ANSWER_MODES = {
    "immediate_session_quiz",
    "past_session_practice",
    "daily_review",
    "roadmap_practice",
    "session_weak_practice",
    "describe_again",
}

ROADMAP_PRACTICE_TYPES = {
    "meaning_match",
    "fill_blank",
    "multiple_choice",
    "better_sentence",
    "sentence_builder",
    "rewrite_challenge",
    "production_challenge",
}

ROADMAP_HARD_TYPES = {
    "rewrite_challenge",
    "production_challenge",
}

SOURCE_PRIORITY = {
    "enhancement": 4,
    "guided_coverage": 3,
    "guided_coverage_hint": 2,
    "final_description": 2,
    "learned_phrase": 1,
}

HIGH_VALUE_PHRASES = {
    "attached to",
    "covered with",
    "surrounded by",
    "visible in the background",
}

POSITIONING_PHRASES = {
    "at the top",
    "behind",
    "in front of",
    "in the background",
    "in the center",
    "in the distance",
    "in the foreground",
    "next to",
    "near",
    "on the left",
    "on the right",
    "resting on",
    "standing near",
}

ATMOSPHERE_WORDS = {
    "atmosphere",
    "busy",
    "calm",
    "dramatic",
    "environment",
    "lively",
    "mood",
    "peaceful",
    "quiet",
    "scene feels",
    "surroundings",
}

ACTION_WORDS = {
    "carrying",
    "facing",
    "gathered",
    "holding",
    "looking",
    "resting",
    "sitting",
    "standing",
    "walking",
    "wearing",
}

DESCRIPTIVE_ADJECTIVES = {
    "bright",
    "calm",
    "climbing",
    "compact",
    "crowded",
    "dense",
    "digital",
    "green",
    "lively",
    "modern",
    "peaceful",
    "soft",
    "sunny",
    "tall",
    "trimmed",
}

LOW_VALUE_NOUNS = {
    "building",
    "chair",
    "image",
    "object",
    "person",
    "scene",
    "thing",
    "tree",
}


def getCompletedSessionLearningInput(
    db: Database,
    sessionId: int,
    userId: int | None = None,
) -> dict[str, Any]:
    return PostSessionQuizService(db).getCompletedSessionLearningInput(sessionId, userId=userId)


def extractReusableLanguageAssetsFromSession(
    db: Database,
    sessionId: int,
    userId: int | None = None,
) -> list[dict[str, Any]]:
    return PostSessionQuizService(db).extractReusableLanguageAssetsFromSession(sessionId, userId=userId)


def generateQuizBankForSession(
    db: Database,
    sessionId: int,
    userId: int | None = None,
) -> dict[str, Any]:
    return PostSessionQuizService(db).generateQuizBankForSession(sessionId, userId=userId)


def getImmediateQuizForSession(
    db: Database,
    sessionId: int,
    userId: int,
) -> dict[str, Any]:
    return PostSessionQuizService(db).getImmediateQuizForSession(sessionId, userId=userId)


def getPracticeQuizForPastSession(
    db: Database,
    sessionId: int,
    userId: int,
) -> dict[str, Any]:
    return PostSessionQuizService(db).getPracticeQuizForPastSession(sessionId, userId=userId)


def updateRoadmapFromSession(
    db: Database,
    sessionId: int,
    userId: int,
) -> dict[str, Any]:
    return PostSessionQuizService(db).updateRoadmapFromSession(sessionId, userId=userId)


def getRoadmapSkillDetail(
    db: Database,
    userId: int,
    skillKey: str,
) -> dict[str, Any]:
    return PostSessionQuizService(db).getRoadmapSkillDetail(userId=userId, skillKey=skillKey)


def getRoadmapOverview(
    db: Database,
    userId: int,
) -> dict[str, Any]:
    return PostSessionQuizService(db).getRoadmapOverview(userId=userId)


def startRoadmapPracticeMission(
    db: Database,
    userId: int,
    skillKey: str,
) -> dict[str, Any]:
    return PostSessionQuizService(db).startRoadmapPracticeMission(userId=userId, skillKey=skillKey)


def getDailyReview(
    db: Database,
    userId: int,
) -> dict[str, Any]:
    return PostSessionQuizService(db).getDailyReview(userId=userId)


def submitQuizAnswer(
    db: Database,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return PostSessionQuizService(db).submitQuizAnswer(payload)


class PostSessionQuizService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def getCompletedSessionLearningInput(
        self,
        sessionId: int,
        *,
        userId: int | None = None,
    ) -> dict[str, Any]:
        session = (
            self.db.get_session(user_id=userId, session_id=sessionId)
            if userId is not None
            else self.db.get_session_by_id(sessionId)
        )
        if not session:
            raise ValueError("Completed session was not found.")

        user_id = int(session["user_id"])
        summary = _json_load(session.get("summary_json"), {})
        raw_analysis = _json_load(session.get("raw_analysis_json"), {})
        image_url = f"/api/sessions/{session['id']}/image"
        phrases = self.db.list_session_phrases(user_id=user_id, session_id=int(session["id"]))
        vocabulary = self.db.list_session_vocabulary(user_id=user_id, session_id=int(session["id"]))

        original_description = _first_text(
            summary.get("originalDescription"),
            summary.get("original_description"),
            raw_analysis.get("originalDescription") if isinstance(raw_analysis, dict) else "",
            session.get("simple_explanation"),
        )
        final_description = _first_text(
            summary.get("finalDescription"),
            summary.get("final_description"),
            summary.get("finalParagraph"),
            summary.get("final_paragraph"),
            raw_analysis.get("finalDescription") if isinstance(raw_analysis, dict) else "",
            session.get("natural_explanation"),
            session.get("narrative_text"),
        )
        enhancement_history = _build_enhancement_history(
            session=session,
            summary=summary,
            raw_analysis=raw_analysis if isinstance(raw_analysis, dict) else {},
        )
        coverage_focuses = _list_from_aliases(summary, "coverageFocuses", "coverage_focuses")
        guided_coverage_responses = _first_list(
            summary.get("guidedCoverageAnswers"),
            summary.get("guided_coverage_answers"),
            summary.get("guidedCoverageResponses"),
            summary.get("guided_coverage_responses"),
            coverage_focuses,
        )
        reusable_phrases = _session_reusable_language(summary=summary, phrases=phrases, vocabulary=vocabulary)

        return {
            "userId": user_id,
            "sessionId": int(session["id"]),
            "imageUrl": image_url,
            "originalDescription": original_description,
            "finalDescription": final_description,
            "enhancementHistory": enhancement_history,
            "guidedCoverageResponses": guided_coverage_responses,
            "reusablePhrasesFromSession": reusable_phrases,
            "coverageFocuses": coverage_focuses,
        }

    def extractReusableLanguageAssetsFromSession(
        self,
        sessionId: int,
        *,
        userId: int | None = None,
    ) -> list[dict[str, Any]]:
        learning_input = self.getCompletedSessionLearningInput(sessionId, userId=userId)
        candidates: list[dict[str, Any]] = []

        self._collect_from_enhancement_history(learning_input, candidates)
        self._collect_from_guided_coverage(learning_input, candidates)
        self._collect_from_final_description(learning_input, candidates)
        self._collect_from_learned_phrases(learning_input, candidates)

        assets = _dedupe_and_filter_assets(candidates)
        created_at = to_iso(utc_now())
        stored_assets = self.db.upsert_reusable_language_assets(
            user_id=int(learning_input["userId"]),
            session_id=int(learning_input["sessionId"]),
            image_url=str(learning_input["imageUrl"]),
            assets=assets,
            created_at=created_at,
        )
        for skill_key in sorted({str(asset.get("roadmap_skill_key") or "") for asset in stored_assets if asset.get("roadmap_skill_key")}):
            self.db.recalculate_roadmap_skill_progress(
                user_id=int(learning_input["userId"]),
                skill_key=skill_key,
                skill_name=roadmap_skill_name(skill_key),
                calculated_at=created_at,
            )
        return [_stored_asset_to_public(row) for row in stored_assets]

    def generateQuizBankForSession(
        self,
        sessionId: int,
        *,
        userId: int | None = None,
    ) -> dict[str, Any]:
        learning_input = self.getCompletedSessionLearningInput(sessionId, userId=userId)
        self.extractReusableLanguageAssetsFromSession(sessionId, userId=int(learning_input["userId"]))
        assets = self.db.list_session_reusable_language_assets(
            user_id=int(learning_input["userId"]),
            session_id=int(learning_input["sessionId"]),
        )
        selected_assets = _select_assets_for_quiz(assets)
        questions: list[dict[str, Any]] = []
        for asset in selected_assets:
            questions.extend(_generate_questions_for_asset(asset, learning_input=learning_input))

        created_at = to_iso(utc_now())
        stored_questions = self.db.bulk_upsert_quiz_questions(
            user_id=int(learning_input["userId"]),
            session_id=int(learning_input["sessionId"]),
            questions=questions,
            created_at=created_at,
        )
        by_type: dict[str, int] = {}
        for question in stored_questions:
            question_type = str(question.get("type") or "")
            by_type[question_type] = by_type.get(question_type, 0) + 1

        return {
            "userId": int(learning_input["userId"]),
            "sessionId": int(learning_input["sessionId"]),
            "selectedAssetCount": len(selected_assets),
            "generatedQuestionCount": len(stored_questions),
            "questionCountByType": by_type,
            "languageAssetIds": [str(asset.get("id")) for asset in selected_assets],
        }

    async def generateQuizBankForSessionWithAI(
        self,
        sessionId: int,
        *,
        analyzer: "AIAnalyzer",
        userId: int | None = None,
    ) -> dict[str, Any]:
        learning_input = self.getCompletedSessionLearningInput(sessionId, userId=userId)
        self.extractReusableLanguageAssetsFromSession(sessionId, userId=int(learning_input["userId"]))
        assets = self.db.list_session_reusable_language_assets(
            user_id=int(learning_input["userId"]),
            session_id=int(learning_input["sessionId"]),
        )
        selected_assets = _select_assets_for_quiz(assets)
        ai_payload = await analyzer.generate_session_quiz_questions(
            session_input=learning_input,
            language_assets=selected_assets,
        )
        ai_questions = ai_payload.get("quizQuestions") if isinstance(ai_payload, dict) else []
        questions = _questions_from_ai_payload(
            ai_questions,
            selected_assets=selected_assets,
        )
        source = "ai" if questions else "template"
        if not questions:
            for asset in selected_assets:
                questions.extend(_generate_questions_for_asset(asset, learning_input=learning_input))

        created_at = to_iso(utc_now())
        stored_questions = self.db.bulk_upsert_quiz_questions(
            user_id=int(learning_input["userId"]),
            session_id=int(learning_input["sessionId"]),
            questions=questions,
            created_at=created_at,
        )
        by_type: dict[str, int] = {}
        for question in stored_questions:
            question_type = str(question.get("type") or "")
            by_type[question_type] = by_type.get(question_type, 0) + 1
        return {
            "userId": int(learning_input["userId"]),
            "sessionId": int(learning_input["sessionId"]),
            "selectedAssetCount": len(selected_assets),
            "generatedQuestionCount": len(stored_questions),
            "questionCountByType": by_type,
            "languageAssetIds": [str(asset.get("id")) for asset in selected_assets],
            "source": source,
        }

    def getImmediateQuizForSession(
        self,
        sessionId: int,
        *,
        userId: int,
    ) -> dict[str, Any]:
        session = self.db.get_session(user_id=userId, session_id=sessionId)
        if not session:
            raise ValueError("Completed session was not found.")
        questions = self.db.list_session_quiz_questions(user_id=userId, session_id=sessionId)
        if not questions:
            self.generateQuizBankForSession(sessionId, userId=userId)
            questions = self.db.list_session_quiz_questions(user_id=userId, session_id=sessionId)

        selected = _select_immediate_quiz_questions(questions)
        shown_at = to_iso(utc_now())
        self.db.mark_quiz_questions_shown(
            user_id=userId,
            session_id=sessionId,
            question_ids=[int(question["id"]) for question in selected],
            shown_at=shown_at,
        )
        return {
            "sessionId": sessionId,
            "questions": [
                _public_quiz_question(
                    {
                        **question,
                        "used_in_immediate_quiz": 1,
                        "last_shown_at": shown_at,
                        "times_shown": int(question.get("times_shown") or 0) + 1,
                    }
                )
                for question in selected
            ],
        }

    def getPracticeQuizForPastSession(
        self,
        sessionId: int,
        *,
        userId: int,
    ) -> dict[str, Any]:
        session = self.db.get_session(user_id=userId, session_id=sessionId)
        if not session:
            raise ValueError("Completed session was not found.")
        questions = self.db.list_session_quiz_questions(user_id=userId, session_id=sessionId)
        if not questions:
            self.generateQuizBankForSession(sessionId, userId=userId)
            questions = self.db.list_session_quiz_questions(user_id=userId, session_id=sessionId)

        assets = self.db.list_session_reusable_language_assets(user_id=userId, session_id=sessionId)
        selected = _select_past_practice_questions(questions, assets=assets)
        shown_at = to_iso(utc_now())
        self.db.mark_quiz_questions_shown(
            user_id=userId,
            session_id=sessionId,
            question_ids=[int(question["id"]) for question in selected],
            shown_at=shown_at,
            used_in_immediate_quiz=False,
        )
        return {
            "sessionId": sessionId,
            "mode": "past_session_practice",
            "questions": [
                _public_quiz_question(
                    {
                        **question,
                        "last_shown_at": shown_at,
                        "times_shown": int(question.get("times_shown") or 0) + 1,
                    }
                )
                for question in selected
            ],
        }

    def updateRoadmapFromSession(
        self,
        sessionId: int,
        *,
        userId: int,
    ) -> dict[str, Any]:
        learning_input = self.getCompletedSessionLearningInput(sessionId, userId=userId)
        self.extractReusableLanguageAssetsFromSession(sessionId, userId=userId)
        now_iso = to_iso(utc_now())
        session_created_at = str(
            self.db.get_session(user_id=userId, session_id=sessionId).get("created_at") or ""
        )
        session_assets = self.db.list_session_reusable_language_assets(user_id=userId, session_id=sessionId)
        affected_skill_names: dict[str, str] = {}
        summary_by_skill: dict[str, dict[str, Any]] = {}
        applied_asset_ids: list[int] = []

        for asset in session_assets:
            asset_id = int(asset.get("id") or 0)
            if not asset_id:
                continue
            roadmap_skill = mapLanguageAssetToRoadmapSkill(asset)
            status = str(asset.get("status") or "").strip()
            if not status:
                status = _initial_asset_status(
                    source=str(asset.get("source") or ""),
                    support_level=_support_level_from_source_text(str(asset.get("original_source_text") or "")),
                )
            status = normalize_roadmap_status(status)
            default_mastery = _initial_asset_mastery_score(status)
            updated_asset = self.db.update_reusable_language_asset_roadmap_defaults(
                user_id=userId,
                asset_id=asset_id,
                roadmap_skill_key=roadmap_skill["skillKey"],
                status=status,
                mastery_score=default_mastery,
                updated_at=now_iso,
            )
            if not updated_asset:
                continue

            skill_key = roadmap_skill["skillKey"]
            skill_name = roadmap_skill["skillName"]
            affected_skill_names[skill_key] = skill_name
            applied_asset_ids.append(asset_id)
            bucket = summary_by_skill.setdefault(
                skill_key,
                {
                    "skillKey": skill_key,
                    "skillName": skill_name,
                    "newAssetsAdded": 0,
                    "assets": [],
                },
            )
            value = str(asset.get("value") or "").strip()
            if _counts_as_new_roadmap_asset(asset, session_created_at=session_created_at):
                bucket["newAssetsAdded"] += 1
                if value and value not in bucket["assets"]:
                    bucket["assets"].append(value)

        self.db.mark_session_reusable_assets_roadmap_applied(
            user_id=userId,
            session_id=sessionId,
            asset_ids=applied_asset_ids,
            applied_at=now_iso,
        )

        updated_skills: list[dict[str, Any]] = []
        for skill_key in sorted(affected_skill_names):
            progress = self.db.recalculate_roadmap_skill_progress(
                user_id=int(learning_input["userId"]),
                skill_key=skill_key,
                skill_name=affected_skill_names[skill_key],
                calculated_at=now_iso,
            )
            bucket = summary_by_skill.get(skill_key, {})
            new_assets_added = int(bucket.get("newAssetsAdded") or 0)
            skill_summary = {
                "skillKey": skill_key,
                "skillName": affected_skill_names[skill_key],
                "newAssetsAdded": new_assets_added,
                "assets": bucket.get("assets") or [],
                "masteredAssetCount": int(progress.get("mastered_asset_count") or 0),
                "totalAssetCount": int(progress.get("total_asset_count") or 0),
                "newAssetCount": int(progress.get("new_asset_count") or 0),
                "weakAssetCount": int(progress.get("weak_asset_count") or 0),
                "dueReviewCount": int(progress.get("due_review_count") or 0),
                "averageMasteryScore": round(float(progress.get("average_mastery_score") or 0.0) * 100),
            }
            if new_assets_added:
                skill_summary["message"] = _roadmap_unlock_message(
                    count=new_assets_added,
                    skill_name=affected_skill_names[skill_key],
                )
            updated_skills.append(skill_summary)

        return {
            "message": _roadmap_update_message(updated_skills),
            "updatedSkills": updated_skills,
        }

    def getRoadmapSkillDetail(
        self,
        *,
        userId: int,
        skillKey: str,
    ) -> dict[str, Any]:
        skill_key = _normalize_roadmap_skill_key(skillKey)
        skill_name = roadmap_skill_name(skill_key)
        now_iso = to_iso(utc_now())
        progress = self.db.recalculate_roadmap_skill_progress(
            user_id=userId,
            skill_key=skill_key,
            skill_name=skill_name,
            calculated_at=now_iso,
        )
        assets = self.db.list_roadmap_skill_assets(user_id=userId, skill_key=skill_key)
        groups = {
            "newAssets": [],
            "weakAssets": [],
            "dueReviewAssets": [],
            "masteredAssets": [],
        }

        for asset in assets:
            public_asset = _roadmap_detail_asset(asset)
            if _is_mastered_roadmap_asset(asset):
                groups["masteredAssets"].append(public_asset)
            elif _is_due_roadmap_asset(asset, now_iso=now_iso):
                groups["dueReviewAssets"].append(public_asset)
            elif _is_weak_roadmap_asset(asset):
                groups["weakAssets"].append(public_asset)
            elif _is_new_roadmap_asset(asset):
                groups["newAssets"].append(public_asset)

        for key in groups:
            groups[key].sort(key=_roadmap_detail_asset_sort_key)

        response = {
            "skillKey": skill_key,
            "skillName": skill_name,
            "description": roadmap_skill_description(skill_key),
            "averageMasteryScore": round(float(progress.get("average_mastery_score") or 0.0) * 100),
            "masteredAssetCount": int(progress.get("mastered_asset_count") or 0),
            "totalAssetCount": int(progress.get("total_asset_count") or 0),
            "newAssets": groups["newAssets"],
            "weakAssets": groups["weakAssets"],
            "dueReviewAssets": groups["dueReviewAssets"],
            "masteredAssets": groups["masteredAssets"],
        }
        if not assets:
            response["emptyMessage"] = "Upload more images to unlock practice for this skill."
        return response

    def getRoadmapOverview(
        self,
        *,
        userId: int,
    ) -> dict[str, Any]:
        now_iso = to_iso(utc_now())
        skills: list[dict[str, Any]] = []
        for skill_key, skill_name in BASE_ROADMAP_SKILLS.items():
            progress = self.db.recalculate_roadmap_skill_progress(
                user_id=userId,
                skill_key=skill_key,
                skill_name=skill_name,
                calculated_at=now_iso,
            )
            total = int(progress.get("total_asset_count") or 0)
            mastered = int(progress.get("mastered_asset_count") or 0)
            item = {
                "skillKey": skill_key,
                "skillName": skill_name,
                "description": roadmap_skill_description(skill_key),
                "progressLabel": f"{mastered}/{total} mastered" if total else "No practice yet",
                "masteredAssetCount": mastered,
                "totalAssetCount": total,
                "newAssetCount": int(progress.get("new_asset_count") or 0),
                "weakAssetCount": int(progress.get("weak_asset_count") or 0),
                "dueReviewCount": int(progress.get("due_review_count") or 0),
                "averageMasteryScore": round(float(progress.get("average_mastery_score") or 0.0) * 100),
            }
            if total <= 0:
                item["emptyMessage"] = "No practice yet. Upload more images to unlock this skill."
            skills.append(item)

        recommended = _recommended_roadmap_skill(skills)
        return {
            "skills": skills,
            "recommendedSkill": recommended,
            "dueReviewCount": sum(int(skill.get("dueReviewCount") or 0) for skill in skills),
            "newAssetCount": sum(int(skill.get("newAssetCount") or 0) for skill in skills),
            "weakAssetCount": sum(int(skill.get("weakAssetCount") or 0) for skill in skills),
        }

    def startRoadmapPracticeMission(
        self,
        *,
        userId: int,
        skillKey: str,
    ) -> dict[str, Any]:
        skill_key = _normalize_roadmap_skill_key(skillKey)
        skill_name = roadmap_skill_name(skill_key)
        assets = self.db.list_roadmap_skill_assets(user_id=userId, skill_key=skill_key)
        practice_assets = _select_roadmap_practice_assets(assets)
        asset_ids = [int(asset.get("id") or 0) for asset in practice_assets if int(asset.get("id") or 0)]
        if asset_ids:
            self._ensureRoadmapPracticeQuestions(userId=userId, assets=practice_assets)
        questions = self.db.list_quiz_questions_for_language_assets(user_id=userId, asset_ids=asset_ids)
        mission_questions = _select_roadmap_mission_questions(questions, asset_ids=asset_ids)
        if len(mission_questions) < 5 and asset_ids:
            self._ensureRoadmapPracticeQuestions(userId=userId, assets=practice_assets, force=True)
            questions = self.db.list_quiz_questions_for_language_assets(user_id=userId, asset_ids=asset_ids)
            mission_questions = _select_roadmap_mission_questions(questions, asset_ids=asset_ids)

        now_iso = to_iso(utc_now())
        selected_questions = mission_questions[:7]
        mission = self.db.create_roadmap_mission_attempt(
            user_id=userId,
            skill_key=skill_key,
            question_ids=[int(question["id"]) for question in selected_questions],
            started_at=now_iso,
        )
        self.db.mark_quiz_questions_shown_for_user(
            user_id=userId,
            question_ids=[int(question["id"]) for question in selected_questions],
            shown_at=now_iso,
        )
        return {
            "mode": "roadmap_practice",
            "skillKey": skill_key,
            "skillName": skill_name,
            "missionId": str(mission.get("id") or ""),
            "questions": [
                _public_quiz_question(
                    {
                        **question,
                        "last_shown_at": now_iso,
                        "times_shown": int(question.get("times_shown") or 0) + 1,
                    }
                )
                for question in selected_questions
            ],
        }

    def _ensureRoadmapPracticeQuestions(
        self,
        *,
        userId: int,
        assets: list[dict[str, Any]],
        force: bool = False,
    ) -> None:
        if not assets:
            return
        existing = self.db.list_quiz_questions_for_language_assets(
            user_id=userId,
            asset_ids=[int(asset.get("id") or 0) for asset in assets if int(asset.get("id") or 0)],
        )
        existing_asset_ids = {
            str(asset_id)
            for question in existing
            if str(question.get("type") or "") in ROADMAP_PRACTICE_TYPES
            for asset_id in question.get("language_asset_ids", [])
        }
        created_at = to_iso(utc_now())
        by_session: dict[int, list[dict[str, Any]]] = {}
        for asset in assets:
            asset_id = str(asset.get("id") or "")
            if not asset_id:
                continue
            if not force and asset_id in existing_asset_ids:
                continue
            source_session_id = int(asset.get("source_session_id") or asset.get("session_id") or 0)
            if not source_session_id:
                continue
            by_session.setdefault(source_session_id, []).append(asset)

        for session_id, session_assets in by_session.items():
            try:
                learning_input = self.getCompletedSessionLearningInput(session_id, userId=userId)
            except ValueError:
                learning_input = {
                    "userId": userId,
                    "sessionId": session_id,
                    "finalDescription": "",
                    "enhancementHistory": [],
                }
            questions: list[dict[str, Any]] = []
            for asset in session_assets:
                questions.extend(
                    question
                    for question in _generate_questions_for_asset(asset, learning_input=learning_input)
                    if str(question.get("type") or "") in ROADMAP_PRACTICE_TYPES
                )
            self.db.bulk_upsert_quiz_questions(
                user_id=userId,
                session_id=session_id,
                questions=questions,
                created_at=created_at,
            )

    def getDailyReview(self, *, userId: int) -> dict[str, Any]:
        now_iso = to_iso(utc_now())
        due_assets = self.db.list_daily_review_assets(user_id=userId, now_iso=now_iso, limit=24)
        due_asset_count = len(due_assets)
        if not due_assets:
            return {
                "mode": "daily_review",
                "dueAssetCount": 0,
                "questions": [],
                "message": "No review due right now.",
            }

        selected_assets = _select_daily_review_assets(due_assets)
        asset_ids = [int(asset.get("id") or 0) for asset in selected_assets if int(asset.get("id") or 0)]
        self._ensureRoadmapPracticeQuestions(userId=userId, assets=selected_assets)
        questions = self.db.list_quiz_questions_for_language_assets(user_id=userId, asset_ids=asset_ids)
        selected_questions = _select_daily_review_questions(questions, asset_ids=asset_ids)
        if len(selected_questions) < 5 and asset_ids:
            self._ensureRoadmapPracticeQuestions(userId=userId, assets=selected_assets, force=True)
            questions = self.db.list_quiz_questions_for_language_assets(user_id=userId, asset_ids=asset_ids)
            selected_questions = _select_daily_review_questions(questions, asset_ids=asset_ids)

        selected_questions = selected_questions[:12]
        self.db.mark_quiz_questions_shown_for_user(
            user_id=userId,
            question_ids=[int(question["id"]) for question in selected_questions],
            shown_at=now_iso,
        )
        public_questions = [
            _public_quiz_question(
                {
                    **question,
                    "last_shown_at": now_iso,
                    "times_shown": int(question.get("times_shown") or 0) + 1,
                }
            )
            for question in selected_questions
        ]
        return {
            "mode": "daily_review",
            "dueAssetCount": due_asset_count,
            "xpAvailable": sum(_roadmap_practice_xp(question) for question in selected_questions),
            "questions": public_questions,
        }

    def submitQuizAnswer(self, payload: dict[str, Any]) -> dict[str, Any]:
        user_id = int(payload.get("userId") or payload.get("user_id") or 0)
        session_id = int(payload.get("sessionId") or payload.get("session_id") or 0)
        quiz_question_id = int(payload.get("quizQuestionId") or payload.get("quiz_question_id") or 0)
        mission_id = int(payload.get("missionId") or payload.get("mission_id") or 0)
        answer = _clean_text(payload.get("answer"))
        mode = str(payload.get("mode") or "").strip()
        if mode not in QUIZ_ANSWER_MODES:
            raise ValueError("Unsupported quiz answer mode.")
        if mode not in {"roadmap_practice", "daily_review"} and not session_id:
            raise ValueError("sessionId is required for this quiz answer mode.")
        question = (
            self.db.get_quiz_question(
                user_id=user_id,
                session_id=session_id,
                quiz_question_id=quiz_question_id,
            )
            if session_id
            else self.db.get_quiz_question_for_user(
                user_id=user_id,
                quiz_question_id=quiz_question_id,
            )
        )
        if not question:
            raise ValueError("Quiz question was not found.")
        if mode == "roadmap_practice":
            return self._submitRoadmapPracticeAnswer(
                user_id=user_id,
                mission_id=mission_id,
                question=question,
                answer=answer,
                hint_used=bool(payload.get("hintUsed") or payload.get("hint_used")),
            )
        if mode == "daily_review":
            return self._submitDailyReviewAnswer(
                user_id=user_id,
                question=question,
                answer=answer,
                hint_used=bool(payload.get("hintUsed") or payload.get("hint_used")),
            )

        evaluation = _evaluate_quiz_answer(question, answer)
        now = utc_now()
        created_at = to_iso(now)
        next_review_at = to_iso(now + _review_delay_for_score(evaluation["score"]))
        xp_earned = _xp_for_quiz_score(evaluation["score"])
        self.db.record_quiz_attempt(
            user_id=user_id,
            session_id=session_id,
            quiz_question_id=quiz_question_id,
            quiz_type=str(question.get("type") or ""),
            language_asset_ids=[str(item) for item in question.get("language_asset_ids", [])],
            mode=mode,
            answer=answer,
            is_correct=bool(evaluation["isCorrect"]),
            score=float(evaluation["score"]),
            xp_earned=xp_earned,
            expected_keywords=evaluation["expectedKeywords"],
            matched_keywords=evaluation["matchedKeywords"],
            created_at=created_at,
            next_review_at=next_review_at,
        )
        updated_assets = self.db.list_session_reusable_language_assets(user_id=user_id, session_id=session_id)
        for skill_key in sorted({str(asset.get("roadmap_skill_key") or "") for asset in updated_assets if asset.get("roadmap_skill_key")}):
            self.db.recalculate_roadmap_skill_progress(
                user_id=user_id,
                skill_key=skill_key,
                skill_name=roadmap_skill_name(skill_key),
                calculated_at=created_at,
            )
        updated_mastery = [
            {
                "languageAssetId": str(asset.get("id")),
                "value": asset.get("value"),
                "masteryScore": float(asset.get("mastery_score") or 0.0),
                "correctCount": int(asset.get("correct_count") or 0),
                "wrongCount": int(asset.get("wrong_count") or 0),
                "nextReviewAt": asset.get("next_review_at"),
            }
            for asset in updated_assets
            if str(asset.get("id")) in {str(item) for item in question.get("language_asset_ids", [])}
        ]
        return {
            "isCorrect": bool(evaluation["isCorrect"]),
            "correctAnswer": question.get("correct_answer") or "",
            "explanation": question.get("explanation") or "",
            "xpEarned": xp_earned,
            "updatedMastery": updated_mastery,
        }

    def _submitRoadmapPracticeAnswer(
        self,
        *,
        user_id: int,
        mission_id: int,
        question: dict[str, Any],
        answer: str,
        hint_used: bool,
    ) -> dict[str, Any]:
        if not mission_id:
            raise ValueError("Roadmap practice missionId is required.")
        mission = self.db.get_roadmap_mission_attempt(user_id=user_id, mission_id=mission_id)
        if not mission:
            raise ValueError("Roadmap practice mission was not found.")
        if str(question.get("id") or "") not in {str(item) for item in mission.get("question_ids", [])}:
            raise ValueError("Quiz question does not belong to this roadmap mission.")

        evaluation = _evaluate_roadmap_practice_answer(question, answer)
        now = utc_now()
        reviewed_at = to_iso(now)
        is_correct = bool(evaluation["isCorrect"])
        base_xp = _roadmap_practice_xp(question) if is_correct else 0
        total_answered_after = int(mission.get("correct_count") or 0) + int(mission.get("wrong_count") or 0) + 1
        total_questions = int(mission.get("total_questions") or 0)
        mission_completed = total_questions > 0 and total_answered_after >= total_questions
        completion_bonus = 15 if mission_completed else 0
        perfect_bonus = (
            10
            if mission_completed
            and is_correct
            and int(mission.get("wrong_count") or 0) == 0
            and int(mission.get("correct_count") or 0) + 1 >= total_questions
            else 0
        )
        xp_earned = base_xp + completion_bonus + perfect_bonus
        next_review_at = to_iso(now + _roadmap_review_delay(is_correct=is_correct, mastery_score=0.0))
        self.db.record_quiz_attempt(
            user_id=user_id,
            session_id=int(question.get("session_id") or 0),
            quiz_question_id=int(question.get("id") or 0),
            quiz_type=str(question.get("type") or ""),
            language_asset_ids=[str(item) for item in question.get("language_asset_ids", [])],
            mode="roadmap_practice",
            answer=answer,
            is_correct=is_correct,
            score=float(evaluation["score"]),
            xp_earned=xp_earned,
            expected_keywords=evaluation["expectedKeywords"],
            matched_keywords=evaluation["matchedKeywords"],
            created_at=reviewed_at,
            next_review_at=next_review_at,
            update_assets=False,
        )

        updated_assets: list[dict[str, Any]] = []
        affected_skill_names: dict[str, str] = {}
        for asset_id in [int(item) for item in question.get("language_asset_ids", []) if str(item).isdigit()]:
            current_asset = self.db.get_reusable_language_asset(user_id=user_id, asset_id=asset_id)
            if not current_asset:
                continue
            old_mastery = float(current_asset.get("mastery_score") or 0.0)
            old_mastery_percent = round(old_mastery * 100)
            gain = _roadmap_mastery_gain(str(question.get("type") or ""), hint_used=hint_used)
            delta = (gain / 100.0) if is_correct else -0.05
            new_mastery = max(0.0, min(1.0, old_mastery + delta))
            status = _roadmap_status_for_mastery(
                new_mastery,
                wrong_count=int(current_asset.get("wrong_count") or 0) + (0 if is_correct else 1),
                recently_wrong=not is_correct,
            )
            next_review_at = to_iso(now + _roadmap_review_delay(is_correct=is_correct, mastery_score=new_mastery))
            updated_asset = self.db.update_language_asset_mastery_for_roadmap_practice(
                user_id=user_id,
                asset_id=asset_id,
                is_correct=is_correct,
                mastery_delta=delta,
                status=status,
                reviewed_at=reviewed_at,
                next_review_at=next_review_at,
            )
            if not updated_asset:
                continue
            skill_key = str(updated_asset.get("roadmap_skill_key") or "")
            if skill_key:
                affected_skill_names[skill_key] = roadmap_skill_name(skill_key)
            updated_assets.append(
                {
                    "assetId": str(updated_asset.get("id") or ""),
                    "value": updated_asset.get("value") or "",
                    "oldMastery": old_mastery_percent,
                    "newMastery": round(float(updated_asset.get("mastery_score") or 0.0) * 100),
                }
            )

        for skill_key, skill_name in affected_skill_names.items():
            self.db.recalculate_roadmap_skill_progress(
                user_id=user_id,
                skill_key=skill_key,
                skill_name=skill_name,
                calculated_at=reviewed_at,
            )
        updated_mission = self.db.update_roadmap_mission_after_answer(
            user_id=user_id,
            mission_id=mission_id,
            is_correct=is_correct,
            xp_earned=xp_earned,
            answered_at=reviewed_at,
        )
        return {
            "isCorrect": is_correct,
            "correctAnswer": question.get("correct_answer") or "",
            "explanation": question.get("explanation") or "",
            "xpEarned": xp_earned,
            "updatedAssets": updated_assets,
            "missionStatus": (updated_mission or {}).get("status") or "started",
        }

    def _submitDailyReviewAnswer(
        self,
        *,
        user_id: int,
        question: dict[str, Any],
        answer: str,
        hint_used: bool,
    ) -> dict[str, Any]:
        evaluation = _evaluate_roadmap_practice_answer(question, answer)
        now = utc_now()
        reviewed_at = to_iso(now)
        is_correct = bool(evaluation["isCorrect"])
        xp_earned = _roadmap_practice_xp(question) if is_correct else 0
        next_review_at = to_iso(now + _roadmap_review_delay(is_correct=is_correct, mastery_score=0.0))
        self.db.record_quiz_attempt(
            user_id=user_id,
            session_id=int(question.get("session_id") or 0),
            quiz_question_id=int(question.get("id") or 0),
            quiz_type=str(question.get("type") or ""),
            language_asset_ids=[str(item) for item in question.get("language_asset_ids", [])],
            mode="daily_review",
            answer=answer,
            is_correct=is_correct,
            score=float(evaluation["score"]),
            xp_earned=xp_earned,
            expected_keywords=evaluation["expectedKeywords"],
            matched_keywords=evaluation["matchedKeywords"],
            created_at=reviewed_at,
            next_review_at=next_review_at,
            update_assets=False,
        )
        updated_assets, affected_skill_names = self._updateSpacedRepetitionAssets(
            user_id=user_id,
            question=question,
            is_correct=is_correct,
            hint_used=hint_used,
            reviewed_at=reviewed_at,
            now=now,
        )
        for skill_key, skill_name in affected_skill_names.items():
            self.db.recalculate_roadmap_skill_progress(
                user_id=user_id,
                skill_key=skill_key,
                skill_name=skill_name,
                calculated_at=reviewed_at,
            )
        return {
            "isCorrect": is_correct,
            "correctAnswer": question.get("correct_answer") or "",
            "explanation": question.get("explanation") or "",
            "xpEarned": xp_earned,
            "updatedAssets": updated_assets,
        }

    def _updateSpacedRepetitionAssets(
        self,
        *,
        user_id: int,
        question: dict[str, Any],
        is_correct: bool,
        hint_used: bool,
        reviewed_at: str,
        now: Any,
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        updated_assets: list[dict[str, Any]] = []
        affected_skill_names: dict[str, str] = {}
        for asset_id in [int(item) for item in question.get("language_asset_ids", []) if str(item).isdigit()]:
            current_asset = self.db.get_reusable_language_asset(user_id=user_id, asset_id=asset_id)
            if not current_asset:
                continue
            old_mastery = float(current_asset.get("mastery_score") or 0.0)
            old_mastery_percent = round(old_mastery * 100)
            gain = _roadmap_mastery_gain(str(question.get("type") or ""), hint_used=hint_used)
            delta = (gain / 100.0) if is_correct else -0.05
            new_mastery = max(0.0, min(1.0, old_mastery + delta))
            status = _roadmap_status_for_mastery(
                new_mastery,
                wrong_count=int(current_asset.get("wrong_count") or 0) + (0 if is_correct else 1),
                recently_wrong=not is_correct,
            )
            next_review_at = to_iso(now + _roadmap_review_delay(is_correct=is_correct, mastery_score=new_mastery))
            updated_asset = self.db.update_language_asset_mastery_for_roadmap_practice(
                user_id=user_id,
                asset_id=asset_id,
                is_correct=is_correct,
                mastery_delta=delta,
                status=status,
                reviewed_at=reviewed_at,
                next_review_at=next_review_at,
            )
            if not updated_asset:
                continue
            skill_key = str(updated_asset.get("roadmap_skill_key") or "")
            if skill_key:
                affected_skill_names[skill_key] = roadmap_skill_name(skill_key)
            updated_assets.append(
                {
                    "assetId": str(updated_asset.get("id") or ""),
                    "value": updated_asset.get("value") or "",
                    "oldMastery": old_mastery_percent,
                    "newMastery": round(float(updated_asset.get("mastery_score") or 0.0) * 100),
                }
            )
        return updated_assets, affected_skill_names

    def _collect_from_enhancement_history(
        self,
        learning_input: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> None:
        for item in learning_input.get("enhancementHistory") or []:
            if isinstance(item, dict):
                texts = [
                    item.get("improvedVersion"),
                    item.get("better_version"),
                    item.get("after"),
                    item.get("newText"),
                    item.get("text"),
                ]
                source_text = _first_text(*texts)
            else:
                source_text = str(item or "").strip()
            self._collect_from_text(source_text, source="enhancement", candidates=candidates)

    def _collect_from_guided_coverage(
        self,
        learning_input: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> None:
        for focus in learning_input.get("coverageFocuses") or []:
            if not isinstance(focus, dict):
                continue
            source_text = " ".join(
                text
                for text in [
                    str(focus.get("title") or "").strip(),
                    str(focus.get("sourceText") or focus.get("source_text") or "").strip(),
                ]
                if text
            )
            for value in _clean_string_list(focus.get("reusableLanguageGoal") or focus.get("reusable_language_goal")):
                self._add_asset(value, source="guided_coverage", source_text=source_text, candidates=candidates)
            for support in focus.get("supportLevels") or focus.get("support_levels") or []:
                if not isinstance(support, dict):
                    continue
                support_level = int(support.get("level") or 0)
                prompt = str(support.get("prompt") or "").strip()
                if prompt:
                    self._collect_sentence_patterns(
                        prompt,
                        source="guided_coverage",
                        source_text=prompt,
                        candidates=candidates,
                        support_level=support_level,
                    )
                for hint in _clean_string_list(support.get("hints")):
                    self._add_asset(
                        hint,
                        source="guided_coverage_hint",
                        source_text=prompt or source_text,
                        candidates=candidates,
                        support_level=support_level,
                    )

    def _collect_from_final_description(
        self,
        learning_input: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> None:
        final_description = str(learning_input.get("finalDescription") or "").strip()
        self._collect_from_text(final_description, source="final_description", candidates=candidates)

    def _collect_from_learned_phrases(
        self,
        learning_input: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> None:
        for item in learning_input.get("reusablePhrasesFromSession") or []:
            if isinstance(item, dict):
                value = _first_text(item.get("value"), item.get("text"), item.get("phrase"), item.get("word"))
                source_text = _first_text(item.get("exampleSentence"), item.get("example"), item.get("sourceText"))
            else:
                value = str(item or "").strip()
                source_text = ""
            self._add_asset(value, source="learned_phrase", source_text=source_text, candidates=candidates)

    def _collect_from_text(
        self,
        text: str,
        *,
        source: str,
        candidates: list[dict[str, Any]],
    ) -> None:
        cleaned = _clean_text(text)
        if not cleaned:
            return

        self._collect_sentence_patterns(cleaned, source=source, source_text=cleaned, candidates=candidates)
        for phrase in _extract_known_phrases(cleaned):
            self._add_asset(phrase, source=source, source_text=cleaned, candidates=candidates)
        for phrase in _extract_collocations(cleaned):
            self._add_asset(phrase, source=source, source_text=cleaned, candidates=candidates)
        for phrase in _extract_action_phrases(cleaned):
            self._add_asset(phrase, source=source, source_text=cleaned, candidates=candidates)

    def _collect_sentence_patterns(
        self,
        text: str,
        *,
        source: str,
        source_text: str,
        candidates: list[dict[str, Any]],
        support_level: int = 0,
    ) -> None:
        for pattern in _extract_sentence_patterns(text):
            self._add_asset(
                pattern,
                source=source,
                source_text=source_text,
                candidates=candidates,
                support_level=support_level,
            )

    def _add_asset(
        self,
        value: str,
        *,
        source: str,
        source_text: str,
        candidates: list[dict[str, Any]],
        support_level: int = 0,
    ) -> None:
        value = _normalize_asset_value(value)
        if not value:
            return
        asset_type = _classify_asset_type(value)
        if asset_type not in ASSET_TYPES:
            return
        scores = _score_asset(value, asset_type)
        if scores["usefulnessScore"] + scores["transferabilityScore"] < 55:
            return
        roadmap_skill = mapLanguageAssetToRoadmapSkill({"value": value, "type": asset_type})
        status = _initial_asset_status(source=source, support_level=support_level)
        candidates.append(
            {
                "value": value,
                "type": asset_type,
                "source": source,
                "meaning": _asset_meaning(value, asset_type),
                "exampleSentence": _asset_example(value, asset_type, source_text),
                "difficultyLevel": _difficulty_level(value, asset_type),
                "usefulnessScore": scores["usefulnessScore"],
                "transferabilityScore": scores["transferabilityScore"],
                "roadmapSkillKey": roadmap_skill["skillKey"],
                "status": status,
                "masteryScore": _initial_asset_mastery_score(status),
                "originalSourceText": source_text,
                "normalizedValue": normalize_answer(value),
            }
        )


def _json_load(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return fallback
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return fallback


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return _clean_text(value)
    return ""


def _first_list(*values: Any) -> list[Any]:
    for value in values:
        if isinstance(value, list):
            return value
    return []


def _list_from_aliases(mapping: dict[str, Any], *keys: str) -> list[Any]:
    if not isinstance(mapping, dict):
        return []
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, list):
            return value
    return []


def _build_enhancement_history(
    *,
    session: dict[str, Any],
    summary: dict[str, Any],
    raw_analysis: dict[str, Any],
) -> list[Any]:
    history = _first_list(
        summary.get("enhancedSentences"),
        summary.get("enhanced_sentences"),
        summary.get("sentenceUpgrades"),
        summary.get("sentence_upgrades"),
        summary.get("enhancementHistory"),
        summary.get("enhancement_history"),
        raw_analysis.get("enhancedSentences"),
        raw_analysis.get("sentenceUpgrades"),
    )
    if history:
        return history

    fallback = _first_text(
        session.get("natural_explanation"),
        session.get("narrative_text"),
        summary.get("finalDescription"),
        summary.get("finalParagraph"),
    )
    return [fallback] if fallback else []


def _session_reusable_language(
    *,
    summary: dict[str, Any],
    phrases: list[dict[str, Any]],
    vocabulary: list[dict[str, Any]],
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for starter in _clean_string_list(summary.get("sentenceStarters") or summary.get("sentence_starters")):
        items.append({"value": starter, "source": "guided_coverage"})
    for focus in _list_from_aliases(summary, "coverageFocuses", "coverage_focuses"):
        if not isinstance(focus, dict):
            continue
        for value in _clean_string_list(focus.get("reusableLanguageGoal") or focus.get("reusable_language_goal")):
            items.append(
                {
                    "value": value,
                    "source": "guided_coverage",
                    "sourceText": str(focus.get("title") or focus.get("sourceText") or ""),
                }
            )
    for item in phrases:
        items.append(
            {
                "value": str(item.get("phrase") or ""),
                "source": "learned_phrase",
                "exampleSentence": str(item.get("example") or ""),
            }
        )
    for item in vocabulary:
        items.append(
            {
                "value": str(item.get("word") or ""),
                "source": "learned_phrase",
                "exampleSentence": str(item.get("example") or ""),
            }
        )
    return [item for item in items if item.get("value")]


def _clean_string_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            cleaned.append(text)
    return cleaned


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _normalize_asset_value(value: str) -> str:
    cleaned = _clean_text(value).strip()
    if not cleaned:
        return ""
    if cleaned.endswith("...") or "___" in cleaned:
        return cleaned.strip(" ,;:!?")
    cleaned = cleaned.strip(" ,.;:!?")
    cleaned = re.sub(r"^(try|use|add)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip(" ,.;:!?")
    normalized = normalize_answer(cleaned)
    if normalized in HIGH_VALUE_PHRASES or normalized in POSITIONING_PHRASES:
        return cleaned
    words = cleaned.split()
    while len(words) > 3 and words[-1].casefold() in {"and", "or", "but", "with", "to", "of"}:
        words.pop()
    cleaned = " ".join(words)
    if len(cleaned) > 80:
        return ""
    return cleaned


def _classify_asset_type(value: str) -> str:
    lowered = value.casefold()
    normalized = normalize_answer(value)
    words = normalized.split()
    if _looks_like_sentence_pattern(value):
        return "sentence_pattern"
    if normalized in HIGH_VALUE_PHRASES:
        return "phrase"
    if normalized in POSITIONING_PHRASES or any(phrase in lowered for phrase in POSITIONING_PHRASES):
        return "positioning_language"
    if any(word in lowered for word in ATMOSPHERE_WORDS):
        return "atmosphere_language"
    if any(word in lowered.split() for word in ACTION_WORDS):
        return "action_language"
    if len(words) >= 2 and words[0] in DESCRIPTIVE_ADJECTIVES:
        return "descriptive_language"
    if len(words) >= 2:
        return "phrase"
    return "vocabulary"


def _score_asset(value: str, asset_type: str) -> dict[str, int]:
    normalized = normalize_answer(value)
    words = normalized.split()
    if asset_type == "sentence_pattern":
        usefulness = 92
        transferability = 94
    elif asset_type == "phrase":
        high_value = normalized in HIGH_VALUE_PHRASES or len(words) >= 2
        usefulness = 90 if high_value else 75
        transferability = 88 if high_value else 74
    elif asset_type == "positioning_language":
        usefulness = 88
        transferability = 92
    elif asset_type == "action_language":
        usefulness = 78
        transferability = 74
    elif asset_type == "atmosphere_language":
        usefulness = 78
        transferability = 80
    elif asset_type == "descriptive_language":
        usefulness = 72
        transferability = 68
    else:
        word = words[0] if words else ""
        if word in LOW_VALUE_NOUNS or not should_surface_term(value, kind="noun"):
            usefulness = 12
            transferability = 16
        else:
            usefulness = 32
            transferability = 34

    if len(words) >= 4 and asset_type != "sentence_pattern":
        transferability -= 8
    return {
        "usefulnessScore": max(0, min(100, usefulness)),
        "transferabilityScore": max(0, min(100, transferability)),
    }


def _difficulty_level(value: str, asset_type: str) -> int:
    word_count = len(normalize_answer(value).split())
    if asset_type in {"sentence_pattern", "positioning_language"} and word_count <= 4:
        return 1
    if word_count <= 2 and asset_type in {"phrase", "vocabulary"}:
        return 1
    if word_count <= 4:
        return 2
    return 3


def _asset_meaning(value: str, asset_type: str) -> str:
    meanings = {
        "phrase": "A reusable phrase for describing visual details naturally.",
        "descriptive_language": "A descriptive word group that makes an image detail more specific.",
        "positioning_language": "Language for explaining where something appears in an image.",
        "atmosphere_language": "Language for describing the mood or feeling of a scene.",
        "action_language": "Language for describing what someone or something is doing.",
        "sentence_pattern": "A reusable sentence frame for building image descriptions.",
        "vocabulary": "A useful word from the image session.",
    }
    return meanings.get(asset_type, f"Useful language for practicing '{value}'.")


def _asset_example(value: str, asset_type: str, source_text: str) -> str:
    source_sentence = _find_sentence_with_value(value, source_text)
    if source_sentence:
        return source_sentence
    lowered = value.casefold()
    if asset_type == "sentence_pattern":
        return _pattern_example(value)
    if asset_type == "positioning_language":
        return f"A small detail is {lowered}."
    if asset_type == "atmosphere_language":
        return f"The scene has a {lowered}."
    if asset_type == "action_language":
        return f"A person is {lowered}."
    if asset_type == "descriptive_language":
        return f"The image includes {lowered}."
    if asset_type == "vocabulary":
        return f"The {lowered} is visible in the image."
    return f"The object is {lowered}."


def _pattern_example(value: str) -> str:
    lowered = value.casefold()
    if "image shows" in lowered:
        return "The image shows a busy street."
    if "visible" in lowered:
        return "A tall building is visible in the background."
    if "background" in lowered:
        return "In the background, several trees are visible."
    if "scene feels" in lowered:
        return "The scene feels calm and peaceful."
    return "The image shows a clear main subject."


def _find_sentence_with_value(value: str, source_text: str) -> str:
    if not value or not source_text:
        return ""
    normalized_value = normalize_answer(value)
    for sentence in _split_sentences(source_text):
        if normalized_value and normalized_value in normalize_answer(sentence):
            return sentence
    return ""


def _split_sentences(text: str) -> list[str]:
    return [
        item.strip()
        for item in re.split(r"(?<=[.!?])\s+", _clean_text(text))
        if item.strip()
    ]


def _extract_known_phrases(text: str) -> list[str]:
    lowered = text.casefold()
    phrases: list[str] = []
    known = sorted(HIGH_VALUE_PHRASES | POSITIONING_PHRASES, key=len, reverse=True)
    for phrase in known:
        if re.search(rf"\b{re.escape(phrase)}\b", lowered):
            phrases.append(phrase)
    return phrases


def _extract_collocations(text: str) -> list[str]:
    phrases: list[str] = []
    adjective_group = "|".join(sorted(DESCRIPTIVE_ADJECTIVES))
    pattern = re.compile(rf"\b({adjective_group})(?:\s+({adjective_group}))?\s+([a-z]{{3,}})\b", re.IGNORECASE)
    for match in pattern.finditer(text):
        phrase = _normalize_asset_value(match.group(0))
        if phrase and len(normalize_answer(phrase).split()) <= 3:
            phrases.append(phrase)
    return phrases


def _extract_action_phrases(text: str) -> list[str]:
    phrases: list[str] = []
    verb_group = "|".join(sorted(ACTION_WORDS))
    for match in re.finditer(rf"\b(?:firmly\s+)?({verb_group})(?:\s+(?:toward|through|near|on|with|a|the)\s+[a-z]+)?\b", text, re.IGNORECASE):
        phrase = _normalize_asset_value(match.group(0))
        if phrase and len(normalize_answer(phrase).split()) >= 2:
            phrases.append(phrase)
    return phrases


def _extract_sentence_patterns(text: str) -> list[str]:
    patterns: list[str] = []
    sentences = _split_sentences(text)
    if _looks_like_sentence_pattern(text) and len(sentences) <= 1 and len(_clean_text(text).split()) <= 12:
        pattern = _normalize_sentence_pattern(text)
        if pattern:
            patterns.append(pattern)

    for sentence in sentences:
        lowered = sentence.casefold()
        if lowered.startswith("the image shows"):
            patterns.append("The image shows...")
        if re.match(r"^a\s+.+\s+is visible\b", lowered):
            patterns.append("A ___ is visible...")
        if lowered.startswith("in the background"):
            patterns.append("In the background, ...")
        if lowered.startswith("the scene feels"):
            patterns.append("The scene feels...")
    return patterns


def _looks_like_sentence_pattern(value: str) -> bool:
    lowered = value.casefold().strip()
    return (
        "..." in lowered
        or "___" in lowered
        or lowered.startswith("the image shows")
        or lowered.startswith("in this scene")
        or lowered.startswith("here we can see")
        or lowered.startswith("in the background,")
        or lowered.startswith("the scene feels")
    )


def _normalize_sentence_pattern(value: str) -> str:
    cleaned = _clean_text(value).strip()
    if not cleaned:
        return ""
    if "___" in cleaned:
        return cleaned
    if cleaned.endswith("..."):
        return cleaned
    if cleaned.endswith("."):
        return cleaned[:-1] + "..."
    if len(cleaned.split()) <= 8:
        return cleaned + "..."
    return ""


def _dedupe_and_filter_assets(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for asset in candidates:
        key = (str(asset.get("normalizedValue") or normalize_answer(str(asset.get("value") or ""))), str(asset.get("type") or ""))
        if not key[0] or not key[1]:
            continue
        current = best_by_key.get(key)
        if not current or _asset_rank(asset) > _asset_rank(current):
            best_by_key[key] = asset
    assets = list(best_by_key.values())
    assets.sort(key=lambda item: (-_asset_rank(item)[0], -_asset_rank(item)[1], str(item.get("value") or "").casefold()))
    return assets


def _asset_rank(asset: dict[str, Any]) -> tuple[int, int, int]:
    usefulness = int(asset.get("usefulnessScore") or 0)
    transferability = int(asset.get("transferabilityScore") or 0)
    source_priority = SOURCE_PRIORITY.get(str(asset.get("source") or ""), 0)
    return (usefulness + transferability, source_priority, usefulness)


def _initial_asset_status(*, source: str, support_level: int = 0) -> str:
    if source == "guided_coverage_hint" or int(support_level or 0) >= 3:
        return "weak"
    return "new"


def _initial_asset_mastery_score(status: str) -> float:
    status = normalize_roadmap_status(status)
    if status == "weak":
        return 0.15
    return 0.20


def _support_level_from_source_text(source_text: str) -> int:
    return 3 if re.search(r"\b(level|support)\s*3\b", source_text or "", flags=re.IGNORECASE) else 0


def _counts_as_new_roadmap_asset(asset: dict[str, Any], *, session_created_at: str) -> bool:
    if asset.get("roadmap_applied_at"):
        return False
    asset_created_at = str(asset.get("asset_created_at") or asset.get("created_at") or "")
    if asset_created_at and session_created_at and asset_created_at < session_created_at:
        return False
    return True


def _roadmap_unlock_message(*, count: int, skill_name: str) -> str:
    phrase_word = "phrase" if int(count or 0) == 1 else "phrases"
    return f"{int(count or 0)} new {skill_name} {phrase_word} unlocked from your image."


def _roadmap_update_message(updated_skills: list[dict[str, Any]]) -> str:
    skills_with_new_assets = [
        skill for skill in updated_skills if int(skill.get("newAssetsAdded") or 0) > 0
    ]
    if len(skills_with_new_assets) == 1:
        skill = skills_with_new_assets[0]
        return _roadmap_unlock_message(
            count=int(skill.get("newAssetsAdded") or 0),
            skill_name=str(skill.get("skillName") or "Roadmap"),
        )
    if skills_with_new_assets:
        return "New content added to your roadmap"
    return "Your roadmap is up to date"


def _recommended_roadmap_skill(skills: list[dict[str, Any]]) -> dict[str, Any] | None:
    practiced = [skill for skill in skills if int(skill.get("totalAssetCount") or 0) > 0]
    if not practiced:
        return None

    def sort_key(skill: dict[str, Any]) -> tuple[int, int, int, int, int, str]:
        due = int(skill.get("dueReviewCount") or 0)
        weak = int(skill.get("weakAssetCount") or 0)
        new = int(skill.get("newAssetCount") or 0)
        total = int(skill.get("totalAssetCount") or 0)
        average = int(skill.get("averageMasteryScore") or 0)
        return (-due, -weak, -new, average, -total, str(skill.get("skillName") or ""))

    return sorted(practiced, key=sort_key)[0]


def _normalize_roadmap_skill_key(skill_key: Any) -> str:
    return re.sub(r"[^a-z0-9_]+", "", str(skill_key or "").strip().casefold().replace("-", "_"))


def _roadmap_detail_asset(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id") or ""),
        "value": row.get("value") or "",
        "meaning": row.get("meaning") or "",
        "exampleSentence": row.get("example_sentence") or "",
        "masteryScore": round(float(row.get("mastery_score") or 0.0) * 100),
        "status": normalize_roadmap_status(row.get("status") or ""),
        "sourceSessionId": str(row.get("source_session_id") or ""),
        "nextReviewAt": row.get("next_review_at"),
        "wrongCount": int(row.get("wrong_count") or 0),
        "recentlyAnsweredWrong": bool(row.get("recently_answered_wrong")),
        "learnedAt": row.get("learned_at") or row.get("created_at") or "",
    }


def _roadmap_detail_asset_sort_key(asset: dict[str, Any]) -> tuple[int, int, str, str, int]:
    next_review_at = str(asset.get("nextReviewAt") or "9999-12-31T23:59:59+00:00")
    learned_at = str(asset.get("learnedAt") or "")
    return (
        0 if asset.get("recentlyAnsweredWrong") else 1,
        int(asset.get("masteryScore") or 0),
        next_review_at,
        learned_at,
        _sortable_asset_id(asset.get("id")),
    )


def _sortable_asset_id(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _is_new_roadmap_asset(asset: dict[str, Any]) -> bool:
    return normalize_roadmap_status(asset.get("status") or "") == "new" or float(asset.get("mastery_score") or 0.0) <= 0.25


def _is_weak_roadmap_asset(asset: dict[str, Any]) -> bool:
    wrong_count = int(asset.get("wrong_count") or 0)
    correct_count = int(asset.get("correct_count") or 0)
    return (
        normalize_roadmap_status(asset.get("status") or "") == "weak"
        or wrong_count > correct_count
        or wrong_count >= 3
        or bool(asset.get("recently_answered_wrong"))
        or bool(asset.get("learned_through_support"))
    )


def _is_due_roadmap_asset(asset: dict[str, Any], *, now_iso: str) -> bool:
    next_review_at = str(asset.get("next_review_at") or "")
    return bool(next_review_at and next_review_at <= now_iso)


def _is_mastered_roadmap_asset(asset: dict[str, Any]) -> bool:
    return normalize_roadmap_status(asset.get("status") or "") == "mastered" or float(asset.get("mastery_score") or 0.0) >= 0.91


def _select_roadmap_practice_assets(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(assets, key=_roadmap_practice_asset_key)[:12]


def _select_daily_review_assets(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(assets, key=_daily_review_asset_key)[:12]


def _daily_review_asset_key(asset: dict[str, Any]) -> tuple[int, float, str, int, str]:
    now_iso = to_iso(utc_now())
    if _is_weak_roadmap_asset(asset):
        bucket = 0
    elif bool(asset.get("learned_through_support")):
        bucket = 1
    elif float(asset.get("mastery_score") or 0.0) <= 0.50:
        bucket = 2
    elif _is_due_roadmap_asset(asset, now_iso=now_iso):
        bucket = 3
    else:
        bucket = 4
    important_skill = 0 if str(asset.get("roadmap_skill_key") or "") in {"positioning", "sentence_patterns", "natural_english"} else 1
    return (
        bucket,
        float(asset.get("mastery_score") or 0.0),
        str(asset.get("next_review_at") or ""),
        important_skill,
        str(asset.get("last_answered_at") or ""),
    )


def _roadmap_practice_asset_key(asset: dict[str, Any]) -> tuple[int, float, str, str]:
    now_iso = to_iso(utc_now())
    status = normalize_roadmap_status(asset.get("status") or "")
    mastery_score = float(asset.get("mastery_score") or 0.0)
    if status == "new":
        bucket = 0
    elif _is_weak_roadmap_asset(asset):
        bucket = 1
    elif _is_due_roadmap_asset(asset, now_iso=now_iso):
        bucket = 2
    elif mastery_score <= 0.25:
        bucket = 0
    elif mastery_score < 0.55:
        bucket = 3
    else:
        bucket = 4
    return (
        bucket,
        mastery_score,
        str(asset.get("next_review_at") or "9999-12-31T23:59:59+00:00"),
        str(asset.get("learned_at") or asset.get("created_at") or ""),
    )


def _select_roadmap_mission_questions(
    questions: list[dict[str, Any]],
    *,
    asset_ids: list[int],
) -> list[dict[str, Any]]:
    asset_priority = {str(asset_id): index for index, asset_id in enumerate(asset_ids)}
    candidates = [
        question
        for question in questions
        if str(question.get("type") or "") in ROADMAP_PRACTICE_TYPES
        and {str(item) for item in question.get("language_asset_ids", [])} & set(asset_priority)
    ]
    candidates.sort(key=lambda question: _roadmap_mission_question_key(question, asset_priority=asset_priority))
    selected: list[dict[str, Any]] = []
    selected_types: set[str] = set()

    def add(question: dict[str, Any]) -> None:
        if all(int(existing.get("id") or 0) != int(question.get("id") or 0) for existing in selected):
            selected.append(question)
            selected_types.add(str(question.get("type") or ""))

    for question in candidates:
        if len(selected) >= 5:
            break
        if str(question.get("type") or "") in selected_types:
            continue
        add(question)

    hard_question = next(
        (
            question
            for question in candidates
            if str(question.get("type") or "") in ROADMAP_HARD_TYPES
            and all(int(existing.get("id") or 0) != int(question.get("id") or 0) for existing in selected)
        ),
        None,
    )
    if hard_question and not any(str(question.get("type") or "") in ROADMAP_HARD_TYPES for question in selected):
        if len(selected) >= 7:
            selected[-1] = hard_question
        else:
            add(hard_question)

    for question in candidates:
        if len(selected) >= 7:
            break
        add(question)

    return selected[:7]


def _select_daily_review_questions(
    questions: list[dict[str, Any]],
    *,
    asset_ids: list[int],
) -> list[dict[str, Any]]:
    selected = _select_roadmap_mission_questions(questions, asset_ids=asset_ids)
    if len(selected) >= 8:
        return selected[:8]
    asset_priority = {str(asset_id): index for index, asset_id in enumerate(asset_ids)}
    candidates = [
        question
        for question in questions
        if str(question.get("type") or "") in ROADMAP_PRACTICE_TYPES
        and {str(item) for item in question.get("language_asset_ids", [])} & set(asset_priority)
    ]
    candidates.sort(key=lambda question: _roadmap_mission_question_key(question, asset_priority=asset_priority))
    for question in candidates:
        if len(selected) >= 8:
            break
        if all(int(existing.get("id") or 0) != int(question.get("id") or 0) for existing in selected):
            selected.append(question)
    return selected[:8]


def _roadmap_mission_question_key(
    question: dict[str, Any],
    *,
    asset_priority: dict[str, int],
) -> tuple[int, int, int, int, int, int]:
    question_asset_priority = min(
        [asset_priority[str(asset_id)] for asset_id in question.get("language_asset_ids", []) if str(asset_id) in asset_priority]
        or [999]
    )
    question_type = str(question.get("type") or "")
    return (
        question_asset_priority,
        1 if int(question.get("used_in_immediate_quiz") or 0) else 0,
        int(question.get("times_shown") or 0),
        1 if question.get("last_shown_at") else 0,
        _roadmap_question_type_order(question_type),
        int(question.get("id") or 0),
    )


def _roadmap_question_type_order(question_type: str) -> int:
    order = {
        "fill_blank": 0,
        "meaning_match": 1,
        "multiple_choice": 2,
        "better_sentence": 3,
        "sentence_builder": 4,
        "rewrite_challenge": 5,
        "production_challenge": 6,
    }
    return order.get(question_type, 99)


def _select_assets_for_quiz(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for asset in assets:
        asset_type = str(asset.get("type") or "")
        priority = QUIZ_PRIORITY_TYPES.get(asset_type, 0)
        usefulness = int(asset.get("usefulness_score") or asset.get("usefulnessScore") or 0)
        transferability = int(asset.get("transferability_score") or asset.get("transferabilityScore") or 0)
        combined_score = usefulness + transferability
        if priority >= 4 and combined_score >= 120:
            selected.append(asset)
        elif asset_type == "vocabulary" and combined_score >= 150:
            selected.append(asset)
    selected.sort(
        key=lambda item: (
            -QUIZ_PRIORITY_TYPES.get(str(item.get("type") or ""), 0),
            -(int(item.get("usefulness_score") or 0) + int(item.get("transferability_score") or 0)),
            str(item.get("value") or "").casefold(),
        )
    )
    return selected[:10]


def _generate_questions_for_asset(
    asset: dict[str, Any],
    *,
    learning_input: dict[str, Any],
) -> list[dict[str, Any]]:
    value = _clean_text(asset.get("value"))
    asset_type = str(asset.get("type") or "").strip()
    if not value or asset_type not in ASSET_TYPES:
        return []

    asset_id = str(asset.get("id") or "")
    difficulty_level = int(asset.get("difficulty_level") or asset.get("difficultyLevel") or 1)
    meaning = _clean_text(asset.get("meaning") or _asset_meaning(value, asset_type))
    example = _context_sentence_for_asset(asset, learning_input=learning_input)
    correct_sentence = _ensure_sentence(_natural_sentence_for_asset(value, asset_type, example))
    weak_sentence = _weak_sentence_for_asset(value, asset_type, correct_sentence)
    blank_sentence = _blank_asset_in_sentence(value, correct_sentence)
    expected_keywords = _expected_keywords(value, asset_type)
    expanded_answer = _expanded_asset_answer(value, correct_sentence)
    questions = [
        _quiz_question(
            asset_id=asset_id,
            question_type="meaning_match",
            question_text=f'What does "{value}" mean?',
            correct_answer=_meaning_match_answer(value, asset_type, meaning),
            options=_meaning_options(value, asset_type, meaning),
            explanation=meaning,
            difficulty_level=difficulty_level,
            expected_keywords=expected_keywords,
        ),
        _quiz_question(
            asset_id=asset_id,
            question_type="fill_blank",
            question_text=blank_sentence,
            correct_answer=value,
            explanation=f'Use "{value}" to make the sentence more natural.',
            difficulty_level=difficulty_level,
            expected_keywords=expected_keywords,
        ),
        _quiz_question(
            asset_id=asset_id,
            question_type="multiple_choice",
            question_text=f"Which phrase best completes the sentence?\n{blank_sentence}",
            correct_answer=value,
            options=_completion_options(value, asset_type),
            explanation=f'"{value}" is the best fit for this image-description sentence.',
            difficulty_level=difficulty_level,
            expected_keywords=expected_keywords,
        ),
        _quiz_question(
            asset_id=asset_id,
            question_type="better_sentence",
            question_text="Which sentence sounds more natural and descriptive?",
            correct_answer=correct_sentence,
            options=[weak_sentence, correct_sentence],
            explanation=f'The stronger sentence uses "{value}" naturally.',
            difficulty_level=max(1, difficulty_level),
            expected_keywords=expected_keywords,
        ),
        _quiz_question(
            asset_id=asset_id,
            question_type="sentence_builder",
            question_text="",
            prompt="Build the sentence.",
            correct_answer=correct_sentence,
            word_bank=_word_bank_for_sentence(correct_sentence, value),
            explanation=f'Put the words in order to use "{value}" naturally.',
            difficulty_level=min(3, difficulty_level + 1),
            expected_keywords=expected_keywords,
        ),
        _quiz_question(
            asset_id=asset_id,
            question_type="rewrite_challenge",
            question_text=f'Improve this sentence using better English:\n"{weak_sentence}"',
            correct_answer=correct_sentence,
            explanation=f'A good answer should use "{value}" naturally. Flexible checking is expected.',
            difficulty_level=min(3, difficulty_level + 1),
            expected_keywords=expected_keywords,
        ),
        _quiz_question(
            asset_id=asset_id,
            question_type="production_challenge",
            question_text=f'Describe the image using "{value}".',
            correct_answer="Should be evaluated flexibly later.",
            explanation=f'A good answer should include "{value}" and fit the image.',
            difficulty_level=min(3, difficulty_level + 1),
            expected_keywords=expected_keywords,
        ),
    ]
    limit = 8 if asset_type in {"phrase", "sentence_pattern", "positioning_language"} else 6
    if asset_type == "descriptive_language":
        limit = 6
    if asset_type == "vocabulary":
        limit = 3
    return questions[:limit]


def _quiz_question(
    *,
    asset_id: str,
    question_type: str,
    question_text: str,
    correct_answer: str,
    explanation: str,
    difficulty_level: int,
    prompt: str = "",
    options: list[str] | None = None,
    word_bank: list[str] | None = None,
    expected_keywords: list[str] | None = None,
    used_in_immediate_quiz: bool = False,
) -> dict[str, Any]:
    question_text = _clean_text(question_text)
    prompt = _clean_text(prompt)
    correct_answer = _clean_text(correct_answer)
    signature_basis = "|".join(
        [
            asset_id,
            question_type,
            normalize_answer(question_text or prompt),
            normalize_answer(correct_answer),
        ]
    )
    return {
        "languageAssetIds": [asset_id],
        "type": question_type,
        "questionText": question_text,
        "prompt": prompt,
        "correctAnswer": correct_answer,
        "options": _dedupe_options(options or []),
        "wordBank": word_bank or [],
        "explanation": _clean_text(explanation),
        "difficultyLevel": max(1, min(3, int(difficulty_level or 1))),
        "expectedKeywords": _dedupe_options(expected_keywords or []),
        "usedInImmediateQuiz": used_in_immediate_quiz,
        "questionSignature": normalize_answer(signature_basis),
    }


def _context_sentence_for_asset(
    asset: dict[str, Any],
    *,
    learning_input: dict[str, Any],
) -> str:
    value = _clean_text(asset.get("value"))
    sources = [
        asset.get("example_sentence"),
        asset.get("exampleSentence"),
        asset.get("original_source_text"),
        learning_input.get("finalDescription"),
        " ".join(str(item) for item in learning_input.get("enhancementHistory") or []),
    ]
    for source in sources:
        sentence = _find_sentence_with_value(value, _clean_text(source))
        if sentence:
            return sentence
    return _asset_example(value, str(asset.get("type") or ""), _clean_text(sources[0]))


def _natural_sentence_for_asset(value: str, asset_type: str, example: str) -> str:
    if example and normalize_answer(value) in normalize_answer(example):
        return example
    lowered = value.casefold()
    if asset_type == "sentence_pattern":
        return _pattern_example(value)
    if normalize_answer(value) == "covered with":
        return "The building is covered with climbing vines."
    if normalize_answer(value) == "surrounded by":
        return "The building is surrounded by dense greenery."
    if normalize_answer(value) == "visible in the background":
        return "A modern building is visible in the background."
    if asset_type == "positioning_language":
        return f"A small detail is {lowered}."
    if asset_type == "atmosphere_language":
        return f"The scene has a {lowered}."
    if asset_type == "action_language":
        return f"A person is {lowered}."
    if asset_type == "descriptive_language":
        return f"The image includes {lowered}."
    return f"The image shows {lowered}."


def _weak_sentence_for_asset(value: str, asset_type: str, correct_sentence: str) -> str:
    normalized = normalize_answer(value)
    if normalized == "covered with":
        return re.sub(r"\bis covered with\b", "has", correct_sentence, flags=re.IGNORECASE)
    if normalized == "surrounded by":
        return re.sub(r"\bis surrounded by\b", "has things around it", correct_sentence, flags=re.IGNORECASE)
    if asset_type == "sentence_pattern":
        return "There are some things in the picture."
    if asset_type == "positioning_language":
        return "There is something in the picture."
    if asset_type == "atmosphere_language":
        return "The scene is nice."
    if asset_type == "action_language":
        return "A person does something."
    if asset_type == "descriptive_language":
        words = value.split()
        simple = words[-1] if words else "detail"
        return f"The image has {simple}."
    return correct_sentence.replace(value, "something")


def _blank_asset_in_sentence(value: str, sentence: str) -> str:
    if sentence and re.search(rf"\b{re.escape(value)}\b", sentence, flags=re.IGNORECASE):
        return re.sub(rf"\b{re.escape(value)}\b", "______", sentence, count=1, flags=re.IGNORECASE)
    return f'Complete the sentence with "{value}": ______'


def _word_bank_for_sentence(sentence: str, value: str) -> list[str]:
    marker = "__ASSET__"
    asset_pattern = re.compile(rf"\b{re.escape(value)}\b", re.IGNORECASE)
    marked = asset_pattern.sub(marker, sentence, count=1)
    words: list[str] = []
    for token in marked.strip().rstrip(".!?").split():
        cleaned = token.strip(" ,;:!?")
        if not cleaned:
            continue
        words.append(value if cleaned == marker else cleaned)
    return words


def _meaning_match_answer(value: str, asset_type: str, meaning: str) -> str:
    normalized = normalize_answer(value)
    if normalized == "covered with":
        return "full of something on its surface"
    if normalized == "surrounded by":
        return "with things all around it"
    if normalized == "in the background":
        return "behind the main subject"
    if asset_type == "sentence_pattern":
        return "a reusable sentence frame for describing an image"
    return meaning or _asset_meaning(value, asset_type)


def _meaning_options(value: str, asset_type: str, meaning: str) -> list[str]:
    correct = _meaning_match_answer(value, asset_type, meaning)
    distractors = [
        "placed far away from something",
        "hidden below something",
        "moving quickly",
        "only naming one object",
        "showing where something appears",
    ]
    if asset_type == "positioning_language":
        distractors = [
            "describing the color of something",
            "showing a fast action",
            "naming the main object only",
            "describing a sound",
        ]
    return _dedupe_options([correct, *distractors])[:4]


def _completion_options(value: str, asset_type: str) -> list[str]:
    if asset_type == "positioning_language":
        distractors = ["quickly", "brightly", "covered with"]
    elif asset_type == "sentence_pattern":
        distractors = ["single word", "object only", "not visible"]
    else:
        distractors = ["between", "under", "beside", "moving quickly"]
    return _dedupe_options([value, *distractors])[:4]


def _expected_keywords(value: str, asset_type: str) -> list[str]:
    keywords = [value]
    if asset_type in {"phrase", "positioning_language", "sentence_pattern"}:
        keywords.append(normalize_answer(value))
    return [item for item in _dedupe_options(keywords) if item]


def _expanded_asset_answer(value: str, sentence: str) -> str:
    normalized_value = normalize_answer(value)
    normalized_sentence = normalize_answer(sentence)
    if normalized_value and normalized_value in normalized_sentence:
        match = re.search(rf"\b{re.escape(value)}\b(?:\s+[a-z]+){{0,3}}", sentence, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip(" ,.;:!?")
    return value


def _image_recall_question(value: str, asset_type: str) -> str:
    if asset_type == "sentence_pattern":
        return "Look at the image. What sentence pattern did you learn for describing it?"
    if asset_type == "positioning_language":
        return "Look at the image. What phrase did you learn for describing position?"
    if asset_type == "atmosphere_language":
        return "Look at the image. What language did you learn for describing the scene's feeling?"
    return f'Look at the image. What phrase did you learn using "{value}"?'


def _ensure_sentence(value: str) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        return ""
    if cleaned.endswith((".", "!", "?")):
        return cleaned
    return cleaned + "."


def _dedupe_options(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            cleaned.append(text)
    return cleaned


def _questions_from_ai_payload(
    ai_questions: Any,
    *,
    selected_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(ai_questions, list):
        return []

    assets_by_value = {
        normalize_answer(str(asset.get("value") or "")): asset
        for asset in selected_assets
        if asset.get("value")
    }
    questions: list[dict[str, Any]] = []
    for raw_question in ai_questions:
        if not isinstance(raw_question, dict):
            continue
        question_type = str(raw_question.get("type") or "").strip()
        if question_type not in QUIZ_TYPES:
            continue
        asset_values = _dedupe_options(
            [str(value or "") for value in raw_question.get("languageAssetValues") or []]
        )
        matched_assets = [
            assets_by_value[normalize_answer(value)]
            for value in asset_values
            if normalize_answer(value) in assets_by_value
        ]
        if not matched_assets:
            continue
        language_asset_ids = [str(asset.get("id")) for asset in matched_assets if asset.get("id")]
        question_text = _clean_text(raw_question.get("questionText"))
        prompt = _clean_text(raw_question.get("prompt"))
        correct_answer = _clean_text(raw_question.get("correctAnswer"))
        if not correct_answer or (not question_text and not prompt):
            continue
        try:
            difficulty_level = int(raw_question.get("difficultyLevel") or 1)
        except (TypeError, ValueError):
            difficulty_level = 1
        expected_keywords = asset_values if question_type in {"production_challenge", "rewrite_challenge"} else []
        if not expected_keywords:
            expected_keywords = _dedupe_options(
                keyword
                for asset in matched_assets
                for keyword in _expected_keywords(str(asset.get("value") or ""), str(asset.get("type") or ""))
            )
        signature_basis = "|".join(
            [
                ",".join(language_asset_ids),
                question_type,
                normalize_answer(question_text or prompt),
                normalize_answer(correct_answer),
            ]
        )
        questions.append(
            {
                "languageAssetIds": language_asset_ids,
                "type": question_type,
                "questionText": question_text,
                "prompt": prompt,
                "correctAnswer": correct_answer,
                "options": _dedupe_options([str(item or "") for item in raw_question.get("options") or []]),
                "wordBank": _dedupe_options([str(item or "") for item in raw_question.get("wordBank") or []]),
                "explanation": _clean_text(raw_question.get("explanation")),
                "difficultyLevel": max(1, min(3, difficulty_level)),
                "expectedKeywords": expected_keywords,
                "usedInImmediateQuiz": False,
                "questionSignature": normalize_answer(signature_basis),
            }
        )
    return questions


def _select_immediate_quiz_questions(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not questions:
        return []

    selected: list[dict[str, Any]] = []
    required_groups = [
        ("fill_blank",),
        ("meaning_match", "multiple_choice"),
        ("better_sentence",),
        ("sentence_builder",),
    ]

    def add_question(question: dict[str, Any] | None) -> None:
        if question and all(int(existing["id"]) != int(question["id"]) for existing in selected):
            selected.append(question)

    for group in required_groups:
        add_question(_best_question_for_types(questions, group, exclude=selected))

    target_count = 6
    production = _best_question_for_types(questions, ("production_challenge",), exclude=selected)
    fill_types = (
        "multiple_choice",
        "meaning_match",
        "rewrite_challenge",
        "fill_blank",
        "better_sentence",
        "sentence_builder",
    )
    while len(selected) < target_count:
        selected_types = {str(question.get("type") or "") for question in selected}
        next_question = None
        for question_type in fill_types:
            if question_type in selected_types:
                continue
            next_question = _best_question_for_types(questions, (question_type,), exclude=selected)
            if next_question:
                break
        if not next_question:
            next_question = _best_question_for_types(questions, fill_types, exclude=selected)
        if not next_question:
            break
        add_question(next_question)

    if production and len(selected) < 7:
        add_question(production)

    if len(selected) < 5:
        for question in _sorted_immediate_candidates(questions):
            add_question(question)
            if len(selected) >= 5:
                break

    non_production = [question for question in selected if question.get("type") != "production_challenge"]
    production_items = [question for question in selected if question.get("type") == "production_challenge"]
    non_production.sort(
        key=lambda question: (
            int(question.get("difficulty_level") or 1),
            int(question.get("times_shown") or 0),
            _immediate_type_order(str(question.get("type") or "")),
            int(question.get("id") or 0),
        )
    )
    return [*non_production, *production_items][:7]


def _select_past_practice_questions(
    questions: list[dict[str, Any]],
    *,
    assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not questions:
        return []
    weak_asset_ids = _weak_language_asset_ids(assets)
    candidates = list(questions)
    candidates.sort(key=lambda question: _past_practice_candidate_key(question, weak_asset_ids=weak_asset_ids))

    selected: list[dict[str, Any]] = []
    selected_types: set[str] = set()

    def add(question: dict[str, Any] | None) -> None:
        if question and all(int(existing["id"]) != int(question["id"]) for existing in selected):
            selected.append(question)
            selected_types.add(str(question.get("type") or ""))

    for question in candidates:
        if str(question.get("type") or "") in selected_types:
            continue
        add(question)
        if len(selected) >= 6:
            break

    for question in candidates:
        if len(selected) >= 8:
            break
        add(question)

    if len(selected) < 5:
        for question in _sorted_immediate_candidates(questions):
            add(question)
            if len(selected) >= 5:
                break

    selected.sort(
        key=lambda question: (
            int(question.get("difficulty_level") or 1),
            _immediate_type_order(str(question.get("type") or "")),
            int(question.get("times_shown") or 0),
            int(question.get("id") or 0),
        )
    )
    return selected[:10]


def _weak_language_asset_ids(assets: list[dict[str, Any]]) -> set[str]:
    now_iso = to_iso(utc_now())
    weak: set[str] = set()
    for asset in assets:
        mastery_score = float(asset.get("mastery_score") or 0.0)
        wrong_count = int(asset.get("wrong_count") or 0)
        correct_count = int(asset.get("correct_count") or 0)
        next_review_at = str(asset.get("next_review_at") or "")
        if (
            mastery_score < 0.55
            or wrong_count > correct_count
            or int(asset.get("recently_answered_wrong") or 0)
            or (next_review_at and next_review_at <= now_iso)
        ):
            weak.add(str(asset.get("id")))
    return weak


def _past_practice_candidate_key(
    question: dict[str, Any],
    *,
    weak_asset_ids: set[str],
) -> tuple[int, int, int, int, int, int]:
    asset_ids = {str(item) for item in question.get("language_asset_ids", [])}
    recently_shown_cutoff = to_iso(utc_now() - timedelta(hours=12))
    last_shown_at = str(question.get("last_shown_at") or "")
    return (
        1 if last_shown_at and last_shown_at >= recently_shown_cutoff else 0,
        0 if asset_ids & weak_asset_ids else 1,
        int(question.get("times_shown") or 0),
        1 if int(question.get("used_in_immediate_quiz") or 0) else 0,
        _immediate_type_order(str(question.get("type") or "")),
        int(question.get("id") or 0),
    )


def _best_question_for_types(
    questions: list[dict[str, Any]],
    question_types: tuple[str, ...],
    *,
    exclude: list[dict[str, Any]],
) -> dict[str, Any] | None:
    excluded_ids = {int(question["id"]) for question in exclude}
    candidates = [
        question
        for question in questions
        if str(question.get("type") or "") in question_types
        and int(question.get("id") or 0) not in excluded_ids
    ]
    if not candidates:
        return None
    candidates.sort(key=_immediate_candidate_key)
    return candidates[0]


def _sorted_immediate_candidates(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = list(questions)
    candidates.sort(key=_immediate_candidate_key)
    return candidates


def _immediate_candidate_key(question: dict[str, Any]) -> tuple[int, int, int, int, int]:
    return (
        1 if int(question.get("used_in_immediate_quiz") or 0) else 0,
        int(question.get("times_shown") or 0),
        int(question.get("difficulty_level") or 1),
        _immediate_type_order(str(question.get("type") or "")),
        int(question.get("id") or 0),
    )


def _immediate_type_order(question_type: str) -> int:
    order = {
        "meaning_match": 0,
        "fill_blank": 1,
        "multiple_choice": 2,
        "better_sentence": 3,
        "sentence_builder": 4,
        "image_recall": 5,
        "rewrite_challenge": 6,
        "production_challenge": 7,
    }
    return order.get(question_type, 99)


def _public_quiz_question(question: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": question.get("id"),
        "userId": question.get("user_id"),
        "sessionId": question.get("session_id"),
        "languageAssetIds": [str(item) for item in question.get("language_asset_ids", [])],
        "type": question.get("type"),
        "questionText": question.get("question_text") or "",
        "prompt": question.get("prompt") or None,
        "correctAnswer": question.get("correct_answer") or "",
        "options": question.get("options") or None,
        "wordBank": question.get("word_bank") or None,
        "explanation": question.get("explanation") or "",
        "difficultyLevel": int(question.get("difficulty_level") or 1),
        "expectedKeywords": question.get("expected_keywords") or [],
        "usedInImmediateQuiz": bool(question.get("used_in_immediate_quiz")),
        "lastShownAt": question.get("last_shown_at"),
        "timesShown": int(question.get("times_shown") or 0),
        "correctCount": int(question.get("correct_count") or 0),
        "wrongCount": int(question.get("wrong_count") or 0),
        "createdAt": question.get("created_at"),
        "updatedAt": question.get("updated_at"),
    }


def _evaluate_quiz_answer(question: dict[str, Any], answer: str) -> dict[str, Any]:
    question_type = str(question.get("type") or "")
    correct_answer = str(question.get("correct_answer") or "")
    expected_keywords = [str(item) for item in question.get("expected_keywords", []) if str(item or "").strip()]
    if not expected_keywords:
        expected_keywords = [correct_answer]

    if question_type in {"rewrite_challenge", "production_challenge"}:
        matched_keywords = [
            keyword
            for keyword in expected_keywords
            if _keyword_matches_answer(keyword, answer)
        ]
        score = len(matched_keywords) / max(1, len(expected_keywords))
        return {
            "isCorrect": score >= 0.999,
            "score": 1.0 if score >= 0.999 else 0.5 if score > 0 else 0.0,
            "expectedKeywords": expected_keywords,
            "matchedKeywords": matched_keywords,
        }

    is_correct = _normalized_quiz_answer(answer) == _normalized_quiz_answer(correct_answer)
    if not is_correct and question_type == "sentence_builder":
        is_correct = _normalized_quiz_answer(" ".join(answer.split())) == _normalized_quiz_answer(correct_answer)
    return {
        "isCorrect": is_correct,
        "score": 1.0 if is_correct else 0.0,
        "expectedKeywords": expected_keywords,
        "matchedKeywords": expected_keywords if is_correct else [],
    }


def _evaluate_roadmap_practice_answer(question: dict[str, Any], answer: str) -> dict[str, Any]:
    question_type = str(question.get("type") or "")
    if question_type in {"rewrite_challenge", "production_challenge"}:
        return _evaluate_flexible_roadmap_answer(question, answer)
    return _evaluate_quiz_answer(question, answer)


def _evaluate_flexible_roadmap_answer(question: dict[str, Any], answer: str) -> dict[str, Any]:
    expected_keywords = [str(item) for item in question.get("expected_keywords", []) if str(item or "").strip()]
    if not expected_keywords:
        expected_keywords = [str(question.get("correct_answer") or "")]
    matched_keywords = [
        keyword
        for keyword in expected_keywords
        if _keyword_matches_answer(keyword, answer)
    ]
    score = len(matched_keywords) / max(1, len(expected_keywords))
    is_correct = bool(matched_keywords) if len(expected_keywords) == 1 else score >= 0.5
    return {
        "isCorrect": is_correct,
        "score": 1.0 if is_correct else 0.0,
        "expectedKeywords": expected_keywords,
        "matchedKeywords": matched_keywords,
    }


def _roadmap_mastery_gain(question_type: str, *, hint_used: bool) -> int:
    gains = {
        "meaning_match": 4,
        "multiple_choice": 4,
        "better_sentence": 6,
        "fill_blank": 7,
        "image_recall": 7,
        "sentence_builder": 9,
        "rewrite_challenge": 12,
        "production_challenge": 15,
    }
    gain = gains.get(question_type, 4)
    return max(1, round(gain * 0.5)) if hint_used else gain


def _roadmap_practice_xp(question: dict[str, Any]) -> int:
    difficulty = int(question.get("difficulty_level") or 1)
    if difficulty >= 3:
        return 12
    if difficulty == 2:
        return 8
    return 5


def _roadmap_status_for_mastery(
    mastery_score: float,
    *,
    wrong_count: int,
    recently_wrong: bool,
) -> str:
    mastery_percent = round(max(0.0, min(1.0, float(mastery_score or 0.0))) * 100)
    if recently_wrong or int(wrong_count or 0) >= 3:
        return "weak"
    if mastery_percent <= 25:
        return "new"
    if mastery_percent <= 50:
        return "learning"
    if mastery_percent <= 70:
        return "familiar"
    if mastery_percent <= 90:
        return "strong"
    return "mastered"


def _roadmap_review_delay(*, is_correct: bool, mastery_score: float) -> timedelta:
    if not is_correct:
        return timedelta(hours=6)
    mastery_percent = round(max(0.0, min(1.0, float(mastery_score or 0.0))) * 100)
    if mastery_percent <= 25:
        return timedelta(days=1)
    if mastery_percent <= 50:
        return timedelta(days=2)
    if mastery_percent <= 70:
        return timedelta(days=4)
    if mastery_percent <= 90:
        return timedelta(days=7)
    return timedelta(days=14)


def _normalized_quiz_answer(value: str) -> str:
    return normalize_answer(str(value or "").replace("...", ""))


def _keyword_matches_answer(keyword: str, answer: str) -> bool:
    normalized_keyword = _normalized_quiz_answer(keyword)
    normalized_answer = _normalized_quiz_answer(answer)
    return bool(normalized_keyword and normalized_keyword in normalized_answer)


def _review_delay_for_score(score: float) -> timedelta:
    score = float(score or 0.0)
    if score >= 1.0:
        return timedelta(days=3)
    if score >= 0.5:
        return timedelta(days=1)
    return timedelta(hours=6)


def _xp_for_quiz_score(score: float) -> int:
    score = float(score or 0.0)
    if score >= 1.0:
        return 5
    if score >= 0.5:
        return 2
    return 0


def _stored_asset_to_public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "value": row.get("value", ""),
        "type": row.get("type", ""),
        "source": row.get("source", ""),
        "meaning": row.get("meaning", ""),
        "exampleSentence": row.get("example_sentence", ""),
        "difficultyLevel": int(row.get("difficulty_level") or 1),
        "usefulnessScore": int(row.get("usefulness_score") or 0),
        "transferabilityScore": int(row.get("transferability_score") or 0),
        "roadmapSkillKey": row.get("roadmap_skill_key", ""),
        "status": row.get("status", ""),
        "masteryScore": round(float(row.get("mastery_score") or 0.0) * 100),
    }
