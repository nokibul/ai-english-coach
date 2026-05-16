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
    "phrase_snap",
    "choose_better",
    "fix_the_sentence",
    "sentence_upgrade_battle",
    "phrase_duel",
    "fix_the_mistake",
    "use_it_or_lose_it",
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


def build_post_improve_quiz_rows(
    *,
    user_id: int,
    session_id: int,
    analysis: dict[str, Any],
    learner_level: str,
    learner_text: str,
    improved_text: str,
    feedback: dict[str, Any],
    created_at: str,
) -> list[dict[str, Any]]:
    seen_prompts: set[str] = set()
    rows: list[dict[str, Any] | None] = []
    explanation = str(
        analysis.get("scene_summary_natural")
        or analysis.get("natural_explanation")
        or analysis.get("native_explanation")
        or analysis.get("scene_summary_simple")
        or ""
    ).strip()
    phrases = _post_improve_phrases(analysis, feedback)
    primary_phrase = phrases[0]["phrase"] if phrases else ""
    missing_details = _feedback_text_list(feedback.get("missing_details"), limit=3)
    better_version = _shorten_to_sentence(
        str(feedback.get("better_version") or improved_text or explanation).strip()
    )
    improved_text = _shorten_to_sentence(improved_text.strip() or better_version)
    visual_terms = _object_action_terms(analysis)
    vocabulary_terms = _post_improve_vocabulary(analysis)
    action_phrase = _micro_action_phrase(analysis, phrases, better_version, improved_text)
    fill_target = _post_improve_fill_target(analysis, phrases, action_phrase)
    snap = _micro_phrase_snap(fill_target, improved_text or better_version or explanation)
    fixed_sentence = improved_text or better_version or _shorten_to_sentence(explanation)
    option_pool = unique_texts([*visual_terms, *vocabulary_terms, *[item["phrase"] for item in phrases]], limit=10)
    comprehension = _post_improve_comprehension_question(analysis, feedback, option_pool)

    if comprehension:
        rows.append(
            _quiz_row(
                user_id=user_id,
                session_id=session_id,
                quiz_type="multiple_choice_comprehension",
                prompt=comprehension["prompt"],
                answer_mode="multiple_choice",
                correct_answer=comprehension["answer"],
                acceptable_answers=[comprehension["answer"]],
                distractors=_deterministic_options(
                    correct=comprehension["answer"],
                    candidates=comprehension["distractors"],
                ),
                explanation=comprehension["explanation"],
                difficulty=_difficulty_for_type("multiple_choice_comprehension", learner_level),
                skill_tag="post-improve quiz",
                metadata=_post_improve_metadata(
                    quiz_label="Multiple Choice",
                    related_phrase=primary_phrase,
                    xp_value=5,
                    source="current image/session",
                ),
                seen_prompts=seen_prompts,
                created_at=created_at,
            )
        )

    pairs = _post_improve_matching_pairs(analysis, phrases, feedback)
    if len(pairs) >= 3:
        matching_pairs = pairs[:5]
        correct_answer = _matching_answer_string(matching_pairs)
        rows.append(
            _quiz_row(
                user_id=user_id,
                session_id=session_id,
                quiz_type="matching_pairs",
                prompt="Match each word or phrase with its meaning.",
                answer_mode="matching",
                correct_answer=correct_answer,
                acceptable_answers=[correct_answer],
                distractors=[],
                explanation="These pairs reinforce useful language from this image.",
                difficulty=_difficulty_for_type("matching_pairs", learner_level),
                skill_tag="post-improve quiz",
                metadata={
                    **_post_improve_metadata(
                        quiz_label="Matching",
                        related_phrase=primary_phrase,
                        xp_value=6,
                        source="current image/session",
                    ),
                    "pairs": matching_pairs,
                },
                seen_prompts=seen_prompts,
                created_at=created_at,
            )
        )

    if snap:
        prompt, answer, acceptable = snap
        rows.append(
            _quiz_row(
                user_id=user_id,
                session_id=session_id,
                quiz_type="fill_blank",
                prompt=f"Fill in the Blank: {prompt}",
                answer_mode="typing",
                correct_answer=answer,
                acceptable_answers=acceptable,
                distractors=_deterministic_options(
                    correct=answer,
                    candidates=[*visual_terms, *vocabulary_terms],
                ),
                explanation="Complete the image phrase with the missing action word.",
                difficulty=_difficulty_for_type("fill_blank", learner_level),
                skill_tag="post-improve quiz",
                metadata=_post_improve_metadata(
                    quiz_label="Fill in the Blank",
                    related_phrase=action_phrase or primary_phrase,
                    xp_value=8,
                    source="current image/session",
                ),
                seen_prompts=seen_prompts,
                created_at=created_at,
            )
        )

    if fixed_sentence:
        rows.append(
            _quiz_row(
                user_id=user_id,
                session_id=session_id,
                quiz_type="sentence_reconstruction",
                prompt="Put the words in the correct order.",
                answer_mode="reorder",
                correct_answer=fixed_sentence,
                acceptable_answers=[fixed_sentence, improved_text],
                distractors=[],
                explanation="Build a natural sentence about the same image.",
                difficulty=_difficulty_for_type("sentence_reconstruction", learner_level),
                skill_tag="post-improve quiz",
                metadata={
                    **_post_improve_metadata(
                        quiz_label="Sentence Reconstruction",
                        related_phrase=primary_phrase or action_phrase,
                        xp_value=10,
                        source="current image/session",
                    ),
                    "reference_answer": fixed_sentence,
                    **_build_sentence_reconstruction_metadata(fixed_sentence),
                },
                seen_prompts=seen_prompts,
                created_at=created_at,
            )
        )

    order = {
        "multiple_choice_comprehension": 0,
        "matching_pairs": 1,
        "fill_blank": 2,
        "sentence_reconstruction": 3,
    }
    return sorted([item for item in rows if item], key=lambda item: order.get(str(item["quiz_type"]), 99))[:8]


