from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

from aiohttp import web

from .ai_service import AIAnalyzer
from .assessment import ONBOARDING_PROMPTS, evaluate_assessment
from .config import AppConfig
from .database import Database
from .learning import canonical_level, level_label
from .mailer import Mailer
from .progress import level_from_xp, update_streak, xp_for_event
from .security import generate_otp, hash_password, hash_token, make_token, verify_password
from .utils import (
    ALLOWED_IMAGE_MIME_TYPES,
    ensure_directory,
    from_iso,
    normalize_answer,
    normalize_phone,
    should_surface_term,
    slugify_filename,
    to_iso,
    utc_now,
)

LEARNING_STAGES = {
    "upload_image",
    "initial_attempt",
    "first_feedback",
    "reusable_language",
    "missing_visual_areas",
    "coverage_layers",
    "layer_success",
    "coverage_complete",
    "polish_stage",
    "final_reveal",
}


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
    app.router.add_get(r"/sessions/{session_id:\d+}", index)
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
    app.router.add_get(r"/api/sessions/{session_id:\d+}/image", session_image)
    app.router.add_get("/api/sessions", list_sessions)
    app.router.add_get(r"/api/sessions/{session_id:\d+}", get_session)
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


def serialize_session_detail(row: dict[str, Any]) -> dict[str, Any]:
    summary = _session_summary_json(row)
    starter_hints = summary.get("starterHints") or summary.get("starter_hints") or []
    sentence_starters = summary.get("sentenceStarters") or summary.get("sentence_starters") or []
    coverage_focuses = summary.get("coverageFocuses") or summary.get("coverage_focuses") or []

    return {
        "id": row["id"],
        "title": row["title"],
        "image_name": row["image_name"],
        "difficulty_band": canonical_level(row["difficulty_band"]),
        "difficulty_label": level_label(row["difficulty_band"]),
        "source_mode": row["source_mode"],
        "created_at": row["created_at"],
        "learning_stage": "initial_attempt",
        "mastery_percent": float(row.get("mastery_percent") or 0.0),
        "image_url": f"/api/sessions/{row['id']}/image",
        "analysis": {
            "starterHints": starter_hints,
            "sentenceStarters": sentence_starters,
            "coverageFocuses": coverage_focuses,
        },
    }


def learning_stage_from_feedback(feedback: dict[str, Any], *, attempt_index: int) -> str:
    if attempt_index <= 1:
        return "first_feedback"
    coverage = feedback.get("coverage") if isinstance(feedback.get("coverage"), dict) else {}
    readiness = feedback.get("readiness") if isinstance(feedback.get("readiness"), dict) else {}
    coverage_percent = _safe_int(
        coverage.get("coveragePercent")
        or coverage.get("coverageScore")
        or feedback.get("coverage_score")
    )
    required_parts = [
        part
        for part in coverage.get("imageParts", [])
        if isinstance(part, dict) and part.get("required", True)
    ]
    covered_parts = [
        part
        for part in required_parts
        if _coverage_part_is_covered(part)
    ]
    missing_parts = [
        part
        for part in required_parts
        if not _coverage_part_is_covered(part)
    ]
    ready = bool(readiness.get("ready"))
    criteria = readiness.get("criteria") if isinstance(readiness.get("criteria"), dict) else {}
    action_required = any(_part_matches(part, ("main_action", "main action")) for part in required_parts)
    category_state = _coverage_category_state(required_parts)
    high_priority_ratio = _high_priority_coverage_ratio(category_state)
    supporting_count = _covered_supporting_category_count(category_state)
    supporting_needed = min(3 if len(_supporting_category_keys(category_state)) >= 4 else 2, len(_supporting_category_keys(category_state)))
    has_main_focus = bool(criteria.get("mainSubject", coverage.get("mainSubjectMentioned") is not False)) and category_state["main_subject"] != "missing"
    has_action = (not action_required) or (
        bool(criteria.get("mainAction", coverage.get("mainActionMentioned") is not False))
        and category_state["people_action"] != "missing"
    )
    has_setting = (bool(criteria.get("settingBackground")) or _covered_part_matches(
        covered_parts, ("setting", "background", "environment", "context")
    )) and (
        category_state["setting_environment"] != "missing"
        or category_state["background"] != "missing"
    )
    detail_count = sum(
        1
        for part in covered_parts
        if _part_matches(
            part,
            (
                "important",
                "object",
                "foreground",
                "detail",
                "setting",
                "background",
                "environment",
                "vehicle",
                "building",
                "tree",
                "lighting",
                "shadow",
                "condition",
                "atmosphere",
                "composition",
                "position",
            ),
        )
    )
    detail_count = max(detail_count, supporting_count)
    natural_english = bool(criteria.get("naturalEnglish", coverage_percent >= 70))
    not_word_list = bool(criteria.get("notAWordList", True))
    critical_missing = _critical_missing_categories(category_state, action_required=action_required)
    enough_coverage = (
        has_main_focus
        and has_action
        and has_setting
        and detail_count >= supporting_needed
        and (ready or natural_english)
        and not_word_list
        and coverage_percent >= 70
        and high_priority_ratio >= 0.7
        and not critical_missing
        and not _high_priority_missing_parts(missing_parts, allow_supporting_misses=True)
    )
    return "coverage_complete" if enough_coverage else "coverage_layers"


