from __future__ import annotations

from datetime import datetime, timedelta


XP_VALUES = {
    "session_created": 25,
    "quiz_correct": 10,
    "quiz_incorrect": 0,
    "review_correct": 15,
    "review_incorrect": 0,
    "weak_item_correct": 25,
    "phrase_used": 10,
    "multiple_phrases_used": 15,
    "combo_bonus": 5,
    "daily_challenge_completed": 40,
}


def level_from_xp(xp_points: int) -> int:
    xp_points = max(0, int(xp_points))
    return 1 + (xp_points // 120)


def xp_for_event(event_name: str) -> int:
    return XP_VALUES.get(event_name, 0)


def combo_bonus_for_streak(streak_count: int) -> int:
    streak_count = max(0, int(streak_count))
    if streak_count >= 3 and streak_count % 3 == 0:
        return xp_for_event("combo_bonus")
    return 0


def update_streak(
    *,
    last_active_on: str | None,
    streak_days: int,
    today: datetime,
) -> tuple[int, str]:
    today_key = today.date().isoformat()
    if not last_active_on:
        return 1, today_key

    if last_active_on == today_key:
        return max(1, int(streak_days)), today_key

    last_day = datetime.fromisoformat(f"{last_active_on}T00:00:00+00:00").date()
    if today.date() - last_day == timedelta(days=1):
        return max(1, int(streak_days)) + 1, today_key

    return 1, today_key


def improvement_percent(current_value: float, previous_value: float) -> int:
    current_value = float(current_value or 0)
    previous_value = float(previous_value or 0)
    if previous_value <= 0:
        if current_value <= 0:
            return 0
        return 100
    return round(((current_value - previous_value) / previous_value) * 100)
