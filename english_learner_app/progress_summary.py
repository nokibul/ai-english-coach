from __future__ import annotations

from typing import Any

from .database import Database
from .progress import level_from_xp
from .utils import to_iso, utc_now


def getUserProgressSummary(db: Database, userId: int) -> dict[str, Any]:
    now_iso = to_iso(utc_now())
    progress = db.ensure_user_progress(user_id=userId, now_iso=now_iso)
    counts = _progress_counts(db, userId)
    total_xp = int(progress.get("xp_points") or 0)
    current_level = int(progress.get("learner_level") or level_from_xp(total_xp) or 1)
    streak = int(progress.get("streak_days") or 0)
    phrases_learned = int(counts.get("phrases_learned") or 0)
    images_completed = max(int(progress.get("sessions_completed") or 0), int(counts.get("images_completed") or 0))
    roadmap_checkpoints_completed = int(counts.get("roadmap_checkpoints_completed") or 0)
    achievements = _achievements(
        streak=streak,
        images_completed=images_completed,
        phrases_learned=phrases_learned,
        completed_roadmap_missions=int(counts.get("completed_roadmap_missions") or 0),
        roadmap_checkpoints_completed=roadmap_checkpoints_completed,
    )
    return {
        "totalXp": total_xp,
        "currentLevel": current_level,
        "levelName": level_name_for_level(current_level),
        "streak": streak,
        "imagesCompleted": images_completed,
        "phrasesLearned": phrases_learned,
        "roadmapCheckpointsCompleted": roadmap_checkpoints_completed,
        "achievements": achievements,
    }


def level_name_for_level(level: int) -> str:
    level = max(1, int(level or 1))
    if level <= 5:
        return "Observer"
    if level <= 10:
        return "Describer"
    if level <= 20:
        return "Explorer"
    if level <= 35:
        return "Articulator"
    if level <= 50:
        return "Communicator"
    return "Storyteller"


def _progress_counts(db: Database, user_id: int) -> dict[str, int]:
    with db._connect() as conn:
        images_completed = conn.execute(
            "SELECT COUNT(*) FROM analysis_sessions WHERE user_id = ?",
            (user_id,),
        ).fetchone()[0]
        phrases_learned = conn.execute(
            "SELECT COUNT(*) FROM reusable_language_assets WHERE user_id = ?",
            (user_id,),
        ).fetchone()[0]
        completed_roadmap_missions = conn.execute(
            """
            SELECT COUNT(*)
            FROM roadmap_mission_attempts
            WHERE user_id = ? AND status = 'completed'
            """,
            (user_id,),
        ).fetchone()[0]
        roadmap_checkpoints_completed = conn.execute(
            """
            SELECT COUNT(*)
            FROM roadmap_skill_progress
            WHERE user_id = ?
              AND total_asset_count > 0
              AND (
                mastered_asset_count >= total_asset_count
                OR average_mastery_score >= 0.91
              )
            """,
            (user_id,),
        ).fetchone()[0]
    return {
        "images_completed": int(images_completed or 0),
        "phrases_learned": int(phrases_learned or 0),
        "completed_roadmap_missions": int(completed_roadmap_missions or 0),
        "roadmap_checkpoints_completed": int(roadmap_checkpoints_completed or 0),
    }


def _achievements(
    *,
    streak: int,
    images_completed: int,
    phrases_learned: int,
    completed_roadmap_missions: int,
    roadmap_checkpoints_completed: int,
) -> list[dict[str, Any]]:
    rules = [
        ("first_session", "First Session", images_completed >= 1),
        ("seven_day_streak", "7-Day Streak", streak >= 7),
        ("first_roadmap_mission", "First Roadmap Mission", completed_roadmap_missions >= 1),
        ("first_checkpoint", "First Checkpoint", roadmap_checkpoints_completed >= 1),
        ("hundred_phrases", "100 Phrases Learned", phrases_learned >= 100),
        ("thirty_day_streak", "30-Day Streak", streak >= 30),
    ]
    return [
        {
            "key": key,
            "name": name,
            "earned": bool(earned),
        }
        for key, name, earned in rules
        if earned
    ]
