from __future__ import annotations

import random
import re
from datetime import datetime, timedelta
from typing import Any

from .utils import normalize_answer, to_iso


DEFAULT_SRS_INTERVALS_MINUTES = [60, 1440, 4320, 10080, 20160, 43200]

FALLBACK_DISTRACTORS = {
    "phrase": [
        "in the middle of nowhere",
        "without much detail",
        "for no clear reason",
        "out of the picture",
    ],
    "word": [
        "window",
        "corner",
        "street",
        "shadow",
    ],
    "action": [
        "sleeping",
        "waiting quietly",
        "walking away",
        "looking down",
    ],
    "phrase_choice": [
        "out of nowhere",
        "on the other side",
        "without any detail",
        "at the exact center",
    ],
    "phrase_usage": [
        "all of a sudden",
        "in every direction",
        "without much context",
        "at full speed",
    ],
    "quiz": [
        "The scene has no clear details.",
        "Everything happens at the same time.",
        "The speaker cannot identify any object.",
        "There is no useful language to learn.",
    ],
}


def _mask_phrase_in_example(example: str, phrase: str) -> str | None:
    pattern = re.compile(re.escape(phrase), re.IGNORECASE)
    if not pattern.search(example):
        return None
    return pattern.sub("_____", example, count=1)


def build_study_cards(
    *,
    user_id: int,
    session_id: int,
    analysis: dict[str, Any],
    now: datetime,
    first_review_minutes: int,
) -> list[dict[str, Any]]:
    due_at = now + timedelta(minutes=first_review_minutes)
    cards: list[dict[str, Any]] = []
    seen_prompts: set[str] = set()

    def push(card: dict[str, Any]) -> None:
        key = normalize_answer(card["prompt"])
        if key in seen_prompts:
            return
        seen_prompts.add(key)
        cards.append(card)

    for item in analysis.get("reusable_language", [])[:8]:
        phrase = str(item.get("text", "")).strip()
        definition = str(
            item.get("definition") or item.get("why_it_matters") or ""
        ).strip()
        example = str(item.get("example") or "").strip()
        if not phrase or not definition:
            continue

        push(
            {
                "user_id": user_id,
                "session_id": session_id,
                "card_kind": "phrase",
                "prompt": f'What does "{phrase}" help you express in natural English?',
                "answer": phrase,
                "context_note": definition,
                "source_kind": "phrase",
                "source_text": phrase,
                "acceptable_answers": [phrase],
                "interval_minutes": first_review_minutes,
                "interval_step": 0,
                "interval_days": first_review_minutes / 1440,
                "ease_factor": 2.5,
                "repetitions": 0,
                "mastery": 0.0,
                "difficulty": 0.2,
                "correct_streak": 0,
                "wrong_streak": 0,
                "review_count": 0,
                "metadata": {"definition": definition},
                "due_at": to_iso(due_at),
                "created_at": to_iso(now),
            }
        )

        reverse_prompt = f'Which reusable phrase matches this meaning: "{definition}"?'
        push(
            {
                "user_id": user_id,
                "session_id": session_id,
                "card_kind": "phrase_choice",
                "prompt": reverse_prompt,
                "answer": phrase,
                "context_note": example or definition,
                "source_kind": "phrase",
                "source_text": phrase,
                "acceptable_answers": [phrase],
                "interval_minutes": first_review_minutes,
                "interval_step": 0,
                "interval_days": first_review_minutes / 1440,
                "ease_factor": 2.5,
                "repetitions": 0,
                "mastery": 0.0,
                "difficulty": 0.25,
                "correct_streak": 0,
                "wrong_streak": 0,
                "review_count": 0,
                "metadata": {"definition": definition},
                "due_at": to_iso(due_at),
                "created_at": to_iso(now),
            }
        )

        if example:
            masked_example = _mask_phrase_in_example(example, phrase)
            if masked_example and masked_example != example:
                push(
                    {
                        "user_id": user_id,
                        "session_id": session_id,
                        "card_kind": "phrase_usage",
                        "prompt": masked_example,
                        "answer": phrase,
                        "context_note": definition,
                        "source_kind": "phrase",
                        "source_text": phrase,
                        "acceptable_answers": [phrase],
                        "interval_minutes": first_review_minutes,
                        "interval_step": 0,
                        "interval_days": first_review_minutes / 1440,
                        "ease_factor": 2.5,
                        "repetitions": 0,
                        "mastery": 0.0,
                        "difficulty": 0.3,
                        "correct_streak": 0,
                        "wrong_streak": 0,
                        "review_count": 0,
                        "metadata": {"definition": definition},
                        "due_at": to_iso(due_at),
                        "created_at": to_iso(now),
                    }
                )

    for item in analysis.get("micro_quiz", [])[:6]:
        question = str(item.get("question", "")).strip()
        answer = str(item.get("answer", "")).strip()
        if not question or not answer:
            continue
        prompt = question if question.endswith("?") else f"{question}?"
        push(
            {
                "user_id": user_id,
                "session_id": session_id,
                "card_kind": "quiz",
                "prompt": prompt,
                "answer": answer,
                "context_note": str(item.get("hint") or "").strip(),
                "source_kind": "quiz",
                "source_text": answer,
                "acceptable_answers": [answer],
                "interval_minutes": first_review_minutes,
                "interval_step": 0,
                "interval_days": first_review_minutes / 1440,
                "ease_factor": 2.5,
                "repetitions": 0,
                "mastery": 0.0,
                "difficulty": 0.35,
                "correct_streak": 0,
                "wrong_streak": 0,
                "review_count": 0,
                "metadata": {},
                "due_at": to_iso(due_at),
                "created_at": to_iso(now),
            }
        )

    return cards


