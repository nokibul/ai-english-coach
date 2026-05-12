from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

from aiohttp import web

from .ai_service import AIAnalyzer
from .assessment import ONBOARDING_QUESTIONS, evaluate_assessment
from .config import AppConfig
from .database import Database
from .learning import canonical_level, level_label
from .mailer import Mailer
from .progress import combo_bonus_for_streak, level_from_xp, update_streak, xp_for_event
from .quiz_engine import (
    QuizSelectionProfile,
    arrange_session_quick_challenge,
    build_post_improve_quiz_rows,
    build_session_assets,
    choose_quiz_candidates,
    evaluate_quiz_response,
)
from .review import build_review_options, calculate_next_review
from .security import generate_otp, hash_password, hash_token, make_token, verify_password
from .utils import (
    ALLOWED_IMAGE_MIME_TYPES,
    ensure_directory,
    from_iso,
    highlight_phrases,
    normalize_answer,
    normalize_phone,
    should_surface_term,
    slugify_filename,
    term_surface_score,
    to_iso,
    utc_now,
)


def build_app(config: AppConfig | None = None) -> web.Application:
    config = config or AppConfig.from_env()
    ensure_directory(config.data_dir)
    ensure_directory(config.uploads_dir)
    ensure_directory(config.database_path.parent)
    db = Database(config.database_path)
    db.initialize()

    app = web.Application(
        client_max_size=max(config.max_upload_bytes + (2 * 1024 * 1024), 64 * 1024 * 1024),
        middlewares=[error_middleware, user_middleware],
    )
    app["config"] = config
    app["db"] = db
    app["mailer"] = Mailer(config)
    app["analyzer"] = AIAnalyzer(config)
    app.on_cleanup.append(close_background_clients)

    app.router.add_get("/", index)
    app.router.add_get("/healthz", healthz)
    app.router.add_static("/static/", str(config.static_dir))

    app.router.add_get("/api/bootstrap", bootstrap)
    app.router.add_post("/api/auth/signup", signup)
    app.router.add_post("/api/auth/resend-otp", resend_otp)
    app.router.add_post("/api/auth/verify-otp", verify_otp)
    app.router.add_post("/api/auth/login", login)
    app.router.add_post("/api/auth/logout", logout)
    app.router.add_get("/api/me", get_me)
    app.router.add_post("/api/analyze", analyze_image)
    app.router.add_post(r"/api/sessions/{session_id:\d+}/feedback", session_feedback)
    app.router.add_post(r"/api/sessions/{session_id:\d+}/post-improve-quiz", session_post_improve_quiz)
    app.router.add_get(r"/api/sessions/{session_id:\d+}/image", session_image)
    app.router.add_get("/api/sessions", list_sessions)
    app.router.add_get(r"/api/sessions/{session_id:\d+}", get_session)
    app.router.add_get("/api/quiz/dashboard", quiz_dashboard)
    app.router.add_post("/api/quiz/start", quiz_start)
    app.router.add_post("/api/quiz/answer", quiz_answer)
    app.router.add_get("/api/review/dashboard", review_dashboard)
    app.router.add_get("/api/review/queue", review_queue)
    app.router.add_post("/api/review/answer", review_answer)
    app.router.add_get("/api/challenge/today", challenge_today)
    app.router.add_get("/api/progress/dashboard", progress_dashboard)
    return app


async def close_background_clients(app: web.Application) -> None:
    await app["analyzer"].close()


@web.middleware
async def error_middleware(request: web.Request, handler):
    try:
        return await handler(request)
    except web.HTTPException as exc:
        if request.path.startswith("/api/"):
            message = exc.reason or exc.text or "Request failed."
            return web.json_response({"error": message}, status=exc.status)
        raise
    except Exception as exc:  # pragma: no cover - best effort safety net
        print(f"[server-error] {exc}")
        if request.path.startswith("/api/"):
            return web.json_response(
                {"error": "Unexpected server error. Check the server logs for details."},
                status=500,
            )
        raise


@web.middleware
async def user_middleware(request: web.Request, handler):
    request["user"] = None
    config: AppConfig = request.app["config"]
    if config.disable_login_flow:
        request["user"] = ensure_dev_user(request.app["db"], config)
        return await handler(request)

    session_cookie = request.cookies.get(config.session_cookie_name)
    if session_cookie:
        token_hash = hash_token(session_cookie)
        request["user"] = request.app["db"].get_user_by_session_hash(
            session_token_hash=token_hash,
            now_iso=to_iso(utc_now()),
        )
    return await handler(request)


def current_user(request: web.Request) -> dict[str, Any]:
    user = request.get("user")
    if not user:
        raise web.HTTPUnauthorized(reason="Please log in first.")
    return user


def ensure_dev_user(db: Database, config: AppConfig) -> dict[str, Any]:
    email = (config.dev_user_email or "dev@local.test").strip().lower()
    user = db.get_user_by_email(email)
    if user:
        if not user["is_verified"]:
            db.set_user_verified(user["id"])
            user = db.get_user_by_id(user["id"])
        return user

    now_iso = to_iso(utc_now())
    user = db.create_user(
        full_name=(config.dev_user_name or "Dev Learner").strip() or "Dev Learner",
        phone=None,
        email=email,
        password_hash=hash_password(make_token(24)),
        difficulty_band="developing",
        fluency_score=60,
        fluency_summary="Development user with login disabled.",
        assessment={"source": "DISABLE_LOGIN_FLOW"},
        created_at=now_iso,
    )
    db.set_user_verified(user["id"])
    return db.get_user_by_id(user["id"])


async def optional_json(request: web.Request) -> dict[str, Any]:
    if not request.can_read_body:
        return {}
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    difficulty_band = canonical_level(user.get("difficulty_band"))
    return {
        "id": user["id"],
        "full_name": user["full_name"],
        "phone": user.get("phone"),
        "email": user["email"],
        "difficulty_band": difficulty_band,
        "difficulty_label": level_label(difficulty_band),
        "fluency_summary": user["fluency_summary"],
        "is_verified": bool(user["is_verified"]),
        "created_at": user["created_at"],
    }


def serialize_session_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "image_name": row["image_name"],
        "difficulty_band": canonical_level(row["difficulty_band"]),
        "difficulty_label": level_label(row["difficulty_band"]),
        "source_mode": row["source_mode"],
        "mastery_percent": float(row.get("mastery_percent") or 0.0),
        "created_at": row["created_at"],
    }