def build_learning_engines_payload(
    feedback: dict[str, Any],
    *,
    learning_stage: str,
) -> dict[str, Any]:
    coverage = feedback.get("coverage") if isinstance(feedback.get("coverage"), dict) else {}
    language_quality = (
        feedback.get("language_quality")
        if isinstance(feedback.get("language_quality"), dict)
        else {}
    )
    readiness = feedback.get("readiness") if isinstance(feedback.get("readiness"), dict) else {}
    coverage_percent = _safe_int(
        coverage.get("coveragePercent")
        or coverage.get("coverageScore")
        or feedback.get("coverage_score")
    )
    covered_areas = _coverage_area_labels(feedback, covered=True)
    missing_areas = _coverage_area_labels(feedback, covered=False)
    coverage_complete = learning_stage == "coverage_complete"
    return {
        "coverage_engine": {
            "purpose": "Checks whether the learner described the important visual parts of the image.",
            "status": "complete" if coverage_complete else "in_progress",
            "score": coverage_percent,
            "level": coverage.get("level", ""),
            "covered_visual_areas": covered_areas,
            "missing_visual_areas": missing_areas,
            "image_parts": coverage.get("imageParts", []),
            "ready_for_articulation": coverage_complete,
            "reason": coverage.get("reason") or readiness.get("reason") or "",
        },
        "articulation_engine": {
            "purpose": "Improves how naturally and expressively the learner says the covered idea.",
            "locked": not coverage_complete,
            "unlock_reason": (
                "Coverage is reasonably complete, so expressive polish is available."
                if coverage_complete
                else "Full polish stays locked until the important visual areas are covered."
            ),
            "language_quality": language_quality,
            "reusable_language": feedback.get("phrase_usage") or feedback.get("reusableLanguage") or {},
            "word_phrase_upgrades": feedback.get("word_phrase_upgrades", []),
        },
    }


def build_highlight_terms(
    *,
    phrases: list[dict[str, Any]],
    vocabulary: list[dict[str, Any]],
    reusable_language: list[dict[str, Any]],
) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    def add(value: Any, *, kind: str = "") -> None:
        text = str(value or "").strip()
        key = normalize_answer(text)
        if not key or key in seen or not should_surface_term(text, kind=kind):
            return
        seen.add(key)
        terms.append(text)

    for item in reusable_language or []:
        add(item.get("text") if isinstance(item, dict) else item, kind="phrase")
    for item in phrases or []:
        add(item.get("phrase") if isinstance(item, dict) else item, kind="phrase")
    for item in vocabulary or []:
        add(item.get("word") if isinstance(item, dict) else item, kind="word")
    return terms[:12]


def _coverage_part_is_covered(part: dict[str, Any]) -> bool:
    status = str(part.get("coverageStatus") or "").casefold()
    return bool(part.get("covered")) or status in {"covered", "partially_covered"}


def _coverage_part_credit(part: dict[str, Any]) -> float:
    status = str(part.get("coverageStatus") or "").casefold()
    if bool(part.get("covered")) or status == "covered":
        return 1.0
    if status == "partially_covered":
        return 0.5
    return 0.0


def _coverage_category_for_part(part: dict[str, Any]) -> str:
    text = " ".join(
        str(part.get(key) or "")
        for key in ("type", "name", "description")
    ).casefold()
    if "main_subject" in text or "main subject" in text or "primary subject" in text:
        return "main_subject"
    if "main_action" in text or "main action" in text or "action" in text or "movement" in text or "interaction" in text:
        return "people_action"
    if any(term in text for term in ("setting", "environment", "context", "place")):
        return "setting_environment"
    if any(term in text for term in ("background", "sky", "behind")):
        return "background"
    if any(term in text for term in ("foreground", "front", "nearest", "nearby", "ground", "entrance", "bottom")):
        return "foreground"
    if any(term in text for term in ("mood", "atmosphere", "lighting", "light", "bright", "shadow", "weather", "condition", "feeling")):
        return "atmosphere_lighting"
    if any(term in text for term in ("important", "object", "detail", "tree", "bush", "shrub", "greenery", "column", "roof", "architecture", "vehicle", "building")):
        return "important_objects"
    return "notable_visual_details"