def build_review_options(card: dict[str, Any], distractor_answers: list[str]) -> list[str]:
    correct_answer = str(card["answer"]).strip()
    unique_answers: list[str] = []
    seen: set[str] = set()

    def push(value: str) -> None:
        normalized = normalize_answer(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_answers.append(value)

    push(correct_answer)
    for answer in distractor_answers:
        push(answer)

    if len(unique_answers) < 4:
        for fallback in FALLBACK_DISTRACTORS.get(card.get("card_kind", ""), []):
            push(fallback)
            if len(unique_answers) >= 4:
                break

    options = unique_answers[:4]
    random.shuffle(options)
    return options


def select_quiz_cards(cards: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    seen_kinds: set[str] = set()

    for card in cards:
        if len(selected) >= limit:
            return selected
        kind = str(card.get("card_kind") or "")
        if kind and kind not in seen_kinds:
            selected.append(card)
            seen_ids.add(int(card["id"]))
            seen_kinds.add(kind)

    for card in cards:
        if len(selected) >= limit:
            break
        card_id = int(card["id"])
        if card_id in seen_ids:
            continue
        selected.append(card)
        seen_ids.add(card_id)

    return selected


def calculate_next_review(
    *,
    card: dict[str, Any],
    quality: int,
    now: datetime,
    first_review_minutes: int,
    response_ms: int | None = None,
    confidence: int | None = None,
) -> dict[str, Any]:
    interval_step = int(card.get("interval_step", 0))
    interval_minutes = int(card.get("interval_minutes", first_review_minutes))
    ease_factor = float(card.get("ease_factor", 2.5))
    mastery = float(card.get("mastery", 0.0))
    difficulty = float(card.get("difficulty", 0.2))
    correct_streak = int(card.get("correct_streak", 0))
    wrong_streak = int(card.get("wrong_streak", 0))
    review_count = int(card.get("review_count", 0)) + 1

    fast_answer = bool(response_ms and response_ms <= 7000)
    high_confidence = (confidence or 2) >= 3
    was_correct = quality >= 3

    if was_correct:
        step_gain = 2 if fast_answer and high_confidence and interval_step < 2 else 1
        interval_step = min(len(DEFAULT_SRS_INTERVALS_MINUTES) - 1, interval_step + step_gain)
        interval_minutes = DEFAULT_SRS_INTERVALS_MINUTES[interval_step]
        correct_streak += 1
        wrong_streak = 0
        mastery = min(1.0, mastery + (0.16 if fast_answer else 0.1) + (0.04 if high_confidence else 0.0))
        difficulty = max(0.1, difficulty - 0.03)
        repetitions = int(card.get("repetitions", 0)) + 1
        last_result = "correct"
    else:
        interval_step = max(0, interval_step - 1)
        interval_minutes = DEFAULT_SRS_INTERVALS_MINUTES[interval_step]
        correct_streak = 0
        wrong_streak += 1
        mastery = max(0.0, mastery - 0.18)
        difficulty = min(0.9, difficulty + 0.05)
        repetitions = 0
        last_result = "incorrect"

    ease_factor = max(
        1.3,
        ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)),
    )
    due_at = now + timedelta(minutes=interval_minutes)

    return {
        "interval_days": interval_minutes / 1440,
        "ease_factor": ease_factor,
        "repetitions": repetitions,
        "due_at": to_iso(due_at),
        "last_reviewed_at": to_iso(now),
        "interval_minutes": interval_minutes,
        "interval_step": interval_step,
        "mastery": round(mastery, 4),
        "difficulty": round(difficulty, 4),
        "correct_streak": correct_streak,
        "wrong_streak": wrong_streak,
        "review_count": review_count,
        "last_quality": quality,
        "last_result": last_result,
        "last_response_ms": response_ms or 0,
        "last_confidence": confidence or 2,
    }