def _difficulty_for_type(quiz_type: str, learner_level: str) -> float:
    base = {
        "multiple_choice_comprehension": 0.18,
        "matching_pairs": 0.28,
        "sentence_reconstruction": 0.5,
        "choose_better": 0.28,
        "fix_the_sentence": 0.48,
        "sentence_upgrade_battle": 0.5,
        "phrase_snap": 0.3,
        "phrase_duel": 0.42,
        "fix_the_mistake": 0.52,
        "use_it_or_lose_it": 0.6,
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


def _post_improve_metadata(
    *,
    quiz_label: str,
    related_phrase: str,
    xp_value: int,
    source: str,
) -> dict[str, Any]:
    return {
        "quiz_label": quiz_label,
        "related_reusable_phrase": related_phrase,
        "xp_value": xp_value,
        "source": source,
        "post_improve": True,
    }


def _post_improve_phrases(analysis: dict[str, Any], feedback: dict[str, Any]) -> list[dict[str, str]]:
    phrase_usage = feedback.get("phrase_usage") if isinstance(feedback.get("phrase_usage"), dict) else {}
    requested: list[str] = []
    requested.extend(_feedback_text_list((phrase_usage or {}).get("suggested"), limit=4))
    requested.extend(_feedback_text_list((phrase_usage or {}).get("used"), limit=4))
    phrase_map: dict[str, dict[str, str]] = {}
    for item in analysis.get("phrases", []):
        phrase = str(item.get("phrase") or "").strip()
        if not phrase:
            continue
        phrase_map[normalize_answer(phrase)] = {
            "phrase": phrase,
            "meaning": str(item.get("meaning_simple") or "").strip(),
            "example": str(item.get("example") or "").strip(),
        }

    ordered: list[dict[str, str]] = []
    for phrase in requested:
        found = phrase_map.get(normalize_answer(phrase))
        if found and found not in ordered:
            ordered.append(found)
    for item in phrase_map.values():
        if item not in ordered:
            ordered.append(item)
    return ordered[:5]


def _post_improve_comprehension_question(
    analysis: dict[str, Any],
    feedback: dict[str, Any],
    option_pool: list[str],
) -> dict[str, Any] | None:
    missing_text = normalize_answer(" ".join(_feedback_text_list(feedback.get("missing_details"), limit=3)))
    objects = [str(item.get("name") or "").strip() for item in analysis.get("objects", []) if str(item.get("name") or "").strip()]
    actions = [
        str(item.get("phrase") or item.get("verb") or "").strip()
        for item in analysis.get("actions", [])
        if str(item.get("phrase") or item.get("verb") or "").strip()
    ]
    background = unique_texts(
        [
            str(analysis.get("environment") or "").strip(),
            *[str(item or "").strip() for item in analysis.get("environment_details", [])],
        ],
        limit=3,
    )
    vocabulary = _post_improve_vocabulary(analysis)
    candidates = [
        (
            "What is the main action in this image?",
            actions[0] if actions else "",
            [*objects, *background, *vocabulary],
            "This checks the main action from the uploaded image.",
            "main action",
        ),
        (
            "Who or what is the main subject?",
            objects[0] if objects else "",
            [*actions, *background, *vocabulary],
            "This checks the main subject from the uploaded image.",
            "main subject",
        ),
        (
            "Which background detail fits the image?",
            background[0] if background else "",
            [*objects, *actions, *vocabulary],
            "This checks the setting or background from the uploaded image.",
            "background",
        ),
        (
            "Which important object appears in the image?",
            objects[1] if len(objects) > 1 else objects[0] if objects else "",
            [*actions, *background, *vocabulary],
            "This checks an important object from the uploaded image.",
            "object",
        ),
        (
            "Which word best fits the atmosphere or description?",
            vocabulary[0] if vocabulary else "",
            [*objects, *actions, *background],
            "This checks a useful descriptive word from the session.",
            "atmosphere",
        ),
    ]
    if "action" in missing_text:
        candidates.insert(0, candidates.pop(0))
    elif "subject" in missing_text or "person" in missing_text:
        candidates.insert(0, candidates.pop(1))
    elif "background" in missing_text or "setting" in missing_text:
        candidates.insert(0, candidates.pop(2))

    for prompt, answer, distractors, explanation, focus in candidates:
        answer = _short_pair_text(answer)
        options = _deterministic_options(
            correct=answer,
            candidates=[_short_pair_text(item) for item in [*distractors, *option_pool]],
            limit=3,
        )
        if answer and len(options) >= 2:
            return {
                "prompt": prompt,
                "answer": answer,
                "distractors": options,
                "explanation": explanation,
                "focus": focus,
            }
    return None


def _post_improve_matching_pairs(
    analysis: dict[str, Any],
    phrases: list[dict[str, str]],
    feedback: dict[str, Any],
) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    for item in phrases[:3]:
        phrase = str(item.get("phrase") or "").strip()
        meaning = str(item.get("meaning") or "").strip()
        if phrase and meaning:
            pairs.append({"left": phrase, "right": meaning})

    for action in analysis.get("actions", [])[:3]:
        verb = str(action.get("verb") or "").strip()
        phrase = str(action.get("phrase") or "").strip()
        if verb and phrase and normalize_answer(verb) != normalize_answer(phrase):
            pairs.append({"left": verb, "right": phrase})

    for index, obj in enumerate(analysis.get("objects", [])[:2]):
        name = str(obj.get("name") or "").strip()
        if name:
            pairs.append({"left": name, "right": "main subject" if index == 0 else "important object"})

    missing = _feedback_text_list(feedback.get("missing_details"), limit=2)
    for detail in missing:
        if detail:
            pairs.append({"left": detail, "right": "important image detail"})

    for vocab in analysis.get("vocabulary", [])[:4]:
        word = str(vocab.get("word") or "").strip()
        meaning = str(vocab.get("meaning_simple") or "").strip()
        if word and meaning:
            pairs.append({"left": word, "right": meaning})

    for phrase in _positioning_phrases_from_analysis(analysis)[:3]:
        pairs.append({"left": phrase, "right": "position phrase"})

    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    for pair in pairs:
        left = _short_pair_text(pair.get("left", ""))
        right = _short_pair_text(pair.get("right", ""))
        key = normalize_answer(f"{left}:{right}")
        if left and right and key not in seen:
            cleaned.append({"left": left, "right": right})
            seen.add(key)
    return cleaned[:5]


def _short_pair_text(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" .!?")
    words = text.split()
    if len(words) > 8:
        text = " ".join(words[:8])
    return text


def _matching_answer_string(pairs: list[dict[str, str]]) -> str:
    return "||".join(f"{pair['left']}=>{pair['right']}" for pair in pairs if pair.get("left") and pair.get("right"))


def _post_improve_vocabulary(analysis: dict[str, Any]) -> list[str]:
    words: list[str] = []
    for item in analysis.get("vocabulary", [])[:5]:
        words.append(str(item.get("word") or "").strip())
    return unique_texts(words, limit=5)


def _micro_action_phrase(
    analysis: dict[str, Any], phrases: list[dict[str, str]], *sentences: str
) -> str:
    for action in analysis.get("actions", [])[:4]:
        phrase = str(action.get("phrase") or "").strip()
        if phrase and len(phrase.split()) >= 2:
            return phrase
    for phrase_item in phrases[:4]:
        phrase = str(phrase_item.get("phrase") or "").strip()
        if phrase and len(phrase.split()) >= 2:
            return phrase
    for sentence in sentences:
        words = re.findall(r"[A-Za-z][A-Za-z'-]*", sentence or "")
        for index, word in enumerate(words[:-1]):
            if _is_action_word(word):
                return " ".join(words[index : min(index + 3, len(words))])
    return ""


def _post_improve_fill_target(
    analysis: dict[str, Any],
    phrases: list[dict[str, str]],
    action_phrase: str,
) -> str:
    for phrase_item in phrases:
        phrase = str(phrase_item.get("phrase") or "").strip()
        if 1 <= len(phrase.split()) <= 4:
            return phrase
    if action_phrase:
        return action_phrase
    for phrase in _positioning_phrases_from_analysis(analysis):
        if phrase:
            return phrase
    for action in analysis.get("actions", [])[:3]:
        verb = str(action.get("verb") or "").strip()
        if verb:
            return verb
    return _first_visual_detail(analysis)


def _micro_phrase_snap(action_phrase: str, source_sentence: str) -> tuple[str, str, list[str]] | None:
    phrase_words = re.findall(r"[A-Za-z][A-Za-z'-]*", action_phrase or "")
    if not phrase_words:
        return None
    answer = action_phrase.strip()
    if len(phrase_words) > 4:
        answer = next((word for word in phrase_words if _is_action_word(word)), phrase_words[0])
    sentence = _shorten_to_sentence(source_sentence)
    if not sentence or normalize_answer(answer) not in normalize_answer(sentence):
        sentence = f"The image shows {action_phrase}."
    masked = _masked_sentence(sentence, answer) or f"The image shows _____."
    acceptable = unique_texts([answer, _base_action_word(answer)] if len(answer.split()) == 1 else [answer], limit=4)
    return masked, answer, acceptable


def _positioning_phrases_from_analysis(analysis: dict[str, Any]) -> list[str]:
    values = [
        str(analysis.get("environment") or ""),
        *[str(item or "") for item in analysis.get("environment_details", [])],
    ]
    phrases: list[str] = []
    for value in values:
        text = value.lower()
        phrases.extend(re.findall(r"\b(?:in|on|near|along|behind|beside|around|across)\s+(?:the\s+)?[a-z]+(?:\s+[a-z]+){0,2}", text))
    return unique_texts([phrase.strip() for phrase in phrases], limit=5)


def _build_sentence_reconstruction_metadata(sentence: str) -> dict[str, Any]:
    chunks = _sentence_to_chunks(sentence)
    shuffled = chunks[:]
    if len(shuffled) > 1:
        random.shuffle(shuffled)
        if shuffled == chunks:
            shuffled = list(reversed(chunks))
    return {
        "tokens": shuffled,
        "correct_tokens": chunks,
    }


def _sentence_to_chunks(sentence: str) -> list[str]:
    words = _sentence_to_words(sentence)
    if len(words) <= 8:
        return words
    target_chunks = 6 if len(words) <= 14 else 8
    chunk_size = max(1, round(len(words) / target_chunks))
    chunks = [" ".join(words[index : index + chunk_size]) for index in range(0, len(words), chunk_size)]
    if len(chunks) > 8:
        chunks = chunks[:7] + [" ".join(" ".join(chunks[7:]).split())]
    return chunks


def _micro_use_phrase(primary_phrase: str, action_phrase: str, fill_answer: str) -> str:
    for value in [fill_answer, action_phrase, primary_phrase]:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _sentence_for_use_phrase(
    *,
    phrase: str,
    source_sentence: str,
    analysis: dict[str, Any],
) -> str:
    phrase = str(phrase or "").strip()
    if not phrase:
        return ""
    sentence = _shorten_to_sentence(source_sentence)
    if normalize_answer(phrase) in normalize_answer(sentence):
        return sentence

    subject = _first_visual_detail(analysis) or "The image"
    if _is_action_word(phrase.split()[0]):
        return f"{subject.capitalize()} is {phrase}."
    return f"The image shows {phrase}."


def _is_action_word(word: str) -> bool:
    text = normalize_answer(word)
    common_actions = {
        "ride",
        "riding",
        "sit",
        "sitting",
        "stand",
        "standing",
        "walk",
        "walking",
        "hold",
        "holding",
        "look",
        "looking",
        "cut",
        "cutting",
        "mow",
        "mowing",
        "use",
        "using",
        "play",
        "playing",
        "wear",
        "wearing",
        "carry",
        "carrying",
        "drive",
        "driving",
    }
    return text in common_actions or text.endswith("ing")


def _base_action_word(word: str) -> str:
    text = str(word or "").strip()
    lowered = text.lower()
    irregular = {
        "riding": "ride",
        "using": "use",
        "driving": "drive",
        "mowing": "mow",
        "sitting": "sit",
        "cutting": "cut",
        "standing": "stand",
    }
    if lowered in irregular:
        return irregular[lowered]
    if lowered.endswith("ing") and len(lowered) > 5:
        stem = text[:-3]
        if stem and stem[-1:] == stem[-2:-1]:
            stem = stem[:-1]
        return stem
    return text


def _feedback_text_list(values: Any, *, limit: int) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    for value in values:
        if isinstance(value, dict):
            text = str(
                value.get("phrase")
                or value.get("text")
                or value.get("detail")
                or value.get("note")
                or ""
            ).strip()
        else:
            text = str(value or "").strip()
        if text:
            cleaned.append(text)
    return unique_texts(cleaned, limit=limit)


def _deterministic_options(*, correct: str, candidates: list[str], limit: int = 3) -> list[str]:
    correct_key = normalize_answer(correct)
    options: list[str] = []
    for candidate in candidates:
        text = str(candidate or "").strip()
        key = normalize_answer(text)
        if text and key and key != correct_key:
            options.append(text)
    return unique_texts(options, limit=limit)


def _shorten_to_sentence(text: str) -> str:
    sentence = re.split(r"(?<=[.!?])\s+", str(text or "").strip())[0].strip()
    return sentence or str(text or "").strip()


def _sentence_with_phrase(text: str, phrase: str) -> str:
    phrase_key = normalize_answer(phrase)
    for sentence in re.split(r"(?<=[.!?])\s+", str(text or "").strip()):
        if phrase_key and phrase_key in normalize_answer(sentence):
            return sentence.strip()
    return ""


def _object_action_terms(analysis: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for obj in analysis.get("objects", [])[:4]:
        terms.append(str(obj.get("name") or "").strip())
    for action in analysis.get("actions", [])[:3]:
        terms.append(str(action.get("phrase") or action.get("verb") or "").strip())
    return unique_texts(terms, limit=6)


def _generic_weak_sentence(analysis: dict[str, Any]) -> str:
    terms = _object_action_terms(analysis)
    if terms:
        return f"The image has {terms[0]}."
    return "The image has something."


def _first_visual_detail(analysis: dict[str, Any]) -> str:
    for obj in analysis.get("objects", [])[:3]:
        name = str(obj.get("name") or "").strip()
        if name:
            return name
    details = analysis.get("environment_details") or []
    if details:
        return str(details[0] or "").strip()
    return ""


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
    quiz_type = str(item.get("quiz_type") or "")
    acceptable_answers = unique_texts(
        item.get("acceptable_answers", []) or [str(item.get("correct_answer") or "").strip()]
    )
    metadata = item.get("metadata") or {}

    if quiz_type == "matching_pairs" and answer_mode == "matching":
        return _evaluate_matching_pairs(
            item=item,
            selected_answer=selected_answer,
            acceptable_answers=acceptable_answers,
            response_ms=response_ms,
            confidence=confidence,
        )
    if quiz_type == "sentence_upgrade_battle" and answer_mode == "typing":
        return _evaluate_sentence_upgrade(
            item=item,
            selected_answer=selected_answer,
            acceptable_answers=acceptable_answers,
            metadata=metadata,
            response_ms=response_ms,
            confidence=confidence,
        )
    if quiz_type == "fix_the_mistake" and answer_mode == "typing":
        return _evaluate_fix_the_mistake(
            item=item,
            selected_answer=selected_answer,
            acceptable_answers=acceptable_answers,
            metadata=metadata,
            response_ms=response_ms,
            confidence=confidence,
        )
    if quiz_type == "fix_the_sentence" and answer_mode == "typing":
        return _evaluate_fix_the_sentence(
            item=item,
            selected_answer=selected_answer,
            acceptable_answers=acceptable_answers,
            metadata=metadata,
            response_ms=response_ms,
            confidence=confidence,
        )
    if quiz_type == "use_it_or_lose_it":
        return _evaluate_use_it_or_lose_it(
            item=item,
            selected_answer=selected_answer,
            acceptable_answers=acceptable_answers,
            metadata=metadata,
            response_ms=response_ms,
            confidence=confidence,
        )
    if quiz_type in {"phrase_snap", "fill_blank"} and answer_mode == "typing":
        return _evaluate_fill_in(
            item=item,
            selected_answer=selected_answer,
            acceptable_answers=acceptable_answers,
            response_ms=response_ms,
            confidence=confidence,
        )
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
        "result_type": "Correct" if is_correct else "Incorrect",
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


def _evaluate_matching_pairs(
    *,
    item: dict[str, Any],
    selected_answer: str,
    acceptable_answers: list[str],
    response_ms: int | None,
    confidence: int | None,
) -> dict[str, Any]:
    expected = _parse_matching_answer(acceptable_answers[0] if acceptable_answers else item.get("correct_answer", ""))
    selected = _parse_matching_answer(selected_answer)
    total = max(1, len(expected))
    correct_count = sum(
        1
        for left, right in expected.items()
        if normalize_answer(selected.get(left, "")) == normalize_answer(right)
    )
    score = correct_count / total
    is_correct = score >= 0.999
    almost = not is_correct and score >= 0.5
    return {
        "correct": is_correct,
        "result_type": "Correct" if is_correct else "Almost Correct" if almost else "Incorrect",
        "score": score,
        "quality": 5 if is_correct else 3 if almost else 2,
        "feedback": {
            "good": "You matched the image language well." if is_correct else "",
            "improve": "" if is_correct else "Match each phrase to the meaning from this image.",
            "corrected_example": str(item.get("correct_answer") or ""),
        },
        "response_ms": response_ms or 0,
        "confidence": confidence or 2,
    }


def _parse_matching_answer(value: Any) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for chunk in str(value or "").split("||"):
        if "=>" not in chunk:
            continue
        left, right = chunk.split("=>", 1)
        left = left.strip()
        right = right.strip()
        if left:
            pairs[left] = right
    return pairs


def _evaluate_reorder(
    *,
    item: dict[str, Any],
    selected_answer: str,
    acceptable_answers: list[str],
    response_ms: int | None,
    confidence: int | None,
) -> dict[str, Any]:
    normalized_selected = normalize_answer(selected_answer)
    normalized_answers = [normalize_answer(answer) for answer in acceptable_answers if normalize_answer(answer)]
    is_correct = any(normalized_selected == answer for answer in normalized_answers)
    reference = normalized_answers[0] if normalized_answers else normalize_answer(item.get("correct_answer"))
    similarity = SequenceMatcher(None, normalized_selected, reference).ratio() if normalized_selected and reference else 0.0
    chunk_score = _chunk_order_score(
        selected_answer=selected_answer,
        correct_tokens=(item.get("metadata") or {}).get("correct_tokens") or [],
    )
    score = 1.0 if is_correct else max(similarity, chunk_score)
    almost = not is_correct and score >= 0.55
    quality = 4 if is_correct else 3 if almost else 2
    return {
        "correct": is_correct,
        "result_type": "Correct" if is_correct else "Almost Correct" if almost else "Incorrect",
        "score": round(score, 3),
        "quality": quality,
        "feedback": {
            "good": "Your word order sounds natural." if is_correct else "",
            "improve": "" if is_correct else "You are close. Keep the chunks in the image sentence order." if almost else "Put the chunks in the sentence order from the image.",
            "corrected_example": str(item.get("correct_answer") or ""),
        },
        "response_ms": response_ms or 0,
        "confidence": confidence or 2,
    }


def _chunk_order_score(*, selected_answer: str, correct_tokens: list[Any]) -> float:
    expected = [normalize_answer(token) for token in correct_tokens if normalize_answer(token)]
    selected = normalize_answer(selected_answer)
    if not expected or not selected:
        return 0.0
    positions = [selected.find(token) for token in expected]
    present = [index for index in positions if index >= 0]
    if not present:
        return 0.0
    in_order = 1
    last = present[0]
    for position in present[1:]:
        if position >= last:
            in_order += 1
            last = position
    coverage = len(present) / len(expected)
    order = in_order / len(expected)
    return round((coverage + order) / 2, 3)


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
    is_almost = not is_correct and score >= 0.38
    quality = 5 if is_correct and score >= 0.75 else 4 if is_correct else 2

    feedback_good = []
    if matched_keywords:
        feedback_good.append(f"You used key idea(s): {', '.join(matched_keywords[:3])}.")
    if similarity >= 0.6:
        feedback_good.append("Your answer is close to the lesson target.")

    improve = ""
    if not is_correct:
        if keywords:
            improve = "You are close. Add more of the key image details in one clear sentence." if is_almost else (
                "Try to include the main object and action in one clear sentence."
            )
        else:
            improve = "Try a shorter sentence with the most important detail first."

    corrected_example = str(metadata.get("reference_answer") or item.get("correct_answer") or "").strip()
    return {
        "correct": is_correct,
        "result_type": "Correct" if is_correct else "Almost Correct" if is_almost else "Incorrect",
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


def _evaluate_fill_in(
    *,
    item: dict[str, Any],
    selected_answer: str,
    acceptable_answers: list[str],
    response_ms: int | None,
    confidence: int | None,
) -> dict[str, Any]:
    selected = selected_answer.strip()
    normalized_selected = normalize_answer(selected)
    exact = any(normalized_selected == normalize_answer(answer) for answer in acceptable_answers)
    close = bool(normalized_selected) and _close_to_any_answer(
        normalized_selected,
        acceptable_answers,
        threshold=0.82,
    )
    result_type = "Correct" if exact else "Almost Correct" if close else "Incorrect"
    score = 1.0 if exact else 0.65 if close else 0.0
    correct_answer = str(item.get("correct_answer") or "")
    return {
        "correct": exact,
        "result_type": result_type,
        "score": score,
        "quality": 5 if exact else 3 if close else 2,
        "feedback": {
            "good": "That word fits the image sentence." if exact else "That is close to the target word." if close else "",
            "improve": "" if exact else f'Use "{correct_answer}" for this blank.',
            "corrected_example": correct_answer,
        },
        "response_ms": response_ms or 0,
        "confidence": confidence or 2,
    }


def _evaluate_sentence_upgrade(
    *,
    item: dict[str, Any],
    selected_answer: str,
    acceptable_answers: list[str],
    metadata: dict[str, Any],
    response_ms: int | None,
    confidence: int | None,
) -> dict[str, Any]:
    selected = selected_answer.strip()
    normalized_selected = normalize_answer(selected)
    weak_sentence = str(metadata.get("weak_sentence") or "").strip()
    reference = str(metadata.get("reference_answer") or item.get("correct_answer") or "").strip()
    keywords = unique_texts(metadata.get("keywords", []), limit=6)
    related_phrase = str(metadata.get("related_reusable_phrase") or "").strip()
    keyword_ratio = _keyword_ratio(normalized_selected, keywords)
    reference_similarity = _best_similarity(normalized_selected, acceptable_answers + [reference])
    weak_similarity = SequenceMatcher(None, normalized_selected, normalize_answer(weak_sentence)).ratio() if weak_sentence else 0.0
    preserves_meaning = keyword_ratio >= 0.45 or reference_similarity >= 0.62
    stronger = bool(selected) and (
        len(selected.split()) >= max(5, len(weak_sentence.split()) + 2)
        or reference_similarity >= 0.68
    ) and weak_similarity < 0.96
    phrase_used = bool(related_phrase) and normalize_answer(related_phrase) in normalized_selected

    score = min(1.0, max(reference_similarity, keyword_ratio) + (0.12 if phrase_used else 0.0))
    is_correct = preserves_meaning and stronger and score >= 0.68
    is_almost = not is_correct and (preserves_meaning or phrase_used or score >= 0.45)
    return {
        "correct": is_correct,
        "result_type": "Correct" if is_correct else "Almost Correct" if is_almost else "Incorrect",
        "score": round(1.0 if is_correct else max(score, 0.55) if is_almost else score, 3),
        "quality": 5 if is_correct else 3 if is_almost else 2,
        "feedback": {
            "good": "You preserved the meaning and made the sentence stronger." if is_correct else (
                "You kept part of the meaning." if is_almost else ""
            ),
            "improve": "" if is_correct else (
                "Make it more specific and more natural than the weak sentence."
                if is_almost
                else "Keep the main meaning, then add clearer image detail."
            ),
            "corrected_example": reference,
        },
        "response_ms": response_ms or 0,
        "confidence": confidence or 2,
    }


def _evaluate_fix_the_mistake(
    *,
    item: dict[str, Any],
    selected_answer: str,
    acceptable_answers: list[str],
    metadata: dict[str, Any],
    response_ms: int | None,
    confidence: int | None,
) -> dict[str, Any]:
    selected = selected_answer.strip()
    normalized_selected = normalize_answer(selected)
    reference = str(metadata.get("reference_answer") or item.get("correct_answer") or "").strip()
    keywords = unique_texts(metadata.get("keywords", []), limit=6)
    similarity = _best_similarity(normalized_selected, acceptable_answers + [reference])
    keyword_ratio = _keyword_ratio(normalized_selected, keywords)
    natural = _looks_like_natural_sentence(selected)
    score = max(similarity, keyword_ratio)
    is_correct = natural and (similarity >= 0.7 or keyword_ratio >= 0.6)
    is_almost = not is_correct and (natural or similarity >= 0.48 or keyword_ratio >= 0.4)
    return {
        "correct": is_correct,
        "result_type": "Correct" if is_correct else "Almost Correct" if is_almost else "Incorrect",
        "score": round(1.0 if is_correct else max(score, 0.55) if is_almost else score, 3),
        "quality": 5 if is_correct else 3 if is_almost else 2,
        "feedback": {
            "good": "That correction sounds natural." if is_correct else (
                "This is close, but it still needs a cleaner correction." if is_almost else ""
            ),
            "improve": "" if is_correct else "Fix the grammar and keep the image meaning clear.",
            "corrected_example": reference,
        },
        "response_ms": response_ms or 0,
        "confidence": confidence or 2,
    }


def _evaluate_fix_the_sentence(
    *,
    item: dict[str, Any],
    selected_answer: str,
    acceptable_answers: list[str],
    metadata: dict[str, Any],
    response_ms: int | None,
    confidence: int | None,
) -> dict[str, Any]:
    selected = selected_answer.strip()
    normalized_selected = normalize_answer(selected)
    reference = str(metadata.get("reference_answer") or item.get("correct_answer") or "").strip()
    weak_sentence = str(metadata.get("weak_sentence") or "").strip()
    keywords = unique_texts(metadata.get("keywords", []), limit=6)
    similarity = _best_similarity(normalized_selected, acceptable_answers + [reference])
    keyword_ratio = _keyword_ratio(normalized_selected, keywords)
    natural = _looks_like_natural_sentence(selected)
    changed_from_weak = (
        SequenceMatcher(None, normalized_selected, normalize_answer(weak_sentence)).ratio() < 0.94
        if weak_sentence
        else True
    )
    action_preserved = _required_action_preserved(normalized_selected, reference, keywords)
    meaning_preserved = action_preserved and (similarity >= 0.58 or keyword_ratio >= 0.45)
    partial_meaning = action_preserved and (similarity >= 0.42 or keyword_ratio >= 0.3)
    grammar_improved = natural and changed_from_weak and _has_basic_sentence_structure(selected)
    close_natural_alternative = natural and meaning_preserved and (similarity >= 0.62 or keyword_ratio >= 0.5)
    is_correct = grammar_improved and close_natural_alternative
    is_almost = not is_correct and (meaning_preserved or partial_meaning or grammar_improved)
    score = 1.0 if is_correct else max(similarity, keyword_ratio, 0.6 if is_almost else 0.0)
    if not selected:
        score = 0.0
        is_almost = False
    return {
        "correct": is_correct,
        "result_type": "Correct" if is_correct else "Almost Correct" if is_almost else "Incorrect",
        "score": round(score, 3),
        "quality": 5 if is_correct else 3 if is_almost else 2,
        "feedback": {
            "good": "Meaning is preserved and the structure is better." if is_correct else (
                "You kept part of the image meaning." if is_almost else ""
            ),
            "improve": "" if is_correct else (
                "Good start. Make the sentence more complete and natural."
                if is_almost
                else "Keep the main meaning and write one complete sentence."
            ),
            "corrected_example": reference,
        },
        "response_ms": response_ms or 0,
        "confidence": confidence or 2,
    }


def _required_action_preserved(normalized_selected: str, reference: str, keywords: list[str]) -> bool:
    action_words: list[str] = []
    for text in [reference, *keywords]:
        for word in re.findall(r"[A-Za-z][A-Za-z'-]*", text or ""):
            if _is_action_word(word):
                action_words.append(word)
    actions = unique_texts(action_words, limit=3)
    if not actions:
        return True
    for action in actions:
        variants = unique_texts([action, _base_action_word(action), f"{_base_action_word(action)}s"], limit=4)
        if any(normalize_answer(variant) in normalized_selected for variant in variants):
            return True
    return False


def _evaluate_use_it_or_lose_it(
    *,
    item: dict[str, Any],
    selected_answer: str,
    acceptable_answers: list[str],
    metadata: dict[str, Any],
    response_ms: int | None,
    confidence: int | None,
) -> dict[str, Any]:
    selected = selected_answer.strip()
    normalized_selected = normalize_answer(selected)
    phrase = str(metadata.get("related_reusable_phrase") or "").strip()
    normalized_phrase = normalize_answer(phrase)
    phrase_present = _required_phrase_present(normalized_selected, normalized_phrase)
    natural = _looks_like_natural_sentence(selected)
    keywords = unique_texts(metadata.get("keywords", []), limit=6)
    keyword_ratio = _keyword_ratio(normalized_selected, [item for item in keywords if normalize_answer(item) != normalized_phrase])
    is_correct = phrase_present and natural and keyword_ratio >= 0.25
    is_almost = not is_correct and phrase_present
    score = 1.0 if is_correct else 0.6 if is_almost else max(0.0, keyword_ratio * 0.45)
    reference = str(metadata.get("reference_answer") or item.get("correct_answer") or "").strip()
    return {
        "correct": is_correct,
        "result_type": "Correct" if is_correct else "Almost Correct" if is_almost else "Incorrect",
        "score": round(score, 3),
        "quality": 5 if is_correct else 3 if is_almost else 2,
        "feedback": {
            "good": f'You used "{phrase}".' if phrase_present else "",
            "improve": "" if is_correct else (
                "The word or phrase is present. Now make the grammar smoother."
                if is_almost
                else f'Use "{phrase}" in one complete sentence about the image.'
            ),
            "corrected_example": reference,
        },
        "response_ms": response_ms or 0,
        "confidence": confidence or 2,
    }


def _required_phrase_present(normalized_selected: str, normalized_phrase: str) -> bool:
    if not normalized_phrase:
        return False
    if normalized_phrase in normalized_selected:
        return True
    phrase_words = normalized_phrase.split()
    if len(phrase_words) == 1:
        base = _base_action_word(phrase_words[0])
        variants = unique_texts([phrase_words[0], base, f"{base}s", f"{base}ing"], limit=5)
        return any(variant and variant in normalized_selected.split() for variant in variants)
    return False


def _close_to_any_answer(normalized_selected: str, acceptable_answers: list[str], *, threshold: float) -> bool:
    return _best_similarity(normalized_selected, acceptable_answers) >= threshold


def _best_similarity(normalized_selected: str, acceptable_answers: list[str]) -> float:
    return max(
        (
            SequenceMatcher(None, normalized_selected, normalize_answer(answer)).ratio()
            for answer in acceptable_answers
            if normalize_answer(answer)
        ),
        default=0.0,
    )


def _keyword_ratio(normalized_text: str, keywords: list[str]) -> float:
    normalized_keywords = [normalize_answer(keyword) for keyword in keywords if normalize_answer(keyword)]
    if not normalized_keywords:
        return 1.0 if normalized_text else 0.0
    matched = [keyword for keyword in normalized_keywords if keyword in normalized_text]
    return len(matched) / len(normalized_keywords)


def _looks_like_natural_sentence(text: str) -> bool:
    words = [word for word in re.findall(r"[A-Za-z']+", text)]
    if len(words) < 5:
        return False
    lowered = normalize_answer(text)
    weak_patterns = [
        "very very",
        "is very",
        "has something",
        "photo has",
        "picture has",
        "i can see something and",
    ]
    if any(pattern in lowered for pattern in weak_patterns):
        return False
    return any(
        verb in lowered.split()
        for verb in {
            "is",
            "are",
            "was",
            "were",
            "has",
            "have",
            "rides",
            "ride",
            "uses",
            "use",
            "drives",
            "drive",
            "carries",
            "carry",
            "holds",
            "hold",
            "shows",
            "looks",
            "seems",
            "riding",
            "walking",
            "standing",
            "sitting",
            "using",
        }
    )


def _has_basic_sentence_structure(text: str) -> bool:
    words = normalize_answer(text).split()
    if len(words) < 5:
        return False
    linking_or_aux = {
        "is",
        "are",
        "was",
        "were",
        "has",
        "have",
        "shows",
        "looks",
        "seems",
    }
    if any(word in words for word in linking_or_aux):
        return True
    return any(
        word in words
        for word in {
            "rides",
            "drives",
            "uses",
            "carries",
            "holds",
            "walks",
            "stands",
            "sits",
        }
    )