def _coverage_category_state(parts: list[dict[str, Any]]) -> dict[str, str]:
    state = {
        "main_subject": "missing",
        "people_action": "not_applicable",
        "setting_environment": "missing",
        "background": "not_applicable",
        "foreground": "not_applicable",
        "important_objects": "not_applicable",
        "atmosphere_lighting": "not_applicable",
        "notable_visual_details": "not_applicable",
    }
    rank = {"not_applicable": -1, "missing": 0, "partially_covered": 1, "covered": 2}
    seen_categories: set[str] = set()
    for part in parts:
        category = _coverage_category_for_part(part)
        seen_categories.add(category)
        credit = _coverage_part_credit(part)
        status = "covered" if credit >= 1 else "partially_covered" if credit > 0 else "missing"
        if rank[status] > rank[state.get(category, "missing")]:
            state[category] = status
    for category in seen_categories:
        state.setdefault(category, "missing")
        if state[category] == "not_applicable":
            state[category] = "missing"
    if state["setting_environment"] == "missing" and state["background"] != "not_applicable":
        state["setting_environment"] = state["background"]
        state["background"] = "not_applicable"
    if "important_objects" not in seen_categories and "notable_visual_details" in seen_categories:
        state["important_objects"] = state["notable_visual_details"]
    return state


def _supporting_category_keys(category_state: dict[str, str]) -> list[str]:
    return [
        key
        for key in (
            "people_action",
            "setting_environment",
            "background",
            "foreground",
            "important_objects",
            "atmosphere_lighting",
            "notable_visual_details",
        )
        if category_state.get(key) != "not_applicable"
    ]


def _covered_supporting_category_count(category_state: dict[str, str]) -> int:
    return sum(
        1
        for key in _supporting_category_keys(category_state)
        if category_state.get(key) in {"covered", "partially_covered"}
    )


def _high_priority_coverage_ratio(category_state: dict[str, str]) -> float:
    categories = [
        key
        for key in (
            "main_subject",
            "people_action",
            "setting_environment",
            "background",
            "foreground",
            "important_objects",
            "atmosphere_lighting",
            "notable_visual_details",
        )
        if category_state.get(key) != "not_applicable"
    ]
    if not categories:
        return 0.0
    credit = sum(
        1.0 if category_state.get(key) == "covered" else 0.5 if category_state.get(key) == "partially_covered" else 0.0
        for key in categories
    )
    return credit / len(categories)


def _critical_missing_categories(category_state: dict[str, str], *, action_required: bool) -> list[str]:
    critical = ["main_subject"]
    if category_state.get("setting_environment") == "missing" and category_state.get("background") == "missing":
        critical.append("setting_environment")
    if action_required:
        critical.append("people_action")
    return [key for key in critical if category_state.get(key) == "missing"]


def _part_matches(part: dict[str, Any], terms: tuple[str, ...]) -> bool:
    text = " ".join(
        str(part.get(key) or "")
        for key in ("type", "name", "description")
    ).casefold()
    return any(term in text for term in terms)


def _covered_part_matches(parts: list[dict[str, Any]], terms: tuple[str, ...]) -> bool:
    return any(_part_matches(part, terms) for part in parts)


def _high_priority_missing_parts(parts: list[dict[str, Any]], *, allow_supporting_misses: bool = False) -> list[dict[str, Any]]:
    terms = (
        (
            "main_subject",
            "main subject",
            "main_action",
            "main action",
            "setting",
            "background",
            "environment",
        )
        if allow_supporting_misses
        else (
            "main_subject",
            "main subject",
            "main_action",
            "main action",
            "setting",
            "background",
            "environment",
            "important",
            "object",
            "foreground",
            "detail",
        )
    )
    return [
        part
        for part in parts
        if _part_matches(part, terms)
    ]


def _safe_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _coverage_area_labels(feedback: dict[str, Any], *, covered: bool) -> list[str]:
    coverage = feedback.get("coverage") if isinstance(feedback.get("coverage"), dict) else {}
    labels: list[str] = []
    for part in coverage.get("imageParts", []):
        if not isinstance(part, dict) or _coverage_part_is_covered(part) is not covered:
            continue
        label = str(part.get("name") or part.get("type") or part.get("description") or "").strip()
        if label:
            labels.append(label.replace("_", " "))
    if not covered:
        for item in coverage.get("missingMajorParts", []) or feedback.get("missing_details", []):
            label = str(item or "").strip()
            if label:
                labels.append(label)
    deduped: list[str] = []
    seen: set[str] = set()
    for label in labels:
        key = normalize_answer(label)
        if key and key not in seen:
            seen.add(key)
            deduped.append(label)
    return deduped[:6]


