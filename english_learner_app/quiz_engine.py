from __future__ import annotations

import random
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

from .learning import adaptive_level, canonical_level, unique_texts
from .utils import normalize_answer


QUIZ_TYPE_PRIORITY = [
    "recognition",
    "phrase_completion",
    "expression_training",
    "situation_understanding",
    "sentence_building",
    "fill_blank",
    "typing",
    "memory_recall",
    "error_focus",
]


@dataclass(slots=True)
class QuizSelectionProfile:
    learner_level: str
    recent_accuracy: float
    fast_correct_ratio: float
    weak_item_count: int

    @property
    def adapted_level(self) -> str:
        return adaptive_level(
            base_level=self.learner_level,
            recent_accuracy=self.recent_accuracy,
            weak_item_count=self.weak_item_count,
            fast_correct_ratio=self.fast_correct_ratio,
        )


def _sentence_to_words(text: str) -> list[str]:
    return [word for word in re.split(r"\s+", text.strip()) if word]


def _masked_sentence(text: str, target: str) -> str | None:
    pattern = re.compile(rf"(?<!\w){re.escape(target)}(?!\w)", re.IGNORECASE)
    if not pattern.search(text):
        return None
    return pattern.sub("_____", text, count=1)


def _pick_distractors(correct_answer: str, candidates: list[str], *, limit: int = 3) -> list[str]:
    correct_key = normalize_answer(correct_answer)
    pool = [
        item
        for item in unique_texts(candidates)
        if normalize_answer(item) and normalize_answer(item) != correct_key
    ]
    random.shuffle(pool)
    return pool[:limit]


def _build_sentence_building_metadata(sentence: str) -> dict[str, Any]:
    words = _sentence_to_words(sentence)
    shuffled = words[:]
    if len(shuffled) > 1:
        random.shuffle(shuffled)
        if shuffled == words:
            shuffled = list(reversed(words))
    return {
        "tokens": shuffled,
        "correct_tokens": words,
    }


def _weak_sentence_prompt_for_phrase(phrase: str, meaning: str) -> str:
    text = phrase.strip()
    if not text or len(text.split()) < 2:
        return ""
    if meaning:
        return f'Rewrite this idea using "{text}": {meaning}'
    return f'Use "{text}" in a new sentence about the image.'


def _typing_keywords(
    *,
    analysis: dict[str, Any],
    limit: int = 5,
) -> list[str]:
    candidates = []
    for obj in analysis.get("objects", [])[:4]:
        candidates.append(str(obj.get("name") or "").strip())
    for action in analysis.get("actions", [])[:3]:
        candidates.append(str(action.get("verb") or "").strip())
        candidates.append(str(action.get("phrase") or "").strip())
    for phrase in analysis.get("phrases", [])[:3]:
        candidates.append(str(phrase.get("phrase") or "").strip())
    return unique_texts(candidates, limit=limit)


def build_session_assets(
    *,
    user_id: int,
    session_id: int,
    analysis: dict[str, Any],
    learner_level: str,
    created_at: str,
    first_review_minutes: int,
) -> dict[str, list[dict[str, Any]]]:
    vocabulary_rows = build_vocabulary_rows(
        user_id=user_id,
        session_id=session_id,
        analysis=analysis,
        created_at=created_at,
    )
    phrase_rows = build_phrase_rows(
        user_id=user_id,
        session_id=session_id,
        analysis=analysis,
        created_at=created_at,
    )
    review_rows = build_review_rows(
        user_id=user_id,
        session_id=session_id,
        analysis=analysis,
        created_at=created_at,
        first_review_minutes=first_review_minutes,
    )
    quiz_rows = build_quiz_rows(
        user_id=user_id,
        session_id=session_id,
        analysis=analysis,
        learner_level=learner_level,
        created_at=created_at,
    )
    return {
        "vocabulary": vocabulary_rows,
        "phrases": phrase_rows,
        "review_items": review_rows,
        "quiz_items": quiz_rows,
    }