def _session_summary_json(row: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(row.get("summary_json") or "{}")
    except json.JSONDecodeError:
        return {}


def build_highlight_terms(
    *,
    phrases: list[dict[str, Any]] | None = None,
    vocabulary: list[dict[str, Any]] | None = None,
    reusable_language: list[dict[str, Any]] | None = None,
) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    def push(value: str, *, kind: str = "") -> None:
        text = str(value or "").strip()
        key = normalize_answer(text)
        if not text or not key or key in seen or not should_surface_term(text, kind=kind):
            return
        seen.add(key)
        terms.append(text)

    for item in phrases or []:
        push(
            str(item.get("phrase") or ""),
            kind=str(item.get("collocation_type") or "phrase").strip(),
        )
    for item in vocabulary or []:
        push(
            str(item.get("word") or ""),
            kind=str(item.get("part_of_speech") or "word").strip(),
        )
    for item in reusable_language or []:
        push(
            str(item.get("text") or ""),
            kind=str(item.get("kind") or "phrase").strip(),
        )
    return sorted(
        terms,
        key=lambda term: (
            -term_surface_score(
                term,
                kind=next(
                    (
                        str(item.get("kind") or "phrase").strip()
                        for item in reusable_language or []
                        if normalize_answer(str(item.get("text") or "")) == normalize_answer(term)
                    ),
                    "",
                ),
            ),
            -len(term),
            term.casefold(),
        ),
    )


def serialize_session_detail(
    db: Database,
    row: dict[str, Any],
    *,
    user_id: int,
) -> dict[str, Any]:
    summary = _session_summary_json(row)
    vocabulary = db.list_session_vocabulary(user_id=user_id, session_id=int(row["id"]))
    phrases = db.list_session_phrases(user_id=user_id, session_id=int(row["id"]))
    quiz_preview = db.list_session_quiz_items(user_id=user_id, session_id=int(row["id"]), limit=12)

    simple_explanation = (
        row.get("simple_explanation")
        or summary.get("scene_summary_simple")
        or row.get("natural_explanation")
        or row.get("narrative_text")
        or ""
    )
    natural_explanation = (
        row.get("natural_explanation")
        or row.get("narrative_text")
        or summary.get("scene_summary_natural")
        or summary.get("native_explanation")
        or ""
    )
    highlighted_html = row.get("highlighted_html") or highlight_phrases(
        natural_explanation,
        build_highlight_terms(
            phrases=phrases,
            vocabulary=vocabulary,
            reusable_language=summary.get("reusable_language", []),
        ),
    )

    return {
        "id": row["id"],
        "title": row["title"],
        "image_name": row["image_name"],
        "difficulty_band": canonical_level(row["difficulty_band"]),
        "difficulty_label": level_label(row["difficulty_band"]),
        "source_mode": row["source_mode"],
        "created_at": row["created_at"],
        "mastery_percent": float(row.get("mastery_percent") or 0.0),
        "image_url": f"/api/sessions/{row['id']}/image",
        "analysis": {
            "simple_explanation": simple_explanation,
            "natural_explanation": natural_explanation,
            "highlighted_html": highlighted_html,
            "objects": summary.get("objects", []),
            "actions": summary.get("actions", []),
            "environment": summary.get("environment", ""),
            "environment_details": summary.get("environment_details", []),
            "teaching_notes": summary.get("teaching_notes") or summary.get("scene_notes", []),
            "vocabulary": vocabulary or summary.get("vocabulary", []),
            "phrases": phrases or summary.get("phrases", []),
            "sentence_patterns": summary.get("sentence_patterns", []),
            "quiz_candidates": summary.get("quiz_candidates", []),
            "reusable_language": summary.get("reusable_language", []),
            "micro_quiz": summary.get("micro_quiz", []),
            "difficulty_note": summary.get("difficulty_note", ""),
            "difficulty_recommendation": summary.get("difficulty_recommendation", ""),
        },
        "quiz_preview": [
            {
                "id": item["id"],
                "quiz_type": item["quiz_type"],
                "prompt": item["prompt"],
                "answer_mode": item["answer_mode"],
                "difficulty": float(item.get("difficulty") or 0.0),
                "skill_tag": item.get("skill_tag", ""),
            }
            for item in quiz_preview
        ],
    }


def serialize_quiz_question(item: dict[str, Any], *, total_questions: int) -> dict[str, Any]:
    metadata = item.get("metadata", {})
    return {
        "id": item["id"],
        "quiz_item_id": item.get("quiz_item_id"),
        "card_id": item.get("card_id"),
        "quiz_type": item["quiz_type"],
        "answer_mode": item["answer_mode"],
        "prompt": item["prompt"],
        "context_note": item.get("context_note", ""),
        "options": list(item.get("options", [])),
        "acceptable_answers": list(item.get("acceptable_answers", [])),
        "metadata": metadata,
        "related_reusable_phrase": metadata.get("related_reusable_phrase", ""),
        "difficulty": float(metadata.get("difficulty", 0.0) or 0.0),
        "xp_value": int(metadata.get("xp_value", 0) or 0),
        "question_index": int(item["question_index"]) + 1,
        "total_questions": total_questions,
    }


def serialize_quiz_run(
    db: Database,
    *,
    user_id: int,
    run_id: int,
    include_question: bool = True,
) -> dict[str, Any] | None:
    run = db.get_quiz_run(user_id=user_id, run_id=run_id)
    if not run:
        return None

    items = db.list_quiz_run_items(run_id=run_id)
    answered_count = sum(1 for item in items if item["was_correct"] is not None)
    remaining_count = max(0, int(run["total_questions"]) - answered_count)
    accuracy_percent = (
        round((int(run["correct_count"]) / answered_count) * 100) if answered_count else 0
    )
    reward_summary = summarize_quiz_rewards(items)
    next_item = next((item for item in items if item["was_correct"] is None), None)

    return {
        "id": run["id"],
        "run_mode": run.get("run_mode", "mixed"),
        "challenge_id": run.get("challenge_id"),
        "session_id": run.get("session_id"),
        "source_label": run.get("source_label", ""),
        "status": run["status"],
        "total_questions": int(run["total_questions"]),
        "answered_count": answered_count,
        "remaining_count": remaining_count,
        "correct_count": int(run["correct_count"]),
        "wrong_count": int(run["wrong_count"]),
        "started_at": run["started_at"],
        "completed_at": run["completed_at"],
        "question": (
            serialize_quiz_question(next_item, total_questions=int(run["total_questions"]))
            if include_question and next_item
            else None
        ),
        "summary": {
            "correct_count": int(run["correct_count"]),
            "wrong_count": int(run["wrong_count"]),
            "accuracy_percent": accuracy_percent,
            **reward_summary,
        },
    }


def summarize_quiz_rewards(items: list[dict[str, Any]]) -> dict[str, Any]:
    total_xp = 0
    combo = 0
    max_combo = 0
    phrases: list[str] = []
    score_improvement = 0
    correct_count = 0
    answered_count = 0
    perfect_quiz = False
    for item in items:
        if item.get("was_correct") is None:
            continue
        answered_count += 1
        metadata = item.get("metadata") or {}
        phrase = str(metadata.get("related_reusable_phrase") or "").strip()
        if phrase and phrase not in phrases:
            phrases.append(phrase)
        score_improvement = max(score_improvement, int(metadata.get("score_improvement") or 0))
        feedback = item.get("feedback") if isinstance(item.get("feedback"), dict) else {}
        if "xp_awarded" in feedback:
            total_xp += int(feedback.get("xp_awarded") or 0)
        score = float(item.get("score") or 0.0)
        correct = bool(item.get("was_correct"))
        almost = not correct and score >= 0.5
        if correct:
            correct_count += 1
            combo += 1
            max_combo = max(max_combo, combo)
            if "xp_awarded" not in feedback:
                total_xp += xp_for_event("quiz_correct")
                if combo >= 3 and combo % 3 == 0:
                    total_xp += xp_for_event("combo_bonus")
        elif almost:
            if "xp_awarded" not in feedback:
                total_xp += xp_for_event("quiz_almost")
        else:
            combo = 0
    if answered_count:
        perfect_quiz = correct_count == answered_count
    return {
        "xp_earned": total_xp,
        "max_combo": max_combo,
        "correct_answers": correct_count,
        "answered_count": answered_count,
        "perfect_quiz": perfect_quiz,
        "phrase_practiced": phrases[0] if phrases else "",
        "phrases_practiced": phrases,
        "score_improvement": score_improvement,
    }


def build_review_dashboard_payload(
    db: Database,
    *,
    user_id: int,
    now_iso: str,
) -> dict[str, Any]:
    due_cards = db.list_review_cards(user_id=user_id, now_iso=now_iso, limit=5, manual_mode=True)
    return {
        "due_count": db.get_stats(user_id=user_id, now_iso=now_iso)["due_count"],
        "weak_items": db.get_stats(user_id=user_id, now_iso=now_iso)["weak_items"],
        "items": [
            {
                "id": card["id"],
                "session_id": card["session_id"],
                "session_title": card["session_title"],
                "card_kind": card["card_kind"],
                "prompt": card["prompt"],
                "context_note": card["context_note"],
                "mastery": float(card.get("mastery") or 0.0),
                "mastery_percent": round(float(card.get("mastery") or 0.0) * 100),
                "wrong_streak": int(card.get("wrong_streak") or 0),
                "is_weak": int(card.get("wrong_streak") or 0) >= 2,
            }
            for card in due_cards
        ],
    }


def build_daily_challenge_summary(challenge: dict[str, Any] | None) -> dict[str, Any] | None:
    if not challenge:
        return None
    return {
        "id": challenge["id"],
        "challenge_date": challenge["challenge_date"],
        "status": challenge["status"],
        "total_questions": int(challenge["total_questions"]),
        "completed_questions": int(challenge["completed_questions"]),
        "correct_count": int(challenge["correct_count"]),
        "xp_awarded": int(challenge.get("xp_awarded") or 0),
        "summary": challenge.get("summary", {}),
        "can_start": challenge["status"] != "completed" and int(challenge["total_questions"]) > 0,
    }


def build_quiz_dashboard(
    db: Database,
    config: AppConfig,
    *,
    user: dict[str, Any],
    now,
) -> dict[str, Any]:
    now_iso = to_iso(now)
    stats = db.get_stats(user_id=user["id"], now_iso=now_iso)
    progress = db.get_quiz_progress(user_id=user["id"])
    active_run = db.get_active_quiz_run(user_id=user["id"])
    active_run_payload = (
        serialize_quiz_run(db, user_id=user["id"], run_id=int(active_run["id"]), include_question=False)
        if active_run
        else None
    )
    last_completed_run = db.get_last_completed_quiz_run(user_id=user["id"])

    cooldown_active = False
    next_available_at = None
    candidate_count = len(db.list_candidate_quiz_items(user_id=user["id"], limit=80))
    can_start = bool(active_run_payload) or candidate_count > 0
    if (
        not active_run_payload
        and last_completed_run
        and last_completed_run.get("completed_at")
        and stats["due_count"] == 0
    ):
        unlock_at = from_iso(last_completed_run["completed_at"]) + timedelta(
            minutes=config.quiz_retake_minutes
        )
        next_available_at = to_iso(unlock_at)
        if unlock_at > now and candidate_count > 0:
            cooldown_active = True
            can_start = False

    available_question_count = min(3, candidate_count) if candidate_count else 0
    profile = db.get_learning_profile_snapshot(user_id=user["id"], now_iso=now_iso)

    return {
        "due_count": stats["due_count"],
        "cards_total": stats["cards_total"],
        "quiz_items_total": stats["quiz_items_total"],
        "weak_items": stats["weak_items"],
        "correct_count": progress["correct_count"],
        "wrong_count": progress["wrong_count"],
        "answered_count": progress["answered_count"],
        "accuracy_percent": (
            round((progress["correct_count"] / progress["answered_count"]) * 100)
            if progress["answered_count"]
            else 0
        ),
        "completed_runs": progress["completed_runs"],
        "cooldown_minutes": config.quiz_retake_minutes,
        "cooldown_active": cooldown_active,
        "next_available_at": next_available_at,
        "can_start": can_start,
        "available_question_count": available_question_count,
        "active_run": active_run_payload,
        "adaptive_level": level_label(canonical_level(user["difficulty_band"])),
        "recent_accuracy_percent": round(float(profile["recent_accuracy"]) * 100),
        "active_profile": profile,
        "last_completed_run": (
            {
                "id": last_completed_run["id"],
                "correct_count": int(last_completed_run["correct_count"]),
                "wrong_count": int(last_completed_run["wrong_count"]),
                "total_questions": int(last_completed_run["total_questions"]),
                "completed_at": last_completed_run["completed_at"],
                "run_mode": last_completed_run.get("run_mode", "mixed"),
            }
            if last_completed_run
            else None
        ),
    }


def mark_due_flags(items: list[dict[str, Any]], *, now_iso: str) -> list[dict[str, Any]]:
    marked: list[dict[str, Any]] = []
    for item in items:
        candidate = dict(item)
        review_due_at = candidate.get("review_due_at")
        candidate["is_due"] = bool(review_due_at and str(review_due_at) <= now_iso)
        marked.append(candidate)
    return marked


def build_quiz_options(
    item: dict[str, Any],
    *,
    pool: list[str],
) -> list[str]:
    if item.get("answer_mode") != "multiple_choice":
        return []

    option_limit = 2 if item.get("quiz_type") in {"choose_better", "phrase_duel"} else 4
    values: list[str] = []
    seen: set[str] = set()
    for value in [item["correct_answer"], *item.get("distractors", []), *pool]:
        text = str(value or "").strip()
        key = normalize_answer(text)
        if not text or not key or key in seen:
            continue
        seen.add(key)
        values.append(text)
        if len(values) >= option_limit:
            break
    if item.get("review_card_id") and len(values) < 4:
        review_card = {
            "card_kind": "quiz",
            "answer": item["correct_answer"],
        }
        values = build_review_options(review_card, values[1:])
    return values


def build_run_items(
    candidates: list[dict[str, Any]],
    *,
    pool: list[str],
) -> list[dict[str, Any]]:
    run_items: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        run_items.append(
            {
                "quiz_item_id": int(candidate["id"]),
                "card_id": candidate.get("review_card_id"),
                "session_id": candidate.get("session_id"),
                "quiz_type": candidate["quiz_type"],
                "answer_mode": candidate["answer_mode"],
                "prompt": candidate["prompt"],
                "context_note": candidate.get("explanation", ""),
                "options": build_quiz_options(candidate, pool=pool),
                "acceptable_answers": list(candidate.get("acceptable_answers", [])),
                "correct_answer": candidate["correct_answer"],
                "explanation": candidate.get("explanation", ""),
                "metadata": {
                    **(candidate.get("metadata", {}) or {}),
                    "difficulty": float(candidate.get("difficulty") or 0.0),
                },
                "question_index": index,
            }
        )
    return run_items


def quiz_difficulty_label(item: dict[str, Any]) -> str:
    metadata = item.get("metadata") or {}
    difficulty = float(metadata.get("difficulty") or 0.0)
    if difficulty <= 0.4:
        return "easy"
    if difficulty <= 0.65:
        return "medium"
    return "hard"


def quiz_base_xp(item: dict[str, Any]) -> int:
    return {
        "easy": 5,
        "medium": 10,
        "hard": 15,
    }[quiz_difficulty_label(item)]


def quiz_has_perfect_phrase_usage(
    *, item: dict[str, Any], selected_answer: str, correct: bool
) -> bool:
    if not correct:
        return False
    metadata = item.get("metadata") or {}
    phrase = str(metadata.get("related_reusable_phrase") or "").strip()
    if not phrase:
        return False
    if str(item.get("quiz_type") or "") == "use_it_or_lose_it":
        return True
    return normalize_answer(phrase) in normalize_answer(selected_answer)


def quiz_run_completion_bonuses(
    *,
    db: Database,
    run_id: int,
    completed: bool,
) -> dict[str, Any]:
    if not completed:
        return {"complete_all_types_bonus": 0, "perfect_quiz_bonus": 0, "completed_types": []}
    items = db.list_quiz_run_items(run_id=run_id)
    answered_types = {
        str(item.get("quiz_type") or "")
        for item in items
        if item.get("was_correct") is not None
    }
    required_types = {
        "multiple_choice_comprehension",
        "matching_pairs",
        "fill_blank",
        "sentence_reconstruction",
    }
    complete_all_types_bonus = 0
    answered_items = [item for item in items if item.get("was_correct") is not None]
    perfect_quiz_bonus = (
        20
        if answered_items
        and len(answered_items) == len(items)
        and all(bool(item.get("was_correct")) for item in answered_items)
        else 0
    )
    return {
        "complete_all_types_bonus": complete_all_types_bonus,
        "perfect_quiz_bonus": perfect_quiz_bonus,
        "completed_types": sorted(answered_types),
    }


def build_quiz_xp_breakdown(
    *,
    item: dict[str, Any],
    selected_answer: str,
    correct: bool,
    almost_correct: bool,
    response_ms: int | None,
    completion_bonuses: dict[str, Any],
) -> dict[str, Any]:
    difficulty = quiz_difficulty_label(item)
    base_by_difficulty = {"easy": 5, "medium": 10, "hard": 15}
    correct_xp = base_by_difficulty[difficulty]
    answer_mode = str(item.get("answer_mode") or "")
    if correct and answer_mode in {"typing", "reorder"}:
        correct_xp += 5
    base_xp = correct_xp if correct else ((correct_xp + 1) // 2 if almost_correct else 0)
    first_try_bonus = 5 if correct else 0
    fast_bonus = 3 if correct and response_ms is not None and response_ms <= 6000 else 0
    completion_xp = int(completion_bonuses.get("complete_all_types_bonus") or 0)
    perfect_quiz_bonus = int(completion_bonuses.get("perfect_quiz_bonus") or 0)
    return {
        "difficulty": difficulty,
        "base_xp": base_xp,
        "first_try_bonus": first_try_bonus,
        "phrase_bonus": 0,
        "fast_bonus": fast_bonus,
        "complete_all_types_bonus": completion_xp,
        "perfect_quiz_bonus": perfect_quiz_bonus,
        "total_before_combo": base_xp + first_try_bonus + fast_bonus + completion_xp + perfect_quiz_bonus,
    }


def phrase_mastery_target_for_quiz(
    *,
    quiz_type: str,
    correct: bool,
    almost_correct: bool,
) -> float:
    if correct and quiz_type == "matching_pairs":
        return 0.75
    if correct and quiz_type in {"fill_blank", "sentence_reconstruction", "sentence_upgrade_battle", "fix_the_mistake", "phrase_duel"}:
        return 0.6
    if correct:
        return 0.35
    if almost_correct:
        return 0.25
    return 0.0


def serialize_phrase_mastery(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    return {
        "phrase": item["phrase"],
        "mastery": float(item.get("mastery") or 0.0),
        "mastery_percent": round(float(item.get("mastery") or 0.0) * 100),
        "state": item.get("mastery_state", "Seen"),
        "correct_count": int(item.get("correct_count") or 0),
    }


def _current_day_key(now) -> str:
    return now.date().isoformat()


def get_or_build_daily_challenge(
    db: Database,
    *,
    user: dict[str, Any],
    now,
) -> dict[str, Any] | None:
    challenge_date = _current_day_key(now)
    challenge = db.get_daily_challenge(user_id=user["id"], challenge_date=challenge_date)
    if challenge:
        return challenge

    now_iso = to_iso(now)
    candidate_items = mark_due_flags(
        db.list_candidate_quiz_items(user_id=user["id"], limit=100),
        now_iso=now_iso,
    )
    if not candidate_items:
        return None

    profile_snapshot = db.get_learning_profile_snapshot(user_id=user["id"], now_iso=now_iso)
    selected = choose_quiz_candidates(
        items=candidate_items,
        profile=QuizSelectionProfile(
            learner_level=user["difficulty_band"],
            recent_accuracy=float(profile_snapshot["recent_accuracy"]),
            fast_correct_ratio=float(profile_snapshot["fast_correct_ratio"]),
            weak_item_count=int(profile_snapshot["weak_item_count"]),
        ),
        limit=3,
        mode="daily_challenge",
    )
    if not selected:
        return None

    pool = [item["correct_answer"] for item in candidate_items]
    run_items = build_run_items(selected, pool=pool)
    challenge = db.create_daily_challenge(
        user_id=user["id"],
        challenge_date=challenge_date,
        items=run_items,
        summary={
            "mix": [item["quiz_type"] for item in selected],
            "due_count": sum(1 for item in selected if item.get("is_due")),
            "weak_focus": sum(
                1
                for item in selected
                if int(item.get("review_wrong_streak") or 0) >= 2 or int(item.get("wrong_count") or 0) >= 2
            ),
        },
        created_at=now_iso,
    )
    return challenge


def apply_progress_event(
    db: Database,
    *,
    user_id: int,
    now,
    xp_delta: int = 0,
    sessions_delta: int = 0,
    quizzes_delta: int = 0,
    activity_correct: bool | None = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    progress = db.ensure_user_progress(user_id=user_id, now_iso=to_iso(now))
    streak_days, last_active_on = update_streak(
        last_active_on=progress.get("last_active_on"),
        streak_days=int(progress.get("streak_days") or 0),
        today=now,
    )
    mastery_counts = db.get_mastery_counts(user_id=user_id)
    combo_streak = int(progress.get("combo_streak") or 0)
    best_combo = int(progress.get("best_combo") or 0)
    combo_bonus = 0

    if activity_correct is True:
        combo_streak += 1
        best_combo = max(best_combo, combo_streak)
        combo_bonus = combo_bonus_for_streak(combo_streak)
    elif activity_correct is False:
        combo_streak = 0

    xp_points = int(progress.get("xp_points") or 0) + max(0, int(xp_delta)) + combo_bonus
    learner_level_number = level_from_xp(xp_points)
    db.save_user_progress(
        user_id=user_id,
        xp_points=xp_points,
        streak_days=streak_days,
        learner_level=learner_level_number,
        sessions_completed=int(progress.get("sessions_completed") or 0) + sessions_delta,
        quizzes_completed=int(progress.get("quizzes_completed") or 0) + quizzes_delta,
        words_learned=mastery_counts["words_learned"],
        phrases_mastered=mastery_counts["phrases_mastered"],
        combo_streak=combo_streak,
        best_combo=best_combo,
        last_active_on=last_active_on,
        updated_at=to_iso(now),
    )
    return db.get_progress_dashboard(user_id=user_id, now_iso=to_iso(now)), {
        "xp_awarded": max(0, int(xp_delta)) + combo_bonus,
        "combo_bonus": combo_bonus,
        "combo_streak": combo_streak,
        "best_combo": best_combo,
    }


async def index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(request.app["config"].static_dir / "index.html")


async def healthz(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def bootstrap(request: web.Request) -> web.Response:
    user = request.get("user")
    stats = None
    progress = None
    quiz = None
    review = None
    challenge = None
    if user:
        now = utc_now()
        stats = request.app["db"].get_stats(user_id=user["id"], now_iso=to_iso(now))
        progress = request.app["db"].get_progress_dashboard(user_id=user["id"], now_iso=to_iso(now))
        quiz = build_quiz_dashboard(request.app["db"], request.app["config"], user=user, now=now)
        review = build_review_dashboard_payload(request.app["db"], user_id=user["id"], now_iso=to_iso(now))
        challenge = build_daily_challenge_summary(
            get_or_build_daily_challenge(request.app["db"], user=user, now=now)
        )

    return web.json_response(
        {
            "app_name": request.app["config"].app_name,
            "questions": ONBOARDING_QUESTIONS,
            "settings": {
                "review_prompt_interval_seconds": request.app[
                    "config"
                ].review_prompt_interval_seconds,
                "quiz_retake_minutes": request.app["config"].quiz_retake_minutes,
                "first_review_minutes": request.app["config"].first_review_minutes,
                "max_upload_bytes": request.app["config"].max_upload_bytes,
            },
            "user": public_user(user) if user else None,
            "stats": stats,
            "progress": progress,
            "quiz": quiz,
            "review": review,
            "challenge": challenge,
        }
    )


async def signup(request: web.Request) -> web.Response:
    payload = await request.json()
    full_name = str(payload.get("full_name") or "").strip()
    email = str(payload.get("email") or "").strip().lower()
    phone = normalize_phone(str(payload.get("phone") or ""))
    password = str(payload.get("password") or "")
    assessment_payload = payload.get("assessment") or {}

    if len(full_name) < 2:
        raise web.HTTPBadRequest(reason="Please enter your full name.")
    if "@" not in email:
        raise web.HTTPBadRequest(reason="Please provide a valid email address.")
    if phone and len(phone) < 8:
        raise web.HTTPBadRequest(reason="Please provide a valid phone number.")
    if len(password) < 8:
        raise web.HTTPBadRequest(reason="Passwords should be at least 8 characters.")

    db: Database = request.app["db"]
    if phone and db.get_user_by_phone(phone):
        raise web.HTTPConflict(reason="That phone number is already registered.")
    if db.get_user_by_email(email):
        raise web.HTTPConflict(reason="That email address is already registered.")

    assessment = evaluate_assessment(assessment_payload)
    now = utc_now()

    try:
        user = db.create_user(
            full_name=full_name,
            phone=phone or None,
            email=email,
            password_hash=hash_password(password),
            difficulty_band=assessment["difficulty_band"],
            fluency_score=assessment["score"],
            fluency_summary=assessment["fluency_summary"],
            assessment=assessment["responses"],
            created_at=to_iso(now),
        )
    except sqlite3.IntegrityError as exc:
        raise web.HTTPConflict(reason="That account already exists.") from exc

    otp = generate_otp()
    db.store_otp(
        user_id=user["id"],
        code_hash=hash_token(otp),
        purpose="signup",
        expires_at=to_iso(now + timedelta(minutes=request.app["config"].otp_ttl_minutes)),
        created_at=to_iso(now),
    )
    try:
        await asyncio.to_thread(
            request.app["mailer"].send_otp,
            email=user["email"],
            otp=otp,
            full_name=user["full_name"],
        )
    except Exception as exc:
        raise web.HTTPBadGateway(
            reason="The OTP email could not be sent. Check your SMTP settings."
        ) from exc

    return web.json_response(
        {
            "message": "Account created. Check your email for the verification code.",
            "email": user["email"],
            "difficulty_band": user["difficulty_band"],
            "difficulty_label": level_label(user["difficulty_band"]),
        },
        status=201,
    )


async def resend_otp(request: web.Request) -> web.Response:
    payload = await request.json()
    email = str(payload.get("email") or "").strip().lower()
    if "@" not in email:
        raise web.HTTPBadRequest(reason="Please provide the email used at signup.")

    db: Database = request.app["db"]
    user = db.get_user_by_email(email)
    if not user:
        raise web.HTTPNotFound(reason="No account matches that email.")
    if user["is_verified"]:
        raise web.HTTPBadRequest(reason="That account is already verified.")

    now = utc_now()
    otp = generate_otp()
    db.store_otp(
        user_id=user["id"],
        code_hash=hash_token(otp),
        purpose="signup",
        expires_at=to_iso(now + timedelta(minutes=request.app["config"].otp_ttl_minutes)),
        created_at=to_iso(now),
    )
    try:
        await asyncio.to_thread(
            request.app["mailer"].send_otp,
            email=user["email"],
            otp=otp,
            full_name=user["full_name"],
        )
    except Exception as exc:
        raise web.HTTPBadGateway(
            reason="The OTP email could not be sent. Check your SMTP settings."
        ) from exc
    return web.json_response({"message": "A fresh OTP has been sent."})


async def verify_otp(request: web.Request) -> web.Response:
    payload = await request.json()
    email = str(payload.get("email") or "").strip().lower()
    otp = str(payload.get("otp") or "").strip()

    if not otp:
        raise web.HTTPBadRequest(reason="Please enter the OTP code from your email.")

    db: Database = request.app["db"]
    user = db.get_user_by_email(email)
    if not user:
        raise web.HTTPNotFound(reason="We could not find that account.")

    now = utc_now()
    otp_record = db.get_active_otp(user_id=user["id"], purpose="signup", now_iso=to_iso(now))
    if not otp_record or otp_record["code_hash"] != hash_token(otp):
        raise web.HTTPBadRequest(reason="That OTP is invalid or has expired.")

    db.consume_otp(otp_record["id"], consumed_at=to_iso(now))
    db.set_user_verified(user["id"])
    session_token = make_token()
    db.create_auth_session(
        user_id=user["id"],
        session_token_hash=hash_token(session_token),
        expires_at=to_iso(now + timedelta(hours=request.app["config"].session_ttl_hours)),
        created_at=to_iso(now),
    )
    refreshed_user = db.get_user_by_id(user["id"])

    response = web.json_response(
        {
            "user": public_user(refreshed_user),
            "stats": db.get_stats(user_id=user["id"], now_iso=to_iso(now)),
            "progress": db.get_progress_dashboard(user_id=user["id"], now_iso=to_iso(now)),
        }
    )
    response.set_cookie(
        request.app["config"].session_cookie_name,
        session_token,
        httponly=True,
        samesite="Lax",
        secure=request.app["config"].cookie_secure,
        max_age=request.app["config"].session_ttl_hours * 3600,
    )
    return response


async def login(request: web.Request) -> web.Response:
    payload = await request.json()
    email = str(payload.get("email") or "").strip().lower()
    password = str(payload.get("password") or "")

    if not email or not password:
        raise web.HTTPBadRequest(reason="Please provide your email and password.")

    db: Database = request.app["db"]
    user = db.get_user_by_email(email)
    if not user or not verify_password(password, user["password_hash"]):
        raise web.HTTPUnauthorized(reason="Email or password is incorrect.")
    if not user["is_verified"]:
        raise web.HTTPUnauthorized(
            reason="Please verify your email OTP before logging in."
        )

    now = utc_now()
    session_token = make_token()
    db.create_auth_session(
        user_id=user["id"],
        session_token_hash=hash_token(session_token),
        expires_at=to_iso(now + timedelta(hours=request.app["config"].session_ttl_hours)),
        created_at=to_iso(now),
    )

    response = web.json_response(
        {
            "user": public_user(user),
            "stats": db.get_stats(user_id=user["id"], now_iso=to_iso(now)),
            "progress": db.get_progress_dashboard(user_id=user["id"], now_iso=to_iso(now)),
        }
    )
    response.set_cookie(
        request.app["config"].session_cookie_name,
        session_token,
        httponly=True,
        samesite="Lax",
        secure=request.app["config"].cookie_secure,
        max_age=request.app["config"].session_ttl_hours * 3600,
    )
    return response


async def logout(request: web.Request) -> web.Response:
    session_cookie_name = request.app["config"].session_cookie_name
    session_token = request.cookies.get(session_cookie_name)
    if session_token:
        request.app["db"].delete_auth_session(hash_token(session_token))

    response = web.json_response({"ok": True})
    response.del_cookie(session_cookie_name)
    return response


async def get_me(request: web.Request) -> web.Response:
    user = current_user(request)
    now = utc_now()
    return web.json_response(
        {
            "user": public_user(user),
            "stats": request.app["db"].get_stats(user_id=user["id"], now_iso=to_iso(now)),
            "progress": request.app["db"].get_progress_dashboard(
                user_id=user["id"], now_iso=to_iso(now)
            ),
        }
    )


async def analyze_image(request: web.Request) -> web.Response:
    user = current_user(request)
    config: AppConfig = request.app["config"]
    reader = await request.multipart()
    image_bytes = b""
    image_name = ""
    mime_type = ""
    notes = ""

    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "image":
            image_name = part.filename or "upload-image"
            mime_type = part.headers.get("Content-Type", "").lower()
            if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
                raise web.HTTPBadRequest(
                    reason="Please upload a JPG, PNG, WEBP, or GIF image."
                )

            chunks = []
            total_size = 0
            while True:
                chunk = await part.read_chunk()
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > config.max_upload_bytes:
                    raise web.HTTPRequestEntityTooLarge(
                        max_size=config.max_upload_bytes, actual_size=total_size
                    )
                chunks.append(chunk)
            image_bytes = b"".join(chunks)
        elif part.name == "notes":
            notes = (await part.text()).strip()

    if not image_bytes:
        raise web.HTTPBadRequest(reason="Please choose an image first.")

    safe_name = slugify_filename(image_name)
    file_dir = config.uploads_dir / str(user["id"])
    ensure_directory(file_dir)
    file_path = file_dir / f"{int(utc_now().timestamp())}-{safe_name}"
    file_path.write_bytes(image_bytes)

    try:
        analysis = await request.app["analyzer"].analyze_image(
            image_bytes=image_bytes,
            mime_type=mime_type,
            filename=image_name,
            image_path=file_path,
            difficulty_band=user["difficulty_band"],
            notes=notes,
        )
    except Exception as exc:
        print(f"[analyze-error] {type(exc).__name__}: {exc}")
        raise web.HTTPBadGateway(
            reason="The image lesson could not be generated. Check your AI configuration."
        ) from exc

    phrases_to_highlight = build_highlight_terms(
        phrases=analysis.get("phrases", []),
        vocabulary=analysis.get("vocabulary", []),
        reusable_language=analysis.get("reusable_language", []),
    )
    highlighted_html = highlight_phrases(
        analysis["scene_summary_natural"],
        phrases_to_highlight,
    )

    db: Database = request.app["db"]
    now = utc_now()
    created_at = to_iso(now)
    try:
        stored_image_path = str(file_path.relative_to(config.data_dir))
    except ValueError:
        stored_image_path = str(file_path.resolve())

    session_id = db.create_analysis_session(
        user_id=user["id"],
        image_name=image_name,
        image_path=stored_image_path,
        title=analysis["title"],
        difficulty_band=user["difficulty_band"],
        simple_explanation=analysis["scene_summary_simple"],
        natural_explanation=analysis["scene_summary_natural"],
        highlighted_html=highlighted_html,
        summary=analysis,
        raw_analysis=analysis.get("raw_analysis", analysis),
        source_mode=analysis.get("source_mode", "local"),
        created_at=created_at,
    )

    assets = build_session_assets(
        user_id=user["id"],
        session_id=session_id,
        analysis=analysis,
        learner_level=user["difficulty_band"],
        created_at=created_at,
        first_review_minutes=config.first_review_minutes,
    )
    db.bulk_create_session_vocabulary_items(assets["vocabulary"])
    db.bulk_create_session_phrase_items(assets["phrases"])
    db.bulk_create_study_cards(assets["review_items"])
    review_map = db.get_session_review_card_map(user_id=user["id"], session_id=session_id)
    for item in assets["quiz_items"]:
        source_text = str(item.get("metadata", {}).get("source_text") or item["correct_answer"])
        item["review_card_id"] = review_map.get(normalize_answer(source_text))
    db.bulk_create_quiz_items(assets["quiz_items"])
    db.sync_session_mastery(session_id=session_id)

    progress, _ = apply_progress_event(
        db,
        user_id=user["id"],
        now=now,
        xp_delta=xp_for_event("session_created"),
        sessions_delta=1,
    )
    session = db.get_session(user_id=user["id"], session_id=session_id)
    challenge = build_daily_challenge_summary(get_or_build_daily_challenge(db, user=user, now=now))
    return web.json_response(
        {
            "session": serialize_session_detail(db, session, user_id=user["id"]),
            "stats": db.get_stats(user_id=user["id"], now_iso=created_at),
            "progress": progress,
            "quiz": build_quiz_dashboard(db, config, user=user, now=now),
            "challenge": challenge,
        }
    )


async def list_sessions(request: web.Request) -> web.Response:
    user = current_user(request)
    sessions = request.app["db"].list_sessions(user["id"])
    return web.json_response({"sessions": [serialize_session_summary(item) for item in sessions]})


async def get_session(request: web.Request) -> web.Response:
    user = current_user(request)
    session_id = int(request.match_info["session_id"])
    session = request.app["db"].get_session(user_id=user["id"], session_id=session_id)
    if not session:
        raise web.HTTPNotFound(reason="That learning session was not found.")
    return web.json_response(
        {"session": serialize_session_detail(request.app["db"], session, user_id=user["id"])}
    )


async def session_feedback(request: web.Request) -> web.Response:
    user = current_user(request)
    session_id = int(request.match_info["session_id"])
    payload = await request.json()
    explanation = str(payload.get("explanation") or "").strip()
    rewrite = str(payload.get("rewrite") or "").strip()
    try:
        attempt_index = max(1, int(payload.get("attempt_index") or payload.get("attempt") or 1))
    except (TypeError, ValueError):
        attempt_index = 1

    if not explanation:
        raise web.HTTPBadRequest(reason="Write a short explanation before asking for feedback.")

    db: Database = request.app["db"]
    session = db.get_session(user_id=user["id"], session_id=session_id)
    if not session:
        raise web.HTTPNotFound(reason="That learning session was not found.")

    session_detail = serialize_session_detail(db, session, user_id=user["id"])
    feedback = await request.app["analyzer"].feedback_on_explanation(
        learner_text=rewrite or explanation,
        original_text=explanation,
        analysis=session_detail["analysis"],
        learner_level=user["difficulty_band"],
        attempt_index=attempt_index,
    )
    phrase_usage = feedback.get("phrase_usage") if isinstance(feedback, dict) else {}
    used_phrase_count = 0
    if isinstance(phrase_usage, dict):
        try:
            used_phrase_count = int(phrase_usage.get("rewardable_count", 0))
        except (TypeError, ValueError):
            used_phrase_count = 0
    reward_meta = {"xp_awarded": 0, "phrase_bonus": 0}
    progress = None
    stats = None
    if used_phrase_count:
        now = utc_now()
        phrase_bonus = (
            xp_for_event("multiple_phrases_used")
            if used_phrase_count >= 2
            else xp_for_event("phrase_used")
        )
        progress, reward_meta = apply_progress_event(
            db,
            user_id=user["id"],
            now=now,
            xp_delta=phrase_bonus,
        )
        reward_meta["phrase_bonus"] = phrase_bonus
        stats = db.get_stats(user_id=user["id"], now_iso=to_iso(now))

    return web.json_response(
        {
            "feedback": feedback,
            "progress": progress,
            "stats": stats,
            "reward": reward_meta,
        }
    )


async def session_post_improve_quiz(request: web.Request) -> web.Response:
    user = current_user(request)
    session_id = int(request.match_info["session_id"])
    payload = await request.json()
    learner_text = str(payload.get("learner_text") or payload.get("explanation") or "").strip()
    improved_text = str(payload.get("improved_text") or payload.get("rewrite") or "").strip()
    feedback = payload.get("feedback") if isinstance(payload.get("feedback"), dict) else {}
    score_improvement = payload.get("score_improvement")
    try:
        score_improvement = max(0, int(score_improvement or 0))
    except (TypeError, ValueError):
        score_improvement = 0

    if not learner_text and not improved_text:
        raise web.HTTPBadRequest(reason="Write and improve an answer before starting the quiz.")

    db: Database = request.app["db"]
    session = db.get_session(user_id=user["id"], session_id=session_id)
    if not session:
        raise web.HTTPNotFound(reason="That learning session was not found.")

    active_run = db.get_active_quiz_run(user_id=user["id"], run_mode="post_improve")
    if active_run and int(active_run.get("session_id") or 0) == session_id:
        run_payload = serialize_quiz_run(
            db, user_id=user["id"], run_id=int(active_run["id"]), include_question=True
        )
        return web.json_response({"run": run_payload, "message": "Your micro quiz is ready."})

    now = utc_now()
    now_iso = to_iso(now)
    session_detail = serialize_session_detail(db, session, user_id=user["id"])
    quiz_rows = build_post_improve_quiz_rows(
        user_id=user["id"],
        session_id=session_id,
        analysis=session_detail["analysis"],
        learner_level=user["difficulty_band"],
        learner_text=learner_text,
        improved_text=improved_text,
        feedback=feedback,
        created_at=now_iso,
    )
    if not quiz_rows:
        raise web.HTTPBadRequest(reason="There was not enough lesson feedback to build a quiz.")
    for row in quiz_rows:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        metadata["score_improvement"] = score_improvement
        row["metadata"] = metadata

    db.deactivate_post_improve_quiz_items(user_id=user["id"], session_id=session_id)
    db.bulk_create_quiz_items(quiz_rows)
    candidates = [
        item
        for item in db.list_candidate_quiz_items(user_id=user["id"], session_id=session_id, limit=80)
        if item.get("skill_tag") == "post-improve quiz"
    ]
    type_order = {
        "multiple_choice_comprehension": 0,
        "matching_pairs": 1,
        "fill_blank": 2,
        "sentence_reconstruction": 3,
    }
    candidates = sorted(
        candidates,
        key=lambda item: (
            type_order.get(str(item.get("quiz_type")), 99),
            float(item.get("difficulty") or 0.0),
            int(item.get("id") or 0),
        ),
    )[:8]
    pool = [item["correct_answer"] for item in candidates]
    run = db.create_quiz_run(
        user_id=user["id"],
        run_mode="post_improve",
        started_at=now_iso,
        items=build_run_items(candidates, pool=pool),
        session_id=session_id,
        source_label="Micro Quiz",
    )
    run_payload = serialize_quiz_run(db, user_id=user["id"], run_id=int(run["id"]), include_question=True)
    return web.json_response(
        {
            "run": run_payload,
            "dashboard": build_quiz_dashboard(db, request.app["config"], user=user, now=now),
            "message": "Quiz ready.",
        }
    )


async def session_image(request: web.Request) -> web.StreamResponse:
    user = current_user(request)
    session_id = int(request.match_info["session_id"])
    session = request.app["db"].get_session(user_id=user["id"], session_id=session_id)
    if not session:
        raise web.HTTPNotFound(reason="That image was not found.")

    stored_image_path = Path(session["image_path"])
    if stored_image_path.is_absolute():
        image_path = stored_image_path
    else:
        image_path = request.app["config"].data_dir / stored_image_path
    if not image_path.exists():
        raise web.HTTPNotFound(reason="The original image file is missing.")
    return web.FileResponse(path=image_path)


async def quiz_dashboard(request: web.Request) -> web.Response:
    user = current_user(request)
    now = utc_now()
    dashboard = build_quiz_dashboard(
        request.app["db"],
        request.app["config"],
        user=user,
        now=now,
    )
    challenge = build_daily_challenge_summary(
        get_or_build_daily_challenge(request.app["db"], user=user, now=now)
    )
    return web.json_response({"dashboard": dashboard, "challenge": challenge})


async def quiz_start(request: web.Request) -> web.Response:
    user = current_user(request)
    payload = await optional_json(request)
    mode = str(payload.get("mode") or "mixed").strip().lower()
    session_id = payload.get("session_id")
    session_id = int(session_id) if session_id not in (None, "") else None

    db: Database = request.app["db"]
    config: AppConfig = request.app["config"]
    now = utc_now()
    now_iso = to_iso(now)
    challenge = None

    active_run = db.get_active_quiz_run(user_id=user["id"])
    if active_run:
        run_payload = serialize_quiz_run(
            db, user_id=user["id"], run_id=int(active_run["id"]), include_question=True
        )
        return web.json_response(
            {
                "run": run_payload,
                "dashboard": build_quiz_dashboard(db, config, user=user, now=now),
                "message": "Your quiz is ready to continue.",
            }
        )

    if mode == "daily_challenge":
        challenge = get_or_build_daily_challenge(db, user=user, now=now)
        if not challenge:
            return web.json_response(
                {
                    "run": None,
                    "dashboard": build_quiz_dashboard(db, config, user=user, now=now),
                    "challenge": None,
                    "message": "Create a lesson first to unlock today's challenge.",
                }
            )
        if challenge["status"] == "completed":
            return web.json_response(
                {
                    "run": None,
                    "dashboard": build_quiz_dashboard(db, config, user=user, now=now),
                    "challenge": build_daily_challenge_summary(challenge),
                    "message": "Today's challenge is already complete.",
                }
            )

    dashboard = build_quiz_dashboard(db, config, user=user, now=now)
    if mode == "mixed" and not dashboard["can_start"]:
        return web.json_response(
            {
                "run": None,
                "dashboard": dashboard,
                "message": "Your next quiz is still cooling down.",
            }
        )

    candidate_items = mark_due_flags(
        db.list_candidate_quiz_items(
            user_id=user["id"],
            session_id=session_id if mode == "session" else None,
            limit=120,
        ),
        now_iso=now_iso,
    )
    if not candidate_items:
        return web.json_response(
            {
                "run": None,
                "dashboard": dashboard,
                "message": "Create a lesson first to unlock quiz questions.",
            }
        )

    profile_snapshot = db.get_learning_profile_snapshot(user_id=user["id"], now_iso=now_iso)
    selected_candidates = choose_quiz_candidates(
        items=candidate_items,
        profile=QuizSelectionProfile(
            learner_level=user["difficulty_band"],
            recent_accuracy=float(profile_snapshot["recent_accuracy"]),
            fast_correct_ratio=float(profile_snapshot["fast_correct_ratio"]),
            weak_item_count=int(profile_snapshot["weak_item_count"]),
        ),
        limit=3,
        mode=mode,
    )
    if mode == "session":
        selected_candidates = arrange_session_quick_challenge(items=selected_candidates, limit=3)

    quiz_items: list[dict[str, Any]]
    if mode == "daily_challenge":
        challenge = get_or_build_daily_challenge(db, user=user, now=now)
        challenge_items = db.list_daily_challenge_items(challenge_id=int(challenge["id"]))
        snapshots = [
            item["snapshot"]
            for item in challenge_items
            if isinstance(item.get("snapshot"), dict) and item.get("snapshot")
        ]
        if snapshots:
            quiz_items = snapshots
        else:
            pool = [item["correct_answer"] for item in candidate_items]
            quiz_items = build_run_items(selected_candidates, pool=pool)
    else:
        pool = [item["correct_answer"] for item in candidate_items]
        quiz_items = build_run_items(selected_candidates, pool=pool)

    run = db.create_quiz_run(
        user_id=user["id"],
        run_mode=mode,
        started_at=now_iso,
        items=quiz_items,
        challenge_id=int(challenge["id"]) if mode == "daily_challenge" and challenge else None,
        session_id=session_id,
        source_label=(
            "Today's challenge"
            if mode == "daily_challenge"
            else "Quick Challenge"
            if mode == "session"
            else "Mistake review"
            if mode == "mistakes"
            else "Mixed review"
        ),
    )
    run_payload = serialize_quiz_run(
        db, user_id=user["id"], run_id=int(run["id"]), include_question=True
    )
    return web.json_response(
        {
            "run": run_payload,
            "dashboard": build_quiz_dashboard(db, config, user=user, now=now),
            "challenge": build_daily_challenge_summary(
                get_or_build_daily_challenge(db, user=user, now=now)
            ),
            "message": "Quiz ready.",
        }
    )


async def quiz_answer(request: web.Request) -> web.Response:
    user = current_user(request)
    payload = await request.json()

    try:
        run_id = int(payload.get("run_id"))
        item_id = int(payload.get("item_id"))
    except (TypeError, ValueError) as exc:
        raise web.HTTPBadRequest(reason="A valid quiz run and question are required.") from exc

    selected_answer = str(payload.get("selected_answer") or "").strip()
    if not selected_answer:
        raise web.HTTPBadRequest(reason="Choose an answer before continuing.")

    response_ms = payload.get("response_ms")
    confidence = payload.get("confidence")
    try:
        response_ms = int(response_ms) if response_ms not in (None, "") else None
    except (TypeError, ValueError):
        response_ms = None
    try:
        confidence = int(confidence) if confidence not in (None, "") else 2
    except (TypeError, ValueError):
        confidence = 2

    db: Database = request.app["db"]
    run = db.get_quiz_run(user_id=user["id"], run_id=run_id)
    if not run:
        raise web.HTTPNotFound(reason="That quiz run could not be found.")
    if run["status"] == "completed":
        raise web.HTTPBadRequest(reason="That quiz is already finished.")

    item = db.get_quiz_run_item(user_id=user["id"], run_id=run_id, item_id=item_id)
    if not item:
        raise web.HTTPNotFound(reason="That quiz question no longer exists.")
    if item["was_correct"] is not None:
        raise web.HTTPBadRequest(reason="That quiz question has already been answered.")

    evaluation = evaluate_quiz_response(
        item=item,
        selected_answer=selected_answer,
        response_ms=response_ms,
        confidence=confidence,
    )
    correct = bool(evaluation["correct"])
    result_type = str(evaluation.get("result_type") or ("Correct" if correct else "Incorrect"))
    almost_correct = result_type == "Almost Correct"
    now = utc_now()
    now_iso = to_iso(now)
    next_schedule = None
    was_weak_item = False

    if item.get("card_id"):
        card = db.get_card(user_id=user["id"], card_id=int(item["card_id"]))
        if card:
            was_weak_item = int(card.get("wrong_streak") or 0) >= 2
            next_schedule = calculate_next_review(
                card=card,
                quality=int(evaluation["quality"]),
                now=now,
                first_review_minutes=request.app["config"].first_review_minutes,
                response_ms=response_ms,
                confidence=confidence,
            )
            db.update_study_card_schedule(card_id=int(card["id"]), **next_schedule)
            db.record_review_attempt(
                card_id=int(card["id"]),
                user_id=user["id"],
                answer_text=selected_answer,
                quality=int(evaluation["quality"]),
                was_correct=correct,
                created_at=now_iso,
                response_ms=response_ms,
                confidence=confidence,
                feedback=evaluation["feedback"],
            )
            db.sync_source_item_progress(
                session_id=int(card["session_id"]),
                source_kind=str(card.get("source_kind") or ""),
                source_text=str(card.get("source_text") or card.get("answer") or ""),
                mastery=float(next_schedule["mastery"]),
                was_correct=correct,
            )

    if item.get("quiz_item_id"):
        db.update_quiz_item_stats(
            quiz_item_id=int(item["quiz_item_id"]),
            was_correct=correct,
            response_ms=response_ms,
            seen_at=now_iso,
        )

    phrase_mastery = None
    related_phrase = str((item.get("metadata") or {}).get("related_reusable_phrase") or "").strip()
    phrase_mastery_target = phrase_mastery_target_for_quiz(
        quiz_type=str(item.get("quiz_type") or ""),
        correct=correct,
        almost_correct=almost_correct,
    )
    if related_phrase and item.get("session_id") and phrase_mastery_target > 0:
        phrase_mastery = serialize_phrase_mastery(
            db.update_phrase_mastery(
                user_id=user["id"],
                session_id=int(item["session_id"]),
                phrase=related_phrase,
                mastery=phrase_mastery_target,
                was_correct=correct,
            )
        )

    db.record_quiz_attempt(
        quiz_item_id=int(item["quiz_item_id"]) if item.get("quiz_item_id") else None,
        card_id=int(item["card_id"]) if item.get("card_id") else None,
        run_id=run_id,
        challenge_id=int(run["challenge_id"]) if run.get("challenge_id") else None,
        user_id=user["id"],
        session_id=int(item["session_id"]) if item.get("session_id") else None,
        quiz_type=str(item.get("quiz_type") or "recognition"),
        answer_mode=str(item.get("answer_mode") or "multiple_choice"),
        selected_answer=selected_answer,
        was_correct=correct,
        score=float(evaluation["score"]),
        response_ms=response_ms,
        confidence=confidence,
        feedback=evaluation["feedback"],
        created_at=now_iso,
    )
    db.record_quiz_item_answer(
        item_id=item_id,
        selected_answer=selected_answer,
        was_correct=correct,
        score=float(evaluation["score"]),
        feedback=evaluation["feedback"],
        response_ms=response_ms,
        confidence=confidence,
        answered_at=now_iso,
    )
    updated_run = db.sync_quiz_run(user_id=user["id"], run_id=run_id, completed_at=now_iso)

    completion_bonuses = quiz_run_completion_bonuses(
        db=db,
        run_id=run_id,
        completed=bool(updated_run and updated_run["status"] == "completed"),
    )
    xp_breakdown = build_quiz_xp_breakdown(
        item=item,
        selected_answer=selected_answer,
        correct=correct,
        almost_correct=almost_correct,
        response_ms=response_ms,
        completion_bonuses=completion_bonuses,
    )
    xp_delta = int(xp_breakdown["total_before_combo"])
    daily_bonus = 0
    quizzes_delta = 1 if updated_run and updated_run["status"] == "completed" else 0
    if updated_run and updated_run["status"] == "completed" and run.get("run_mode") == "daily_challenge":
        if run.get("challenge_id"):
            db.update_daily_challenge(
                challenge_id=int(run["challenge_id"]),
                status="completed",
                completed_questions=int(updated_run["total_questions"]),
                correct_count=int(updated_run["correct_count"]),
                xp_awarded=0,
                completed_at=now_iso,
            )

    progress, reward_meta = apply_progress_event(
        db,
        user_id=user["id"],
        now=now,
        xp_delta=xp_delta,
        quizzes_delta=quizzes_delta,
        activity_correct=True if correct else False if not almost_correct else None,
    )
    xp_breakdown["combo_bonus"] = int(reward_meta["combo_bonus"])
    xp_breakdown["weak_item_bonus"] = 0
    xp_breakdown["daily_bonus"] = daily_bonus
    xp_breakdown["total"] = int(reward_meta["xp_awarded"])
    result_feedback = {
        **(evaluation["feedback"] or {}),
        "xp_awarded": int(reward_meta["xp_awarded"]),
        "combo_bonus": int(reward_meta["combo_bonus"]),
        "combo_streak": int(reward_meta["combo_streak"]),
        "perfect_quiz_bonus": int(xp_breakdown.get("perfect_quiz_bonus") or 0),
        "fast_bonus": int(xp_breakdown.get("fast_bonus") or 0),
        "first_try_bonus": int(xp_breakdown.get("first_try_bonus") or 0),
    }
    db.record_quiz_item_answer(
        item_id=item_id,
        selected_answer=selected_answer,
        was_correct=correct,
        score=float(evaluation["score"]),
        feedback=result_feedback,
        response_ms=response_ms,
        confidence=confidence,
        answered_at=now_iso,
    )
    run_payload = serialize_quiz_run(db, user_id=user["id"], run_id=run_id, include_question=True)
    dashboard = build_quiz_dashboard(
        db,
        request.app["config"],
        user=user,
        now=now,
    )
    return web.json_response(
        {
            "result": {
                "correct": correct,
                "result_type": result_type,
                "almost_correct": almost_correct,
                "quiz_type": str(item.get("quiz_type") or ""),
                "selected_answer": selected_answer,
                "metadata": item.get("metadata") or {},
                "correct_answer": item["correct_answer"],
                "context_note": item.get("context_note", ""),
                "feedback": result_feedback,
                "score": float(evaluation["score"]),
                "next_due_at": next_schedule["due_at"] if next_schedule else None,
                "question_index": int(item["question_index"]) + 1,
                "xp_awarded": int(reward_meta["xp_awarded"]),
                "xp_breakdown": xp_breakdown,
                "phrase_mastery": phrase_mastery,
                "combo_bonus": int(reward_meta["combo_bonus"]),
                "combo_streak": int(reward_meta["combo_streak"]),
                "best_combo": int(reward_meta["best_combo"]),
                "daily_bonus": daily_bonus,
                "was_weak_item": was_weak_item,
            },
            "run": run_payload,
            "dashboard": dashboard,
            "stats": db.get_stats(user_id=user["id"], now_iso=now_iso),
            "progress": progress,
            "challenge": build_daily_challenge_summary(get_or_build_daily_challenge(db, user=user, now=now)),
        }
    )


async def review_dashboard(request: web.Request) -> web.Response:
    user = current_user(request)
    now = utc_now()
    return web.json_response(
        {
            "review": build_review_dashboard_payload(
                request.app["db"], user_id=user["id"], now_iso=to_iso(now)
            ),
            "progress": request.app["db"].get_progress_dashboard(
                user_id=user["id"], now_iso=to_iso(now)
            ),
        }
    )


async def review_queue(request: web.Request) -> web.Response:
    user = current_user(request)
    mode = request.query.get("mode", "auto").strip().lower()
    try:
        limit = max(1, min(int(request.query.get("limit", "5")), 10))
    except ValueError as exc:
        raise web.HTTPBadRequest(reason="The review limit must be a number.") from exc
    manual_mode = mode == "manual"
    now = utc_now()

    db: Database = request.app["db"]
    cards = db.list_review_cards(
        user_id=user["id"],
        now_iso=to_iso(now),
        limit=limit,
        manual_mode=manual_mode,
    )

    serialized_cards = []
    for card in cards:
        distractors = db.get_distractor_answers(user_id=user["id"], card_id=card["id"], limit=8)
        serialized_cards.append(
            {
                "id": card["id"],
                "session_id": card["session_id"],
                "session_title": card["session_title"],
                "card_kind": card["card_kind"],
                "prompt": card["prompt"],
                "context_note": card["context_note"],
                "options": build_review_options(card, distractors),
                "mastery": float(card.get("mastery") or 0.0),
                "mastery_percent": round(float(card.get("mastery") or 0.0) * 100),
                "wrong_streak": int(card.get("wrong_streak") or 0),
                "is_weak": int(card.get("wrong_streak") or 0) >= 2,
            }
        )

    return web.json_response(
        {
            "cards": serialized_cards,
            "stats": db.get_stats(user_id=user["id"], now_iso=to_iso(now)),
            "review": build_review_dashboard_payload(db, user_id=user["id"], now_iso=to_iso(now)),
        }
    )


async def review_answer(request: web.Request) -> web.Response:
    user = current_user(request)
    payload = await request.json()
    try:
        card_id = int(payload.get("card_id"))
    except (TypeError, ValueError) as exc:
        raise web.HTTPBadRequest(reason="A valid card id is required.") from exc

    selected_answer = str(payload.get("selected_answer") or "").strip()
    if not selected_answer:
        raise web.HTTPBadRequest(reason="Please choose an answer first.")

    try:
        response_ms = int(payload.get("response_ms")) if payload.get("response_ms") else None
    except (TypeError, ValueError):
        response_ms = None
    try:
        confidence = int(payload.get("confidence")) if payload.get("confidence") else 2
    except (TypeError, ValueError):
        confidence = 2

    db: Database = request.app["db"]
    card = db.get_card(user_id=user["id"], card_id=card_id)
    if not card:
        raise web.HTTPNotFound(reason="That review card no longer exists.")

    acceptable_answers = card.get("acceptable_answers") or [card["answer"]]
    correct = any(
        normalize_answer(selected_answer) == normalize_answer(answer)
        for answer in acceptable_answers
    )
    quality = 4 if correct else 2
    now = utc_now()
    next_schedule = calculate_next_review(
        card=card,
        quality=quality,
        now=now,
        first_review_minutes=request.app["config"].first_review_minutes,
        response_ms=response_ms,
        confidence=confidence,
    )
    db.update_study_card_schedule(card_id=card_id, **next_schedule)
    feedback = {
        "good": "Nice recall." if correct else "",
        "improve": "" if correct else "Try again with the key word or phrase from the lesson.",
        "corrected_example": card["answer"],
    }
    db.record_review_attempt(
        card_id=card_id,
        user_id=user["id"],
        answer_text=selected_answer,
        quality=quality,
        was_correct=correct,
        created_at=to_iso(now),
        response_ms=response_ms,
        confidence=confidence,
        feedback=feedback,
    )
    db.sync_source_item_progress(
        session_id=int(card["session_id"]),
        source_kind=str(card.get("source_kind") or ""),
        source_text=str(card.get("source_text") or card.get("answer") or ""),
        mastery=float(next_schedule["mastery"]),
        was_correct=correct,
    )
    was_weak_item = int(card.get("wrong_streak") or 0) >= 2
    xp_delta = (
        xp_for_event("weak_item_correct")
        if correct and was_weak_item
        else xp_for_event("review_correct" if correct else "review_incorrect")
    )
    progress, reward_meta = apply_progress_event(
        db,
        user_id=user["id"],
        now=now,
        xp_delta=xp_delta,
        activity_correct=correct,
    )

    return web.json_response(
        {
            "result": {
                "correct": correct,
                "correct_answer": card["answer"],
                "context_note": card["context_note"],
                "next_due_at": next_schedule["due_at"],
                "session_title": card["session_title"],
                "feedback": feedback,
                "xp_awarded": int(reward_meta["xp_awarded"]),
                "combo_bonus": int(reward_meta["combo_bonus"]),
                "combo_streak": int(reward_meta["combo_streak"]),
                "was_weak_item": was_weak_item,
            },
            "stats": db.get_stats(user_id=user["id"], now_iso=to_iso(now)),
            "review": build_review_dashboard_payload(db, user_id=user["id"], now_iso=to_iso(now)),
            "progress": progress,
        }
    )


async def challenge_today(request: web.Request) -> web.Response:
    user = current_user(request)
    now = utc_now()
    challenge = build_daily_challenge_summary(
        get_or_build_daily_challenge(request.app["db"], user=user, now=now)
    )
    return web.json_response(
        {
            "challenge": challenge,
            "progress": request.app["db"].get_progress_dashboard(
                user_id=user["id"], now_iso=to_iso(now)
            ),
        }
    )


async def progress_dashboard(request: web.Request) -> web.Response:
    user = current_user(request)
    now = utc_now()
    return web.json_response(
        {
            "progress": request.app["db"].get_progress_dashboard(
                user_id=user["id"], now_iso=to_iso(now)
            ),
            "stats": request.app["db"].get_stats(user_id=user["id"], now_iso=to_iso(now)),
        }
    )


def main() -> None:
    app = build_app()
    config: AppConfig = app["config"]
    web.run_app(app, host=config.host, port=config.port)