def apply_progress_event(
    db: Database,
    *,
    user_id: int,
    now,
    xp_delta: int = 0,
    sessions_delta: int = 0,
) -> tuple[dict[str, Any], dict[str, int]]:
    progress = db.ensure_user_progress(user_id=user_id, now_iso=to_iso(now))
    streak_days, last_active_on = update_streak(
        last_active_on=progress.get("last_active_on"),
        streak_days=int(progress.get("streak_days") or 0),
        today=now,
    )
    mastery_counts = db.get_mastery_counts(user_id=user_id)

    xp_points = int(progress.get("xp_points") or 0) + max(0, int(xp_delta))
    learner_level_number = level_from_xp(xp_points)
    db.save_user_progress(
        user_id=user_id,
        xp_points=xp_points,
        streak_days=streak_days,
        learner_level=learner_level_number,
        sessions_completed=int(progress.get("sessions_completed") or 0) + sessions_delta,
        words_learned=mastery_counts["words_learned"],
        phrases_mastered=mastery_counts["phrases_mastered"],
        last_active_on=last_active_on,
        updated_at=to_iso(now),
    )
    return db.get_progress_dashboard(user_id=user_id, now_iso=to_iso(now)), {
        "xp_awarded": max(0, int(xp_delta)),
    }


async def index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(request.app["config"].static_dir / "index.html")


async def healthz(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def bootstrap(request: web.Request) -> web.Response:
    user = request.get("user")
    stats = None
    progress = None
    if user:
        now = utc_now()
        stats = request.app["db"].get_stats(user_id=user["id"], now_iso=to_iso(now))
        progress = request.app["db"].get_progress_dashboard(user_id=user["id"], now_iso=to_iso(now))

    return web.json_response(
        {
            "app_name": request.app["config"].app_name,
            "settings": {
                "max_upload_bytes": request.app["config"].max_upload_bytes,
            },
            "user": public_user(user) if user else None,
            "stats": stats,
            "progress": progress,
        }
    )


async def signup(request: web.Request) -> web.Response:
    payload = await request.json()
    full_name = str(payload.get("full_name") or "").strip()
    email = str(payload.get("email") or "").strip().lower()
    phone = normalize_phone(str(payload.get("phone") or ""))
    password = str(payload.get("password") or "")
    raw_assessment = payload.get("assessment")
    assessment_payload = raw_assessment if isinstance(raw_assessment, dict) else {}
    assessment_payload = {
        prompt["id"]: assessment_payload.get(prompt["id"]) or 3
        for prompt in ONBOARDING_PROMPTS
    }

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
        print(user["difficulty_band"])
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
            reason="The image guidance could not be generated. Check your AI configuration."
        ) from exc

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
        title="Image articulation",
        difficulty_band=user["difficulty_band"],
        simple_explanation="",
        natural_explanation="",
        highlighted_html="",
        summary=analysis,
        raw_analysis=analysis.get("raw_analysis", analysis),
        source_mode=analysis.get("source_mode", "local"),
        created_at=created_at,
    )

    progress, _ = apply_progress_event(
        db,
        user_id=user["id"],
        now=now,
        xp_delta=xp_for_event("session_created"),
        sessions_delta=1,
    )
    session = db.get_session(user_id=user["id"], session_id=session_id)
    return web.json_response(
        {
            "session": serialize_session_detail(session),
            "stats": db.get_stats(user_id=user["id"], now_iso=created_at),
            "progress": progress,
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
        {"session": serialize_session_detail(session)}
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

    session_detail = serialize_session_detail(session)
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

    learning_stage = learning_stage_from_feedback(feedback, attempt_index=attempt_index)
    feedback["learning_stage"] = learning_stage
    engines = build_learning_engines_payload(feedback, learning_stage=learning_stage)
    coverage_engine = engines["coverage_engine"]
    articulation_engine = engines["articulation_engine"]
    feedback["coverage_engine"] = coverage_engine
    feedback["articulation_engine"] = articulation_engine
    feedback["learning_flow"] = {
        "stage": learning_stage,
        "coverage_complete": learning_stage == "coverage_complete",
        "coverage_before_articulation": True,
        "coverage_focus": "visual_parts",
        "articulation_focus": "natural_polish",
        "covered_visual_areas": coverage_engine["covered_visual_areas"],
        "missing_visual_areas": coverage_engine["missing_visual_areas"],
        "reusable_language": articulation_engine["reusable_language"],
        "articulation_locked": articulation_engine["locked"],
        "coverage_engine": coverage_engine,
        "articulation_engine": articulation_engine,
    }

    return web.json_response(
        {
            "feedback": feedback,
            "learning_stage": learning_stage,
            "progress": progress,
            "stats": stats,
            "reward": reward_meta,
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