def build_vocabulary_rows(
    *,
    user_id: int,
    session_id: int,
    analysis: dict[str, Any],
    created_at: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in analysis.get("vocabulary", [])[:10]:
        word = str(item.get("word") or "").strip()
        meaning_simple = str(item.get("meaning_simple") or "").strip()
        key = normalize_answer(word)
        if not word or not meaning_simple or key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "user_id": user_id,
                "session_id": session_id,
                "word": word,
                "part_of_speech": str(item.get("part_of_speech") or "").strip(),
                "meaning_simple": meaning_simple,
                "example": str(item.get("example") or "").strip(),
                "examples": list(item.get("examples") or []),
                "frequency_priority": str(item.get("frequency_priority") or "high").strip(),
                "mastery": 0.0,
                "correct_count": 0,
                "wrong_count": 0,
                "created_at": created_at,
            }
        )
    return rows


def build_phrase_rows(
    *,
    user_id: int,
    session_id: int,
    analysis: dict[str, Any],
    created_at: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in analysis.get("phrases", [])[:10]:
        phrase = str(item.get("phrase") or "").strip()
        meaning_simple = str(item.get("meaning_simple") or "").strip()
        key = normalize_answer(phrase)
        if not phrase or not meaning_simple or key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "user_id": user_id,
                "session_id": session_id,
                "phrase": phrase,
                "meaning_simple": meaning_simple,
                "example": str(item.get("example") or "").strip(),
                "examples": list(item.get("examples") or []),
                "reusable": 1 if item.get("reusable", True) else 0,
                "collocation_type": str(item.get("collocation_type") or "phrase").strip(),
                "mastery": 0.0,
                "correct_count": 0,
                "wrong_count": 0,
                "created_at": created_at,
            }
        )
    return rows


