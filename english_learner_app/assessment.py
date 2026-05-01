from __future__ import annotations

from typing import Any


ONBOARDING_QUESTIONS = [
    {
        "id": "listening_confidence",
        "prompt": "How easily do you understand short everyday English conversations?",
        "min_label": "I need slow, simple English",
        "max_label": "I follow them comfortably",
    },
    {
        "id": "description_confidence",
        "prompt": "How confident are you when describing a photo or situation in English?",
        "min_label": "I struggle to form sentences",
        "max_label": "I can describe things fluently",
    },
    {
        "id": "reading_frequency",
        "prompt": "How often do you read in English without translating every line?",
        "min_label": "Rarely",
        "max_label": "Almost every day",
    },
    {
        "id": "phrase_familiarity",
        "prompt": "How comfortable are you with natural expressions and reusable phrases?",
        "min_label": "Mostly basic words only",
        "max_label": "Idioms and phrases feel natural",
    },
]


def evaluate_assessment(responses: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(responses, dict):
        raise ValueError("Assessment responses must be an object.")

    cleaned: dict[str, int] = {}
    for question in ONBOARDING_QUESTIONS:
        raw_value = responses.get(question["id"])
        if raw_value in (None, ""):
            raise ValueError("Please answer all fluency questions.")

        try:
            value = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Assessment answers must be numbers from 1 to 5.") from exc

        if value < 1 or value > 5:
            raise ValueError("Assessment answers must stay between 1 and 5.")
        cleaned[question["id"]] = value

    score = sum(cleaned.values())
    if score <= 8:
        band = "beginner"
        summary = (
            "Use short sentences, very common vocabulary, and direct explanations "
            "with frequent repetition."
        )
    elif score <= 15:
        band = "developing"
        summary = (
            "Use natural English with richer detail, common collocations, and a mix "
            "of explanation plus practice."
        )
    else:
        band = "advancing"
        summary = (
            "Use dense, native-like English with nuance, flexible phrasing, and more "
            "subtle vocabulary from real-life conversation."
        )

    return {
        "score": score,
        "difficulty_band": band,
        "fluency_summary": summary,
        "responses": cleaned,
    }