def build_review_rows(
    *,
    user_id: int,
    session_id: int,
    analysis: dict[str, Any],
    created_at: str,
    first_review_minutes: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_prompts: set[str] = set()

    for vocab in analysis.get("vocabulary", [])[:8]:
        word = str(vocab.get("word") or "").strip()
        meaning_simple = str(vocab.get("meaning_simple") or "").strip()
        example = str(vocab.get("example") or "").strip()
        if not word or not meaning_simple:
            continue
        prompt = f'Which word from this lesson means "{meaning_simple}"?'
        key = normalize_answer(prompt)
        if key in seen_prompts:
            continue
        seen_prompts.add(key)
        rows.append(
            _review_row(
                user_id=user_id,
                session_id=session_id,
                card_kind="word",
                prompt=prompt,
                answer=word,
                context_note=example,
                source_kind="vocabulary",
                source_text=word,
                created_at=created_at,
                first_review_minutes=first_review_minutes,
                acceptable_answers=[word],
                metadata={"part_of_speech": vocab.get("part_of_speech", "")},
            )
        )

    for phrase in analysis.get("phrases", [])[:8]:
        text = str(phrase.get("phrase") or "").strip()
        meaning = str(phrase.get("meaning_simple") or "").strip()
        example = str(phrase.get("example") or "").strip()
        if not text or not meaning:
            continue
        prompt = f'What phrase from this lesson means "{meaning}"?'
        key = normalize_answer(prompt)
        if key in seen_prompts:
            continue
        seen_prompts.add(key)
        rows.append(
            _review_row(
                user_id=user_id,
                session_id=session_id,
                card_kind="phrase",
                prompt=prompt,
                answer=text,
                context_note=example,
                source_kind="phrase",
                source_text=text,
                created_at=created_at,
                first_review_minutes=first_review_minutes,
                acceptable_answers=[text],
                metadata={"meaning_simple": meaning},
            )
        )

    for action in analysis.get("actions", [])[:5]:
        phrase = str(action.get("phrase") or action.get("verb") or "").strip()
        meaning = str(action.get("meaning_simple") or action.get("description") or "").strip()
        if not phrase or not meaning:
            continue
        prompt = f'What action is important in this image: "{meaning}"?'
        key = normalize_answer(prompt)
        if key in seen_prompts:
            continue
        seen_prompts.add(key)
        rows.append(
            _review_row(
                user_id=user_id,
                session_id=session_id,
                card_kind="action",
                prompt=prompt,
                answer=phrase,
                context_note=str(action.get("subject") or "").strip(),
                source_kind="action",
                source_text=phrase,
                created_at=created_at,
                first_review_minutes=first_review_minutes,
                acceptable_answers=[phrase, str(action.get("verb") or "").strip()],
                metadata={"object": action.get("object", "")},
            )
        )

    return rows


def _review_row(
    *,
    user_id: int,
    session_id: int,
    card_kind: str,
    prompt: str,
    answer: str,
    context_note: str,
    source_kind: str,
    source_text: str,
    created_at: str,
    first_review_minutes: int,
    acceptable_answers: list[str],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    due_at = datetime.fromisoformat(created_at) + timedelta(minutes=first_review_minutes)
    return {
        "user_id": user_id,
        "session_id": session_id,
        "card_kind": card_kind,
        "prompt": prompt,
        "answer": answer,
        "context_note": context_note,
        "source_kind": source_kind,
        "source_text": source_text,
        "acceptable_answers": unique_texts(acceptable_answers),
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
        "metadata": metadata,
        "due_at": due_at.isoformat(),
        "created_at": created_at,
    }


def build_quiz_rows(
    *,
    user_id: int,
    session_id: int,
    analysis: dict[str, Any],
    learner_level: str,
    created_at: str,
) -> list[dict[str, Any]]:
    quiz_rows: list[dict[str, Any]] = []
    seen_prompts: set[str] = set()

    object_names = unique_texts(
        [str(item.get("name") or "").strip() for item in analysis.get("objects", [])],
        limit=8,
    )
    action_phrases = unique_texts(
        [
            str(item.get("phrase") or item.get("verb") or "").strip()
            for item in analysis.get("actions", [])
        ],
        limit=8,
    )
    phrase_texts = unique_texts(
        [str(item.get("phrase") or "").strip() for item in analysis.get("phrases", [])],
        limit=10,
    )
    distractor_pool = unique_texts(object_names + action_phrases + phrase_texts)
    all_examples = [
        str(item.get("example") or "").strip()
        for item in analysis.get("vocabulary", []) + analysis.get("phrases", [])
        if str(item.get("example") or "").strip()
    ]

    for obj in analysis.get("objects", [])[:4]:
        name = str(obj.get("name") or "").strip()
        description = str(obj.get("description") or "").strip()
        if not name:
            continue
        prompt = "What is one key object in this image?"
        quiz_rows.append(
            _quiz_row(
                user_id=user_id,
                session_id=session_id,
                quiz_type="recognition",
                prompt=prompt,
                answer_mode="multiple_choice",
                correct_answer=name,
                acceptable_answers=[name],
                distractors=_pick_distractors(name, distractor_pool),
                explanation=description or f'"{name}" is one of the important image details.',
                difficulty=_difficulty_for_type("recognition", learner_level),
                skill_tag="object recognition",
                metadata={"source_text": name},
                seen_prompts=seen_prompts,
                created_at=created_at,
            )
        )

    for phrase in analysis.get("phrases", [])[:4]:
        text = str(phrase.get("phrase") or "").strip()
        example = str(phrase.get("example") or "").strip()
        meaning = str(phrase.get("meaning_simple") or "").strip()
        if not text:
            continue
        if meaning:
            quiz_rows.append(
                _quiz_row(
                    user_id=user_id,
                    session_id=session_id,
                    quiz_type="phrase_completion",
                    prompt=f'Which reusable phrase means "{meaning}"?',
                    answer_mode="multiple_choice",
                    correct_answer=text,
                    acceptable_answers=[text],
                    distractors=_pick_distractors(text, phrase_texts),
                    explanation=f'Use "{text}" when you want to express this idea naturally.',
                    difficulty=_difficulty_for_type("phrase_completion", learner_level),
                    skill_tag="phrase meaning",
                    metadata={"source_text": text, "phrase_focus": True},
                    seen_prompts=seen_prompts,
                    created_at=created_at,
                )
            )
        if not example:
            continue
        masked = _masked_sentence(example, text)
        if masked:
            quiz_rows.append(
                _quiz_row(
                    user_id=user_id,
                    session_id=session_id,
                    quiz_type="expression_training",
                    prompt=masked,
                    answer_mode="multiple_choice",
                    correct_answer=text,
                    acceptable_answers=[text],
                    distractors=_pick_distractors(text, phrase_texts),
                    explanation=meaning or f'Use "{text}" when this idea fits the picture.',
                    difficulty=_difficulty_for_type("expression_training", learner_level),
                    skill_tag="reusable phrase",
                    metadata={"source_text": text, "phrase_focus": True},
                    seen_prompts=seen_prompts,
                    created_at=created_at,
                )
            )
        weak_prompt = _weak_sentence_prompt_for_phrase(text, meaning)
        if weak_prompt:
            quiz_rows.append(
                _quiz_row(
                    user_id=user_id,
                    session_id=session_id,
                    quiz_type="typing",
                    prompt=weak_prompt,
                    answer_mode="typing",
                    correct_answer=text,
                    acceptable_answers=[text],
                    distractors=[],
                    explanation=example or meaning or f'Use "{text}" naturally in your sentence.',
                    difficulty=_difficulty_for_type("typing", learner_level),
                    skill_tag="use this phrase",
                    metadata={
                        "keywords": [text],
                        "source_text": text,
                        "phrase_focus": True,
                        "reference_answer": example or text,
                    },
                    seen_prompts=seen_prompts,
                    created_at=created_at,
                )
            )

    for action in analysis.get("actions", [])[:4]:
        phrase = str(action.get("phrase") or action.get("verb") or "").strip()
        subject = str(action.get("subject") or "The person").strip() or "The person"
        if not phrase:
            continue
        prompt = f"{subject} is _____."
        distractors = _pick_distractors(
            phrase,
            action_phrases
            + [
                "standing still",
                "walking away",
                "looking around",
                "waiting nearby",
            ],
        )
        if distractors:
            quiz_rows.append(
                _quiz_row(
                    user_id=user_id,
                    session_id=session_id,
                    quiz_type="phrase_completion",
                    prompt=prompt,
                    answer_mode="multiple_choice",
                    correct_answer=phrase,
                    acceptable_answers=[phrase, str(action.get("verb") or "").strip()],
                    distractors=distractors,
                    explanation=str(action.get("description") or "").strip()
                    or f'The best action phrase here is "{phrase}".',
                    difficulty=_difficulty_for_type("phrase_completion", learner_level),
                    skill_tag="action phrase",
                    metadata={"source_text": phrase},
                    seen_prompts=seen_prompts,
                    created_at=created_at,
                )
            )

    if analysis.get("scene_summary_simple"):
        scene_answer = str(analysis.get("scene_summary_simple") or "").strip()
        scene_prompt = "What is happening in this image?"
        scene_distractors = unique_texts(
            [
                str(item.get("distractor") or "").strip()
                for item in analysis.get("quiz_candidates", [])
                if str(item.get("distractor") or "").strip()
            ]
            + [
                "A person is sleeping in a quiet room.",
                "Nothing clear is happening in the scene.",
                "The image only shows a close-up object with no action.",
            ],
            limit=3,
        )
        quiz_rows.append(
            _quiz_row(
                user_id=user_id,
                session_id=session_id,
                quiz_type="situation_understanding",
                prompt=scene_prompt,
                answer_mode="multiple_choice",
                correct_answer=scene_answer,
                acceptable_answers=[scene_answer],
                distractors=scene_distractors,
                explanation=str(analysis.get("environment") or "").strip()
                or "This option matches the main scene summary.",
                difficulty=_difficulty_for_type("situation_understanding", learner_level),
                skill_tag="scene understanding",
                metadata={"source_text": scene_answer},
                seen_prompts=seen_prompts,
                created_at=created_at,
            )
        )

    for example in all_examples[:3]:
        tokens = _sentence_to_words(example)
        if len(tokens) < 4:
            continue
        quiz_rows.append(
            _quiz_row(
                user_id=user_id,
                session_id=session_id,
                quiz_type="sentence_building",
                prompt="Put the words in the correct order.",
                answer_mode="reorder",
                correct_answer=example,
                acceptable_answers=[example],
                distractors=[],
                explanation="This sentence matches the natural phrase order from the lesson.",
                difficulty=_difficulty_for_type("sentence_building", learner_level),
                skill_tag="sentence building",
                metadata=_build_sentence_building_metadata(example),
                seen_prompts=seen_prompts,
                created_at=created_at,
            )
        )

    for pattern in analysis.get("sentence_patterns", [])[:4]:
        pattern_text = str(pattern.get("pattern") or "").strip()
        example = str(pattern.get("example") or "").strip()
        usage_note = str(pattern.get("usage_note") or "").strip()
        if not pattern_text or not example:
            continue
        quiz_rows.append(
            _quiz_row(
                user_id=user_id,
                session_id=session_id,
                quiz_type="error_focus",
                prompt=f"Which sentence structure would improve this idea? {usage_note or 'Describe the image more naturally.'}",
                answer_mode="multiple_choice",
                correct_answer=pattern_text,
                acceptable_answers=[pattern_text],
                distractors=_pick_distractors(
                    pattern_text,
                    [
                        "Very good thing ...",
                        "Photo has stuff ...",
                        "It is doing there ...",
                        "The image make ...",
                    ],
                ),
                explanation=example,
                difficulty=_difficulty_for_type("error_focus", learner_level),
                skill_tag="sentence improvement",
                metadata={"source_text": pattern_text, "reference_answer": example},
                seen_prompts=seen_prompts,
                created_at=created_at,
            )
        )

    for vocab in analysis.get("vocabulary", [])[:4]:
        word = str(vocab.get("word") or "").strip()
        example = str(vocab.get("example") or "").strip()
        meaning = str(vocab.get("meaning_simple") or "").strip()
        if not word or not example:
            continue
        masked = _masked_sentence(example, word)
        if not masked:
            continue
        quiz_rows.append(
            _quiz_row(
                user_id=user_id,
                session_id=session_id,
                quiz_type="fill_blank",
                prompt=masked,
                answer_mode="typing",
                correct_answer=word,
                acceptable_answers=[word],
                distractors=[],
                explanation=meaning or f'The missing word is "{word}".',
                difficulty=_difficulty_for_type("fill_blank", learner_level),
                skill_tag="vocabulary",
                metadata={"source_text": word},
                seen_prompts=seen_prompts,
                created_at=created_at,
            )
        )

    typing_reference = str(analysis.get("scene_summary_simple") or "").strip()
    if typing_reference:
        quiz_rows.append(
            _quiz_row(
                user_id=user_id,
                session_id=session_id,
                quiz_type="typing",
                prompt="Describe this image in one simple sentence.",
                answer_mode="typing",
                correct_answer=typing_reference,
                acceptable_answers=[typing_reference],
                distractors=[],
                explanation="A short sentence with the main object and action is enough.",
                difficulty=_difficulty_for_type("typing", learner_level),
                skill_tag="active recall",
                metadata={
                    "keywords": _typing_keywords(analysis=analysis),
                    "reference_answer": typing_reference,
                },
                seen_prompts=seen_prompts,
                created_at=created_at,
            )
        )

    memory_focus = object_names[:1] + action_phrases[:1]
    if memory_focus:
        answer = ", ".join(memory_focus)
        quiz_rows.append(
            _quiz_row(
                user_id=user_id,
                session_id=session_id,
                quiz_type="memory_recall",
                prompt="From this lesson, what do you remember first?",
                answer_mode="typing",
                correct_answer=answer,
                acceptable_answers=memory_focus,
                distractors=[],
                explanation="Remembering even one key object or action helps build long-term memory.",
                difficulty=_difficulty_for_type("memory_recall", learner_level),
                skill_tag="memory recall",
                metadata={"keywords": memory_focus, "reference_answer": answer},
                seen_prompts=seen_prompts,
                created_at=created_at,
            )
        )

    return [item for item in quiz_rows if item]


def _quiz_row(
    *,
    user_id: int,
    session_id: int,
    quiz_type: str,
    prompt: str,
    answer_mode: str,
    correct_answer: str,
    acceptable_answers: list[str],
    distractors: list[str],
    explanation: str,
    difficulty: float,
    skill_tag: str,
    metadata: dict[str, Any],
    seen_prompts: set[str],
    created_at: str,
) -> dict[str, Any] | None:
    key = normalize_answer(f"{quiz_type}:{prompt}")
    if not prompt or not correct_answer or key in seen_prompts:
        return None
    seen_prompts.add(key)
    return {
        "user_id": user_id,
        "session_id": session_id,
        "quiz_type": quiz_type,
        "prompt": prompt,
        "answer_mode": answer_mode,
        "correct_answer": correct_answer,
        "acceptable_answers": unique_texts(acceptable_answers),
        "distractors": unique_texts(distractors, limit=3),
        "explanation": explanation,
        "difficulty": difficulty,
        "skill_tag": skill_tag,
        "metadata": metadata,
        "created_at": created_at,
    }


def _difficulty_for_type(quiz_type: str, learner_level: str) -> float:
    base = {
        "recognition": 0.15,
        "phrase_completion": 0.28,
        "expression_training": 0.34,
        "situation_understanding": 0.42,
        "sentence_building": 0.55,
        "fill_blank": 0.45,
        "typing": 0.7,
        "memory_recall": 0.76,
        "error_focus": 0.18,
    }.get(quiz_type, 0.35)
    level = canonical_level(learner_level)
    if level == "beginner":
        return max(0.1, base - 0.08)
    if level == "advancing":
        return min(0.95, base + 0.08)
    return base


def arrange_session_quick_challenge(
    *,
    items: list[dict[str, Any]],
    limit: int = 5,
) -> list[dict[str, Any]]:
    if not items:
        return []

    limit = max(3, min(limit, 5))
    selected: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    def take_matching(max_count: int, allowed_types: set[str]) -> None:
        for item in sorted(
            items,
            key=lambda candidate: (
                0 if candidate.get("metadata", {}).get("phrase_focus") else 1,
                float(candidate.get("difficulty") or 0.0),
            ),
        ):
            if len(selected) >= limit or max_count <= 0:
                return
            item_id = int(item["id"])
            if item_id in seen_ids or str(item.get("quiz_type") or "") not in allowed_types:
                continue
            selected.append(item)
            seen_ids.add(item_id)
            max_count -= 1

    take_matching(3, {"phrase_completion", "expression_training", "typing"})
    take_matching(1, {"fill_blank", "sentence_building", "error_focus"})
    take_matching(1, {"recognition", "situation_understanding", "memory_recall"})
    take_matching(1, {"typing"})

    for item in sorted(items, key=lambda candidate: float(candidate.get("difficulty") or 0.0)):
        if len(selected) >= limit:
            break
        item_id = int(item["id"])
        if item_id in seen_ids:
            continue
        selected.append(item)
        seen_ids.add(item_id)

    return selected[:limit]


def choose_quiz_candidates(
    *,
    items: list[dict[str, Any]],
    profile: QuizSelectionProfile,
    limit: int,
    mode: str,
) -> list[dict[str, Any]]:
    if not items:
        return []

    adapted_level = profile.adapted_level
    target_max = {
        "beginner": 0.55,
        "developing": 0.72,
        "advancing": 0.95,
    }[adapted_level]

    def score(item: dict[str, Any]) -> tuple[float, float, float, float]:
        due_bonus = 1.5 if item.get("is_due") else 0.0
        weak_bonus = (
            float(item.get("review_wrong_streak") or 0) * 0.65
            + float(item.get("wrong_count") or 0) * 0.25
        )
        freshness_bonus = 0.25 if int(item.get("times_shown") or 0) == 0 else 0.0
        difficulty = float(item.get("difficulty") or 0.3)
        if mode == "mistakes":
            weak_bonus += 1.2
        if mode == "session":
            freshness_bonus += 0.45
        if difficulty > target_max and adapted_level == "beginner":
            weak_bonus -= 0.5
        return (
            due_bonus + weak_bonus + freshness_bonus,
            -abs(difficulty - target_max),
            -float(item.get("times_shown") or 0),
            -QUIZ_TYPE_PRIORITY.index(item.get("quiz_type"))
            if item.get("quiz_type") in QUIZ_TYPE_PRIORITY
            else -99,
        )

    sorted_items = sorted(items, key=score, reverse=True)
    selected: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    seen_types: defaultdict[str, int] = defaultdict(int)

    for item in sorted_items:
        if len(selected) >= limit:
            break
        item_id = int(item["id"])
        quiz_type = str(item.get("quiz_type") or "")
        if item_id in seen_ids:
            continue
        if len(selected) < min(limit, len(QUIZ_TYPE_PRIORITY)) and seen_types[quiz_type] >= 1:
            continue
        seen_ids.add(item_id)
        seen_types[quiz_type] += 1
        selected.append(item)

    for item in sorted_items:
        if len(selected) >= limit:
            break
        item_id = int(item["id"])
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)
        selected.append(item)

    if mode in {"mistakes", "daily_challenge"}:
        selected = apply_error_focus(selected)

    return selected


def apply_error_focus(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    adjusted: list[dict[str, Any]] = []
    for item in items:
        if int(item.get("review_wrong_streak") or 0) < 2 and int(item.get("wrong_count") or 0) < 2:
            adjusted.append(item)
            continue

        clone = dict(item)
        clone["quiz_type"] = "error_focus"
        clone["difficulty"] = min(0.25, float(item.get("difficulty") or 0.3))
        clone["answer_mode"] = "multiple_choice"
        if not clone.get("distractors"):
            candidate_pool = clone.get("acceptable_answers", []) + [
                "background",
                "object",
                "action",
                "place",
            ]
            clone["distractors"] = _pick_distractors(
                str(clone.get("correct_answer") or ""),
                candidate_pool,
            )
        clone["prompt"] = f"Let's review a tricky one: {clone['prompt']}"
        adjusted.append(clone)
    return adjusted


def evaluate_quiz_response(
    *,
    item: dict[str, Any],
    selected_answer: str,
    response_ms: int | None,
    confidence: int | None,
) -> dict[str, Any]:
    answer_mode = str(item.get("answer_mode") or "multiple_choice")
    acceptable_answers = unique_texts(
        item.get("acceptable_answers", []) or [str(item.get("correct_answer") or "").strip()]
    )
    metadata = item.get("metadata") or {}

    if answer_mode == "reorder":
        return _evaluate_reorder(
            item=item,
            selected_answer=selected_answer,
            acceptable_answers=acceptable_answers,
            response_ms=response_ms,
            confidence=confidence,
        )
    if answer_mode == "typing":
        return _evaluate_typing(
            item=item,
            selected_answer=selected_answer,
            acceptable_answers=acceptable_answers,
            metadata=metadata,
            response_ms=response_ms,
            confidence=confidence,
        )
    return _evaluate_choice(
        item=item,
        selected_answer=selected_answer,
        acceptable_answers=acceptable_answers,
        response_ms=response_ms,
        confidence=confidence,
    )


def _evaluate_choice(
    *,
    item: dict[str, Any],
    selected_answer: str,
    acceptable_answers: list[str],
    response_ms: int | None,
    confidence: int | None,
) -> dict[str, Any]:
    normalized_selected = normalize_answer(selected_answer)
    is_correct = any(normalized_selected == normalize_answer(answer) for answer in acceptable_answers)
    score = 1.0 if is_correct else 0.0
    quality = 5 if is_correct and (response_ms or 0) < 6000 else 4 if is_correct else 2
    return {
        "correct": is_correct,
        "score": score,
        "quality": quality,
        "feedback": {
            "good": "You matched the key meaning correctly." if is_correct else "",
            "improve": "" if is_correct else "Look at the main object, action, or phrase more closely.",
            "corrected_example": str(item.get("correct_answer") or ""),
        },
        "response_ms": response_ms or 0,
        "confidence": confidence or 2,
    }


def _evaluate_reorder(
    *,
    item: dict[str, Any],
    selected_answer: str,
    acceptable_answers: list[str],
    response_ms: int | None,
    confidence: int | None,
) -> dict[str, Any]:
    normalized_selected = normalize_answer(selected_answer)
    is_correct = any(normalized_selected == normalize_answer(answer) for answer in acceptable_answers)
    score = 1.0 if is_correct else 0.35 if normalized_selected else 0.0
    quality = 4 if is_correct else 2
    return {
        "correct": is_correct,
        "score": score,
        "quality": quality,
        "feedback": {
            "good": "Your word order sounds natural." if is_correct else "",
            "improve": "" if is_correct else "Keep the key phrase together and watch the sentence order.",
            "corrected_example": str(item.get("correct_answer") or ""),
        },
        "response_ms": response_ms or 0,
        "confidence": confidence or 2,
    }


def _evaluate_typing(
    *,
    item: dict[str, Any],
    selected_answer: str,
    acceptable_answers: list[str],
    metadata: dict[str, Any],
    response_ms: int | None,
    confidence: int | None,
) -> dict[str, Any]:
    normalized_selected = normalize_answer(selected_answer)
    similarity = max(
        (
            SequenceMatcher(None, normalized_selected, normalize_answer(answer)).ratio()
            for answer in acceptable_answers
            if normalize_answer(answer)
        ),
        default=0.0,
    )

    keywords = unique_texts(metadata.get("keywords", []))
    matched_keywords = [
        keyword for keyword in keywords if normalize_answer(keyword) in normalized_selected
    ]
    keyword_ratio = (
        len(matched_keywords) / len(keywords)
        if keywords
        else (1.0 if normalized_selected else 0.0)
    )
    score = max(similarity, keyword_ratio)
    is_correct = score >= 0.55 or (keywords and len(matched_keywords) >= min(2, len(keywords)))
    quality = 5 if is_correct and score >= 0.75 else 4 if is_correct else 2

    feedback_good = []
    if matched_keywords:
        feedback_good.append(f"You used key idea(s): {', '.join(matched_keywords[:3])}.")
    if similarity >= 0.6:
        feedback_good.append("Your answer is close to the lesson target.")

    improve = ""
    if not is_correct:
        if keywords:
            improve = (
                "Try to include the main object and action in one clear sentence."
            )
        else:
            improve = "Try a shorter sentence with the most important detail first."

    corrected_example = str(metadata.get("reference_answer") or item.get("correct_answer") or "").strip()
    return {
        "correct": is_correct,
        "score": round(score, 3),
        "quality": quality,
        "feedback": {
            "good": " ".join(feedback_good).strip(),
            "improve": improve,
            "corrected_example": corrected_example,
        },
        "response_ms": response_ms or 0,
        "confidence": confidence or 2,
    }
