from __future__ import annotations

import base64
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import httpx

from .config import AppConfig
from .learning import canonical_level, level_guidance, level_label
from .utils import (
    extract_json_payload,
    normalize_answer,
    should_surface_term,
    term_surface_score,
)


QUIZ_GENERATION_TYPES = {
    "meaning_match",
    "fill_blank",
    "multiple_choice",
    "better_sentence",
    "sentence_builder",
    "rewrite_challenge",
    "production_challenge",
    "image_recall",
}

def buildSessionQuizGenerationPrompt(
    sessionInput: dict[str, Any],
    languageAssets: list[dict[str, Any]],
) -> str:
    prompt_payload = {
        "sessionInput": {
            "sessionId": sessionInput.get("sessionId"),
            "imageUrl": sessionInput.get("imageUrl"),
            "originalDescription": sessionInput.get("originalDescription") or "",
            "finalDescription": sessionInput.get("finalDescription") or "",
            "enhancementHistory": sessionInput.get("enhancementHistory") or [],
            "guidedCoverageResponses": sessionInput.get("guidedCoverageResponses") or [],
            "coverageFocuses": sessionInput.get("coverageFocuses") or [],
        },
        "languageAssets": [
            {
                "id": asset.get("id"),
                "value": asset.get("value") or "",
                "type": asset.get("type") or "",
                "meaning": asset.get("meaning") or asset.get("meaning_simple") or "",
                "exampleSentence": asset.get("exampleSentence") or asset.get("example_sentence") or "",
                "difficultyLevel": asset.get("difficultyLevel") or asset.get("difficulty_level") or 1,
                "usefulnessScore": asset.get("usefulnessScore") or asset.get("usefulness_score") or 0,
                "transferabilityScore": asset.get("transferabilityScore") or asset.get("transferability_score") or 0,
            }
            for asset in languageAssets
        ],
    }

    return (
        "You are the Post-Session Quiz Generation Engine for an AI English articulation app.\n"
        "Your job is to help the learner practice REUSABLE ENGLISH from one completed image session.\n"
        "The quiz must teach transferable phrases, sentence patterns, collocations, and descriptive language.\n"
        "The quiz must NOT feel like a memory test about the image.\n\n"

        "Return strict JSON only.\n"
        "No markdown.\n"
        "No explanations outside JSON.\n\n"

        "CORE PRINCIPLE:\n"
        "Quiz the LANGUAGE, not the IMAGE.\n"
        "The image is only context. The learning target is reusable English.\n\n"

        "GOOD QUIZ TARGETS:\n"
        "- reusable phrases: covered with, surrounded by, visible in the background\n"
        "- descriptive chunks: dense greenery, compact digital stopwatch\n"
        "- sentence patterns: The image shows..., A ___ is visible..., The scene feels...\n"
        "- positioning language: in the foreground, in the background, next to, attached to\n"
        "- atmosphere language: calm atmosphere, peaceful surroundings, lively environment\n"
        "- action language: firmly holding, walking through, gathered together\n\n"

        "BAD QUIZ TARGETS:\n"
        "- questions that ask the learner to remember image facts\n"
        "- questions where the answer is only useful for this one image\n"
        "- questions like: What was in the image?\n"
        "- questions like: What color was the object?\n"
        "- questions like: Where were the vines?\n"
        "- questions like: What did the user upload?\n"
        "- questions like: What object was shown?\n\n"

        "A quiz may mention the image context, but the answer must be reusable English.\n\n"

        "BAD EXAMPLE:\n"
        "{\n"
        '  "type": "image_recall",\n'
        '  "questionText": "What was around the building?",\n'
        '  "correctAnswer": "trees"\n'
        "}\n\n"

        "GOOD EXAMPLE:\n"
        "{\n"
        '  "type": "fill_blank",\n'
        '  "languageAssetValues": ["surrounded by"],\n'
        '  "questionText": "The building is ______ greenery.",\n'
        '  "correctAnswer": "surrounded by",\n'
        '  "options": ["surrounded by", "under", "between", "behind"],\n'
        '  "explanation": "\\"Surrounded by\\" means something is all around the subject.",\n'
        '  "difficultyLevel": 1\n'
        "}\n\n"

        "EXPECTED JSON SHAPE:\n"
        "{\n"
        '  "quizQuestions": [\n'
        "    {\n"
        '      "type": "fill_blank",\n'
        '      "languageAssetValues": ["covered with"],\n'
        '      "questionText": "The building is ______ climbing vines.",\n'
        '      "prompt": null,\n'
        '      "correctAnswer": "covered with",\n'
        '      "options": ["covered with", "under", "behind", "between"],\n'
        '      "wordBank": null,\n'
        '      "explanation": "\\"Covered with\\" means something has another thing over its surface.",\n'
        '      "difficultyLevel": 1\n'
        "    }\n"
        "  ]\n"
        "}\n\n"

        "ALLOWED TYPES:\n"
        "- meaning_match\n"
        "- fill_blank\n"
        "- multiple_choice\n"
        "- better_sentence\n"
        "- sentence_builder\n"
        "- rewrite_challenge\n"
        "- production_challenge\n"
        "- image_recall\n\n"

        "QUIZ TYPE RULES:\n\n"

        "meaning_match:\n"
        "- Ask what a reusable phrase means.\n"
        "- The correct answer should explain the phrase simply.\n"
        "- Do not ask what happened in the image.\n\n"

        "fill_blank:\n"
        "- Blank should be the reusable phrase or language chunk.\n"
        "- Example: The building is ______ climbing vines.\n"
        "- Correct answer: covered with\n\n"

        "multiple_choice:\n"
        "- Ask which reusable phrase best completes a sentence.\n"
        "- Options should be language choices, not image facts.\n\n"

        "better_sentence:\n"
        "- Compare a weak/simple sentence with a more natural reusable version.\n"
        "- This is very important for articulation growth.\n"
        "- Example weak: The building has vines.\n"
        "- Example better: The building is covered with climbing vines.\n\n"

        "sentence_builder:\n"
        "- Use the target phrase inside the word bank.\n"
        "- The answer should be a reusable sentence pattern.\n\n"

        "rewrite_challenge:\n"
        "- Ask the learner to improve a weak sentence using the target asset.\n"
        "- The target asset must be listed in languageAssetValues.\n\n"

        "production_challenge:\n"
        "- Ask the learner to use a reusable phrase in a sentence.\n"
        "- It may use this image context, but should train future use.\n"
        "- Example: Write a sentence using 'surrounded by'.\n\n"

        "image_recall:\n"
        "- Use sparingly.\n"
        "- It must still ask for reusable language, not image facts.\n"
        "- Good: What phrase did you learn for saying something is all around the subject?\n"
        "- Bad: What was around the building?\n\n"

        "GENERATION RULES:\n"
        "- Generate quizzes only from the provided session content and language assets.\n"
        "- Do not introduce unrelated topics, objects, scenes, names, or places.\n"
        "- Prefer reusable language over simple object names.\n"
        "- Do not generate quizzes whose answer is a simple object noun unless it is part of a useful phrase.\n"
        "- Make questions beginner-friendly.\n"
        "- Use i+1 difficulty: slightly above the learner's current production, but still achievable.\n"
        "- Questions should feel connected to the user's image, but the answer should teach reusable English.\n"
        "- Generate varied question types.\n"
        "- Avoid duplicate questions and repeated wording.\n"
        "- For each high-value asset, generate 5-8 quiz questions when possible.\n"
        "- Prioritize phrases, sentence patterns, positioning language, atmosphere language, action language, and descriptive collocations.\n"
        "- Avoid over-generating for simple nouns.\n"
        "- For rewrite_challenge and production_challenge, do not require exact string matching; include the target asset in languageAssetValues.\n"
        "- prompt, options, and wordBank may be null when not needed.\n"
        "- difficultyLevel must be 1, 2, or 3.\n\n"

        "QUALITY CHECK BEFORE RETURNING JSON:\n"
        "- Every question must have at least one languageAssetValues item.\n"
        "- The correctAnswer should usually be a reusable phrase, sentence pattern, or improved sentence.\n"
        "- Remove questions that mainly test image memory.\n"
        "- Remove questions where the answer is only useful for this one image.\n"
        "- Remove questions about colors, counts, objects, or locations unless they directly teach a reusable phrase.\n\n"

        "SESSION AND LANGUAGE ASSETS JSON:\n"
        f"{json.dumps(prompt_payload, ensure_ascii=True)}"
    )


def _validate_session_quiz_generation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Quiz generation payload must be a JSON object.")
    raw_questions = payload.get("quizQuestions")
    if not isinstance(raw_questions, list):
        raise ValueError('Quiz generation payload must include "quizQuestions" as a list.')

    questions: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for raw_question in raw_questions:
        if not isinstance(raw_question, dict):
            continue
        question_type = str(raw_question.get("type") or "").strip()
        if question_type not in QUIZ_GENERATION_TYPES:
            raise ValueError(f"Unsupported quiz question type: {question_type}")
        language_asset_values = _clean_quiz_string_list(raw_question.get("languageAssetValues"))
        question_text = _clean_quiz_text(raw_question.get("questionText"))
        prompt = _clean_quiz_text(raw_question.get("prompt"))
        correct_answer = _clean_quiz_text(raw_question.get("correctAnswer"))
        options = _clean_quiz_nullable_list(raw_question.get("options"))
        word_bank = _clean_quiz_nullable_list(raw_question.get("wordBank"))
        explanation = _clean_quiz_text(raw_question.get("explanation"))
        try:
            difficulty_level = int(raw_question.get("difficultyLevel") or 1)
        except (TypeError, ValueError):
            difficulty_level = 1
        difficulty_level = max(1, min(3, difficulty_level))

        if not language_asset_values:
            raise ValueError("Each quiz question must include languageAssetValues.")
        if not correct_answer:
            raise ValueError("Each quiz question must include correctAnswer.")
        if not question_text and not prompt:
            raise ValueError("Each quiz question must include questionText or prompt.")
        if question_type in {"meaning_match", "multiple_choice", "better_sentence"} and len(options or []) < 2:
            raise ValueError(f"{question_type} questions must include at least two options.")
        if question_type == "sentence_builder" and not word_bank:
            raise ValueError("sentence_builder questions must include a wordBank.")

        key = (
            question_type,
            normalize_answer(question_text or prompt),
            normalize_answer(correct_answer),
        )
        if key in seen:
            continue
        seen.add(key)
        questions.append(
            {
                "type": question_type,
                "languageAssetValues": language_asset_values,
                "questionText": question_text,
                "prompt": prompt or None,
                "correctAnswer": correct_answer,
                "options": options,
                "wordBank": word_bank,
                "explanation": explanation,
                "difficultyLevel": difficulty_level,
            }
        )

    if not questions:
        raise ValueError("Quiz generation payload did not include any valid questions.")
    return {"quizQuestions": questions}


def _build_quiz_generation_repair_prompt(
    *,
    original_prompt: str,
    invalid_output: str,
    error_message: str,
) -> str:
    return (
        "Repair the quiz generation output so it is valid strict JSON only.\n"
        "No markdown.\n"
        "No comments.\n"
        "No text outside JSON.\n"
        "Return exactly this top-level shape: {\"quizQuestions\": [...]}.\n"
        "Every question must use one allowed type, include languageAssetValues, questionText or prompt, correctAnswer, explanation, and difficultyLevel 1-3.\n"
        "Use only the original session content and language assets.\n\n"
        f"Validation error:\n{error_message}\n\n"
        f"Original instructions:\n{original_prompt[:6000]}\n\n"
        f"Invalid output:\n{invalid_output[:6000]}"
    )


def _clean_quiz_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def _clean_quiz_string_list(value: Any) -> list[str]:
    values = value if isinstance(value, list) else []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _clean_quiz_text(item)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            cleaned.append(text)
    return cleaned


def _clean_quiz_nullable_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    cleaned = _clean_quiz_string_list(value)
    return cleaned or None


class AIAnalyzer:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    async def analyze_image(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        filename: str,
        image_path: Path | None = None,
        difficulty_band: str,
        notes: str,
    ) -> dict[str, Any]:
        if self.config.ai_backend == "openai" and self.config.openai_api_key:
            return await self._openai_response(
                image_bytes=image_bytes,
                mime_type=mime_type,
                difficulty_band=difficulty_band,
                notes=notes,
            )
        if self.config.demo_mode or not self.config.openai_api_key:
            return self._demo_response(filename=filename, difficulty_band=difficulty_band, notes=notes)
        raise ValueError(f"Unsupported AI backend: {self.config.ai_backend}")

    async def close(self) -> None:
        return None

    def _analysis_max_new_tokens(self) -> int:
        return min(max(self.config.inference_max_new_tokens, 500), 900)

    def _repair_max_new_tokens(self) -> int:
        return min(max(self.config.inference_max_new_tokens, 240), 520)

    async def _openai_response(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        difficulty_band: str,
        notes: str,
    ) -> dict[str, Any]:
        prompt = self._build_prompt(difficulty_band=difficulty_band, notes=notes)
        image_data = base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "model": self.config.openai_model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_image",
                            "image_url": f"data:{mime_type};base64,{image_data}",
                            "detail": "high",
                        },
                    ],
                }
            ],
            "max_output_tokens": 3600,
        }

        headers = {
            "Authorization": f"Bearer {self.config.openai_api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.config.openai_base_url}/responses",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()

        data = response.json()
        output_text = self._extract_output_text(data)
        analysis = self._parse_analysis_output(output_text)
        normalized = self._normalize_scene_guidance(analysis)
        normalized["source_mode"] = "openai"
        return normalized

    def _extract_output_text(self, payload: dict[str, Any]) -> str:
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        parts: list[str] = []
        for item in payload.get("output", []):
            for content in item.get("content", []):
                if isinstance(content, dict) and content.get("text"):
                    parts.append(str(content["text"]))
        if parts:
            return "\n".join(parts)
        raise ValueError("The AI response did not include any text output.")

    def _short_text(self, value: Any, *, limit: int) -> str:
        text = re.sub(r"\s+", " ", str(value or "").strip())
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 3)].rstrip() + "..."

    def _parse_analysis_output(self, output_text: str) -> dict[str, Any]:
        try:
            return extract_json_payload(output_text)
        except Exception:
            salvaged = self._salvage_analysis_from_output(output_text)
            if salvaged:
                return salvaged
            raise

    def _build_prompt(self, *, difficulty_band: str, notes: str) -> str:
        return self._build_guided_coverage_analysis_prompt(difficulty_band=difficulty_band, notes=notes)

    def _build_guided_coverage_analysis_prompt(self, *, difficulty_band: str, notes: str) -> str:
        print('_build_guided_coverage_analysis_prompt')
        learner_level = canonical_level(difficulty_band)

        notes_block = (
            f"Learner note from the user: {notes.strip()}"
            if notes.strip()
            else "Learner note from the user: none."
        )

        return (
            "You are the Scene Guidance Engine for an articulation-coaching app.\n"
            "The learner, not the AI, writes the image description.\n"
            "Your role is to help the learner build reusable English from real images.\n"
            "Do not fully explain the image.\n"
            "Do not generate a lesson.\n"
            "Do not write a final paragraph.\n"
            "Keep guidance lightweight, incremental, and learner-centered.\n"
            "Return ONLY valid JSON.\n"
            "No markdown.\n"
            "No text outside JSON.\n\n"

            "Return exactly this JSON structure:\n"
            "{\n"
            '  "starterHints": [{"label":"","type":"object|phrase|sentence_structure"}],\n'
            '  "sentenceStarters": ["The image shows...", "In this scene...", "Here we can see..."],\n'
            '  "coverageFocuses": [\n'
            "    {\n"
            '      "id":"",\n'
            '      "title":"",\n'
            '      "mode":"add_missing_detail|polish_existing_detail",\n'
            '      "alreadyMentioned":false,\n'
            '      "sourceText":"",\n'
            '      "reusableLanguageGoal":[""],\n'
            '      "importance":0.8,\n'
            '      "supportLevels":[\n'
            '        {"level":1,"prompt":"","hints":[""]},\n'
            '        {"level":2,"prompt":"","hints":[""]},\n'
            '        {"level":3,"prompt":"","hints":[""]}\n'
            "      ]\n"
            "    }\n"
            "  ]\n"
            "}\n\n"

            "GENERAL RULES:\n"
            "- Keep all outputs short, practical, natural, and beginner-friendly.\n"
            "- The primary goal is to teach reusable language: useful nouns, verbs, adjectives, phrases, collocations, and sentence structures.\n"
            "- Every focus should help the learner learn language they can reuse in future images.\n"
            "- The learner should remain the main describer of the image.\n"
            "- Avoid scene summaries.\n"
            "- Avoid overexplaining.\n"
            "- Avoid decomposing the entire image too early.\n\n"

            "STARTER HINT RULES:\n"
            "- starterHints must contain exactly 1 tiny visually obvious hint.\n"
            "- Prefer one high-value reusable phrase or main visual subject.\n"
            "- Good starter hint styles:\n"
            "  - digital stopwatch\n"
            "  - climbing vines\n"
            "  - covered with\n"
            "  - bright daylight\n\n"

            "SENTENCE STARTER RULES:\n"
            "- sentenceStarters must stay generic.\n"
            "- Do not mention image-specific objects.\n"
            "- Keep them reusable across many images.\n\n"

            "TWO-PATH GUIDED COVERAGE RULE:\n"
            "- If the learner missed an important visual aspect, create mode add_missing_detail.\n"
            "- If the learner already mentioned an aspect but wrote it simply, create mode polish_existing_detail.\n"
            "- Do not force missing coverage if the learner already covered most important parts.\n"
            "- If coverage is already good, use polish_existing_detail focuses to help them make existing ideas more articulate.\n\n"

            "MODE: add_missing_detail\n"
            "- Use this when the learner did not mention an important visible aspect.\n"
            "- The prompt should help the learner add one missing visual detail.\n"
            "- Example: user mentioned building but missed greenery.\n"
            "- Focus: Greenery around the building.\n"
            "- reusableLanguageGoal: ['surrounded by', 'climbing vines', 'green shrubs']\n\n"

            "MODE: polish_existing_detail\n"
            "- Use this when the learner already mentioned the aspect but it can be expressed better.\n"
            "- The prompt should help the learner add richer wording to an existing idea.\n"
            "- sourceText must contain the learner's exact/simple wording if available.\n"
            "- Example: user wrote 'building with vines'.\n"
            "- Focus: Improve the vine description.\n"
            "- reusableLanguageGoal: ['covered with', 'dense climbing vines', 'attached to']\n\n"

            "COVERAGE FOCUS RULES:\n"
            "- coverageFocuses must contain 3-5 important focuses.\n"
            "- Each focus must teach reusable language, not just make the user mention objects.\n"
            "- Every focus must describe a different visual/language aspect.\n"
            "- Avoid duplicate focuses.\n"
            "- Keep focuses beginner-friendly, visually important, and conversational.\n"
            "- Never use generic wording like object, thing, or main object if the visible subject can be named.\n\n"

            "SUPPORT LEVEL RULES:\n"
            "- Each coverage focus must contain exactly 3 supportLevels.\n"
            "- Each supportLevels item must contain only level, prompt, and hints.\n"
            "- Level 1: open observation.\n"
            "- Level 2: more focused guidance.\n"
            "- Level 3: sentence frame with ___.\n"
            "- Hints are hidden until the learner asks for help.\n"
            "- Hints must be generated separately for each support level.\n"
            "- Hints should become easier as levels increase.\n"
            "- Level 3 hints must fit naturally into the sentence-frame blank.\n\n"

            "ADD_MISSING_DETAIL EXAMPLE:\n"
            "{\n"
            '  "id":"building_greenery",\n'
            '  "title":"Greenery around the building",\n'
            '  "mode":"add_missing_detail",\n'
            '  "alreadyMentioned":false,\n'
            '  "sourceText":"",\n'
            '  "reusableLanguageGoal":["surrounded by","climbing vines","green shrubs"],\n'
            '  "importance":0.9,\n'
            '  "supportLevels":[\n'
            '    {"level":1,"prompt":"What do you notice about the greenery around the building?","hints":["greenery","plants"]},\n'
            '    {"level":2,"prompt":"Can you describe the vines or plants near the building?","hints":["climbing vines","green shrubs"]},\n'
            '    {"level":3,"prompt":"The building is surrounded by ___.","hints":["green shrubs","climbing vines","dense greenery"]}\n'
            "  ]\n"
            "}\n\n"

            "POLISH_EXISTING_DETAIL EXAMPLE:\n"
            "{\n"
            '  "id":"polish_vines",\n'
            '  "title":"Make the vine description richer",\n'
            '  "mode":"polish_existing_detail",\n'
            '  "alreadyMentioned":true,\n'
            '  "sourceText":"building with vines",\n'
            '  "reusableLanguageGoal":["covered with","dense climbing vines","attached to the wall"],\n'
            '  "importance":0.9,\n'
            '  "supportLevels":[\n'
            '    {"level":1,"prompt":"How can you describe the vines more clearly?","hints":["vines","wall plants"]},\n'
            '    {"level":2,"prompt":"Can you describe how the vines cover the building?","hints":["covered with","climbing vines"]},\n'
            '    {"level":3,"prompt":"The building is covered with ___.","hints":["dense climbing vines","green leaves","wall plants"]}\n'
            "  ]\n"
            "}\n\n"

            "REUSABLE LANGUAGE QUALITY RULES:\n"
            "- Prefer high-value chunks like covered with, surrounded by, attached to, standing near, in the background, filled with, lined with.\n"
            "- Prefer useful descriptive nouns and phrases like climbing vines, concrete columns, bright daylight, calm atmosphere, green shrubs.\n"
            "- Do not teach only basic object names if a better reusable phrase is visible.\n"
            "- Do not create abstract or advanced phrases that beginners cannot reuse.\n\n"

            "OUTPUT VALIDATION:\n"
            "- Do not include supportLevels beyond levels 1, 2, and 3.\n"
            "- Level 3 prompt must contain ___.\n"
            "- Level 3 hints must fit the blank.\n"
            "- Do not put hints directly on the coverage focus.\n"
            "- Do not include technical labels or UI instructions in prompts.\n"
            "- Prompts must sound human, focused, and learner-friendly.\n"
            "- Every focus must have a clear reusableLanguageGoal.\n\n"

            f"{notes_block}"
        )

    async def feedback_on_explanation(
        self,
        *,
        learner_text: str,
        original_text: str,
        analysis: dict[str, Any],
        learner_level: str,
        attempt_index: int = 1,
    ) -> dict[str, Any]:
        fallback = self._heuristic_explanation_feedback(
            learner_text=learner_text,
            original_text=original_text,
            analysis=analysis,
        )
        prompt = self._build_articulation_enhancement_prompt(
            learner_text=learner_text,
            original_text=original_text,
            analysis=analysis,
            learner_level=learner_level,
            attempt_index=attempt_index,
        )
        try:
            output_text = await self._request_text_generation(
                prompt=prompt,
                max_output_tokens=1600,
                temperature=0.2,
            )
            try:
                payload = extract_json_payload(output_text)
            except Exception:
                raise
            normalized = self._normalize_explanation_feedback(payload, fallback=fallback)
            self._attach_initial_attempt_feedback(
                normalized,
                payload=payload,
                learner_text=learner_text,
                analysis=analysis,
                attempt_index=attempt_index,
            )
            return self._apply_progressive_coaching(
                normalized,
                analysis=analysis,
                learner_text=learner_text,
                original_text=original_text,
                attempt_index=attempt_index,
            )
        except Exception as exc:
            print(f"[feedback-fallback] {type(exc).__name__}: {exc}")
            self._attach_initial_attempt_feedback(
                fallback,
                payload={},
                learner_text=learner_text,
                analysis=analysis,
                attempt_index=attempt_index,
            )
            return self._apply_progressive_coaching(
                fallback,
                analysis=analysis,
                learner_text=learner_text,
                original_text=original_text,
                attempt_index=attempt_index,
            )

    async def generate_session_quiz_questions(
        self,
        *,
        session_input: dict[str, Any],
        language_assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        prompt = buildSessionQuizGenerationPrompt(session_input, language_assets)
        try:
            output_text = await self._request_text_generation(
                prompt=prompt,
                max_output_tokens=3600,
                temperature=0.2,
            )
            try:
                payload = extract_json_payload(output_text)
                return _validate_session_quiz_generation_payload(payload)
            except Exception as first_exc:
                repair_prompt = _build_quiz_generation_repair_prompt(
                    original_prompt=prompt,
                    invalid_output=output_text,
                    error_message=str(first_exc),
                )
                repaired_text = await self._request_text_generation(
                    prompt=repair_prompt,
                    max_output_tokens=3600,
                    temperature=0.0,
                )
                repaired_payload = extract_json_payload(repaired_text)
                return _validate_session_quiz_generation_payload(repaired_payload)
        except Exception as exc:
            print(f"[quiz-generation-fallback] {type(exc).__name__}: {exc}")
            return {"quizQuestions": []}

    def _build_articulation_enhancement_prompt(
        self,
        *,
        learner_text: str,
        original_text: str,
        analysis: dict[str, Any],
        learner_level: str,
        attempt_index: int,
    ) -> str:
        print('_build_articulation_enhancement_prompt taking feedback and enhancing')
        scene_guidance = {
            "starterHints": analysis.get("starterHints") or [],
            "sentenceStarters": analysis.get("sentenceStarters") or [],
            "coverageFocuses": analysis.get("coverageFocuses") or [],
        }

        mode = (
            "initial enhancement"
            if attempt_index <= 1
            else "guided coverage enhancement"
        )

        return (
            "You are the Articulation Enhancement Engine for an image-description app.\n"
            "The learner, not the AI, writes the image description.\n"
            "Your job is to improve the learner's own sentences and guide the next missing coverage focus.\n\n"

            f"Learner level: {level_label(canonical_level(learner_level))}.\n"
            f"Mode: {mode}.\n\n"

            "CORE BEHAVIOR:\n"
            "- Do not generate a full paragraph from scratch.\n"
            "- Do not replace the learner's idea with your own.\n"
            "- Do not introduce major new visual details the learner did not mention.\n"
            "- Improve the learner's existing expression.\n"
            "- Keep improvements incremental, natural, and beginner-friendly.\n"
            "- Guided coverage should introduce missing image areas gradually later.\n\n"

            "CORE ENHANCEMENT PHILOSOPHY:\n"
            "- Assume beginner learners almost always have room for articulation improvement.\n"
            "- Unless the learner sentence is already highly natural, visually specific, fluent, reusable, and articulate, generate at least one meaningful upgrade.\n"
            "- Prefer noticeable articulation improvement over conservative minimal edits.\n"
            "- The learner should clearly feel that their sentence became richer and more expressive.\n"
            "- Improvements should feel rewarding and visible to a human learner.\n\n"

            "YOUR ENHANCEMENT GOALS:\n"
            "- improve articulation\n"
            "- improve grammar\n"
            "- improve sentence fluency\n"
            "- improve natural phrasing\n"
            "- improve descriptive wording\n"
            "- improve visual specificity\n"
            "- improve reusable language\n"
            "- improve object clarity\n"
            "- improve observable detail expression\n"
            "- improve concise elaboration\n"
            "- improve positioning language\n"
            "- improve stronger visual phrasing\n"
            "- improve beginner-friendly natural expression\n\n"

            "ENHANCEMENT EVALUATION PROCESS:\n"
            "- Before generating upgrades, internally evaluate whether the learner sentence can become more natural, specific, visually descriptive, or reusable.\n"
            "- Prefer observable visual specificity over cosmetic rewrites.\n"
            "- Prefer stronger articulation over longer sentences.\n"
            "- Prefer reusable descriptive phrasing whenever possible.\n"
            "- Prefer upgrades that sound more human and expressive.\n"
            "- Prefer upgrades that introduce stronger observable image details already implied by the learner sentence.\n"
            "- Grammar correction alone is usually NOT enough.\n"
            "- Small article fixes or tiny wording swaps are usually NOT meaningful upgrades.\n\n"

            "WHEN EVALUATING POSSIBLE UPGRADES, CONSIDER IMPROVING:\n"
            "- visual specificity\n"
            "- descriptive richness\n"
            "- object detail\n"
            "- reusable language chunks\n"
            "- natural spoken English\n"
            "- articulation quality\n"
            "- sentence fluency\n"
            "- positioning language\n"
            "- observable object properties\n"
            "- concise elaboration\n"
            "- stronger verbs\n"
            "- stronger adjectives\n"
            "- stronger visual phrasing\n\n"

            "STRONG ARTICULATION UPGRADES OFTEN INTRODUCE:\n"
            "- observable visual details\n"
            "- visible object properties\n"
            "- positioning language\n"
            "- reusable descriptive phrases\n"
            "- stronger observable verbs\n"
            "- texture\n"
            "- shape\n"
            "- color\n"
            "- structure\n"
            "- framing language\n"
            "- practical natural English phrasing\n\n"

            "PREFER REUSABLE ARTICULATION PATTERNS SUCH AS:\n"
            "- covered with\n"
            "- surrounded by\n"
            "- attached to\n"
            "- standing near\n"
            "- firmly holding\n"
            "- brightly lit\n"
            "- visible in the background\n"
            "- gathered together\n"
            "- close-up view\n\n"

            "PREFER OBSERVABLE UPGRADES SUCH AS:\n"
            "- climbing vines\n"
            "- dense greenery\n"
            "- tall concrete columns\n"
            "- compact digital stopwatch\n"
            "- visible control buttons\n"
            "- rectangular display screen\n"
            "- attached wrist strap\n"
            "- bright daylight\n"
            "- group of people standing together\n\n"

            "AVOID WEAK FILLER REWRITES SUCH AS:\n"
            "- clear view\n"
            "- nice object\n"
            "- beautiful image\n"
            "- interesting object\n"
            "- good device\n\n"

            "A MEANINGFUL UPGRADE SHOULD FEEL:\n"
            "- more visual\n"
            "- more expressive\n"
            "- more natural\n"
            "- more descriptive\n"
            "- more reusable\n"
            "- more articulate\n\n"

            "A REWRITE IS WEAK IF IT ONLY:\n"
            "- adds articles like 'a' or 'the'\n"
            "- slightly rearranges wording\n"
            "- adds weak adjectives\n"
            "- increases sentence length without adding observable value\n"
            "- performs grammar correction only\n"
            "- replaces words with near-identical wording\n\n"

            "GOOD ENHANCEMENT BEHAVIOR:\n"
            "- The image shows vines.\n"
            "→ The image shows dense climbing vines attached to the building.\n\n"

            "- The image shows a building.\n"
            "→ The image shows a tall modern building.\n\n"

            "- The image shows a building with vines.\n"
            "→ The image shows a modern building covered with climbing vines.\n\n"

            "- The image shows stopwatch.\n"
            "→ The image shows a compact digital stopwatch.\n\n"

            "- The image shows a digital stopwatch.\n"
            "→ The image shows a compact digital stopwatch with visible buttons.\n\n"

            "- hand holding a stopwatch\n"
            "→ a hand firmly holding a digital stopwatch\n\n"

            "- holding a stopwatch\n"
            "→ firmly holding a stopwatch\n\n"

            "- The scene create a calm feeling.\n"
            "→ The scene creates a calm and peaceful atmosphere.\n\n"

            "BAD ENHANCEMENT BEHAVIOR:\n"
            "- The image shows a digital stopwatch.\n"
            "→ The image shows a clear view of a digital stopwatch.\n\n"

            "- The image shows stopwatch.\n"
            "→ The image shows a stopwatch.\n\n"

            "- The image shows a building.\n"
            "→ The image shows a nice building.\n\n"

            "ENHANCEMENT SCOPE RESTRICTION:\n"
            "- Stay strictly inside what the learner already described.\n"
            "- Do not introduce unrelated scene details.\n"
            "- Do not prematurely expand into untouched image areas.\n"
            "- Guided coverage will handle missing scene parts later.\n\n"

            "EMPTY UPGRADE RULE:\n"
            "- Return empty upgrades ONLY if the learner sentence is already highly natural, specific, fluent, visually descriptive, and articulate.\n"
            "- Beginner learner descriptions will usually benefit from at least one articulation improvement.\n"
            "- Do not return empty upgrades just because the sentence is understandable.\n"
            "- Understandable is not the same as articulate.\n\n"

            "GUIDED COVERAGE RULE:\n"
            "- Use coverageFocuses only to decide the next small area to ask the learner to add.\n"
            "- Coverage status and guided practice progress are separate.\n"
            "- Do not end guided coverage just because the learner already mentioned important visual aspects.\n"
            "- If the learner already mentioned an important coverage focus, treat it as polish_existing_detail practice.\n"
            "- If the learner did not mention an important coverage focus, treat it as add_missing_detail practice.\n"
            "- Finish guided coverage only after important aspects are covered or practiced and the planned focus path is complete.\n"
            "- If this is the first attempt, enhance only covered ideas and put missing areas in missingDetails/nextStepInstructions.\n"
            "- If this is a later attempt, enhance the evolving description and guide the next missing focus.\n\n"

            "FOR LATER ATTEMPTS:\n"
            "- Evaluate coverage only from the Current learner explanation.\n"
            "- Use the First learner explanation only as before/after context.\n"
            "- Do not mark an area missing if the Current learner explanation already covers it.\n\n"

            "INVALID ANSWERS ARE:\n"
            "- random text\n"
            "- keyword stuffing\n"
            "- disconnected fragments\n"
            "- unrelated responses\n"
            "- off-task answers\n\n"

            "Return valid JSON only with this exact structured shape:\n"
            "{\n"
            '  "score": 0,\n'
            '  "scores": {"vocabulary": 0, "structure": 0, "depth": 0, "clarity": 0},\n'
            '  "languageQuality": {"score": 0, "clarity": 0, "vocabulary": 0, "structure": 0, "grammar": 0, "naturalness": 0, "reusableLanguage": 0},\n'
            '  "answerValidation": {"valid": true, "reason": "", "retryMessage": ""},\n'
            '  "coverage": {\n'
            '    "mainSubjectMentioned": false,\n'
            '    "mainActionMentioned": false,\n'
            '    "imageParts": [{"name": "", "description": "", "type": "main_subject", "required": true, "weight": 0, "coverageStatus": "missing", "covered": false, "evidence": ""}],\n'
            '    "missingMajorParts": [],\n'
            '    "coverageScore": 0,\n'
            '    "coveragePercent": 0,\n'
            '    "accuracyPenalty": 0,\n'
            '    "scoreCapApplied": 0\n'
            "  },\n"
            '  "readiness": {"ready": false, "reason": "", "criteria": {"mainSubject": false, "mainAction": false, "settingBackground": false, "twoImportantDetails": false, "naturalEnglish": false, "notAWordList": false, "overallSense": false}},\n'
            '  "mainIssue": "",\n'
            '  "whatWentWell": ["", ""],\n'
            '  "fixes": ["", "", ""],\n'
            '  "nextStepInstructions": ["", ""],\n'
            '  "reusableLanguage": {"usedWell": [""], "tryNext": [""], "misused": [{"phrase": "", "note": ""}], "message": ""},\n'
            '  "missingDetails": ["", "", ""],\n'
            '  "inlineImprovements": [{"targetText": "", "replacementText": "", "why": "", "example": ""}],\n'
            '  "initialAttemptFeedback": {\n'
            '    "acknowledgement": "",\n'
            '    "coveredEnhancement": "",\n'
            '    "enhancement": {"upgrades": [{"id": "u1", "targetText": "", "replacementText": "", "reason": "", "example": "", "category": "natural_phrasing"}]},\n'
            '    "message": "",\n'
            '    "reusableLanguageFromEnhancement": {"nouns": [""], "verbs": [""], "phrases": [""], "collocations": [""], "sentenceStructures": [""], "positioningLanguage": [""], "atmosphereLanguage": [""]}\n'
            "  },\n"
            '  "improvedVersion": ""\n'
            "}\n\n"

            "OUTPUT RULES:\n"
            "- improvedVersion must remain the learner's own description made clearer, more articulate, and more natural.\n"
            "- Create 1-4 atomic upgrades.\n"
            "- targetText must exactly exist in the learner answer.\n"
            "- replacementText must be a short replacement phrase, not a full paragraph.\n"
            "- Keep feedback concise and action-oriented.\n"
            "- Use beginner-friendly natural English.\n"
            "- Avoid literary, poetic, or academic rewrites.\n"
            "- missingDetails should come only from uncovered coverageFocuses.\n"
            "- nextStepInstructions should contain only the next one or two useful guidance steps.\n"
            "- Mark readiness.ready true only when most important coverageFocuses are covered and the description is understandable.\n"
            "- initialAttemptFeedback.enhancement.upgrades should usually contain at least one upgrade unless the learner answer is already very articulate.\n"
            "- inlineImprovements should mirror the same upgrade opportunities when possible.\n\n"

            f"Scene guidance JSON:\n"
            f"{json.dumps(scene_guidance, ensure_ascii=True)}\n\n"

            f"First learner explanation, if any:\n"
            f"{self._short_text(original_text, limit=360)}\n\n"

            f"Current learner explanation:\n"
            f"{self._short_text(learner_text, limit=520)}"
        )

    def _normalize_explanation_feedback(
        self,
        payload: dict[str, Any],
        *,
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return fallback

        scores_payload = payload.get("scores") if isinstance(payload.get("scores"), dict) else {}
        scores = {}
        for key in ("vocabulary", "structure", "depth", "clarity"):
            try:
                value = int(scores_payload.get(key, fallback["scores"][key]))
            except (TypeError, ValueError):
                value = fallback["scores"][key]
            scores[key] = max(1, min(10, value))

        reusable_payload = payload.get("reusableLanguage")
        if reusable_payload is None:
            reusable_payload = payload.get("phrase_usage")
        language_quality = self._normalize_language_quality(payload.get("languageQuality"))
        validation_payload = (
            payload.get("answerValidation")
            if isinstance(payload.get("answerValidation"), dict)
            else {}
        )
        fallback_coverage = (
            fallback.get("coverage") if isinstance(fallback.get("coverage"), dict) else {}
        )
        ai_coverage_payload = (
            payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
        )
        has_ai_coverage = bool(ai_coverage_payload.get("imageParts"))
        use_fallback_coverage = not has_ai_coverage and bool(fallback_coverage.get("imageParts"))
        validation_valid = validation_payload.get("valid")
        if (
            validation_valid is False
            or str(validation_valid).strip().casefold() == "false"
        ) and not has_ai_coverage:
            retry_feedback = self._retry_feedback(
                score=self._normalize_retry_score(payload.get("score")),
                main_issue=self._clean_text_value(
                    validation_payload.get("reason")
                    or payload.get("mainIssue")
                    or payload.get("main_issue")
                )
                or "Your answer does not clearly describe the image yet.",
                fixes=self._clean_string_list(
                    payload.get("fixes") or payload.get("fix_this_to_improve"),
                    limit=3,
                )
                or [
                    "Mention the main subject.",
                    "Describe the setting.",
                    "Add 1-2 visible details.",
                ],
            )
            retry_message = self._clean_text_value(validation_payload.get("retryMessage"))
            if retry_message:
                retry_feedback["retry_message"] = retry_message
            return retry_feedback
        coverage = (
            self._normalize_coverage(fallback_coverage)
            if use_fallback_coverage
            else self._normalize_coverage(ai_coverage_payload)
        )
        score = (
            self._normalize_feedback_score(fallback.get("score"), fallback=fallback)
            if use_fallback_coverage
            else self._normalize_feedback_score(payload.get("score"), fallback=fallback)
        )
        if use_fallback_coverage and isinstance(fallback.get("scores"), dict):
            scores = {
                key: max(1, min(10, int(fallback["scores"].get(key, scores[key]))))
                for key in ("vocabulary", "structure", "depth", "clarity")
            }
        if use_fallback_coverage and isinstance(fallback.get("language_quality"), dict):
            language_quality = self._normalize_language_quality(fallback.get("language_quality"))
        score_cap = self._normalized_coverage_hard_cap(coverage)
        coverage["scoreCapApplied"] = score_cap
        if isinstance(score_cap, int) and score_cap > 0:
            score = min(score, score_cap)
        readiness = self._normalize_feedback_readiness(
            payload.get("readiness"),
            coverage=coverage,
            score=score,
            fallback=fallback.get("readiness") if isinstance(fallback.get("readiness"), dict) else {},
        )
        fresh_missing_details = (
            self._clean_string_list(coverage.get("missingMajorParts"), limit=3)
            if has_ai_coverage or use_fallback_coverage
            else []
        )
        if has_ai_coverage or use_fallback_coverage:
            missing_details_source = fresh_missing_details or [
                "No major visual detail is missing; focus on making the wording stronger."
            ]
        else:
            missing_details_source = (
                payload.get("missingDetails")
                or payload.get("missing_details")
                or fallback["missing_details"]
            )

        normalized = {
            "score": score,
            "scores": scores,
            "language_quality": language_quality,
            "coverage": coverage,
            "readiness": readiness,
            "is_ready": bool(readiness.get("ready")),
            "main_issue": (
                self._clean_text_value(fallback.get("main_issue"))
                if use_fallback_coverage
                else self._clean_text_value(payload.get("mainIssue") or payload.get("main_issue"))
            )
            or self._clean_text_value(fallback["main_issue"])
            or "Focus on one clearer detail and stronger wording.",
            "what_did_well": self._clean_string_list(
                payload.get("whatWentWell") or payload.get("what_did_well") or fallback["what_did_well"],
                limit=2,
            )
            or fallback["what_did_well"],
            "missing_details": self._clean_string_list(
                missing_details_source,
                limit=3,
            ),
            "phrase_usage": self._normalize_phrase_usage(
                reusable_payload,
                fallback=fallback["phrase_usage"],
            ),
            "fix_this_to_improve": self._clean_string_list(
                payload.get("fixes") or payload.get("fix_this_to_improve") or fallback["fix_this_to_improve"],
                limit=3,
            )
            or fallback["fix_this_to_improve"],
            "next_step_instructions": self._clean_string_list(
                payload.get("nextStepInstructions")
                or payload.get("next_step_instructions")
                or fallback.get("next_step_instructions"),
                limit=2,
            ),
            "word_phrase_upgrades": self._normalize_feedback_alternatives(
                payload.get("inlineImprovements")
                or payload.get("word_phrase_upgrades")
                or fallback["word_phrase_upgrades"],
                fallback=fallback["word_phrase_upgrades"],
            ),
            "improvements": self._clean_string_list(
                payload.get("improvements") or fallback["improvements"],
                limit=5,
            )
            or fallback["improvements"],
            "better_version": self._normalize_better_version(
                payload.get("improvedVersion") or payload.get("better_version"),
                fallback=fallback["better_version"],
            ),
            "alternatives": self._normalize_feedback_alternatives(
                payload.get("alternatives") or fallback["alternatives"],
                fallback=fallback["alternatives"],
            ),
            "weak_points": self._clean_string_list(
                payload.get("weak_points") or fallback["weak_points"],
                limit=4,
            )
            or fallback["weak_points"],
            "reusable_sentence_structures": self._clean_string_list(
                payload.get("reusable_sentence_structures")
                or fallback["reusable_sentence_structures"],
                limit=5,
            )
            or fallback["reusable_sentence_structures"],
        }
        if not normalized["next_step_instructions"]:
            normalized["next_step_instructions"] = self._build_next_step_instructions(
                feedback=normalized,
                analysis={},
            )
        self._dedupe_feedback_sections(normalized)
        return normalized

    def _attach_initial_attempt_feedback(
        self,
        feedback: dict[str, Any],
        *,
        payload: dict[str, Any],
        learner_text: str,
        analysis: dict[str, Any],
        attempt_index: int = 1,
    ) -> None:
        payload = payload if isinstance(payload, dict) else {}
        initial_payload = (
            payload.get("initialAttemptFeedback")
            if isinstance(payload.get("initialAttemptFeedback"), dict)
            else {}
        )
        covered_areas = self._covered_area_labels(feedback)
        missing_areas = self._missing_area_labels(feedback)
        acknowledgement = self._clean_text_value(initial_payload.get("acknowledgement"))
        if not acknowledgement:
            acknowledgement = self._initial_acknowledgement(covered_areas, learner_text)

        covered_enhancement = self._clean_text_value(initial_payload.get("coveredEnhancement"))
        enhancement_payload = self._initial_enhancement_payload(payload, initial_payload)
        improved_preview = self._clean_text_value(
            enhancement_payload.get("improvedPreview") or enhancement_payload.get("improved_preview")
        )
        if not covered_enhancement and improved_preview:
            covered_enhancement = improved_preview
        if not covered_enhancement:
            covered_enhancement = self._covered_only_enhancement(
                learner_text=learner_text,
                covered_areas=covered_areas,
            )
        if self._enhancement_mentions_missing_area(covered_enhancement, missing_areas):
            covered_enhancement = self._covered_only_enhancement(
                learner_text=learner_text,
                covered_areas=covered_areas,
            )
            improved_preview = covered_enhancement

        reusable_payload = (
            initial_payload.get("reusableLanguageFromEnhancement")
            if isinstance(initial_payload.get("reusableLanguageFromEnhancement"), dict)
            else {}
        )
        reusable_language = self._normalize_initial_reusable_language(
            reusable_payload,
            enhancement=covered_enhancement,
            analysis=analysis,
            covered_areas=covered_areas,
        )
        raw_improvements = (
            enhancement_payload.get("upgrades")
            or enhancement_payload.get("improvements")
            or initial_payload.get("upgrades")
            or initial_payload.get("improvements")
            or initial_payload.get("improvementCards")
            or []
        )
        improvements = self._normalize_initial_improvement_cards(
            raw_improvements,
            learner_text=learner_text,
        )
        if missing_areas:
            improvements = [
                card
                for card in improvements
                if not self._enhancement_mentions_missing_area(
                    " ".join(
                        [
                            self._clean_text_value(card.get("suggestedText")),
                            self._clean_text_value(card.get("finalPreview")),
                        ]
                    ),
                    missing_areas,
                )
            ]
        if not improvements:
            improvements = self._fallback_initial_improvement_cards(learner_text)
        improved_preview = self._clean_text_value(improved_preview or covered_enhancement)
        upgrades = self._initial_upgrades_payload(improvements)
        initial_feedback = {
            "acknowledgement": acknowledgement,
            "covered_enhancement": covered_enhancement,
            "has_improvements": bool(upgrades),
            "improved_preview": improved_preview,
            "upgrades": upgrades,
            "enhancement": {
                "hasImprovements": bool(upgrades),
                "improvedPreview": improved_preview,
                "upgrades": upgrades,
            },
            "improvements": improvements,
            "message": self._clean_text_value(initial_payload.get("message"))
            or "Let’s make this more expressive.",
            "reusable_language": reusable_language,
            "missing_visual_areas": missing_areas[:5],
            "prepares_coverage_layers": True,
        }
        feedback["initial_attempt_feedback"] = initial_feedback
        if attempt_index <= 1:
            feedback["better_version"] = covered_enhancement
            feedback["main_issue"] = (
                f"Next, add another visual area: {missing_areas[0]}."
                if missing_areas
                else "You covered the main visual areas; next you can make the wording more natural."
            )
            feedback["missing_details"] = missing_areas[:3]
            feedback["next_step_instructions"] = (
                [f"Add {missing_areas[0]} in the next layer."]
                if missing_areas
                else ["Move to a polish pass for clearer, more natural wording."]
            )
        else:
            feedback.setdefault("better_version", covered_enhancement)
            if missing_areas and not feedback.get("missing_details"):
                feedback["missing_details"] = missing_areas[:3]

    def _initial_enhancement_payload(
        self,
        payload: dict[str, Any],
        initial_payload: dict[str, Any],
    ) -> dict[str, Any]:
        for value in (
            initial_payload.get("enhancement"),
            initial_payload.get("aiEnhancement"),
            initial_payload.get("ai_enhancement"),
            payload.get("aiEnhancement"),
            payload.get("ai_enhancement"),
            payload.get("enhancement"),
        ):
            if isinstance(value, dict):
                return value
        return {}

    def _initial_upgrades_payload(self, improvements: list[dict[str, Any]]) -> list[dict[str, Any]]:
        upgrades: list[dict[str, Any]] = []
        for index, item in enumerate(improvements[:5]):
            target = self._clean_text_value(item.get("targetText") or item.get("currentText"))
            replacement = self._clean_text_value(item.get("replacementText") or item.get("suggestedText"))
            if not target or not replacement:
                continue
            upgrades.append(
                {
                    "id": self._clean_text_value(item.get("id")) or f"u{index + 1}",
                    "targetText": target,
                    "replacementText": replacement,
                    "reason": self._clean_text_value(item.get("reason") or item.get("whyItHelps")),
                    "example": self._clean_text_value(item.get("example")),
                    "finalPreview": self._clean_text_value(item.get("finalPreview")),
                    "category": self._clean_text_value(item.get("category")) or "natural_phrasing",
                }
            )
        return upgrades

    def _normalize_initial_improvement_cards(self, raw_items: Any, *, learner_text: str) -> list[dict[str, Any]]:
        items = raw_items if isinstance(raw_items, list) else []
        cards: list[dict[str, Any]] = []
        for index, item in enumerate(items[:5]):
            if not isinstance(item, dict):
                continue
            suggested = self._clean_text_value(
                item.get("suggestedText")
                or item.get("suggested_text")
                or item.get("replacementText")
                or item.get("replacement_text")
                or item.get("newText")
                or item.get("new")
                or item.get("suggested")
            )
            current = self._clean_text_value(
                item.get("currentText")
                or item.get("current_text")
                or item.get("targetText")
                or item.get("target_text")
                or item.get("oldText")
                or item.get("old")
            )
            current = self._find_initial_text_occurrence(learner_text, current)
            current_words = current.split()
            suggested_words = suggested.split()
            final_preview = self._replacement_preview(
                learner_text,
                current=current,
                suggested=suggested,
            )
            if (
                not suggested
                or not current
                or normalize_answer(suggested) == normalize_answer(current)
                or normalize_answer(current) == normalize_answer(learner_text)
                or len(current_words) > 10
                or len(suggested_words) > 16
                or len(current_words) > max(4, len(learner_text.split()) // 2)
                or not self._initial_preview_looks_safe(
                    final_preview,
                    original=learner_text,
                    current=current,
                    suggested=suggested,
                )
            ):
                continue
            category = self._normalize_initial_improvement_category(item.get("category"))
            try:
                xp_reward = int(item.get("xpReward") or item.get("xp_reward") or 10)
            except (TypeError, ValueError):
                xp_reward = 10
            why_it_helps = self._clean_text_value(item.get("whyItHelps") or item.get("why_it_helps") or item.get("why") or item.get("reason"))
            if not why_it_helps:
                why_it_helps = "This keeps your meaning but makes the sentence sound a little more natural."
            example = self._clean_text_value(item.get("example"))
            if not example:
                example = self._generic_improvement_example(current=current, suggested=suggested)
            cards.append(
                {
                    "id": self._clean_text_value(item.get("id")) or f"{category}-{index + 1}",
                    "category": category,
                    "title": self._clean_text_value(item.get("title")) or "Useful improvement",
                    "currentText": current,
                    "suggestedText": suggested,
                    "targetText": current,
                    "replacementText": suggested,
                    "whyItHelps": why_it_helps,
                    "reason": why_it_helps,
                    "example": example,
                    "finalPreview": final_preview,
                    "xpReward": 5,
                }
            )
        return cards

    def _find_initial_text_occurrence(self, source: str, target: str) -> str:
        source = self._clean_text_value(source)
        target = self._clean_text_value(target)
        if not source or not target:
            return ""
        if target in source:
            return target
        match = re.search(re.escape(target), source, flags=re.IGNORECASE)
        return match.group(0) if match else ""

    def _replacement_preview(self, source: str, *, current: str, suggested: str) -> str:
        source = self._clean_text_value(source)
        current = self._clean_text_value(current)
        suggested = self._clean_text_value(suggested)
        if not source or not current or not suggested:
            return ""
        match = re.search(re.escape(current), source, flags=re.IGNORECASE)
        if not match:
            return ""
        return self._clean_text_value(f"{source[:match.start()]}{suggested}{source[match.end():]}")

    def _initial_preview_looks_safe(
        self,
        preview: str,
        *,
        original: str,
        current: str,
        suggested: str,
    ) -> bool:
        preview = self._clean_text_value(preview)
        original = self._clean_text_value(original)
        current = self._clean_text_value(current)
        suggested = self._clean_text_value(suggested)
        if not preview or not original or not current or not suggested:
            return False
        if normalize_answer(preview) == normalize_answer(original):
            return False
        if normalize_answer(current) == normalize_answer(original):
            return False
        if re.search(r"\b([A-Za-z][A-Za-z'-]*)\s+\1\b", preview, flags=re.IGNORECASE):
            return False
        if re.search(r"\b(?:of|with|to|in|on|at|near|around|beside|behind|under)\s*[.!?]?$", preview, flags=re.IGNORECASE):
            return False
        if len(preview.split()) > max(28, len(original.split()) + 12):
            return False
        return True

    def _normalize_initial_improvement_category(self, category: Any) -> str:
        value = self._clean_text_value(category).casefold().replace("-", "_").replace(" ", "_")
        allowed = {"subject_clarity", "sentence_flow", "natural_phrasing", "grammar_fix", "visual_clarity"}
        category_map = {
            "grammar": "grammar_fix",
            "grammar_correction": "grammar_fix",
            "spelling": "grammar_fix",
            "spelling_correction": "grammar_fix",
            "article": "grammar_fix",
            "article_correction": "grammar_fix",
            "article_usage": "grammar_fix",
            "preposition": "grammar_fix",
            "preposition_correction": "grammar_fix",
            "preposition_usage": "grammar_fix",
            "sentence_restructuring": "sentence_flow",
            "cleaner_sentence_flow": "sentence_flow",
            "flow": "sentence_flow",
            "better_descriptive_wording": "visual_clarity",
            "stronger_visual_detail": "visual_clarity",
            "visual_detail": "visual_clarity",
            "better_atmosphere_wording": "visual_clarity",
            "atmosphere_phrasing": "visual_clarity",
            "better_positioning_language": "visual_clarity",
            "positioning_language": "visual_clarity",
            "more_reusable_phrase": "natural_phrasing",
            "reusable_phrase": "natural_phrasing",
            "natural_phrase": "natural_phrasing",
        }
        mapped = category_map.get(value, value)
        return mapped if mapped in allowed else "natural_phrasing"

    def _generic_improvement_example(self, *, current: str, suggested: str) -> str:
        suggested = self._clean_text_value(suggested)
        current = self._clean_text_value(current)
        if not suggested:
            suggested = current or "clear wording"
        lower = suggested.casefold()
        if lower.startswith(("shows", "includes", "features", "appears")):
            return f"The image {suggested} the main detail."
        if lower.startswith(("moving", "standing", "sitting", "walking", "looking")):
            return f"The subject is {suggested}."
        return f"Use '{suggested}' to make the sentence sound more natural."

    def _fallback_initial_improvement_cards(self, learner_text: str) -> list[dict[str, Any]]:
        text = self._clean_text_value(learner_text)
        if not text:
            return []

        def spelling_suggestion(match: re.Match[str]) -> str:
            value = match.group(0)
            plural = value.casefold().endswith("s")
            return "rickshaws" if plural else "rickshaw"

        def image_has_suggestion(match: re.Match[str]) -> str:
            phrase = match.group(0)
            subject = re.sub(r"\s+has$", "", phrase, flags=re.IGNORECASE)
            return f"{subject} includes"

        def image_includes_suggestion(match: re.Match[str]) -> str:
            return "The image includes" if match.group(0)[:1].isupper() else "the image includes"

        def image_show_agreement_suggestion(match: re.Match[str]) -> str:
            phrase = match.group(0)
            subject = re.sub(r"\s+show$", "", phrase, flags=re.IGNORECASE)
            return f"{subject} shows"

        def image_is_shows_suggestion(match: re.Match[str]) -> str:
            phrase = match.group(0)
            subject = re.sub(r"\s+is\s+shows$", "", phrase, flags=re.IGNORECASE)
            return f"{subject} shows"

        def vehicle_movement_suggestion(match: re.Match[str]) -> str:
            phrase = match.group(1)
            if not re.search(
                r"\b(?:car|cars|sedan|sedans|rickshaw|rickshaws|rikshaw|rikshaws|bus|buses|truck|trucks|van|vans|vehicle|vehicles|bike|bikes|motorcycle|motorcycles|bicycle|bicycles)\b",
                phrase,
                flags=re.IGNORECASE,
            ):
                return ""
            phrase = re.sub(r"\brikshaws\b", "rickshaws", phrase, flags=re.IGNORECASE)
            phrase = re.sub(r"\brikshaw\b", "rickshaw", phrase, flags=re.IGNORECASE)
            return f"{phrase} moving"

        candidates: list[dict[str, Any]] = []
        checks: list[tuple[str, str | Any, str, str, str, str]] = [
            (
                r"\battached with\b",
                "attached to",
                "grammar_fix",
                "Better preposition",
                "This uses the natural preposition for something connected to a surface.",
                "The vines are attached to the wall.",
            ),
            (
                r"\bscene create\b",
                "scene creates",
                "grammar_fix",
                "Correct verb form",
                "This fixes the verb so the sentence sounds natural.",
                "The scene creates a calm feeling.",
            ),
            (
                r"\bcalm feeling\b",
                "peaceful atmosphere",
                "visual_clarity",
                "Smoother feeling phrase",
                "This is a natural way to describe the mood of a scene.",
                "The greenery creates a peaceful atmosphere.",
            ),
            (
                r"\bbuilding with vines\b",
                "building covered with climbing vines",
                "visual_clarity",
                "More visual wording",
                "This describes the same building and vines more clearly.",
                "The image shows a building covered with climbing vines.",
            ),
            (
                r"\bcovered by vines\b",
                "covered with vines",
                "natural_phrasing",
                "More natural phrase",
                "This is the more common phrase for describing a surface.",
                "The wall is covered with vines.",
            ),
            (
                r"\bcovered with vines\b",
                "covered with climbing vines",
                "visual_clarity",
                "More specific wording",
                "This keeps your idea and names the type of vines more clearly.",
                "The building is covered with climbing vines.",
            ),
            (
                r"\bwith vines\b",
                "with climbing vines",
                "visual_clarity",
                "More specific wording",
                "This keeps the same detail but makes it a little more visual.",
                "The building is covered with climbing vines.",
            ),
            (
                r"\b(?:The|A|An) shows\b",
                "The image shows",
                "grammar_fix",
                "Clearer sentence structure",
                "This fixes the sentence structure while keeping your meaning simple.",
                "The image shows a baby.",
            ),
            (
                r"\b(?:the|a|an) shows\b",
                "the image shows",
                "grammar_fix",
                "Clearer sentence structure",
                "This fixes the sentence structure while keeping your meaning simple.",
                "The image shows a baby.",
            ),
            (
                r"\bThis shows\b",
                "This image shows",
                "grammar_fix",
                "Clearer sentence structure",
                "This makes the subject of the sentence clear.",
                "This image shows a baby.",
            ),
            (
                r"\bthis shows\b",
                "this image shows",
                "grammar_fix",
                "Clearer sentence structure",
                "This makes the subject of the sentence clear.",
                "This image shows a baby.",
            ),
            (
                r"\b(?:image|picture|photo|scene) show\b",
                image_show_agreement_suggestion,
                "grammar_fix",
                "Correct verb form",
                "This fixes the verb so the sentence sounds natural.",
                "The image shows a baby.",
            ),
            (
                r"\b(?:image|picture|photo|scene) is shows\b",
                image_is_shows_suggestion,
                "grammar_fix",
                "Cleaner sentence structure",
                "This removes the extra verb and makes the sentence clear.",
                "The image shows a baby.",
            ),
            (
                r"\b((?:a|an|the)\s+[\w'-]+(?:\s+[\w'-]+){0,2}\s+and\s+(?:(?:a|an|the)\s+)?[\w'-]+(?:\s+[\w'-]+){0,2})\s+driving\b",
                vehicle_movement_suggestion,
                "sentence_flow",
                "Smoother action phrase",
                "This improves the movement phrase while keeping the same vehicles and action.",
                "A car and rickshaw are moving along the road.",
            ),
            (
                r"\brikshaws?\b",
                spelling_suggestion,
                "grammar_fix",
                "Cleaner spelling",
                "This fixes the spelling while keeping your meaning the same.",
                "A rickshaw is moving along the road.",
            ),
            (
                r"\bricksha\b",
                "rickshaw",
                "grammar_fix",
                "Cleaner spelling",
                "This uses the standard spelling for the vehicle.",
                "A rickshaw is moving along the road.",
            ),
            (
                r"\bt\s*shirt\b|\btshirt\b",
                "T-shirt",
                "grammar_fix",
                "Cleaner spelling",
                "This is the more natural spelling for the clothing word.",
                "He is wearing a blue T-shirt.",
            ),
            (
                r"\bdriving on the road\b",
                "moving along the road",
                "natural_phrasing",
                "Smoother movement",
                "This sounds smoother when describing vehicles in an image.",
                "Two vehicles are moving along the road.",
            ),
            (
                r"\bon the road on a sunny day\b",
                "along the road on a sunny day",
                "sentence_flow",
                "Cleaner flow",
                "This avoids repeating 'on' and makes the sentence flow better.",
                "The vehicles move along the road on a sunny day.",
            ),
            (
                r"\bon the road\b",
                "along the road",
                "natural_phrasing",
                "Smoother position phrase",
                "This sounds more natural when describing where something appears.",
                "The vehicle is along the road.",
            ),
            (
                r"\bin the image\b",
                "in the scene",
                "natural_phrasing",
                "More natural image wording",
                "This is a reusable phrase for image descriptions.",
                "Several details appear in the scene.",
            ),
            (
                r"\bis on\b",
                "is positioned on",
                "visual_clarity",
                "Clearer positioning",
                "This makes the position sound more specific.",
                "The object is positioned on the table.",
            ),
            (
                r"\bare on\b",
                "are positioned on",
                "visual_clarity",
                "Clearer positioning",
                "This makes the position sound more specific.",
                "The objects are positioned on the table.",
            ),
            (
                r"\bthere is\b",
                image_includes_suggestion,
                "natural_phrasing",
                "More direct image phrasing",
                "This sounds more natural for describing what appears in an image.",
                "The image includes one clear subject.",
            ),
            (
                r"\bthere are\b",
                image_includes_suggestion,
                "natural_phrasing",
                "More direct image phrasing",
                "This sounds more natural for describing what appears in an image.",
                "The image includes several clear details.",
            ),
            (
                r"\b(?:picture|photo|scene|image) has\b",
                image_has_suggestion,
                "natural_phrasing",
                "Cleaner image phrasing",
                "This sounds smoother and more reusable for image descriptions.",
                "The image includes several visible details.",
            ),
            (
                r"\bis standing\b",
                "is standing clearly",
                "visual_clarity",
                "Slightly clearer action",
                "This keeps the action but makes it sound more descriptive.",
                "The person is standing clearly near the doorway.",
            ),
            (
                r"\bis sitting\b",
                "is sitting calmly",
                "visual_clarity",
                "Slightly clearer action",
                "This keeps the action but makes it sound more descriptive.",
                "The person is sitting calmly on a chair.",
            ),
            (
                r"\bis walking\b",
                "is walking along",
                "visual_clarity",
                "Smoother action",
                "This makes the movement sound more natural.",
                "The person is walking along the path.",
            ),
            (
                r"\bis smiling\b",
                "is smiling gently",
                "visual_clarity",
                "More expressive detail",
                "This keeps the expression but makes it more descriptive.",
                "The person is smiling gently.",
            ),
            (
                r"\bsmiles\b",
                "smiles gently",
                "visual_clarity",
                "More expressive action",
                "This keeps the expression but makes it more descriptive.",
                "The person smiles gently.",
            ),
            (
                r"\bstands\b",
                "stands clearly",
                "visual_clarity",
                "Slightly clearer action",
                "This keeps the action but makes it sound more descriptive.",
                "The person stands clearly near the doorway.",
            ),
            (
                r"\bsits\b",
                "sits calmly",
                "visual_clarity",
                "Slightly clearer action",
                "This keeps the action but makes it sound more descriptive.",
                "The person sits calmly on a chair.",
            ),
            (
                r"\bwalks\b",
                "walks along",
                "visual_clarity",
                "Smoother action",
                "This makes the movement sound more natural.",
                "The person walks along the path.",
            ),
        ]

        occupied: list[tuple[int, int]] = []
        for pattern, replacement, category, title, why_it_helps, example in checks:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            start, end = match.span()
            if any(start < used_end and end > used_start for used_start, used_end in occupied):
                continue
            current = self._clean_text_value(match.group(0))
            suggested = replacement(match) if callable(replacement) else replacement
            suggested = self._clean_text_value(suggested)
            if (
                not current
                or not suggested
                or normalize_answer(current) == normalize_answer(suggested)
                or len(current.split()) > 10
                or len(suggested.split()) > 16
                or len(current.split()) > max(4, len(text.split()) // 2)
            ):
                continue
            final_preview = self._replacement_preview(text, current=current, suggested=suggested)
            if not self._initial_preview_looks_safe(
                final_preview,
                original=text,
                current=current,
                suggested=suggested,
            ):
                continue
            occupied.append((start, end))
            candidates.append(
                {
                    "id": f"fallback-enhancement-{len(candidates) + 1}",
                    "category": category,
                    "title": title,
                    "currentText": current,
                    "suggestedText": suggested,
                    "targetText": current,
                    "replacementText": suggested,
                    "whyItHelps": why_it_helps,
                    "reason": why_it_helps,
                    "example": example,
                    "finalPreview": final_preview,
                    "xpReward": 5,
                }
            )
            if len(candidates) >= 3:
                return candidates

        words = re.findall(r"[A-Za-z][A-Za-z'-]*", text)
        normalized = normalize_answer(text)
        if (
            len(candidates) < 3
            and len(words) <= 8
            and re.search(r"\b(?:the|this) (?:image|picture|photo|scene) shows\b", text, flags=re.IGNORECASE)
            and "clear view" not in normalized
        ):
            match = re.search(r"\b(?:the|this) (?:image|picture|photo|scene) shows\b", text, flags=re.IGNORECASE)
            if match:
                starter = match.group(0)
                suggested = f"{starter} a clear view of"
                final_preview = self._replacement_preview(text, current=starter, suggested=suggested)
                if not self._initial_preview_looks_safe(
                    final_preview,
                    original=text,
                    current=starter,
                    suggested=suggested,
                ):
                    return candidates[:3]
                candidates.append(
                    {
                        "id": f"fallback-enhancement-{len(candidates) + 1}",
                        "category": "natural_phrasing",
                        "title": "More natural phrasing",
                        "currentText": starter,
                        "suggestedText": suggested,
                        "targetText": starter,
                        "replacementText": suggested,
                        "whyItHelps": "This keeps your idea but makes the sentence sound a little more descriptive.",
                        "reason": "This keeps your idea but makes the sentence sound a little more descriptive.",
                        "example": "The image shows a clear view of the main subject.",
                        "finalPreview": final_preview,
                        "xpReward": 5,
                    }
                )

        return candidates[:3]

    def _covered_area_labels(self, feedback: dict[str, Any]) -> list[str]:
        coverage = feedback.get("coverage") if isinstance(feedback.get("coverage"), dict) else {}
        labels: list[str] = []
        for part in coverage.get("imageParts", []):
            if not isinstance(part, dict):
                continue
            status = str(part.get("coverageStatus") or "").casefold()
            if not (part.get("covered") is True or status in {"covered", "partially_covered"}):
                continue
            label = self._clean_text_value(part.get("name") or part.get("description") or part.get("type"))
            if label:
                labels.append(label.replace("_", " "))
        return self._clean_string_list(labels, limit=6)

    def _missing_area_labels(self, feedback: dict[str, Any]) -> list[str]:
        coverage = feedback.get("coverage") if isinstance(feedback.get("coverage"), dict) else {}
        labels: list[str] = []
        for part in coverage.get("imageParts", []):
            if not isinstance(part, dict):
                continue
            status = str(part.get("coverageStatus") or "").casefold()
            missing = part.get("covered") is False or status in {"missing", "inaccurate"}
            if not missing:
                continue
            label = self._clean_text_value(part.get("name") or part.get("description") or part.get("type"))
            if label:
                labels.append(label.replace("_", " "))
        labels.extend(self._clean_string_list(coverage.get("missingMajorParts") or feedback.get("missing_details"), limit=6))
        return self._clean_string_list(labels, limit=6)

    def _initial_acknowledgement(self, covered_areas: list[str], learner_text: str) -> str:
        if covered_areas:
            return f"Nice start — you described {self._join_short_list(covered_areas[:3])}."
        trimmed = self._short_text(learner_text, limit=80)
        return f"Nice start — you began with your own observation{f': {trimmed}' if trimmed else '.'}"

    def _covered_only_enhancement(self, *, learner_text: str, covered_areas: list[str]) -> str:
        base = self._clean_text_value(learner_text).rstrip(".!?")
        if covered_areas:
            subject = self._join_short_list(covered_areas[:3])
            if any(word in normalize_answer(subject) for word in ("road", "street")):
                return f"The image shows {subject} in a clearer, more natural way."
            return f"The image shows {subject} clearly."
        if base:
            return f"The image shows {base}."
        return "The image shows the visual details you noticed."

    def _enhancement_mentions_missing_area(self, enhancement: str, missing_areas: list[str]) -> bool:
        key = normalize_answer(enhancement)
        for area in missing_areas:
            area_key = normalize_answer(area)
            if area_key and len(area_key) >= 4 and area_key in key:
                return True
        return False

    def _normalize_initial_reusable_language(
        self,
        payload: dict[str, Any],
        *,
        enhancement: str,
        analysis: dict[str, Any],
        covered_areas: list[str],
    ) -> dict[str, list[str]]:
        text = normalize_answer(enhancement)
        phrase_candidates = [
            str(item.get("phrase") or "").strip()
            for item in analysis.get("phrases", [])
            if isinstance(item, dict) and str(item.get("phrase") or "").strip()
        ]
        structure_candidates = [
            str(item.get("pattern") or "").strip()
            for item in analysis.get("sentence_patterns", [])
            if isinstance(item, dict) and str(item.get("pattern") or "").strip()
        ]
        reusable = {
            "nouns": self._clean_string_list(payload.get("nouns"), limit=5) or self._nounish_terms_from_text(enhancement, covered_areas),
            "verbs": self._clean_string_list(payload.get("verbs"), limit=4) or self._verbish_terms_from_text(enhancement),
            "phrases": self._clean_string_list(payload.get("phrases"), limit=5) or self._terms_present_in_text(text, phrase_candidates, limit=3),
            "collocations": self._clean_string_list(payload.get("collocations"), limit=5) or self._collocations_from_enhancement(enhancement),
            "sentence_structures": self._clean_string_list(payload.get("sentenceStructures") or payload.get("sentence_structures"), limit=3) or self._terms_present_in_text(text, structure_candidates, limit=2) or ["The image shows ..."],
            "positioning_language": self._clean_string_list(payload.get("positioningLanguage") or payload.get("positioning_language"), limit=4) or self._positioning_language_from_text(enhancement),
            "atmosphere_language": self._clean_string_list(payload.get("atmosphereLanguage") or payload.get("atmosphere_language"), limit=4) or self._atmosphere_language_from_text(enhancement),
        }
        return reusable

    def _nounish_terms_from_text(self, text: str, covered_areas: list[str]) -> list[str]:
        candidates = [*covered_areas]
        candidates.extend(re.findall(r"\b[a-zA-Z][a-zA-Z-]{3,}\b", text))
        blocked = {"image", "shows", "clearer", "natural", "quiet", "lined"}
        return self._clean_string_list(
            [item for item in candidates if normalize_answer(item) not in blocked],
            limit=5,
        )

    def _verbish_terms_from_text(self, text: str) -> list[str]:
        verbs = re.findall(r"\b(?:shows|has|includes|stands|sits|runs|lines|appears|looks|describes|covered|lined)\b", text, flags=re.I)
        return self._clean_string_list(verbs, limit=4)

    def _collocations_from_enhancement(self, text: str) -> list[str]:
        patterns = [
            r"\bquiet urban road\b",
            r"\btall buildings\b",
            r"\blined with [a-z\s-]+\b",
            r"\bin the background\b",
            r"\bin the foreground\b",
            r"\b[a-z]+ road\b",
        ]
        found: list[str] = []
        for pattern in patterns:
            found.extend(match.group(0) for match in re.finditer(pattern, text, flags=re.I))
        return self._clean_string_list(found, limit=5)

    def _positioning_language_from_text(self, text: str) -> list[str]:
        terms = re.findall(r"\b(?:in the background|in the foreground|beside|near|behind|lined with|along|under|over|around)\b", text, flags=re.I)
        return self._clean_string_list(terms, limit=4)

    def _atmosphere_language_from_text(self, text: str) -> list[str]:
        terms = re.findall(r"\b(?:quiet|busy|calm|crowded|shaded|sunny|bright|peaceful|urban|natural)\b", text, flags=re.I)
        return self._clean_string_list(terms, limit=4)

    def _terms_present_in_text(self, text_key: str, candidates: list[str], *, limit: int) -> list[str]:
        return self._clean_string_list(
            [item for item in candidates if normalize_answer(item) in text_key],
            limit=limit,
        )

    def _join_short_list(self, items: list[str]) -> str:
        clean = self._clean_string_list(items, limit=4)
        if not clean:
            return ""
        if len(clean) == 1:
            return clean[0]
        if len(clean) == 2:
            return f"{clean[0]} and {clean[1]}"
        return f"{', '.join(clean[:-1])}, and {clean[-1]}"

    def _normalize_feedback_readiness(
        self,
        payload: Any,
        *,
        coverage: dict[str, Any],
        score: int,
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        payload = payload if isinstance(payload, dict) else {}
        criteria_payload = payload.get("criteria") if isinstance(payload.get("criteria"), dict) else {}
        fallback_criteria = fallback.get("criteria") if isinstance(fallback.get("criteria"), dict) else {}
        image_parts = coverage.get("imageParts") if isinstance(coverage.get("imageParts"), list) else []

        def covered_type(name: str) -> bool:
            for part in image_parts:
                if not isinstance(part, dict):
                    continue
                part_type = str(part.get("type") or "").casefold()
                status = str(part.get("coverageStatus") or "").casefold()
                if name in part_type and (part.get("covered") is True or status == "covered"):
                    return True
            return False

        detail_count = 0
        for part in image_parts:
            if not isinstance(part, dict):
                continue
            part_type = str(part.get("type") or "").casefold()
            status = str(part.get("coverageStatus") or "").casefold()
            if (
                any(key in part_type for key in ("important", "foreground", "detail", "object"))
                and (part.get("covered") is True or status == "covered")
            ):
                detail_count += 1

        criteria = {
            "mainSubject": bool(criteria_payload.get("mainSubject", fallback_criteria.get("mainSubject", coverage.get("mainSubjectMentioned") is not False))),
            "mainAction": bool(criteria_payload.get("mainAction", fallback_criteria.get("mainAction", coverage.get("mainActionMentioned") is not False))),
            "settingBackground": bool(criteria_payload.get("settingBackground", fallback_criteria.get("settingBackground", covered_type("setting") or covered_type("background")))),
            "twoImportantDetails": bool(criteria_payload.get("twoImportantDetails", fallback_criteria.get("twoImportantDetails", detail_count >= 2))),
            "naturalEnglish": bool(criteria_payload.get("naturalEnglish", fallback_criteria.get("naturalEnglish", score >= 60))),
            "notAWordList": bool(criteria_payload.get("notAWordList", fallback_criteria.get("notAWordList", True))),
            "overallSense": bool(criteria_payload.get("overallSense", fallback_criteria.get("overallSense", score >= 72 and int(coverage.get("coveragePercent") or coverage.get("coverageScore") or 0) >= 75))),
        }
        inferred_ready = all(criteria.values())
        explicit_ready = payload.get("ready")
        if explicit_ready is None:
            explicit_ready = payload.get("is_ready")
        ready = bool(explicit_ready) if isinstance(explicit_ready, bool) else inferred_ready
        if ready and not inferred_ready:
            ready = False
        return {
            "ready": ready,
            "reason": self._clean_text_value(payload.get("reason") or fallback.get("reason"))
            or (
                "The explanation covers the image well enough."
                if ready
                else "Keep adding the missing image coverage before the final reveal."
            ),
            "criteria": criteria,
        }

    def _apply_progressive_coaching(
        self,
        feedback: dict[str, Any],
        *,
        analysis: dict[str, Any],
        learner_text: str,
        original_text: str,
        attempt_index: int,
    ) -> dict[str, Any]:
        coached = dict(feedback)
        attempt_index = max(1, int(attempt_index or 1))
        state = self._progressive_dimension_state(coached, analysis=analysis)
        focus_areas = self._select_progressive_focus_areas(state)
        specific_guidance = self._build_specific_guidance(
            focus_areas=focus_areas,
            feedback=coached,
            analysis=analysis,
        )
        suggestions = specific_guidance["actionable_suggestions"]
        raw_score = int(coached.get("score") or 0)
        score = self._progressive_score(
            raw_score,
            state=state,
            attempt_index=attempt_index,
            validation_retry=bool(coached.get("retry_required")) and raw_score <= 25,
        )
        coached["score"] = score
        coached["articulation_level"] = self._articulation_level(score)
        coached["focus_areas"] = focus_areas
        coached["actionable_suggestions"] = suggestions
        coached["specific_guidance"] = specific_guidance
        coached["dimension_tracker"] = self._dimension_tracker(state)
        coached["next_focus_instruction"] = specific_guidance["next_focus_instruction"]
        coached["coaching_message"] = self._progressive_coaching_message(
            score=score,
            state=state,
            focus_areas=focus_areas,
            attempt_index=attempt_index,
        )
        coached["what_improved"] = self._progressive_improvement_note(
            feedback=coached,
            learner_text=learner_text,
            original_text=original_text,
            state=state,
        )

        ready = self._progressive_ready_for_final_reveal(
            state=state,
            score=score,
            attempt_index=attempt_index,
        )
        readiness = coached.get("readiness") if isinstance(coached.get("readiness"), dict) else {}
        readiness = dict(readiness)
        readiness["ready"] = ready
        readiness["reason"] = (
            "The explanation is complete, natural, and ready for reinforcement."
            if ready
            else "Keep refining the current focus areas before the final reveal."
        )
        coached["readiness"] = readiness
        coached["is_ready"] = ready
        if not ready:
            coached["retry_required"] = False
            coached["cta_label"] = "Improve explanation"
        return coached

    def _progressive_dimension_state(
        self,
        feedback: dict[str, Any],
        *,
        analysis: dict[str, Any],
    ) -> dict[str, bool]:
        readiness = feedback.get("readiness") if isinstance(feedback.get("readiness"), dict) else {}
        criteria = readiness.get("criteria") if isinstance(readiness.get("criteria"), dict) else {}
        coverage = feedback.get("coverage") if isinstance(feedback.get("coverage"), dict) else {}
        language = feedback.get("language_quality") if isinstance(feedback.get("language_quality"), dict) else {}
        image_parts = coverage.get("imageParts") if isinstance(coverage.get("imageParts"), list) else []

        def covered_type(*needles: str) -> bool:
            for part in image_parts:
                if not isinstance(part, dict):
                    continue
                part_type = str(part.get("type") or "").casefold()
                if not any(needle in part_type for needle in needles):
                    continue
                status = str(part.get("coverageStatus") or "").casefold()
                if part.get("covered") is True or status in {"covered", "partially_covered"}:
                    return True
            return False

        natural_score = int(language.get("naturalness") or language.get("score") or 0)
        structure_score = int(language.get("structure") or 0)
        vocabulary_score = int(language.get("vocabulary") or 0)
        action_required = bool(analysis.get("actions"))
        return {
            "main subject": bool(criteria.get("mainSubject", coverage.get("mainSubjectMentioned") is not False)),
            "main action": (
                True
                if not action_required
                else bool(criteria.get("mainAction", coverage.get("mainActionMentioned") is not False))
            ),
            "foreground": covered_type("foreground"),
            "background/setting": bool(criteria.get("settingBackground", covered_type("setting", "background"))),
            "important objects": covered_type("important", "object", "detail"),
            "mood/atmosphere": covered_type("mood") or self._feedback_mood_in_text(str(feedback.get("better_version") or "")),
            "sentence flow": structure_score >= 60 or bool(criteria.get("naturalEnglish")),
            "vocabulary strength": vocabulary_score >= 60 or bool(feedback.get("phrase_usage", {}).get("used") if isinstance(feedback.get("phrase_usage"), dict) else False),
            "articulation/naturalness": natural_score >= 60 or bool(criteria.get("naturalEnglish")),
            "sentence connection": structure_score >= 65 or bool(criteria.get("notAWordList")),
            "descriptive depth": bool(criteria.get("twoImportantDetails")) or covered_type("foreground") and covered_type("important"),
        }

    def _select_progressive_focus_areas(self, state: dict[str, bool]) -> list[str]:
        priority = [
            "main subject",
            "main action",
            "background/setting",
            "foreground",
            "important objects",
            "mood/atmosphere",
            "sentence flow",
            "vocabulary strength",
            "articulation/naturalness",
            "sentence connection",
            "descriptive depth",
        ]
        missing = [dimension for dimension in priority if not state.get(dimension)]
        if not missing:
            return ["articulation/naturalness", "sentence flow"]
        return missing[:2]

    def _build_specific_guidance(
        self,
        *,
        focus_areas: list[str],
        feedback: dict[str, Any],
        analysis: dict[str, Any],
    ) -> dict[str, Any]:
        nouns: list[str] = []
        verbs: list[str] = []
        details: list[str] = []
        suggestions: list[str] = []
        for focus in focus_areas[:2]:
            focus_hints = self._specific_hints_for_focus(
                focus=focus,
                feedback=feedback,
                analysis=analysis,
            )
            nouns.extend(focus_hints["nouns"])
            verbs.extend(focus_hints["verbs"])
            details.extend(focus_hints["details"])
            if focus_hints["suggestion"]:
                suggestions.append(focus_hints["suggestion"])

        nouns = self._unique_short_hints(nouns, limit=5)
        verbs = self._unique_short_hints(verbs, limit=4)
        details = self._unique_short_hints(details, limit=5)
        words = self._unique_short_hints([*nouns, *verbs, *details], limit=7)
        sentence_starter = self._specific_sentence_starter(
            focus_areas=focus_areas,
            analysis=analysis,
            nouns=nouns,
            verbs=verbs,
            details=details,
        )
        next_focus_instruction = self._specific_next_focus_instruction(
            focus_areas=focus_areas,
            sentence_starter=sentence_starter,
        )
        if not suggestions:
            suggestions = [next_focus_instruction]
        return {
            "focus_areas": focus_areas[:2],
            "nouns": nouns,
            "verbs": verbs,
            "details": details,
            "words": words,
            "sentence_starter": sentence_starter,
            "next_focus_instruction": next_focus_instruction,
            "actionable_suggestions": self._unique_short_hints(suggestions, limit=2),
        }

    def _specific_hints_for_focus(
        self,
        *,
        focus: str,
        feedback: dict[str, Any],
        analysis: dict[str, Any],
    ) -> dict[str, Any]:
        objects = analysis.get("objects") if isinstance(analysis.get("objects"), list) else []
        actions = analysis.get("actions") if isinstance(analysis.get("actions"), list) else []
        environment = self._clean_text_value(analysis.get("environment"))
        environment_details = self._clean_string_list(analysis.get("environment_details") or [], limit=6)
        primary_subject = self._primary_subject_name(objects)
        main_action = self._main_action_phrase(actions)
        important_objects = self._important_object_names(objects, primary_subject=primary_subject)
        background_details = self._background_detail_hints(environment=environment, details=environment_details)
        foreground_details = self._foreground_detail_hints(objects=objects, details=environment_details)
        missing = self._clean_string_list(
            feedback.get("missing_details")
            or (feedback.get("coverage") or {}).get("missingMajorParts")
            or [],
            limit=3,
        )
        phrase_usage = feedback.get("phrase_usage") if isinstance(feedback.get("phrase_usage"), dict) else {}
        suggested_phrases = self._clean_string_list(phrase_usage.get("suggested"), limit=2)
        vocabulary = [
            self._clean_text_value(item.get("word"))
            for item in (analysis.get("vocabulary") or [])[:4]
            if isinstance(item, dict)
        ]
        phrases = [
            self._clean_text_value(item.get("phrase"))
            for item in (analysis.get("phrases") or [])[:4]
            if isinstance(item, dict)
        ]

        if focus == "main subject":
            subject = primary_subject or (important_objects[0] if important_objects else "the main subject")
            return {
                "nouns": [subject],
                "verbs": [],
                "details": [self._object_description(objects, subject)] if subject else [],
                "suggestion": f"Mention the main subject: {subject}.",
            }
        if focus == "main action":
            action = main_action or "the main action"
            return {
                "nouns": [primary_subject, *important_objects[:2]],
                "verbs": self._action_verbs(actions),
                "details": [action],
                "suggestion": f"Mention the main action: {action}.",
            }
        if focus == "background/setting":
            details = background_details or missing[:2]
            detail_text = self._join_hints(details) or "the setting or background"
            return {
                "nouns": details,
                "verbs": [],
                "details": details,
                "suggestion": f"Add the background: {detail_text}.",
            }
        if focus == "foreground":
            details = foreground_details or important_objects[:2] or missing[:2]
            detail_text = self._join_hints(details) or "the nearest visible detail"
            return {
                "nouns": details,
                "verbs": [],
                "details": details,
                "suggestion": f"Add the foreground detail: {detail_text}.",
            }
        if focus == "important objects":
            details = important_objects[:3] or missing[:2]
            detail_text = self._join_hints(details) or "one important visible object"
            return {
                "nouns": details,
                "verbs": [],
                "details": details,
                "suggestion": f"Include these visible objects: {detail_text}.",
            }
        if focus == "mood/atmosphere":
            mood = self._mood_part_description(
                analysis,
                self._clean_text_value(analysis.get("natural_explanation") or analysis.get("scene_summary_natural")),
                environment,
            )
            mood_words = self._mood_words_from_text(mood) or self._mood_words_from_text(
                self._clean_text_value(analysis.get("natural_explanation") or "")
            )
            if not mood_words:
                mood_words = ["calm" if background_details else "natural"]
            return {
                "nouns": background_details[:2],
                "verbs": [],
                "details": mood_words[:2],
                "suggestion": f"Describe the atmosphere: {self._join_hints(mood_words[:2])}.",
            }
        if focus == "vocabulary strength":
            words = [*suggested_phrases, *phrases, *vocabulary]
            return {
                "nouns": words[:3],
                "verbs": [],
                "details": words[:3],
                "suggestion": f"Use one stronger phrase: {words[0]}." if words else "",
            }
        if focus in {"sentence flow", "sentence connection", "articulation/naturalness"}:
            details = [item for item in [main_action, *(background_details[:2] or important_objects[:2])] if item]
            return {
                "nouns": [primary_subject, *background_details[:2]],
                "verbs": self._action_verbs(actions),
                "details": details,
                "suggestion": "Connect the action and background in one smooth sentence.",
            }
        if focus == "descriptive depth":
            details = [*important_objects[:2], *background_details[:2], *foreground_details[:1]]
            detail_text = self._join_hints(details[:3]) or "one more specific visible detail"
            return {
                "nouns": details[:3],
                "verbs": self._action_verbs(actions)[:1],
                "details": details[:3],
                "suggestion": f"Add one specific visible detail: {detail_text}.",
            }
        return {"nouns": [], "verbs": [], "details": [], "suggestion": ""}

    def _specific_sentence_starter(
        self,
        *,
        focus_areas: list[str],
        analysis: dict[str, Any],
        nouns: list[str],
        verbs: list[str],
        details: list[str],
    ) -> str:
        objects = analysis.get("objects") if isinstance(analysis.get("objects"), list) else []
        actions = analysis.get("actions") if isinstance(analysis.get("actions"), list) else []
        environment = self._clean_text_value(analysis.get("environment"))
        environment_details = self._clean_string_list(analysis.get("environment_details") or [], limit=4)
        primary_subject = self._primary_subject_name(objects) or "main subject"
        subject_text = self._sentence_subject_label(primary_subject)
        action = self._main_action_phrase(actions)
        background = self._background_detail_hints(environment=environment, details=environment_details)
        foreground = self._foreground_detail_hints(objects=objects, details=environment_details)
        focus_set = set(focus_areas[:2])

        if "main action" in focus_set and action:
            return self._ensure_sentence_punctuation(f"{subject_text} is {action}")
        if "background/setting" in focus_set:
            target = self._join_hints(background[:3] or details[:3])
            if target:
                verb = "are" if len(background[:3] or details[:3]) > 1 else "is"
                return self._ensure_sentence_punctuation(f"In the background, there {verb} {target}")
        if "foreground" in focus_set:
            target = self._join_hints(foreground[:2] or details[:2])
            if target:
                return self._ensure_sentence_punctuation(f"In the foreground, there is {target}")
        if "important objects" in focus_set:
            target = self._join_hints(nouns[:3])
            if target:
                return self._ensure_sentence_punctuation(f"You can also see {target}")
        if "mood/atmosphere" in focus_set:
            mood = details[0] if details else "calm"
            return self._ensure_sentence_punctuation(f"The scene feels {mood}")
        if focus_set & {"sentence flow", "sentence connection", "articulation/naturalness"}:
            background_text = self._join_hints(background[:2])
            if action and background_text:
                return self._ensure_sentence_punctuation(
                    f"{subject_text} is {action}, while the background shows {background_text}"
                )
        if action:
            return self._ensure_sentence_punctuation(f"{subject_text} is {action}")
        if nouns:
            return self._ensure_sentence_punctuation(f"The image shows {self._join_hints(nouns[:2])}")
        return "The image shows the main subject clearly."

    def _sentence_subject_label(self, subject: str) -> str:
        text = self._clean_text_value(subject).strip(" ,.;:")
        if not text:
            return "The main subject"
        if re.match(r"^(a|an|the|this|that|these|those)\b", text, flags=re.I):
            return text[0].upper() + text[1:]
        return f"The {text}"

    def _specific_next_focus_instruction(self, *, focus_areas: list[str], sentence_starter: str) -> str:
        focus_set = set(focus_areas[:2])
        if "main action" in focus_set and "background/setting" in focus_set:
            return "Add one sentence saying what the main subject is doing, then one short background detail."
        if "main action" in focus_set:
            return "Add one sentence saying exactly what the main subject is doing."
        if "background/setting" in focus_set and "mood/atmosphere" in focus_set:
            return "Add one sentence about the background and one word for the mood."
        if "background/setting" in focus_set:
            return "Add one sentence about the background using the structure above."
        if "foreground" in focus_set or "important objects" in focus_set:
            return "Add one sentence with the visible detail listed above."
        if "mood/atmosphere" in focus_set:
            return "Add one short phrase that describes the overall feeling of the image."
        if focus_set & {"sentence flow", "sentence connection", "articulation/naturalness"}:
            return "Rewrite your answer by connecting the action and background in one smooth sentence."
        if "vocabulary strength" in focus_set:
            return "Replace one general word with one exact word from the hint list."
        return f"Use this next: {sentence_starter}"

    def _main_action_phrase(self, actions: list[Any]) -> str:
        for item in actions:
            if not isinstance(item, dict):
                continue
            phrase = self._clean_text_value(item.get("phrase") or item.get("description"))
            verb = self._clean_text_value(item.get("verb"))
            if phrase:
                return self._strip_subject_from_action(phrase)
            if verb:
                return verb
        return ""

    def _strip_subject_from_action(self, phrase: str) -> str:
        text = self._clean_text_value(phrase).rstrip(".")
        text = re.sub(r"^(a|an|the)\s+[^,.]{1,40}\s+(is|are|was|were)\s+", "", text, flags=re.I)
        return text

    def _action_verbs(self, actions: list[Any]) -> list[str]:
        verbs: list[str] = []
        for item in actions:
            if not isinstance(item, dict):
                continue
            verb = self._clean_text_value(item.get("verb"))
            phrase = self._clean_text_value(item.get("phrase"))
            if verb:
                verbs.append(verb)
            match = re.search(r"\b[a-z][a-z-]*ing\b", phrase, flags=re.I)
            if match:
                verbs.append(match.group(0))
        return self._unique_short_hints(verbs, limit=4)

    def _important_object_names(self, objects: list[Any], *, primary_subject: str) -> list[str]:
        names: list[str] = []
        primary_key = normalize_answer(primary_subject)
        for item in objects:
            if not isinstance(item, dict):
                continue
            name = self._clean_text_value(item.get("name"))
            if not name or normalize_answer(name) == primary_key:
                continue
            names.append(name)
        return self._unique_short_hints(names, limit=5)

    def _object_description(self, objects: list[Any], subject: str) -> str:
        subject_key = normalize_answer(subject)
        for item in objects:
            if not isinstance(item, dict):
                continue
            if normalize_answer(str(item.get("name") or "")) == subject_key:
                return self._clean_text_value(item.get("description"))
        return ""

    def _background_detail_hints(self, *, environment: str, details: list[str]) -> list[str]:
        candidates = [environment, *details]
        background_words = re.compile(
            r"\b(background|sky|tree|trees|bush|bushes|building|buildings|wall|road|street|park|garden|yard|field|lawn|water|mountain|palm|cloud|outside|outdoor|indoors|room)\b",
            re.I,
        )
        matched = [item for item in candidates if background_words.search(item or "")]
        return self._unique_short_hints(matched or candidates, limit=4)

    def _foreground_detail_hints(self, *, objects: list[Any], details: list[str]) -> list[str]:
        candidates: list[str] = []
        foreground_words = re.compile(r"\b(foreground|front|near|nearby|close|grass|ground|floor|path|pavement|road|table|lawn)\b", re.I)
        for item in objects:
            if not isinstance(item, dict):
                continue
            name = self._clean_text_value(item.get("name"))
            description = self._clean_text_value(item.get("description"))
            if foreground_words.search(f"{name} {description}"):
                candidates.append(name or description)
        candidates.extend([detail for detail in details if foreground_words.search(detail)])
        return self._unique_short_hints(candidates, limit=4)

    def _mood_words_from_text(self, text: str) -> list[str]:
        mood_words = [
            "calm",
            "peaceful",
            "quiet",
            "busy",
            "crowded",
            "relaxed",
            "serious",
            "bright",
            "sunny",
            "friendly",
            "tense",
            "casual",
        ]
        normalized = normalize_answer(text)
        return [word for word in mood_words if word in normalized][:3]

    def _unique_short_hints(self, values: list[str], *, limit: int) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = self._clean_text_value(value).strip(" ,.;:")
            key = normalize_answer(text)
            if not text or not key or key in seen:
                continue
            seen.add(key)
            cleaned.append(text)
            if len(cleaned) >= limit:
                break
        return cleaned

    def _join_hints(self, values: list[str]) -> str:
        hints = self._unique_short_hints(values, limit=4)
        if not hints:
            return ""
        if len(hints) == 1:
            return hints[0]
        return f"{', '.join(hints[:-1])}, and {hints[-1]}"

    def _progressive_score(
        self,
        score: int,
        *,
        state: dict[str, bool],
        attempt_index: int,
        validation_retry: bool = False,
    ) -> int:
        if validation_retry:
            return max(1, min(25, score))
        completed = sum(1 for value in state.values() if value)
        coverage_floor = min(88, 18 + completed * 7)
        score = max(score, coverage_floor)
        caps = {1: 62, 2: 74, 3: 84, 4: 91}
        cap = caps.get(attempt_index, 95)
        if all(state.values()):
            cap = max(cap, 90)
        return max(1, min(cap, score))

    def _articulation_level(self, score: int) -> str:
        if score < 45:
            return "Basic"
        if score < 60:
            return "Clear"
        if score < 75:
            return "Descriptive"
        if score < 88:
            return "Natural"
        return "Fluent"

    def _dimension_tracker(self, state: dict[str, bool]) -> list[dict[str, Any]]:
        display = [
            ("main subject", "Main subject"),
            ("main action", "Main action"),
            ("background/setting", "Background/setting"),
            ("foreground", "Foreground"),
            ("important objects", "Important objects"),
            ("mood/atmosphere", "Mood/atmosphere"),
            ("sentence flow", "Sentence flow"),
            ("vocabulary strength", "Vocabulary strength"),
            ("articulation/naturalness", "Naturalness"),
            ("sentence connection", "Sentence connection"),
            ("descriptive depth", "Descriptive depth"),
        ]
        return [
            {"key": key, "label": label, "complete": bool(state.get(key))}
            for key, label in display
        ]

    def _progressive_ready_for_final_reveal(
        self,
        *,
        state: dict[str, bool],
        score: int,
        attempt_index: int,
    ) -> bool:
        required = [
            "main subject",
            "main action",
            "background/setting",
            "important objects",
            "sentence flow",
            "articulation/naturalness",
            "descriptive depth",
        ]
        return attempt_index >= 3 and score >= 82 and all(state.get(item) for item in required)

    def _progressive_coaching_message(
        self,
        *,
        score: int,
        state: dict[str, bool],
        focus_areas: list[str],
        attempt_index: int,
    ) -> str:
        if self._progressive_ready_for_final_reveal(state=state, score=score, attempt_index=attempt_index):
            return "Excellent articulation. Your explanation now feels complete and natural."
        if attempt_index == 1:
            return "Good start. Let’s build the description one layer at a time."
        focus_text = " and ".join(focus_areas[:2]).replace("/", " or ")
        return f"Nice improvement. Now focus on {focus_text}."

    def _progressive_improvement_note(
        self,
        *,
        feedback: dict[str, Any],
        learner_text: str,
        original_text: str,
        state: dict[str, bool],
    ) -> str:
        positives = self._clean_string_list(feedback.get("what_did_well"), limit=1)
        if positives:
            return positives[0]
        if normalize_answer(learner_text) != normalize_answer(original_text):
            return "Your revision is moving toward a fuller explanation."
        completed = [label for label, complete in state.items() if complete]
        if completed:
            return f"You already have {completed[0]}."
        return "You started with your own observation."

    def _build_next_step_instructions(
        self,
        *,
        feedback: dict[str, Any],
        analysis: dict[str, Any],
    ) -> list[str]:
        coverage = feedback.get("coverage") if isinstance(feedback.get("coverage"), dict) else {}
        missing = self._clean_string_list(
            feedback.get("missing_details") or coverage.get("missingMajorParts") or [],
            limit=2,
        )
        upgrades = feedback.get("word_phrase_upgrades") if isinstance(feedback.get("word_phrase_upgrades"), list) else []
        structures = self._clean_string_list(feedback.get("reusable_sentence_structures"), limit=1)
        steps: list[str] = []
        if missing and not re.search(r"no major visual detail", missing[0], re.I):
            detail = missing[0]
            steps.append(
                detail
                if re.match(r"^(mention|add|describe)\b", detail, re.I)
                else f"Mention this missing observation: {detail}."
            )
        for item in upgrades:
            if isinstance(item, dict):
                phrase = self._clean_text_value(
                    item.get("use") or item.get("new") or item.get("strong")
                )
            else:
                phrase = self._clean_text_value(item)
            if phrase:
                steps.append(f"Use a stronger phrase if it fits: {phrase}.")
                break
        if structures:
            steps.append(f"Use this structure: {structures[0]}")
        if not steps:
            steps = [
                "Mention the setting/background with one visible detail.",
                "Use one specific image phrase instead of a general word.",
                "Use: The main subject is ..., while the background shows ...",
            ]
        return steps[:2]

    def _normalize_retry_score(self, value: Any) -> int:
        try:
            score = int(value)
        except (TypeError, ValueError):
            score = 8
        return max(0, min(15, score))

    def _normalize_feedback_score(self, value: Any, *, fallback: dict[str, Any]) -> int:
        try:
            score = int(value)
        except (TypeError, ValueError):
            fallback_score = fallback.get("score")
            if isinstance(fallback_score, int):
                score = fallback_score
            else:
                scores = fallback.get("scores") or {}
                values = [
                    max(1, min(10, int(scores.get(key, 5))))
                    for key in ("vocabulary", "structure", "depth", "clarity")
                ]
                score = round((sum(values) / len(values)) * 10)
        return max(1, min(100, score))

    def _normalize_language_quality(self, value: Any) -> dict[str, int]:
        payload = value if isinstance(value, dict) else {}
        fields = ("clarity", "vocabulary", "structure", "grammar", "naturalness", "reusableLanguage")
        normalized: dict[str, int] = {}
        for field in fields:
            try:
                raw_score = int(payload.get(field) or payload.get(self._snake_case(field)) or 0)
            except (TypeError, ValueError):
                raw_score = 0
            normalized[field] = max(0, min(100, raw_score))
        try:
            total = int(payload.get("score") or 0)
        except (TypeError, ValueError):
            total = 0
        if total <= 0 and any(normalized.values()):
            total = self._weighted_language_quality_score(normalized)
        normalized["score"] = max(0, min(100, total))
        return normalized

    def _snake_case(self, value: str) -> str:
        return re.sub(r"(?<!^)([A-Z])", r"_\1", value).lower()

    def _weighted_language_quality_score(self, scores: dict[str, int]) -> int:
        weights = {
            "clarity": 25,
            "vocabulary": 20,
            "structure": 20,
            "grammar": 15,
            "naturalness": 10,
            "reusableLanguage": 10,
        }
        return round(sum(scores.get(key, 0) * weight for key, weight in weights.items()) / 100)

    def _normalize_coverage(self, value: Any) -> dict[str, Any]:
        payload = value if isinstance(value, dict) else {}
        level = self._clean_text_value(payload.get("level")).lower()
        if level not in {"low", "partial", "overall", "strong"}:
            level = ""
        try:
            score_cap = int(payload.get("scoreCapApplied") or payload.get("score_cap_applied") or 0)
        except (TypeError, ValueError):
            score_cap = 0
        image_parts = self._normalize_coverage_parts(payload.get("imageParts") or payload.get("image_parts"))
        main_subject_value = payload.get("mainSubjectMentioned")
        if main_subject_value is None:
            main_subject_value = payload.get("main_subject_mentioned")
        main_action_value = payload.get("mainActionMentioned")
        if main_action_value is None:
            main_action_value = payload.get("main_action_mentioned")
        main_subject_mentioned = (
            self._env_bool_from_any(main_subject_value)
            if main_subject_value is not None
            else self._part_type_has_credit(image_parts, "main_subject")
        )
        main_action_mentioned = (
            self._env_bool_from_any(main_action_value)
            if main_action_value is not None
            else self._part_type_has_credit(image_parts, "main_action")
        )
        return {
            "level": level,
            "mainSubjectMentioned": main_subject_mentioned,
            "mainActionMentioned": main_action_mentioned,
            "imageParts": image_parts,
            "missingMajorParts": self._clean_string_list(
                payload.get("missingMajorParts") or payload.get("missing_major_parts"),
                limit=5,
            ),
            "coveragePercent": self._normalize_percent(
                payload.get("coveragePercent") or payload.get("coverage_percent")
            ),
            "coverageScore": self._normalize_percent(
                payload.get("coverageScore") or payload.get("coverage_score")
            ),
            "accuracyPenalty": self._normalize_percent(
                payload.get("accuracyPenalty") or payload.get("accuracy_penalty")
            ),
            "scoreCapApplied": max(0, min(100, score_cap)),
            "reason": self._clean_text_value(payload.get("reason")),
        }

    def _normalize_coverage_parts(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        parts: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            part = (
                self._clean_text_value(item.get("part"))
                or self._clean_text_value(item.get("name"))
                or self._clean_text_value(item.get("type"))
            )
            if not part:
                continue
            part_type = self._clean_text_value(item.get("type"))
            name = self._clean_text_value(item.get("name")) or part
            description = self._clean_text_value(item.get("description"))
            try:
                weight = float(item.get("weight") or 0)
            except (TypeError, ValueError):
                weight = 0.0
            covered = item.get("covered")
            coverage_status = self._normalize_coverage_status(
                item.get("coverageStatus") or item.get("coverage_status"),
                covered=covered,
            )
            parts.append(
                {
                    "part": part,
                    "name": name,
                    "description": description,
                    "type": part_type,
                    "required": bool(item.get("required", True)),
                    "weight": max(0.0, min(100.0, weight)),
                    "coverageStatus": coverage_status,
                    "covered": coverage_status == "covered",
                    "evidence": self._clean_text_value(item.get("evidence")),
                }
            )
            if len(parts) >= 8:
                break
        return parts

    def _normalize_coverage_status(self, value: Any, *, covered: Any = None) -> str:
        status = self._clean_text_value(value).lower().replace("-", "_").replace(" ", "_")
        if status in {"covered", "partially_covered", "missing", "inaccurate"}:
            return status
        if covered is True or str(covered).strip().casefold() == "true":
            return "covered"
        return "missing"

    def _part_type_has_credit(self, parts: list[dict[str, Any]], part_type: str) -> bool:
        return any(
            str(part.get("type") or "") == part_type
            and self._coverage_status_credit(str(part.get("coverageStatus") or "missing")) > 0
            for part in parts
        )

    def _env_bool_from_any(self, value: Any) -> bool:
        return value is True or str(value).strip().casefold() in {"1", "true", "yes", "on"}

    def _normalize_percent(self, value: Any) -> int:
        try:
            percent = int(round(float(value)))
        except (TypeError, ValueError):
            percent = 0
        return max(0, min(100, percent))

    def _normalized_coverage_hard_cap(self, coverage: dict[str, Any]) -> int:
        original_cap = int(coverage.get("scoreCapApplied") or 0)
        parts = coverage.get("imageParts") if isinstance(coverage.get("imageParts"), list) else []
        if not parts:
            return original_cap

        cap = original_cap if original_cap > 0 else 95
        coverage_score = int(coverage.get("coverageScore") or coverage.get("coveragePercent") or 0)
        credited_parts = [
            part
            for part in parts
            if self._coverage_status_credit(str(part.get("coverageStatus") or "missing")) > 0
        ]
        credited_types = {str(part.get("type") or "") for part in credited_parts}
        has_main_subject = any(str(part.get("type") or "") == "main_subject" for part in parts)
        has_main_action = any(str(part.get("type") or "") == "main_action" for part in parts)
        main_subject_mentioned = bool(coverage.get("mainSubjectMentioned"))
        main_action_mentioned = bool(coverage.get("mainActionMentioned"))

        if (
            has_main_subject
            and not main_subject_mentioned
            and (not has_main_action or not main_action_mentioned)
            and credited_types
            and credited_types.isdisjoint({"main_subject", "main_action"})
            and bool(credited_types & {"setting", "mood"})
        ):
            cap = min(cap, 25)
        if credited_types <= {"foreground", "important_object"} and credited_types:
            cap = min(cap, 25)
        if len(credited_parts) <= 1:
            cap = min(cap, 30)
        if has_main_subject and not main_subject_mentioned:
            cap = min(cap, 40)
        if has_main_action and not main_action_mentioned:
            cap = min(cap, 50)
        if coverage_score < 45:
            cap = min(cap, 45)
        if has_main_subject and main_subject_mentioned and "setting" not in credited_types:
            cap = min(cap, 55)
        if coverage_score < 70:
            cap = min(cap, 70)
        elif coverage_score < 85:
            cap = min(cap, 80)
        elif coverage_score < 95:
            cap = min(cap, 90)
        else:
            cap = min(cap, 95)
        return max(0, min(100, cap))

    def _normalize_feedback_alternatives(
        self,
        raw_items: Any,
        *,
        fallback: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        items = raw_items if isinstance(raw_items, list) else []
        cleaned: list[dict[str, str]] = []
        for item in items[:5]:
            if not isinstance(item, dict):
                continue
            use = self._clean_text_value(
                item.get("replacementText")
                or item.get("replacement_text")
                or item.get("use")
                or item.get("new")
                or item.get("better")
            )
            if not use:
                continue
            instead_of = self._clean_text_value(
                item.get("targetText")
                or item.get("target_text")
                or item.get("instead_of")
                or item.get("old")
                or item.get("weak")
            )
            cleaned.append(
                {
                    "instead_of": instead_of,
                    "use": use,
                    "why": self._clean_text_value(item.get("why"))
                    or self._clean_text_value(item.get("reason"))
                    or "This sounds more natural for describing an image.",
                    "example": self._clean_text_value(item.get("example")),
                    "final_preview": self._clean_text_value(
                        item.get("finalPreview") or item.get("final_preview")
                    ),
                }
            )
        return cleaned or fallback

    def _normalize_phrase_usage(
        self,
        raw_value: Any,
        *,
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        payload = raw_value if isinstance(raw_value, dict) else {}
        partial_items = self._normalize_phrase_issue_list(
            payload.get("partial") or fallback.get("partial") or [],
            include_attempt=True,
        )
        misused_items = self._normalize_phrase_issue_list(
            payload.get("misused") or fallback.get("misused") or [],
            include_attempt=False,
        )

        used = self._clean_string_list(
            payload.get("usedWell") or payload.get("used") or fallback.get("used") or [],
            limit=5,
        )
        suggested = self._clean_string_list(
            payload.get("tryNext") or payload.get("suggested") or fallback.get("suggested") or [],
            limit=3,
        )
        rewardable_count = payload.get("rewardable_count", fallback.get("rewardable_count", len(used)))
        try:
            rewardable_count = int(rewardable_count)
        except (TypeError, ValueError):
            rewardable_count = len(used)
        rewardable_count = max(0, min(len(used), rewardable_count))
        message = self._clean_text_value(payload.get("message")) or self._clean_text_value(
            fallback.get("message") or ""
        )
        return {
            "used": used,
            "suggested": suggested,
            "partial": partial_items,
            "misused": misused_items,
            "rewardable_count": rewardable_count,
            "message": message
            or self._phrase_usage_message(
                used=used,
                suggested=suggested,
                partial=partial_items,
                misused=misused_items,
            ),
        }

    def _normalize_phrase_issue_list(
        self,
        raw_items: Any,
        *,
        include_attempt: bool,
    ) -> list[dict[str, str]]:
        cleaned: list[dict[str, str]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            phrase = self._clean_text_value(item.get("phrase"))
            note = self._clean_text_value(item.get("note"))
            if phrase:
                cleaned_item = {"phrase": phrase, "note": note}
                if include_attempt:
                    cleaned_item["attempt"] = self._clean_text_value(item.get("attempt"))
                cleaned.append(cleaned_item)
                if len(cleaned) >= 3:
                    break
        return cleaned

    def _phrase_usage_message(
        self,
        *,
        used: list[str],
        suggested: list[str],
        partial: list[dict[str, str]],
        misused: list[dict[str, str]],
    ) -> str:
        if misused:
            issue = misused[0]
            note = issue.get("note") or "Use it inside a complete sentence."
            return f"Reusable language: '{issue['phrase']}' needs adjustment. {note}"
        if used:
            message = f"Reusable language: Good use of reusable language: {', '.join(used[:2])}."
            if suggested:
                message += f" Try adding '{suggested[0]}' next."
            return message
        if partial:
            item = partial[0]
            attempt = item.get("attempt") or "part of the phrase"
            return (
                f"Reusable language: You used '{attempt}', but try the full phrase "
                f"'{item['phrase']}' for stronger expression."
            )
        if suggested:
            return (
                "Reusable language: Your explanation can still be clear without exact phrases, "
                f"but try using '{suggested[0]}' to strengthen your vocabulary."
            )
        return "Reusable language: Try using one learned phrase naturally in your rewrite."

    def _heuristic_grammar_score(
        self,
        *,
        text: str,
        words: list[str],
        sentences: list[str],
    ) -> int:
        if not words:
            return 1
        score = 5
        if sentences:
            score += 1
        if text and text[0].isupper():
            score += 1
        if re.search(r"[.!?]$", text.strip()):
            score += 1
        if not re.search(r"\b(is|are|am|was|were|has|have|do|does|can|seems|appears)\b", text, re.I):
            score -= 1
        if re.search(r"\b(a|an)\s+[aeiou]", text, re.I) or re.search(r"\ban\s+[^aeiou\s]", text, re.I):
            score -= 1
        if re.search(r"\b(he|she|it)\s+are\b|\b(they|we|you)\s+is\b", text, re.I):
            score -= 2
        return max(1, min(10, score))

    def _heuristic_naturalness_score(
        self,
        *,
        text: str,
        phrase_usage: dict[str, Any],
        sentence_count: int,
    ) -> int:
        score = 5
        if sentence_count >= 2:
            score += 1
        if re.search(r"\b(in the background|next to|near|appears to be|looks like|in front of)\b", text, re.I):
            score += 2
        if phrase_usage.get("used"):
            score += 1
        if phrase_usage.get("misused"):
            score -= 2
        if re.search(r"\bvery very|good good|nice picture|beautiful image\b", text, re.I):
            score -= 1
        return max(1, min(10, score))

    def _heuristic_reusable_language_score(self, phrase_usage: dict[str, Any]) -> int:
        used_count = len(phrase_usage.get("used") or [])
        rewardable = int(phrase_usage.get("rewardable_count") or 0)
        misused_count = len(phrase_usage.get("misused") or [])
        partial_count = len(phrase_usage.get("partial") or [])
        score = 4 + min(3, used_count) + min(2, rewardable) + min(1, partial_count)
        score -= min(3, misused_count * 2)
        return max(1, min(10, score))

    def _retry_feedback(
        self,
        *,
        score: int,
        main_issue: str,
        fixes: list[str],
        max_score: int = 15,
    ) -> dict[str, Any]:
        score_cap = max(1, min(45, int(max_score)))
        score = max(1, min(score_cap, int(score)))
        return {
            "score": score,
            "scores": {"vocabulary": 1, "structure": 1, "depth": 1, "clarity": 1},
            "language_quality": {
                "score": 0,
                "clarity": 0,
                "vocabulary": 0,
                "structure": 0,
                "grammar": 0,
                "naturalness": 0,
                "reusableLanguage": 0,
            },
            "coverage": {
                "level": "low",
                "mainSubjectMentioned": False,
                "mainActionMentioned": False,
                "imageParts": [],
                "missingMajorParts": [],
                "coverageScore": 0,
                "coveragePercent": 0,
                "accuracyPenalty": 0,
                "scoreCapApplied": score_cap,
                "reason": main_issue,
            },
            "readiness": {
                "ready": False,
                "reason": main_issue,
                "criteria": {
                    "mainSubject": False,
                    "mainAction": False,
                    "settingBackground": False,
                    "twoImportantDetails": False,
                    "naturalEnglish": False,
                    "notAWordList": False,
                    "overallSense": False,
                },
            },
            "is_ready": False,
            "main_issue": main_issue,
            "what_did_well": [],
            "missing_details": [],
            "phrase_usage": {
                "used": [],
                "suggested": [],
                "partial": [],
                "misused": [],
                "rewardable_count": 0,
                "message": "None yet. First, write a clear description of the image.",
            },
            "fix_this_to_improve": fixes[:3],
            "next_step_instructions": fixes[:2],
            "word_phrase_upgrades": [],
            "improvements": fixes[:3],
            "better_version": "",
            "alternatives": [],
            "weak_points": fixes[:3],
            "reusable_sentence_structures": [],
            "retry_required": True,
            "retry_message": "Try again with a clear sentence about what you can see.",
            "cta_label": "Try Again",
        }

    def _heuristic_explanation_feedback(
        self,
        *,
        learner_text: str,
        original_text: str,
        analysis: dict[str, Any],
    ) -> dict[str, Any]:
        text = re.sub(r"\s+", " ", learner_text.strip())
        words = re.findall(r"[A-Za-z']+", text)
        sentences = self._split_sentences(text) or ([text] if text else [])
        vocab_items = analysis.get("vocabulary", [])[:6]
        phrase_items = analysis.get("phrases", [])[:6]
        pattern_items = analysis.get("sentence_patterns", [])[:5]
        object_items = analysis.get("objects", [])[:8]
        action_items = analysis.get("actions", [])[:6]
        environment_details = analysis.get("environment_details", [])[:6]
        required_parts = self._extract_required_image_parts(analysis)

        used_vocab = [
            str(item.get("word") or "").strip()
            for item in vocab_items
            if self._word_in_text(str(item.get("word") or ""), text)
        ]
        used_phrases = [
            str(item.get("phrase") or "").strip()
            for item in phrase_items
            if self._phrase_in_text(str(item.get("phrase") or ""), text)
        ]
        missing_vocab = [
            str(item.get("word") or "").strip()
            for item in vocab_items
            if str(item.get("word") or "").strip() not in used_vocab
        ][:3]
        missing_phrases = [
            str(item.get("phrase") or "").strip()
            for item in phrase_items
            if str(item.get("phrase") or "").strip() not in used_phrases
        ][:3]
        phrase_usage = self._detect_reusable_phrase_usage(text, phrase_items)
        used_phrases = list(dict.fromkeys([*used_phrases, *phrase_usage["used"]]))
        missing_phrases = [
            str(item.get("phrase") or "").strip()
            for item in phrase_items
            if str(item.get("phrase") or "").strip()
            and str(item.get("phrase") or "").strip() not in used_phrases
        ][:3]

        visual_targets = self._feedback_visual_targets(
            objects=object_items,
            actions=action_items,
            environment_details=environment_details,
        )
        mentioned_targets = [
            item for item in visual_targets if self._feedback_target_in_text(item["text"], text)
        ]
        primary_subject = self._primary_subject_name(object_items)
        main_subject_mentioned = (
            self._feedback_subject_in_text(primary_subject, text)
            if primary_subject
            else True
        )
        setting_targets = [
            str(analysis.get("environment") or "").strip(),
            *[str(item or "").strip() for item in environment_details],
        ]
        setting_mentioned = any(
            self._feedback_target_in_text(target, text)
            for target in setting_targets
            if target
        ) or self._feedback_setting_word_in_text(text)
        action_mentioned = any(
            self._feedback_target_in_text(
                str(item.get("phrase") or item.get("verb") or ""), text
            )
            for item in action_items
        )
        mentioned_detail_labels = [
            item["label"]
            for item in mentioned_targets
            if normalize_answer(item["label"]) != normalize_answer(primary_subject)
        ]
        non_setting_detail_count = len(
            [
                label
                for label in mentioned_detail_labels
                if not any(
                    normalize_answer(label) == normalize_answer(target)
                    for target in setting_targets
                    if target
                )
            ]
        )
        if action_mentioned:
            non_setting_detail_count += 1
        mood_mentioned = self._feedback_mood_in_text(text)
        foreground_mentioned = self._feedback_foreground_in_text(text) or non_setting_detail_count >= 2
        action_required = bool(action_items)

        missing_details = self._coverage_missing_major_parts(
            primary_subject=primary_subject,
            main_subject_mentioned=main_subject_mentioned,
            action_required=action_required,
            action_mentioned=action_mentioned,
            setting_mentioned=setting_mentioned,
            foreground_mentioned=foreground_mentioned,
            important_detail_count=non_setting_detail_count,
            mood_mentioned=mood_mentioned,
            fallback_details=[
                item["label"] for item in visual_targets if item not in mentioned_targets
            ],
        )

        lexical_variety = len({word.casefold() for word in words if len(word) > 3})
        vocab_score = min(
            10,
            max(
                3,
                4
                + min(3, lexical_variety // 4)
                + min(2, len(set(used_vocab)) + len(set(used_phrases))),
            ),
        )
        if phrase_usage["used"]:
            vocab_score = min(10, vocab_score + (1 if len(phrase_usage["used"]) == 1 else 2))
        elif vocab_score >= 7:
            vocab_score -= 1
        structure_score = min(
            10,
            max(3, 4 + min(3, len(sentences)) + (1 if "," in text else 0) + (1 if len(words) >= 18 else 0)),
        )
        depth_score = min(
            10,
            max(
                2,
                3
                + min(3, len(words) // 8)
                + min(3, int(main_subject_mentioned) + int(setting_mentioned) + non_setting_detail_count),
            ),
        )
        clarity_score = min(
            10,
            max(3, 5 + (2 if len(words) >= 10 else 0) + (1 if sentences else 0) + (1 if len(text) > 0 and text[0].isupper() else 0)),
        )
        grammar_score = self._heuristic_grammar_score(text=text, words=words, sentences=sentences)
        naturalness_score = self._heuristic_naturalness_score(
            text=text,
            phrase_usage=phrase_usage,
            sentence_count=len(sentences),
        )
        reusable_score = self._heuristic_reusable_language_score(phrase_usage)
        language_quality = {
            "clarity": clarity_score * 10,
            "vocabulary": vocab_score * 10,
            "structure": structure_score * 10,
            "grammar": grammar_score * 10,
            "naturalness": naturalness_score * 10,
            "reusableLanguage": reusable_score * 10,
        }
        language_quality["score"] = self._weighted_language_quality_score(language_quality)

        patterns = [
            str(item.get("pattern") or "").strip()
            for item in pattern_items
            if str(item.get("pattern") or "").strip()
        ]
        if not patterns:
            patterns = [
                "There is/are ... in the image.",
                "In the background, ...",
                "The main subject is ...",
            ]

        alternatives: list[dict[str, str]] = []
        for phrase in missing_phrases[:3]:
            alternatives.append(
                {
                    "instead_of": "simple wording",
                    "use": phrase,
                    "why": "It gives your image description a reusable natural phrase.",
                }
            )
        for word in missing_vocab[:2]:
            alternatives.append(
                {
                    "instead_of": "general word",
                    "use": word,
                    "why": "It names an important detail more clearly.",
                }
            )

        weak_points = []
        if len(sentences) < 2:
            weak_points.append("Add one more sentence with a detail or position.")
        if not used_phrases:
            weak_points.append("Use at least one reusable phrase from the lesson.")
        if len(words) < 12:
            weak_points.append("Make the explanation a little deeper.")
        if missing_details:
            weak_points.append(f"Missing visual detail: {missing_details[0]}.")
        if not weak_points:
            weak_points.append("Keep improving sentence variety and detail.")

        improvements = [
            "Keep your own idea, but make the details more specific.",
            "Use position or relationship language when it helps the image feel clearer.",
            "Upgrade general wording with stronger image vocabulary.",
        ]
        if missing_vocab:
            improvements.append(f"Try adding: {', '.join(missing_vocab)}.")
        if missing_phrases:
            improvements.append(f"Try a phrase like: {missing_phrases[0]}.")
        if missing_details:
            improvements.append(f"Add this missing visual detail: {missing_details[0]}.")

        language_score = int(language_quality["score"])
        coverage = self._heuristic_coverage(
            required_parts=required_parts,
            learner_text=text,
            primary_subject=primary_subject,
            main_subject_mentioned=main_subject_mentioned,
            action_required=action_required,
            action_mentioned=action_mentioned,
            setting_mentioned=setting_mentioned,
            foreground_mentioned=foreground_mentioned,
            important_detail_count=non_setting_detail_count,
            mood_mentioned=mood_mentioned,
            word_count=len(words),
        )
        coverage["missingMajorParts"] = missing_details[:4]
        coverage_score = int(coverage.get("coverageScore") or coverage.get("coveragePercent") or 0)
        accuracy_penalty = int(coverage.get("accuracyPenalty") or 0)
        score_cap = int(coverage["scoreCapApplied"])
        language_bonus = self._language_quality_bonus(language_score)
        score = max(
            0,
            min(score_cap, coverage_score + language_bonus - accuracy_penalty),
        )
        score = min(score, score_cap)
        coverage_missing_details = self._prioritized_missing_part_labels(coverage)
        if coverage_missing_details:
            missing_details = coverage_missing_details
            coverage["missingMajorParts"] = coverage_missing_details[:5]
        better_text = self._improve_learner_text(
            text,
            missing_details=self._improved_version_missing_details(coverage, missing_details),
            missing_phrases=missing_phrases,
            missing_vocab=missing_vocab,
        )
        what_did_well = []
        covered_summary = self._covered_parts_summary(coverage)
        if covered_summary:
            what_did_well.append(f"You covered {covered_summary}.")
        if len(words) >= 10:
            what_did_well.append("You wrote enough to communicate a clear idea.")
        if clarity_score >= 7:
            what_did_well.append("Your meaning is understandable.")
        if used_vocab or used_phrases:
            what_did_well.append("You used useful image-related language.")
        if not what_did_well:
            what_did_well.append("You started with your own observation, which is the right habit.")

        main_issue = self._coverage_feedback_main_issue(
            coverage=coverage,
            fallback=(
                f"You missed an important visible detail: {missing_details[0]}."
                if missing_details
                else "Your answer is understandable; now make it more specific and natural."
            ),
        )
        fix_this = [
            "Keep your original idea, but add the major parts of the image.",
            "Make the sentence structure smoother and more complete.",
        ]
        if missing_details:
            fix_this.insert(0, f"Mention {missing_details[0]} if it fits your observation.")
        phrase_message = self._phrase_usage_message(
            used=phrase_usage["used"],
            suggested=missing_phrases[:3],
            partial=phrase_usage["partial"],
            misused=phrase_usage["misused"],
        )
        if phrase_usage["used"]:
            what_did_well.append(phrase_message)
        elif phrase_usage["partial"]:
            fix_this.append(phrase_message)
        elif missing_phrases:
            fix_this.append(f"Use one learned phrase naturally, such as '{missing_phrases[0]}'.")

        readiness = self._normalize_feedback_readiness(
            {},
            coverage=coverage,
            score=score,
            fallback={},
        )
        next_step_instructions = self._build_next_step_instructions(
            feedback={
                "missing_details": missing_details,
                "coverage": coverage,
                "word_phrase_upgrades": alternatives,
                "reusable_sentence_structures": patterns,
            },
            analysis=analysis,
        )

        return {
            "score": score,
            "scores": {
                "vocabulary": vocab_score,
                "structure": structure_score,
                "depth": depth_score,
                "clarity": clarity_score,
            },
            "language_quality": language_quality,
            "coverage": coverage,
            "readiness": readiness,
            "is_ready": bool(readiness.get("ready")),
            "main_issue": main_issue,
            "what_did_well": what_did_well[:4],
            "missing_details": missing_details or ["No major visual detail is missing; focus on making the wording stronger."],
            "phrase_usage": {
                "used": phrase_usage["used"],
                "suggested": missing_phrases[:3],
                "partial": phrase_usage["partial"],
                "misused": phrase_usage["misused"],
                "rewardable_count": phrase_usage["rewardable_count"],
                "message": phrase_message,
            },
            "fix_this_to_improve": fix_this[:5],
            "next_step_instructions": next_step_instructions,
            "word_phrase_upgrades": alternatives[:5]
            or [
                {
                    "instead_of": "simple wording",
                    "use": patterns[0],
                    "why": "This gives you a reusable frame while keeping your own idea.",
                }
            ],
            "improvements": improvements[:5],
            "better_version": better_text,
            "alternatives": alternatives[:5]
            or [
                {
                    "instead_of": "short sentence",
                    "use": patterns[0],
                    "why": "This gives you a reusable frame for describing images.",
                }
            ],
            "weak_points": weak_points[:4],
            "reusable_sentence_structures": patterns[:5],
        }

    def _extract_required_image_parts(self, analysis: dict[str, Any]) -> list[dict[str, Any]]:
        objects = analysis.get("objects", [])[:8]
        actions = analysis.get("actions", [])[:4]
        environment = self._clean_text_value(analysis.get("environment"))
        environment_details = self._clean_string_list(
            analysis.get("environment_details") or [],
            limit=6,
        )
        explanation = self._clean_text_value(
            analysis.get("natural_explanation")
            or analysis.get("scene_summary_natural")
            or analysis.get("native_explanation")
        )
        primary_subject = self._primary_subject_name(objects)
        has_action = bool(actions)
        mood = self._mood_part_description(analysis, explanation, environment)
        weights = self._required_part_weights(
            has_action=has_action,
            mood_present=bool(mood),
            mood_important=self._mood_part_is_important(analysis, explanation, mood),
        )

        parts: list[dict[str, Any]] = []

        def push(part_type: str, name: str, description: str, weight: float) -> None:
            cleaned_name = self._clean_text_value(name)
            cleaned_description = self._clean_text_value(description)
            if not cleaned_name and not cleaned_description:
                return
            if any(item["type"] == part_type for item in parts):
                return
            parts.append(
                {
                    "type": part_type,
                    "name": cleaned_name or part_type.replace("_", " "),
                    "description": cleaned_description or cleaned_name,
                    "weight": float(weight),
                }
            )

        primary_object = self._object_by_name(objects, primary_subject)
        if primary_subject:
            push(
                "main_subject",
                primary_subject,
                str((primary_object or {}).get("description") or primary_subject),
                weights["main_subject"],
            )

        if has_action:
            action = actions[0]
            action_name = str(action.get("phrase") or action.get("verb") or "main action")
            action_description = str(action.get("description") or action.get("phrase") or action_name)
            push("main_action", action_name, action_description, weights["main_action"])

        setting_description = "; ".join([item for item in [environment, *environment_details[:3]] if item])
        if setting_description:
            push("setting", "setting/background", setting_description, weights["setting"])

        important_objects = [
            str(item.get("name") or "").strip()
            for item in objects
            if str(item.get("name") or "").strip()
            and normalize_answer(str(item.get("name") or "")) != normalize_answer(primary_subject)
        ][:3]
        if important_objects:
            push(
                "important_object",
                "important objects",
                ", ".join(important_objects),
                weights["important_object"],
            )

        foreground = self._foreground_part_description(objects, environment_details, explanation)
        if foreground:
            push("foreground", "foreground/details", foreground, weights["foreground"])

        if mood:
            push("mood", "mood/overall meaning", mood, weights["mood"])

        self._normalize_required_part_weights(parts)
        return parts

    def _required_part_weights(
        self,
        *,
        has_action: bool,
        mood_present: bool,
        mood_important: bool,
    ) -> dict[str, float]:
        weights = {
            "main_subject": 25.0,
            "main_action": 20.0 if has_action else 0.0,
            "setting": 15.0,
            "important_object": 15.0,
            "foreground": 10.0,
            "mood": 15.0 if mood_present else 0.0,
        }
        if not has_action:
            weights["main_subject"] += 8.0
            weights["important_object"] += 6.0
            weights["setting"] += 6.0
        if mood_present and not mood_important:
            mood_shift = min(10.0, weights["mood"])
            weights["mood"] -= mood_shift
            weights["main_subject"] += 6.0
            weights["foreground"] += mood_shift - 6.0
        return weights

    def _default_required_image_parts(
        self,
        *,
        primary_subject: str,
        action_required: bool,
    ) -> list[dict[str, Any]]:
        parts = [
            {
                "type": "main_subject",
                "name": "main subject",
                "description": primary_subject or "the main subject",
                "weight": 25.0,
            },
            {
                "type": "setting",
                "name": "setting/background",
                "description": "the setting or background",
                "weight": 15.0,
            },
            {
                "type": "important_object",
                "name": "important objects",
                "description": "important visible objects",
                "weight": 15.0,
            },
            {
                "type": "foreground",
                "name": "foreground/details",
                "description": "foreground or nearby visible details",
                "weight": 10.0,
            },
            {
                "type": "mood",
                "name": "mood/overall meaning",
                "description": "the mood or overall meaning",
                "weight": 15.0,
            },
        ]
        if action_required:
            parts.insert(
                1,
                {
                    "type": "main_action",
                    "name": "main action",
                    "description": "the main visible action",
                    "weight": 20.0,
                },
            )
        else:
            parts[0]["weight"] = 33.0
            parts[1]["weight"] = 21.0
            parts[2]["weight"] = 21.0
        self._normalize_required_part_weights(parts)
        return parts

    def _normalize_required_part_weights(self, parts: list[dict[str, Any]]) -> None:
        total = sum(float(item.get("weight") or 0.0) for item in parts)
        if total <= 0:
            return
        for item in parts:
            item["weight"] = round((float(item.get("weight") or 0.0) / total) * 100, 2)

    def _object_by_name(self, objects: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
        normalized_name = normalize_answer(name)
        for item in objects:
            if normalize_answer(str(item.get("name") or "")) == normalized_name:
                return item
        return None

    def _foreground_part_description(
        self,
        objects: list[dict[str, Any]],
        environment_details: list[Any],
        explanation: str,
    ) -> str:
        foreground_markers = {
            "foreground",
            "front",
            "near",
            "nearby",
            "close",
            "grass",
            "ground",
            "floor",
            "path",
            "pavement",
            "road",
            "table",
        }
        for item in objects:
            text = " ".join(
                [
                    str(item.get("name") or ""),
                    str(item.get("position") or ""),
                    str(item.get("description") or ""),
                ]
            )
            if any(self._word_in_text(marker, text) for marker in foreground_markers):
                return self._clean_text_value(str(item.get("description") or item.get("name") or ""))
        for detail in environment_details:
            detail_text = str(detail or "")
            if any(self._word_in_text(marker, detail_text) for marker in foreground_markers):
                return self._clean_text_value(detail_text)
        if any(self._word_in_text(marker, explanation) for marker in foreground_markers):
            return "foreground or nearest visible details"
        return ""

    def _mood_part_description(
        self,
        analysis: dict[str, Any],
        explanation: str,
        environment: str,
    ) -> str:
        raw_analysis = analysis.get("raw_analysis") if isinstance(analysis.get("raw_analysis"), dict) else {}
        raw_environment = raw_analysis.get("environment")
        raw_environment_mood = (
            raw_environment.get("mood")
            if isinstance(raw_environment, dict)
            else ""
        )
        mood = self._clean_text_value(
            raw_analysis.get("mood")
            or raw_analysis.get("atmosphere")
            or raw_environment_mood
        )
        if mood:
            return mood
        combined = f"{explanation} {environment}"
        mood_words = [
            "calm",
            "peaceful",
            "quiet",
            "busy",
            "crowded",
            "relaxed",
            "serious",
            "happy",
            "sad",
            "warm",
            "bright",
            "dark",
            "friendly",
            "lonely",
            "comfortable",
            "tense",
            "casual",
            "sunny",
            "tidy",
        ]
        for word in mood_words:
            if self._word_in_text(word, combined):
                return f"{word} atmosphere"
        return ""

    def _mood_part_is_important(
        self,
        analysis: dict[str, Any],
        explanation: str,
        mood: str,
    ) -> bool:
        if not mood:
            return False
        raw_analysis = analysis.get("raw_analysis") if isinstance(analysis.get("raw_analysis"), dict) else {}
        raw_environment = raw_analysis.get("environment")
        if raw_analysis.get("mood") or raw_analysis.get("atmosphere"):
            return True
        if isinstance(raw_environment, dict) and raw_environment.get("mood"):
            return True
        mood_terms = {
            "calm",
            "peaceful",
            "busy",
            "crowded",
            "tense",
            "lonely",
            "dramatic",
            "serious",
            "cheerful",
            "relaxed",
        }
        normalized_mood = normalize_answer(mood)
        if any(term in normalized_mood for term in mood_terms):
            return True
        mood_mentions = sum(
            1 for term in mood_terms if self._word_in_text(term, explanation)
        )
        return mood_mentions >= 2

    def _feedback_subject_in_text(self, subject: str, text: str) -> bool:
        subject = str(subject or "").strip()
        if not subject:
            return False
        terms = [subject]
        normalized = normalize_answer(subject)
        person_terms = {"person", "people", "man", "woman", "child", "children", "boy", "girl"}
        if set(normalized.split()) & person_terms:
            terms.extend(["person", "people", "man", "woman", "child", "boy", "girl", "someone"])
        vehicle_terms = {"car", "bus", "truck", "vehicle", "bike", "bicycle", "motorcycle"}
        if set(normalized.split()) & vehicle_terms:
            terms.extend(["car", "bus", "truck", "vehicle", "bike", "bicycle", "motorcycle"])
        return any(self._feedback_target_in_text(term, text) for term in terms)

    def _feedback_setting_word_in_text(self, text: str) -> bool:
        setting_words = {
            "background",
            "setting",
            "outside",
            "outdoor",
            "indoors",
            "indoor",
            "street",
            "road",
            "park",
            "room",
            "river",
            "garden",
            "sky",
            "bridge",
            "building",
            "cafe",
            "market",
            "forest",
            "beach",
        }
        return any(self._word_in_text(word, text) for word in setting_words)

    def _feedback_mood_in_text(self, text: str) -> bool:
        mood_words = {
            "calm",
            "peaceful",
            "quiet",
            "busy",
            "crowded",
            "relaxed",
            "serious",
            "happy",
            "sad",
            "warm",
            "cold",
            "bright",
            "dark",
            "friendly",
            "lonely",
            "comfortable",
            "tense",
            "casual",
        }
        return any(self._word_in_text(word, text) for word in mood_words)

    def _feedback_foreground_in_text(self, text: str) -> bool:
        foreground_words = {
            "foreground",
            "front",
            "near",
            "nearby",
            "close",
            "grass",
            "ground",
            "floor",
            "path",
            "pavement",
            "road",
            "table",
        }
        return any(self._word_in_text(word, text) for word in foreground_words)

    def _coverage_missing_major_parts(
        self,
        *,
        primary_subject: str,
        main_subject_mentioned: bool,
        action_required: bool,
        action_mentioned: bool,
        setting_mentioned: bool,
        foreground_mentioned: bool,
        important_detail_count: int,
        mood_mentioned: bool,
        fallback_details: list[str],
    ) -> list[str]:
        missing: list[str] = []
        if primary_subject and not main_subject_mentioned:
            missing.append(f"the main subject ({primary_subject})")
        if action_required and not action_mentioned:
            missing.append("the main action")
        if not setting_mentioned:
            missing.append("the setting or background")
        if important_detail_count < 1:
            missing.append("important objects or visible details")
        if not foreground_mentioned:
            missing.append("the foreground or nearest visible details")
        if mood_mentioned is False:
            missing.append("the mood or atmosphere")
        for detail in fallback_details:
            if len(missing) >= 4:
                break
            if detail not in missing:
                missing.append(detail)
        return missing[:4]

    def _heuristic_coverage(
        self,
        *,
        required_parts: list[dict[str, Any]],
        learner_text: str,
        primary_subject: str,
        main_subject_mentioned: bool,
        action_required: bool,
        action_mentioned: bool,
        setting_mentioned: bool,
        foreground_mentioned: bool,
        important_detail_count: int,
        mood_mentioned: bool,
        word_count: int,
    ) -> dict[str, Any]:
        parts = self._heuristic_coverage_parts(
            required_parts=required_parts,
            learner_text=learner_text,
            primary_subject=primary_subject,
            main_subject_mentioned=main_subject_mentioned,
            action_required=action_required,
            action_mentioned=action_mentioned,
            setting_mentioned=setting_mentioned,
            foreground_mentioned=foreground_mentioned,
            important_detail_count=important_detail_count,
            mood_mentioned=mood_mentioned,
        )
        total_weight = sum(float(part["weight"]) for part in parts) or 1.0
        covered_weight = sum(
            float(part["weight"]) * self._coverage_status_credit(str(part.get("coverageStatus") or "missing"))
            for part in parts
        )
        coverage_score = round((covered_weight / total_weight) * 100)
        coverage_percent = coverage_score
        accuracy_penalty = min(
            25,
            sum(
                12 if part.get("type") in {"main_subject", "main_action"} else 7
                for part in parts
                if part.get("coverageStatus") == "inaccurate"
            ),
        )
        cap_result = self._hard_score_cap(
            parts=parts,
            coverage_score=coverage_score,
            word_count=word_count,
            main_subject_mentioned=main_subject_mentioned,
            action_required=action_required,
            action_mentioned=action_mentioned,
            setting_mentioned=setting_mentioned,
            important_detail_count=important_detail_count,
            mood_mentioned=mood_mentioned,
        )

        return {
            "level": cap_result["level"],
            "imageParts": parts,
            "missingMajorParts": [part["part"] for part in parts if not part["covered"]][:5],
            "coverageScore": coverage_score,
            "coveragePercent": coverage_percent,
            "mainSubjectMentioned": main_subject_mentioned,
            "mainActionMentioned": action_mentioned if action_required else False,
            "accuracyPenalty": accuracy_penalty,
            "scoreCapApplied": cap_result["cap"],
            "reason": cap_result["reason"],
        }

    def _hard_score_cap(
        self,
        *,
        parts: list[dict[str, Any]],
        coverage_score: int,
        word_count: int,
        main_subject_mentioned: bool,
        action_required: bool,
        action_mentioned: bool,
        setting_mentioned: bool,
        important_detail_count: int,
        mood_mentioned: bool,
    ) -> dict[str, Any]:
        credited_parts = [
            part
            for part in parts
            if self._coverage_status_credit(str(part.get("coverageStatus") or "missing")) > 0
        ]
        credited_types = {str(part.get("type") or "") for part in credited_parts}
        credited_count = len(credited_parts)

        if word_count < 4:
            return {
                "level": "low",
                "cap": 15,
                "reason": "Your answer is too short to describe the image clearly.",
            }
        if (
            not main_subject_mentioned
            and (not action_required or not action_mentioned)
            and credited_types
            and credited_types.isdisjoint({"main_subject", "main_action"})
            and bool(credited_types & {"setting", "mood"})
        ):
            return {
                "level": "low",
                "cap": 25,
                "reason": (
                    "Your English may be clear, but you only described the background "
                    "and missed the main subject, main action, and foreground, so your score is limited."
                ),
            }
        if credited_types <= {"foreground", "important_object"} and credited_types:
            return {
                "level": "low",
                "cap": 25,
                "reason": "You only described the foreground, so the overall image is missing.",
            }
        if credited_count <= 1:
            return {
                "level": "low",
                "cap": 30,
                "reason": "You described only one small part of the image, so the score is limited.",
            }
        if not main_subject_mentioned:
            return {
                "level": "low",
                "cap": 40,
                "reason": "Your answer misses the main subject of the image, so the score is limited.",
            }
        if action_required and not action_mentioned:
            return {
                "level": "partial",
                "cap": 50,
                "reason": (
                    "You mentioned the main subject, but you missed the main action, "
                    "so the score is limited."
                ),
            }
        if coverage_score < 45:
            return {
                "level": "partial",
                "cap": 45,
                "reason": "You described only one portion of the image, so the score is limited.",
            }
        if main_subject_mentioned and not setting_mentioned:
            return {
                "level": "partial",
                "cap": 55,
                "reason": (
                    "You mentioned the main subject, but you did not describe the setting "
                    "or background, so the answer feels incomplete."
                ),
            }
        if coverage_score < 70 or important_detail_count < 1:
            return {
                "level": "partial",
                "cap": 70,
                "reason": (
                    "You covered part of the image, but several major parts are still missing."
                ),
            }
        if coverage_score < 85 or not mood_mentioned:
            return {
                "level": "overall",
                "cap": 80,
                "reason": "You covered the overall image, but the answer is still brief or missing depth.",
            }
        if coverage_score < 95:
            return {
                "level": "strong",
                "cap": 90,
                "reason": "You covered most major parts clearly, but it is not fully complete yet.",
            }
        return {
            "level": "strong",
            "cap": 95,
            "reason": "You covered most major parts of the image clearly.",
        }

    def _score_realism_adjustment(
        self,
        *,
        coverage: dict[str, Any],
        language_score: int,
        word_count: int,
    ) -> int:
        coverage_score = int(coverage.get("coverageScore") or coverage.get("coveragePercent") or 0)
        cap = int(coverage.get("scoreCapApplied") or 0)
        main_subject_mentioned = bool(coverage.get("mainSubjectMentioned"))
        if not main_subject_mentioned and language_score >= 75:
            return -5
        if coverage_score >= 80 and word_count <= 16 and language_score >= 55 and cap >= 80:
            return 5
        if coverage_score < 50 and language_score >= 75:
            return -3
        return 0

    def _language_quality_bonus(self, language_score: int) -> int:
        try:
            score = int(language_score)
        except (TypeError, ValueError):
            score = 0
        return max(0, min(10, round(score / 10)))

    def _prioritized_missing_part_labels(self, coverage: dict[str, Any]) -> list[str]:
        parts = coverage.get("imageParts") if isinstance(coverage.get("imageParts"), list) else []
        missing = [
            part
            for part in parts
            if self._coverage_status_credit(str(part.get("coverageStatus") or "missing")) <= 0
        ]
        priority = {
            "main_subject": 0,
            "main_action": 1,
            "setting": 2,
            "important_object": 3,
            "foreground": 4,
            "mood": 5,
        }
        missing.sort(key=lambda part: priority.get(str(part.get("type") or ""), 99))
        labels = [self._coverage_part_label(part) for part in missing]
        return [label for label in labels if label][:5]

    def _coverage_part_label(self, part: dict[str, Any]) -> str:
        part_type = str(part.get("type") or "")
        name = self._clean_text_value(part.get("name"))
        description = self._clean_text_value(part.get("description"))
        if part_type == "main_subject":
            return f"the main subject ({name or description or 'main subject'})"
        if part_type == "main_action":
            return f"the main action ({name or description or 'main action'})"
        if part_type == "setting":
            return "the setting or background"
        if part_type == "important_object":
            return f"important objects ({description or name})" if (description or name) else "important objects"
        if part_type == "foreground":
            return "the foreground or nearest visible details"
        if part_type == "mood":
            return "the mood or atmosphere"
        return description or name

    def _covered_parts_summary(self, coverage: dict[str, Any]) -> str:
        parts = coverage.get("imageParts") if isinstance(coverage.get("imageParts"), list) else []
        covered = [
            self._coverage_part_label(part)
            for part in parts
            if self._coverage_status_credit(str(part.get("coverageStatus") or "missing")) > 0
        ]
        covered = [item for item in covered if item]
        if not covered:
            return ""
        return self._join_natural_list(covered[:3])

    def _coverage_feedback_main_issue(
        self,
        *,
        coverage: dict[str, Any],
        fallback: str,
    ) -> str:
        missing = self._prioritized_missing_part_labels(coverage)
        covered = self._covered_parts_summary(coverage)
        cap = int(coverage.get("scoreCapApplied") or 0)
        reason = self._clean_text_value(coverage.get("reason"))
        if missing:
            missing_text = self._join_natural_list(missing[:3])
            if covered:
                message = f"You covered {covered}, but missed {missing_text}."
            else:
                message = f"You missed {missing_text}."
            if cap and cap < 95:
                message += f" Your score is capped at {cap} because the whole image is not covered."
            elif reason:
                message += f" {reason}"
            return message
        if cap and cap < 95 and reason:
            return f"{reason} Your score is capped at {cap}."
        return fallback

    def _join_natural_list(self, items: list[str]) -> str:
        cleaned = [item for item in items if item]
        if not cleaned:
            return ""
        if len(cleaned) == 1:
            return cleaned[0]
        if len(cleaned) == 2:
            return f"{cleaned[0]} and {cleaned[1]}"
        return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}"

    def _improved_version_missing_details(
        self,
        coverage: dict[str, Any],
        missing_details: list[str],
    ) -> list[str]:
        parts = coverage.get("imageParts") if isinstance(coverage.get("imageParts"), list) else []
        priority = {
            "main_subject": 0,
            "main_action": 1,
            "setting": 2,
            "important_object": 3,
            "foreground": 4,
            "mood": 5,
        }
        missing_parts = [
            part
            for part in parts
            if self._coverage_status_credit(str(part.get("coverageStatus") or "missing")) <= 0
        ]
        missing_parts.sort(key=lambda part: priority.get(str(part.get("type") or ""), 99))
        details = [
            self._clean_text_value(part.get("description")) or self._coverage_part_label(part)
            for part in missing_parts
        ]
        details.extend(missing_details)
        cleaned: list[str] = []
        seen: set[str] = set()
        for detail in details:
            key = normalize_answer(detail)
            if detail and key and key not in seen:
                seen.add(key)
                cleaned.append(detail)
            if len(cleaned) >= 3:
                break
        return cleaned

    def _heuristic_coverage_parts(
        self,
        *,
        required_parts: list[dict[str, Any]],
        learner_text: str,
        primary_subject: str,
        main_subject_mentioned: bool,
        action_required: bool,
        action_mentioned: bool,
        setting_mentioned: bool,
        foreground_mentioned: bool,
        important_detail_count: int,
        mood_mentioned: bool,
    ) -> list[dict[str, Any]]:
        if not required_parts:
            required_parts = self._default_required_image_parts(
                primary_subject=primary_subject,
                action_required=action_required,
            )

        type_coverage = {
            "main_subject": (
                "covered" if main_subject_mentioned else "missing",
                primary_subject if main_subject_mentioned else "",
            ),
            "main_action": (
                "covered" if action_mentioned else "missing",
                "main action mentioned" if action_mentioned else "",
            ),
            "setting": (
                "covered" if setting_mentioned else "missing",
                "setting or background mentioned" if setting_mentioned else "",
            ),
            "important_object": (
                "covered" if important_detail_count >= 2 else "partially_covered" if important_detail_count == 1 else "missing",
                "important visible object mentioned" if important_detail_count >= 1 else "",
            ),
            "foreground": (
                "covered" if foreground_mentioned else "missing",
                "foreground or nearby detail mentioned" if foreground_mentioned else "",
            ),
            "mood": (
                "covered" if mood_mentioned else "missing",
                "mood or overall meaning mentioned" if mood_mentioned else "",
            ),
        }
        parts: list[dict[str, Any]] = []
        for part in required_parts:
            part_type = str(part.get("type") or "").strip()
            coverage_status, evidence = self._part_coverage_status(
                part=part,
                learner_text=learner_text,
                fallback_status=type_coverage.get(part_type, ("missing", ""))[0],
                fallback_evidence=type_coverage.get(part_type, ("missing", ""))[1],
            )
            coverage_status = self._part_accuracy_status(
                part=part,
                learner_text=learner_text,
                default_status=coverage_status,
            )
            parts.append(
                {
                    "part": str(part.get("name") or part_type or "image part"),
                    "name": str(part.get("name") or part_type or "image part"),
                    "description": str(part.get("description") or "").strip(),
                    "type": part_type,
                    "required": True,
                    "weight": float(part.get("weight") or 0.0),
                    "coverageStatus": coverage_status,
                    "covered": coverage_status == "covered",
                    "evidence": evidence,
                }
            )
        return parts

    def _part_coverage_status(
        self,
        *,
        part: dict[str, Any],
        learner_text: str,
        fallback_status: str,
        fallback_evidence: str,
    ) -> tuple[str, str]:
        part_type = str(part.get("type") or "")
        description = str(part.get("description") or "")
        name = str(part.get("name") or "")
        if part_type == "important_object":
            candidates = [
                item.strip()
                for item in re.split(r",|;|\band\b", description)
                if item.strip()
            ]
            candidates = candidates or [name]
            hits = [
                item
                for item in candidates
                if self._feedback_target_in_text(item, learner_text)
            ]
            if len(hits) >= max(1, min(2, len(candidates))):
                return "covered", ", ".join(hits[:2])
            if hits:
                return "partially_covered", hits[0]
            return "missing", ""
        if part_type in {"foreground", "setting", "mood"}:
            if self._feedback_target_in_text(description, learner_text) or self._feedback_target_in_text(name, learner_text):
                return "covered", name
            return fallback_status, fallback_evidence
        return fallback_status, fallback_evidence

    def _coverage_status_credit(self, status: str) -> float:
        if status == "covered":
            return 1.0
        if status == "partially_covered":
            return 0.5
        return 0.0

    def _part_accuracy_status(
        self,
        *,
        part: dict[str, Any],
        learner_text: str,
        default_status: str,
    ) -> str:
        part_type = str(part.get("type") or "")
        expected_text = " ".join(
            [
                str(part.get("name") or ""),
                str(part.get("description") or ""),
            ]
        )
        if not self._has_conflicting_visual_claim(
            expected_text=expected_text,
            learner_text=learner_text,
            part_type=part_type,
        ):
            return default_status
        return "inaccurate"

    def _has_conflicting_visual_claim(
        self,
        *,
        expected_text: str,
        learner_text: str,
        part_type: str,
    ) -> bool:
        expected = normalize_answer(expected_text)
        learner = normalize_answer(learner_text)
        if part_type == "main_action":
            action_conflicts = [
                {"sitting", "standing"},
                {"walking", "running"},
                {"mowing", "driving", "sitting", "standing"},
                {"holding", "throwing"},
            ]
            for group in action_conflicts:
                expected_hits = {word for word in group if word in expected}
                learner_hits = {word for word in group if word in learner}
                if expected_hits and learner_hits and expected_hits.isdisjoint(learner_hits):
                    return True
        if part_type == "setting":
            setting_conflicts = [
                {"indoor", "indoors", "outdoor", "outside"},
                {"day", "night"},
                {"city", "forest", "beach", "room"},
            ]
            for group in setting_conflicts:
                expected_hits = {word for word in group if word in expected}
                learner_hits = {word for word in group if word in learner}
                if expected_hits and learner_hits and expected_hits.isdisjoint(learner_hits):
                    return True
        return False

    def _feedback_visual_targets(
        self,
        *,
        objects: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        environment_details: list[Any],
    ) -> list[dict[str, str]]:
        targets: list[dict[str, str]] = []
        seen: set[str] = set()

        def push(text: str, label: str) -> None:
            cleaned = re.sub(r"\s+", " ", str(text or "").strip())
            key = normalize_answer(cleaned)
            if not cleaned or not key or key in seen:
                return
            seen.add(key)
            targets.append({"text": cleaned, "label": label or cleaned})

        for item in objects:
            name = str(item.get("name") or "").strip()
            position = str(item.get("position") or "").strip()
            description = str(item.get("description") or "").strip()
            if name:
                push(name, name)
            if position and position.lower() not in {"center", "centre"}:
                push(position, f"the {position} area")
            if description:
                for sentence in self._split_sentences(description)[:1]:
                    push(sentence, sentence)

        for item in actions:
            phrase = str(item.get("phrase") or item.get("verb") or "").strip()
            if phrase:
                push(phrase, phrase)

        for item in environment_details:
            push(str(item), str(item))

        return targets[:10]

    def _feedback_target_in_text(self, target: str, text: str) -> bool:
        cleaned = str(target or "").strip()
        if not cleaned:
            return False
        if " " in cleaned:
            words = [
                word
                for word in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", cleaned)
                if word.casefold() not in {"the", "and", "with", "this", "that", "there"}
            ]
            if not words:
                return normalize_answer(cleaned) in normalize_answer(text)
            return any(self._word_in_text(word, text) for word in words[:4])
        return self._word_in_text(cleaned, text)

    def _detect_reusable_phrase_usage(
        self,
        text: str,
        phrase_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        normalized_text = normalize_answer(text)
        used: list[str] = []
        partial: list[dict[str, str]] = []
        misused: list[dict[str, str]] = []
        rewardable_count = 0

        for item in phrase_items:
            phrase = str(item.get("phrase") or "").strip()
            if not phrase:
                continue
            normalized_phrase = normalize_answer(phrase)
            if not normalized_phrase:
                continue
            if normalized_phrase in normalized_text or self._phrase_in_text(phrase, text):
                used.append(phrase)
                if self._phrase_has_context(phrase, text):
                    rewardable_count += 1
                else:
                    misused.append(
                        {
                            "phrase": phrase,
                            "note": self._phrase_context_note(phrase),
                        }
                    )
                continue
            if self._near_phrase_match(normalized_phrase, normalized_text):
                partial.append(
                    {
                        "attempt": self._nearest_phrase_window(normalized_phrase, normalized_text),
                        "phrase": phrase,
                        "note": f"Use the full phrase '{phrase}' for stronger expression.",
                    }
                )
                continue
            partial_attempt = self._partial_phrase_attempt(normalized_phrase, normalized_text)
            if partial_attempt:
                partial.append(
                    {
                        "attempt": partial_attempt,
                        "phrase": phrase,
                        "note": f"Try the full phrase '{phrase}' for stronger expression.",
                    }
                )

        unique_used = list(dict.fromkeys(used))[:5]
        return {
            "used": unique_used,
            "partial": partial[:3],
            "misused": misused[:3],
            "rewardable_count": min(rewardable_count, len(unique_used)),
        }

    def _phrase_has_context(self, phrase: str, text: str) -> bool:
        phrase_words = normalize_answer(phrase).split()
        text_words = normalize_answer(text).split()
        if not phrase_words:
            return False
        if len(text_words) >= len(phrase_words) + 4:
            return True
        return bool(re.search(r"[.!?]\s+\w+", text.strip()))

    def _phrase_context_note(self, phrase: str) -> str:
        normalized = normalize_answer(phrase)
        if normalized.startswith(("under ", "in ", "on ", "next to ", "beside ")):
            return f"Put it in a complete sentence, e.g. 'The main detail is {phrase}.'"
        return f"Use it with enough context, e.g. 'This part of the image feels {phrase}.'"

    def _nearest_phrase_window(self, normalized_phrase: str, normalized_text: str) -> str:
        phrase_words = normalized_phrase.split()
        text_words = normalized_text.split()
        window_size = len(phrase_words)
        best_window = ""
        best_ratio = 0.0
        for index in range(0, max(0, len(text_words) - window_size + 1)):
            window = " ".join(text_words[index : index + window_size])
            ratio = SequenceMatcher(None, normalized_phrase, window).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_window = window
        return best_window

    def _partial_phrase_attempt(self, normalized_phrase: str, normalized_text: str) -> str:
        phrase_words = [
            word
            for word in normalized_phrase.split()
            if len(word) > 3 and word not in {"with", "from", "into", "this", "that"}
        ]
        text_words = set(normalized_text.split())
        matches = [word for word in phrase_words if word in text_words]
        if len(phrase_words) >= 2 and 0 < len(matches) < len(phrase_words):
            return " ".join(matches)
        return ""

    def _near_phrase_match(self, normalized_phrase: str, normalized_text: str) -> bool:
        phrase_words = normalized_phrase.split()
        text_words = normalized_text.split()
        if len(phrase_words) < 2 or len(text_words) < len(phrase_words):
            return False
        window_size = len(phrase_words)
        for index in range(0, len(text_words) - window_size + 1):
            window = " ".join(text_words[index : index + window_size])
            if SequenceMatcher(None, normalized_phrase, window).ratio() >= 0.84:
                return True
        return False

    def _improve_learner_text(
        self,
        text: str,
        *,
        missing_details: list[str],
        missing_phrases: list[str],
        missing_vocab: list[str],
    ) -> str:
        cleaned = self._ensure_sentence_punctuation(re.sub(r"\s+", " ", text.strip()))
        if not cleaned:
            cleaned = "I can see the main subject in the image."

        additions: list[str] = []
        for detail in missing_details[:2]:
            additions.append(f"It also includes {detail}")
        if missing_phrases:
            additions.append(f"This could be described as {missing_phrases[0]}")
        elif missing_vocab:
            additions.append(f"A useful detail to mention is {missing_vocab[0]}")

        if additions:
            addition_text = " ".join(
                self._ensure_sentence_punctuation(addition)
                for addition in additions[:3]
            )
            return f"{cleaned} {addition_text}"
        return cleaned

    def _normalize_scene_guidance(self, raw: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raw = {}
        starter_hints = self._normalize_starter_hints_for_guidance(
            raw.get("starterHints") or raw.get("starter_hints") or []
        )
        sentence_starters = self._normalize_sentence_starters_for_guidance(
            raw.get("sentenceStarters") or raw.get("sentence_starters") or []
        )
        coverage_focuses = self._normalize_coverage_focuses(
            raw.get("coverageFocuses") or raw.get("coverage_focuses") or []
        )

        fallback = self._fallback_scene_guidance()
        return {
            "starterHints": starter_hints or fallback["starterHints"],
            "sentenceStarters": sentence_starters or fallback["sentenceStarters"],
            "coverageFocuses": coverage_focuses or fallback["coverageFocuses"],
            "raw_analysis": raw,
        }

    def _normalize_starter_hints_for_guidance(self, raw_items: Any) -> list[dict[str, str]]:
        hints: list[dict[str, str]] = []
        seen: set[str] = set()
        allowed = {"object", "phrase", "sentence_structure"}
        for item in raw_items if isinstance(raw_items, list) else []:
            if isinstance(item, dict):
                label = self._clean_text_value(item.get("label") or item.get("text") or item.get("phrase"))
                hint_type = self._clean_text_value(item.get("type")).lower()
            else:
                label = self._clean_text_value(item)
                hint_type = "phrase" if len(label.split()) > 1 else "object"
            if hint_type in {"word", "noun"}:
                hint_type = "object"
            if hint_type not in allowed:
                hint_type = "phrase" if len(label.split()) > 1 else "object"
            key = normalize_answer(label)
            if not key or key in seen:
                continue
            seen.add(key)
            hints.append({"label": label[:48], "type": hint_type})
            if len(hints) >= 3:
                break
        return hints

    def _normalize_sentence_starters_for_guidance(self, raw_items: Any) -> list[str]:
        starters: list[str] = []
        seen: set[str] = set()
        for item in raw_items if isinstance(raw_items, list) else []:
            text = self._clean_text_value(item).strip()
            if not text:
                continue
            text = re.sub(r"\s+", " ", text)
            key = normalize_answer(text)
            if key in seen:
                continue
            if re.search(r"\b(man|woman|child|car|tree|building|flower|road|room|person)\b", key):
                continue
            seen.add(key)
            starters.append(text[:60])
            if len(starters) >= 4:
                break
        return starters

    def _normalize_coverage_focuses(self, raw_items: Any) -> list[dict[str, Any]]:
        focuses: list[dict[str, Any]] = []
        seen: set[str] = set()
        seen_aspects: set[str] = set()
        for index, item in enumerate(raw_items if isinstance(raw_items, list) else []):
            if not isinstance(item, dict):
                continue
            title = self._clean_text_value(item.get("title") or item.get("label") or item.get("focus"))
            key = normalize_answer(title)
            if not key or key in seen:
                continue
            aspect_key = self._coverage_focus_aspect_key(item, title)
            if aspect_key and aspect_key in seen_aspects:
                continue
            seen.add(key)
            if aspect_key:
                seen_aspects.add(aspect_key)
            focus_id = self._safe_target_id(item.get("id") or key or f"focus-{index + 1}")
            support_levels = self._normalize_support_levels(item.get("supportLevels") or item.get("support_levels"), title)
            mode = self._clean_text_value(item.get("mode"))
            if mode not in {"add_missing_detail", "polish_existing_detail"}:
                mode = "add_missing_detail"
            already_mentioned = bool(item.get("alreadyMentioned") or item.get("already_mentioned"))
            if already_mentioned:
                mode = "polish_existing_detail"
            focuses.append(
                {
                    "id": focus_id,
                    "title": title[:80],
                    "mode": mode,
                    "alreadyMentioned": already_mentioned,
                    "sourceText": self._clean_text_value(item.get("sourceText") or item.get("source_text"))[:160],
                    "importance": self._normalize_importance(item.get("importance"), default=0.7),
                    "supportLevels": support_levels,
                }
            )
            if len(focuses) >= 5:
                break
        return focuses

    def _coverage_focus_aspect_key(self, item: dict[str, Any], title: str) -> str:
        parts: list[str] = [
            title,
            self._clean_text_value(item.get("id")),
            self._clean_text_value(item.get("label")),
            self._clean_text_value(item.get("focus")),
            self._clean_text_value(item.get("visualFocus") or item.get("visual_focus")),
            self._clean_text_value(item.get("category")),
        ]
        text = normalize_answer(" ".join(part for part in parts if part))
        if not text:
            return ""
        if re.search(r"\b(hold|holding|held|hand|grip|finger)\b", text):
            return "holding"
        if re.search(r"\b(main|subject|stopwatch|device|item)\b", text):
            return "main_subject"
        if re.search(r"\b(structure|building|architecture|shape|display|screen|screens|button|buttons|control|controls)\b", text):
            return "structure"
        if re.search(r"\b(greenery|plant|plants|tree|trees|leaf|leaves|bush|shrub)\b", text):
            return "greenery"
        if re.search(r"\b(atmosphere|sky|mood|cloud|feeling)\b", text):
            return "atmosphere"
        if re.search(r"\b(light|lighting|sun|shadow|reflection)\b", text):
            return "lighting"
        if re.search(r"\b(texture|surface|material)\b", text):
            return "texture"
        if re.search(r"\b(person|people|man|woman|child|crowd)\b", text):
            return "people"
        if re.search(r"\b(walk|walking|run|running|drive|driving|move|moving|action)\b", text):
            return "movement"
        if re.search(r"\b(position|near|beside|behind|front|background|foreground|left|right|around)\b", text):
            return "position"
        return text

    def _normalize_support_levels(self, raw_items: Any, title: str) -> list[dict[str, Any]]:
        by_level: dict[int, dict[str, Any]] = {}
        for item in raw_items if isinstance(raw_items, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                level = int(item.get("level") or 0)
            except (TypeError, ValueError):
                level = 0
            if not 1 <= level <= 3:
                continue
            prompt = self._support_prompt_text(item.get("prompt") or item.get("text"), title, level)
            legacy_hint = item.get("hint") if item.get("prompt") is None else None
            hints = self._normalize_support_level_hints(item.get("hints") or item.get("hint_options") or [], title, level, legacy_hint)
            by_level[level] = {"prompt": prompt, "hints": hints}
        return [
            {
                "level": level,
                "prompt": by_level.get(level, {}).get("prompt") or self._fallback_support_prompt(title, level),
                "hints": by_level.get(level, {}).get("hints") or self._fallback_support_hints(title, level),
            }
            for level in range(1, 4)
        ]

    def _support_prompt_text(self, value: Any, title: str, level: int) -> str:
        text = self._clean_text_value(value)
        if not text:
            return self._fallback_support_prompt(title, level)
        text = text.strip()
        if level == 3 and "___" not in text:
            return self._fallback_support_prompt(title, level)
        if level < 3 and not re.search(r"\?$", text):
            return self._fallback_support_prompt(title, level)
        return text[:180]

    def _fallback_support_prompt(self, title: str, level: int) -> str:
        readable_focus = self._support_focus_phrase(title)
        if level == 1:
            return f"What do you notice about {readable_focus}?"
        if level == 2:
            return f"Can you describe one specific detail about {readable_focus}?"
        if re.match(r"^(how|the way)\b", readable_focus, flags=re.I):
            return "It is ___."
        if re.search(r"\b(and|or)\b", readable_focus, flags=re.I):
            return "I can see ___."
        return f"{readable_focus[:1].upper()}{readable_focus[1:]} is ___."

    def _support_focus_phrase(self, title: str) -> str:
        focus = self._clean_text_value(title).strip(" .") or "this part of the image"
        readable_focus = focus[0].lower() + focus[1:] if focus else "this part of the image"
        if not re.match(r"^(the|a|an|this|that|these|those|how|the way)\b", readable_focus, flags=re.I):
            readable_focus = f"the {readable_focus}"
        return readable_focus

    def _normalize_support_level_hints(
        self,
        values: Any,
        title: str,
        level: int,
        legacy_hint: Any = None,
    ) -> list[str]:
        candidates = values if isinstance(values, list) else []
        if legacy_hint is not None:
            candidates = [legacy_hint, *candidates]
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in candidates:
            hint = self._support_hint_text(value, title)
            if not hint:
                continue
            if len(hint.split()) > 5:
                hint = " ".join(hint.split()[:5]).strip()
            key = normalize_answer(hint)
            if not key or key in seen:
                continue
            seen.add(key)
            cleaned.append(hint[:80])
            if len(cleaned) >= 3:
                break
        return cleaned

    def _fallback_support_hints(self, title: str, level: int) -> list[str]:
        focus = self._support_hint_text(title, title) or "visible detail"
        words = [word for word in re.split(r"\s+", focus) if len(word) > 2]
        short_focus = " ".join(words[:3]) or focus
        return [short_focus[:80]]

    def _support_hint_text(self, value: Any, title: str) -> str:
        text = self._clean_text_value(value)
        clean_title = self._clean_text_value(title)
        if not text:
            return ""
        text = text.replace("?", "").strip()
        replacements = [
            (r"^what do you notice about\s+", ""),
            (r"^what can you add about\s+", ""),
            (r"^what can you add to\s+", ""),
            (r"^look closely at\s+", ""),
            (r"^look at\s+", ""),
            (r"^can you mention\s+", ""),
            (r"^can you describe\s+", ""),
            (r"^describe\s+", ""),
            (r"^which\s+", ""),
            (r"^where is\s+", "position of "),
            (r"^where are\s+", "position of "),
            (r"^who is\s+", ""),
        ]
        for pattern, replacement in replacements:
            text = re.sub(pattern, replacement, text, flags=re.I).strip()
        if not text or re.match(r"^(what|where|who|which|can you|look closely|look at|describe|add|mention|finish|use)\b", text, flags=re.I):
            text = clean_title
        text = re.sub(r"_{2,}", "", text).strip(" .!?")
        return text[:140]

    def _fallback_scene_guidance(self) -> dict[str, Any]:
        return {
            "starterHints": [
                {"label": "main subject", "type": "object"},
                {"label": "in the background", "type": "phrase"},
                {"label": "The image shows...", "type": "sentence_structure"},
            ],
            "sentenceStarters": [
                "The image shows...",
                "In this scene...",
                "Here we can see...",
            ],
            "coverageFocuses": [
                {
                    "id": "main_subject",
                    "title": "Main subject",
                    "importance": 1.0,
                    "supportLevels": self._normalize_support_levels([], "the main subject"),
                },
                {
                    "id": "background_setting",
                    "title": "Background or setting",
                    "importance": 0.8,
                    "supportLevels": self._normalize_support_levels([], "the background or setting"),
                },
                {
                    "id": "visible_details",
                    "title": "Important visible details",
                    "importance": 0.7,
                    "supportLevels": self._normalize_support_levels([], "important visible details"),
                },
            ],
        }

    async def _request_text_generation(
        self,
        *,
        prompt: str,
        max_output_tokens: int,
        temperature: float,
    ) -> str:
        if self.config.ai_backend == "openai" and self.config.openai_api_key:
            payload = {
                "model": self.config.openai_model,
                "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
                "max_output_tokens": max_output_tokens,
            }
            headers = {
                "Authorization": f"Bearer {self.config.openai_api_key}",
                "Content-Type": "application/json",
            }
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.config.openai_base_url}/responses",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
            return self._extract_output_text(response.json())

        raise ValueError("No AI backend is available for articulation enhancement.")

    def _normalize_example_list(
        self,
        target_text: str,
        raw_examples: Any,
        *,
        fallback_examples: list[str],
    ) -> list[str]:
        values = raw_examples if isinstance(raw_examples, list) else []
        matcher = self._phrase_in_text if " " in target_text.strip() else self._word_in_text
        cleaned: list[str] = []
        seen: set[str] = set()

        for value in [*values, *fallback_examples]:
            sentence = self._ensure_sentence_punctuation(str(value or "").strip())
            key = normalize_answer(sentence)
            if not sentence or not key or key in seen or not matcher(target_text, sentence):
                continue
            seen.add(key)
            cleaned.append(sentence)
            if len(cleaned) >= 5:
                break

        return cleaned

    def _normalize_sentence_pattern_examples(
        self,
        raw_examples: Any,
        *,
        fallback_examples: list[str],
    ) -> list[str]:
        values = raw_examples if isinstance(raw_examples, list) else []
        cleaned: list[str] = []
        seen: set[str] = set()

        for value in [*values, *fallback_examples]:
            sentence = self._ensure_sentence_punctuation(str(value or "").strip())
            key = normalize_answer(sentence)
            if (
                not sentence
                or not key
                or key in seen
                or "..." in sentence
                or len(sentence.split()) < 4
            ):
                continue
            seen.add(key)
            cleaned.append(sentence)
            if len(cleaned) >= 5:
                break

        return cleaned

    def _normalize_explanation(self, text: str) -> str:
        cleaned = re.sub(r"\r\n?", "\n", text).strip()
        if not cleaned:
            return ""

        blocks = [
            re.sub(r"\s+", " ", re.sub(r"^[\-\*\u2022]+\s*", "", block.strip()))
            for block in re.split(r"\n\s*\n", cleaned)
            if block.strip()
        ]
        if len(blocks) >= 2:
            return "\n\n".join(blocks[:6])

        sentences = self._split_sentences(cleaned)
        if len(sentences) <= 2:
            return re.sub(r"\s+", " ", cleaned)

        chunk_size = 2 if len(sentences) <= 8 else 3
        paragraphs = [
            " ".join(sentences[index : index + chunk_size]).strip()
            for index in range(0, len(sentences), chunk_size)
            if " ".join(sentences[index : index + chunk_size]).strip()
        ]
        return "\n\n".join(paragraphs[:6])

    def _split_sentences(self, text: str) -> list[str]:
        flattened = re.sub(r"\s*\n+\s*", " ", text.strip())
        return [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", flattened)
            if sentence.strip()
        ]

    def _normalize_simple_summary(self, text: str, *, fallback_text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text.strip())
        if cleaned:
            return cleaned
        sentences = self._split_sentences(fallback_text)
        return " ".join(sentences[:2]).strip()

    def _salvage_analysis_from_output(self, output_text: str) -> dict[str, Any] | None:
        stripped = output_text.strip()
        if not stripped:
            return None

        raw: dict[str, Any] = {
            "starterHints": self._extract_field_value(stripped, "starterHints")
            or self._extract_field_value(stripped, "starter_hints")
            or [],
            "sentenceStarters": self._extract_field_value(stripped, "sentenceStarters")
            or self._extract_field_value(stripped, "sentence_starters")
            or [],
            "coverageFocuses": self._extract_field_value(stripped, "coverageFocuses")
            or self._extract_field_value(stripped, "coverage_focuses")
            or [],
        }
        if not raw["starterHints"] and not raw["sentenceStarters"] and not raw["coverageFocuses"]:
            return None
        return raw

    def _extract_field_value(self, text: str, key: str) -> Any:
        match = re.search(rf'"{re.escape(key)}"\s*:\s*', text)
        if not match:
            return None
        value_text = self._consume_json_value(text, match.end())
        if not value_text:
            return None
        try:
            return json.loads(value_text)
        except json.JSONDecodeError:
            if value_text.startswith('"') and value_text.endswith('"'):
                return self._decode_loose_json_string(value_text[1:-1])
            return None

    def _decode_loose_json_string(self, value: str) -> str:
        text = value.replace("\r\n", "\n").replace("\r", "\n")
        replacements = {
            '\\"': '"',
            "\\n": "\n",
            "\\t": "\t",
            "\\r": "\r",
            "\\/": "/",
            "\\\\": "\\",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        return text.strip()

    def _consume_json_value(self, text: str, start_index: int) -> str | None:
        length = len(text)
        index = start_index
        while index < length and text[index].isspace():
            index += 1
        if index >= length:
            return None

        opener = text[index]
        if opener == '"':
            end_index = self._find_string_end(text, index)
            return text[index : end_index + 1] if end_index is not None else None

        if opener in "[{":
            closer = "]" if opener == "[" else "}"
            depth = 0
            in_string = False
            escaped = False
            for cursor in range(index, length):
                char = text[cursor]
                if in_string:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        in_string = False
                    continue
                if char == '"':
                    in_string = True
                elif char == opener:
                    depth += 1
                elif char == closer:
                    depth -= 1
                    if depth == 0:
                        return text[index : cursor + 1]
            return None

        primitive_match = re.match(r"(true|false|null|-?\d+(?:\.\d+)?)", text[index:])
        if primitive_match:
            return primitive_match.group(1)
        return None

    def _find_string_end(self, text: str, start_index: int) -> int | None:
        escaped = False
        for cursor in range(start_index + 1, len(text)):
            char = text[cursor]
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                return cursor
        return None

    def _normalize_title(
        self,
        title: str,
        *,
        objects: list[dict[str, Any]],
        actions: list[dict[str, Any]],
    ) -> str:
        if title:
            return title
        if actions:
            action = str(actions[0].get("phrase") or actions[0].get("verb") or "").strip()
            if action:
                return action.capitalize()
        if objects:
            return f"About the {objects[0]['name']}"
        return "Image lesson"

    def _primary_subject_name(self, objects: list[dict[str, Any]]) -> str:
        best_name = ""
        best_score = -1.0
        for item in objects:
            try:
                score = float(item.get("importance") or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            name = str(item.get("name") or "").strip()
            if name and score > best_score:
                best_name = name
                best_score = score
        return best_name

    def _normalize_importance(self, value: Any, *, default: float) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return default
        return max(0.0, min(1.0, numeric))

    def _normalize_confidence(self, value: Any, *, default: str = "medium") -> str:
        text = str(value or "").strip().lower()
        if text in {"high", "medium", "low"}:
            return text
        return default

    def _normalize_articulation_targets(
        self,
        raw_items: list[Any],
        *,
        objects: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        environment_text: str,
        environment_details: list[str],
        visual_zones: list[dict[str, Any]],
        vocabulary: list[dict[str, Any]],
        phrases: list[dict[str, Any]],
        natural_explanation: str,
    ) -> list[dict[str, Any]]:
        targets: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in raw_items if isinstance(raw_items, list) else []:
            if not isinstance(item, dict):
                continue
            prompt = self._clean_text_value(item.get("prompt") or "")
            label = self._clean_text_value(item.get("label") or item.get("title") or prompt)
            focus = self._clean_text_value(item.get("visual_focus") or item.get("focus") or label)
            category = self._normalize_target_category(item.get("category") or label or prompt)
            if not prompt and focus:
                prompt = f"Describe {focus}."
            if not label and focus:
                label = focus
            if self._is_generic_articulation_target(label, prompt):
                continue
            evidence = self._clean_string_list(item.get("evidence") or item.get("visual_evidence") or [], limit=4)
            hints = self._clean_string_list(item.get("hints") or item.get("words") or [], limit=6)
            if not (prompt and (focus or evidence or hints)):
                continue
            key = normalize_answer(f"{category} {label} {focus}")
            if key in seen:
                continue
            seen.add(key)
            targets.append(
                {
                    "id": self._safe_target_id(item.get("id") or key or f"target-{len(targets) + 1}"),
                    "label": label[:80],
                    "prompt": self._target_prompt(prompt, focus),
                    "category": category,
                    "visual_focus": focus[:80],
                    "evidence": evidence,
                    "hints": hints,
                    "importance": self._normalize_importance(item.get("importance"), default=0.6),
                }
            )
            if len(targets) >= 6:
                break

        if len(targets) < 3:
            targets = self._fallback_articulation_targets(
                objects=objects,
                actions=actions,
                environment_text=environment_text,
                environment_details=environment_details,
                visual_zones=visual_zones,
                vocabulary=vocabulary,
                phrases=phrases,
                natural_explanation=natural_explanation,
                existing=targets,
            )
        return targets[:6]

    def _fallback_articulation_targets(
        self,
        *,
        objects: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        environment_text: str,
        environment_details: list[str],
        visual_zones: list[dict[str, Any]],
        vocabulary: list[dict[str, Any]],
        phrases: list[dict[str, Any]],
        natural_explanation: str,
        existing: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        targets = list(existing)
        seen = {normalize_answer(f"{item.get('category')} {item.get('label')} {item.get('visual_focus')}") for item in targets}

        def add(label: str, category: str, focus: str, evidence: list[str], hints: list[str], importance: float = 0.55) -> None:
            key = normalize_answer(f"{category} {label} {focus}")
            if not label or key in seen or len(targets) >= 6:
                return
            seen.add(key)
            targets.append(
                {
                    "id": self._safe_target_id(key or f"target-{len(targets) + 1}"),
                    "label": label[:80],
                    "prompt": self._target_prompt(f"Describe {focus or label}.", focus or label),
                    "category": category,
                    "visual_focus": (focus or label)[:80],
                    "evidence": self._clean_string_list(evidence, limit=4),
                    "hints": self._clean_string_list(hints, limit=6),
                    "importance": importance,
                }
            )

        for obj in sorted(objects, key=lambda item: float(item.get("importance") or 0), reverse=True)[:3]:
            name = self._clean_text_value(obj.get("name") or "")
            if not name:
                continue
            evidence = [obj.get("description", ""), obj.get("position", ""), *(obj.get("visual_evidence") or [])]
            hints = [name, obj.get("color", ""), obj.get("position", ""), *(obj.get("visual_evidence") or [])]
            add(f"Add detail about {name}", "appearance", name, evidence, hints, float(obj.get("importance") or 0.6))

        for action in actions[:2]:
            phrase = self._clean_text_value(action.get("phrase") or action.get("verb") or "")
            if phrase:
                category = self._normalize_target_category(phrase)
                add(f"Add detail about {phrase}", category, phrase, [action.get("visible_evidence", ""), action.get("description", "")], [phrase, action.get("verb", "")], float(action.get("importance") or 0.6))

        for zone in sorted(visual_zones, key=lambda item: float(item.get("importance") or 0), reverse=True):
            if len(targets) >= 6:
                break
            zone_name = self._clean_text_value(zone.get("zone") or "").replace("_", " ")
            elements = self._clean_string_list(zone.get("elements") or [], limit=4)
            opportunities = self._clean_string_list(zone.get("articulation_opportunities") or [], limit=4)
            focus = self._best_zone_focus(zone_name=zone_name, elements=elements, opportunities=opportunities)
            if not focus:
                continue
            category = self._normalize_target_category(f"{focus} {' '.join(opportunities)} {zone_name}")
            if category == "detail":
                category = "composition" if zone_name in {"background", "upper composition"} else "environment"
            label = self._zone_target_label(focus=focus, category=category, zone_name=zone_name)
            add(label, category, focus, [zone_name, *elements, *opportunities], [focus, *elements[:2], *opportunities[:2]], float(zone.get("importance") or 0.55))

        for detail in environment_details[:3]:
            clean = self._clean_text_value(detail)
            if clean:
                category = self._normalize_target_category(clean)
                if category == "detail":
                    category = "condition" if re.search(r"\b(dust|dirty|messy|clutter|broken|worn|clean|maintained)\b", clean, re.I) else "environment"
                add(f"Add detail about {clean}", category, clean, [environment_text, clean], [clean, "nearby", "in the background"])

        if environment_text and len(targets) < 3:
            add(f"Describe the area around {environment_text}", "environment", environment_text, environment_details, [environment_text, "around it", "behind it"])

        mood_words = [
            self._clean_text_value(item.get("word") or item.get("phrase") or "")
            for item in vocabulary
            if re.search(r"\b(calm|busy|quiet|bright|dark|messy|dusty|crowded|peaceful|neglected|warm|lively)\b", str(item), re.I)
        ]
        if mood_words and re.search(r"\b(calm|busy|quiet|bright|dark|messy|dusty|crowded|peaceful|neglected|warm|lively)\b", natural_explanation, re.I):
            add("Describe the feeling of the scene", "atmosphere", "the feeling of the scene", environment_details, mood_words[:5])

        phrase_hints = [self._clean_text_value(item.get("phrase") or "") for item in phrases[:4]]
        if phrase_hints and objects and len(targets) < 4:
            focus = self._clean_text_value(objects[0].get("name") or "")
            add(f"Add the position of the {focus}", "positioning", focus, [objects[0].get("position", ""), *environment_details[:2]], phrase_hints)
        return targets

    def _normalize_visual_zones(self, raw_items: Any) -> list[dict[str, Any]]:
        zones: list[dict[str, Any]] = []
        seen: set[str] = set()
        allowed = {"foreground", "middle_ground", "background", "upper_composition", "supporting_zone"}
        for item in raw_items if isinstance(raw_items, list) else []:
            if not isinstance(item, dict):
                continue
            raw_zone = str(item.get("zone") or item.get("name") or "").strip().lower().replace("-", "_").replace(" ", "_")
            zone = raw_zone if raw_zone in allowed else normalize_answer(raw_zone).replace(" ", "_")
            aliases = {
                "middleground": "middle_ground",
                "middle": "middle_ground",
                "upper": "upper_composition",
                "uppercomposition": "upper_composition",
                "supporting": "supporting_zone",
            }
            zone = aliases.get(zone, zone)
            if zone not in allowed:
                zone = "supporting_zone"
            elements = self._clean_string_list(item.get("elements") or item.get("visible_elements") or [], limit=6)
            opportunities = self._clean_string_list(
                item.get("articulation_opportunities") or item.get("opportunities") or item.get("details") or [],
                limit=6,
            )
            if not elements and not opportunities:
                continue
            key = f"{zone}:{normalize_answer(' '.join(elements[:3]))}"
            if key in seen:
                continue
            seen.add(key)
            zones.append(
                {
                    "zone": zone,
                    "elements": elements,
                    "articulation_opportunities": opportunities,
                    "richness_potential": self._normalize_richness_potential(item.get("richness_potential")),
                    "importance": self._normalize_importance(item.get("importance"), default=0.55),
                }
            )
            if len(zones) >= 8:
                break
        return zones

    def _normalize_richness_potential(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        return text if text in {"low", "medium", "high"} else "medium"

    def _best_zone_focus(self, *, zone_name: str, elements: list[str], opportunities: list[str]) -> str:
        candidates = [*elements, *opportunities]
        priority = [
            r"\b(apartment buildings?|buildings?|unfinished structure|construction|architecture)\b",
            r"\b(wires?|poles?|skyline|upper|background)\b",
            r"\b(lighting|sunlight|shadow|reflection)\b",
            r"\b(contrast|behind|foreground|middle ground|background)\b",
        ]
        for pattern in priority:
            match = next((item for item in candidates if re.search(pattern, item, re.I)), "")
            if match:
                return self._clean_text_value(match)
        if zone_name in {"background", "upper composition"} and candidates:
            return self._clean_text_value(candidates[0])
        return self._clean_text_value(candidates[0] if candidates else "")

    def _zone_target_label(self, *, focus: str, category: str, zone_name: str) -> str:
        focus_text = self._clean_text_value(focus)
        if re.search(r"\b(apartment|building|structure|construction|architecture)\b", focus_text, re.I):
            return f"Describe the {focus_text} in the background"
        if category == "lighting":
            return f"Describe the lighting near {focus_text}"
        if category in {"composition", "positioning", "contrast"}:
            return f"Add the noticeable detail in the {zone_name or 'background'}"
        return f"Add detail about {focus_text}"

    def _normalize_target_category(self, value: Any) -> str:
        text = normalize_answer(str(value or ""))
        if re.search(r"\b(light|shadow|sun|bright)\b", text):
            return "lighting"
        if re.search(r"\b(texture|rough|smooth|fabric|surface)\b", text):
            return "texture"
        if re.search(r"\b(color|petal|appearance|shape|surface)\b", text):
            return "appearance"
        if re.search(r"\b(apartment|building|structure|construction|architecture)\b", text):
            return "environment"
        if re.search(r"\b(position|arrange|foreground|background|near|behind|under)\b", text):
            return "positioning"
        if re.search(r"\b(composition|layout|framing|focus|center|contrast)\b", text):
            return "composition"
        if re.search(r"\b(contrast|different|stands out|against)\b", text):
            return "contrast"
        if re.search(r"\b(feel|mood|atmosphere|calm|busy|messy|peaceful)\b", text):
            return "atmosphere"
        if re.search(r"\b(condition|dust|dirty|clean|clutter|maintained)\b", text):
            return "condition"
        if re.search(r"\b(walking|running|driving|crowd|moving|traffic|movement)\b", text):
            return "movement"
        if re.search(r"\b(holding|using|carrying|talking|playing|interaction|together)\b", text):
            return "interaction"
        if re.search(r"\b(room|street|garden|background|surrounding|area|place|environment)\b", text):
            return "environment"
        return "detail"

    def _is_generic_articulation_target(self, label: str, prompt: str) -> bool:
        text = normalize_answer(f"{label} {prompt}")
        generic = {
            "subject",
            "action",
            "environment",
            "details",
            "atmosphere",
            "describe the subject",
            "describe the action",
            "describe the environment",
            "describe the details",
        }
        return text in generic

    def _normalize_image_type(self, value: Any) -> str:
        text = normalize_answer(str(value or ""))
        allowed = {
            "flower",
            "room",
            "street",
            "nature",
            "portrait",
            "object",
            "food",
            "indoor_area",
            "outdoor_area",
            "other",
        }
        text = text.replace(" ", "_").replace("-", "_")
        return text if text in allowed else "other"

    def _target_prompt(self, prompt: str, focus: str) -> str:
        cleaned = self._clean_text_value(prompt)
        if not cleaned and focus:
            cleaned = f"Describe {focus}."
        if cleaned and not re.match(r"^(describe|what|where|how|which)\b", cleaned, re.I):
            cleaned = f"Describe {cleaned[0].lower()}{cleaned[1:]}"
        return cleaned[:120]

    def _safe_target_id(self, value: Any) -> str:
        text = normalize_answer(str(value or "target"))
        text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
        return text[:48] or "target"

    def _normalize_objects(self, raw_items: list[Any]) -> list[dict[str, Any]]:
        objects: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in raw_items[:8]:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                description = str(item.get("description") or "").strip()
                color = str(item.get("color") or "").strip()
                position = str(item.get("position") or "").strip()
                importance = self._normalize_importance(item.get("importance"), default=0.6)
                confidence = self._normalize_confidence(
                    item.get("confidence") or item.get("identification_confidence") or item.get("object_confidence"),
                    default="medium",
                )
                visual_evidence = self._clean_string_list(
                    item.get("visual_evidence") or item.get("evidence") or [],
                    limit=4,
                )
            else:
                name = str(item).strip()
                description = ""
                color = ""
                position = ""
                importance = 0.6
                confidence = "medium"
                visual_evidence = []
            safe_name, safe_description = self._conservative_object_label(
                name=name,
                description=description,
                color=color,
                position=position,
                confidence=confidence,
                visual_evidence=visual_evidence,
            )
            name = safe_name
            description = safe_description
            key = name.casefold()
            if not name or key in seen:
                continue
            seen.add(key)
            objects.append(
                {
                    "name": name,
                    "description": description or f"{name.capitalize()} is one of the visible image details.",
                    "importance": importance,
                    "color": color,
                    "position": position,
                    "confidence": confidence,
                    "visual_evidence": visual_evidence,
                    "original_name": self._clean_text_value(str(item.get("name") or "") if isinstance(item, dict) else str(item)),
                }
            )
        return objects

    def _downgrade_uncertain_object_language(self, text: str, objects: list[dict[str, Any]]) -> str:
        updated = str(text or "")
        for item in objects:
            original = str(item.get("original_name") or "").strip()
            safe = str(item.get("name") or "").strip()
            confidence = str(item.get("confidence") or "medium").strip().lower()
            if original and safe and confidence != "high" and normalize_answer(original) != normalize_answer(safe):
                updated = re.sub(re.escape(original), safe, updated, flags=re.I)
        replacements = {
            r"\bgaming\s+pc\b": "electronic device",
            r"\bdesktop\s+computer\b": "electronic device",
            r"\bcomputer\s+tower\b": "electronic device",
            r"\bserver\s+machine\b": "electronic device",
            r"\bworkstation\s+setup\b": "desk area",
            r"\bworkstation\s+tower\b": "electronic device",
        }
        for pattern, replacement in replacements.items():
            updated = re.sub(pattern, replacement, updated, flags=re.I)
        return updated

    def _normalize_actions(self, raw_items: list[Any]) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in raw_items[:8]:
            if isinstance(item, dict):
                verb = str(item.get("verb") or "").strip()
                subject = str(item.get("subject") or "").strip()
                object_text = str(item.get("object") or "").strip()
                phrase = str(item.get("phrase") or "").strip() or " ".join(
                    part for part in [verb, object_text] if part
                ).strip()
                description = str(item.get("description") or "").strip()
                importance = self._normalize_importance(item.get("importance"), default=0.6)
                confidence = self._normalize_confidence(item.get("confidence"), default="medium")
                visible_evidence = str(item.get("visible_evidence") or item.get("evidence") or "").strip()
            else:
                phrase = str(item).strip()
                verb = phrase.split(" ", 1)[0] if phrase else ""
                subject = ""
                object_text = ""
                description = ""
                importance = 0.6
                confidence = "medium"
                visible_evidence = ""
            if not self._action_is_visibly_supported(
                verb=verb,
                phrase=phrase,
                confidence=confidence,
                visible_evidence=visible_evidence,
            ):
                continue
            key = phrase.casefold()
            if not phrase or key in seen:
                continue
            seen.add(key)
            actions.append(
                {
                    "verb": verb or phrase,
                    "subject": subject,
                    "object": object_text,
                    "phrase": phrase,
                    "description": description or f'The image suggests the action "{phrase}".',
                    "importance": importance,
                    "confidence": confidence,
                    "visible_evidence": visible_evidence,
                }
            )
        return actions

    def _conservative_object_label(
        self,
        *,
        name: str,
        description: str,
        color: str,
        position: str,
        confidence: str,
        visual_evidence: list[str],
    ) -> tuple[str, str]:
        cleaned_name = self._clean_text_value(name)
        cleaned_description = self._clean_text_value(description)
        evidence_text = " ".join([cleaned_name, cleaned_description, color, position, *visual_evidence]).lower()
        uncertain_exact_label = re.search(
            r"\b(desktop|computer tower|gaming pc|pc tower|server|workstation|computer case|cpu|desktop computer|machine)\b",
            evidence_text,
            re.I,
        )
        box_like = re.search(r"\b(box|rectangular|case|device|equipment|black|dark|under|desk|wire|cable)\b", evidence_text, re.I)
        if confidence == "low" or (confidence != "high" and uncertain_exact_label):
            safe_name = self._generic_visual_object_name(evidence_text, confidence=confidence)
            safe_description = self._generic_visual_object_description(
                safe_name=safe_name,
                color=color,
                position=position,
                visual_evidence=visual_evidence,
            )
            return safe_name, safe_description
        if confidence == "medium" and box_like and uncertain_exact_label:
            safe_name = "black electronic device" if "black" in evidence_text or "dark" in evidence_text else "box-shaped device"
            safe_description = self._generic_visual_object_description(
                safe_name=safe_name,
                color=color,
                position=position,
                visual_evidence=visual_evidence,
                qualifier="appears to be",
            )
            return safe_name, safe_description
        if confidence == "medium" and cleaned_description and not re.search(r"\b(appears|looks like|seems|possibly)\b", cleaned_description, re.I):
            cleaned_description = f"It appears to be {cleaned_description[0].lower()}{cleaned_description[1:]}"
        return cleaned_name, cleaned_description

    def _generic_visual_object_name(self, evidence_text: str, *, confidence: str) -> str:
        dark = "black" in evidence_text or "dark" in evidence_text
        rectangular = any(word in evidence_text for word in ("rectangular", "box", "case", "tower"))
        electronic = any(word in evidence_text for word in ("wire", "cable", "electronic", "device", "equipment"))
        if confidence != "low" and electronic:
            return "black electronic device" if dark else "electronic device"
        if rectangular and electronic:
            return "dark rectangular equipment" if dark else "rectangular equipment"
        if rectangular:
            return "black rectangular object" if dark else "box-like object"
        return "black object" if dark else "unclear object"

    def _generic_visual_object_description(
        self,
        *,
        safe_name: str,
        color: str,
        position: str,
        visual_evidence: list[str],
        qualifier: str = "",
    ) -> str:
        safe_key = normalize_answer(safe_name)
        pieces = []
        if color and normalize_answer(color) not in safe_key:
            pieces.append(color)
        pieces.extend([safe_name, position, *visual_evidence[:2]])
        compact: list[str] = []
        seen: set[str] = set()
        for piece in pieces:
            cleaned = self._clean_text_value(piece)
            key = normalize_answer(cleaned)
            if cleaned and key and key not in seen and key not in safe_key:
                compact.append(cleaned)
                seen.add(key)
            elif cleaned == safe_name and key not in seen:
                compact.append(cleaned)
                seen.add(key)
        base = " ".join(compact) or safe_name
        if qualifier:
            article = "an" if base[:1].lower() in {"a", "e", "i", "o", "u"} else "a"
            return f"The object {qualifier} {article} {base}."
        return f"The image shows {base}."

    def _action_is_visibly_supported(
        self,
        *,
        verb: str,
        phrase: str,
        confidence: str,
        visible_evidence: str,
    ) -> bool:
        text = f"{verb} {phrase} {visible_evidence}".lower()
        if confidence == "low":
            return False
        if not text.strip():
            return False
        if re.search(r"\b(shown|visible|appears?|seems|looks|sits?|stands?|located|placed|resting|lying|is|are|has|contains)\b", text):
            return False
        return bool(
            re.search(
                r"\b(walking|running|riding|driving|holding|using|carrying|eating|drinking|playing|working|cutting|cooking|moving|crossing|climbing|throwing|jumping|swimming|writing|reading)\b",
                text,
            )
        )

    def _normalize_environment(self, raw_environment: Any) -> tuple[str, list[str]]:
        if isinstance(raw_environment, dict):
            setting = str(raw_environment.get("setting") or "").strip()
            details = self._clean_string_list(raw_environment.get("details") or [], limit=5)
            mood = str(raw_environment.get("mood") or "").strip()
            parts = [setting] + details + ([mood] if mood else [])
            return " ".join(part for part in parts if part).strip(), details
        if isinstance(raw_environment, list):
            details = self._clean_string_list(raw_environment, limit=5)
            return " ".join(details), details
        environment_text = str(raw_environment or "").strip()
        return environment_text, [environment_text] if environment_text else []

    def _normalize_vocabulary(self, raw_items: list[Any]) -> list[dict[str, Any]]:
        vocabulary: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in raw_items[:12]:
            if not isinstance(item, dict):
                continue
            word = str(item.get("word") or "").strip()
            meaning = str(item.get("meaning_simple") or "").strip()
            key = word.casefold()
            if (
                not word
                or not meaning
                or key in seen
                or not should_surface_term(
                    word,
                    kind=str(item.get("part_of_speech") or "word").strip(),
                )
            ):
                continue
            seen.add(key)
            examples = self._normalize_example_list(
                word,
                item.get("examples") or [],
                fallback_examples=[str(item.get("example") or "").strip()],
            )
            vocabulary.append(
                {
                    "word": word,
                    "part_of_speech": str(item.get("part_of_speech") or "").strip(),
                    "meaning_simple": meaning,
                    "example": examples[0] if examples else str(item.get("example") or "").strip(),
                    "examples": examples,
                    "frequency_priority": str(item.get("frequency_priority") or "high").strip(),
                }
            )
        return vocabulary

    def _normalize_phrases(
        self,
        raw_phrases: list[Any],
        legacy_language: list[Any],
        natural_explanation: str,
    ) -> list[dict[str, Any]]:
        phrases: list[dict[str, Any]] = []
        seen: set[str] = set()

        def push(
            phrase: str,
            *,
            meaning_simple: str,
            example: str,
            examples: Any = None,
            reusable: bool = True,
            collocation_type: str = "phrase",
        ) -> None:
            key = phrase.casefold()
            if not phrase or not meaning_simple or key in seen:
                return
            seen.add(key)
            normalized_examples = self._normalize_example_list(
                phrase,
                examples or [],
                fallback_examples=[example],
            )
            phrases.append(
                {
                    "phrase": phrase,
                    "meaning_simple": meaning_simple,
                    "example": normalized_examples[0] if normalized_examples else example,
                    "examples": normalized_examples,
                    "reusable": bool(reusable),
                    "collocation_type": collocation_type,
                }
            )

        for item in raw_phrases[:10]:
            if not isinstance(item, dict):
                continue
            push(
                str(item.get("phrase") or "").strip(),
                meaning_simple=str(item.get("meaning_simple") or "").strip(),
                example=str(item.get("example") or "").strip(),
                examples=item.get("examples") or [],
                reusable=bool(item.get("reusable", True)),
                collocation_type=str(item.get("collocation_type") or "phrase").strip(),
            )

        for item in legacy_language[:10]:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text or not self._phrase_in_text(text, natural_explanation):
                continue
            push(
                text,
                meaning_simple=str(item.get("definition") or "").strip(),
                example=str(item.get("example") or "").strip(),
                examples=item.get("examples") or [],
                collocation_type=str(item.get("kind") or "phrase").strip(),
            )

        return phrases

    def _normalize_sentence_patterns(self, raw_items: list[Any]) -> list[dict[str, Any]]:
        patterns: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in raw_items[:6]:
            if not isinstance(item, dict):
                continue
            pattern = str(item.get("pattern") or "").strip()
            key = pattern.casefold()
            if not pattern or key in seen or not should_surface_term(pattern, kind="sentence pattern"):
                continue
            seen.add(key)
            patterns.append(
                {
                    "pattern": pattern,
                    "example": str(item.get("example") or "").strip(),
                    "usage_note": str(item.get("usage_note") or "").strip(),
                    "examples": self._normalize_sentence_pattern_examples(
                        item.get("examples") or [],
                        fallback_examples=[str(item.get("example") or "").strip()],
                    ),
                }
            )
        return patterns

    def _normalize_sentence_starters(
        self,
        raw_items: list[Any],
        *,
        objects: list[dict[str, Any]],
        actions: list[dict[str, Any]],
    ) -> list[str]:
        blocked_terms = {
            normalize_answer(str(item.get("name") or ""))
            for item in objects
            if str(item.get("name") or "").strip()
        }
        blocked_terms.update(
            normalize_answer(str(item.get("verb") or item.get("phrase") or ""))
            for item in actions
            if str(item.get("verb") or item.get("phrase") or "").strip()
        )
        starters: list[str] = []
        seen: set[str] = set()
        for value in [
            *(raw_items if isinstance(raw_items, list) else []),
            "The image shows ...",
            "Here we see ...",
            "This scene shows ...",
            "In this picture, ...",
            "The photo captures ...",
            "At first glance, ...",
        ]:
            text = self._clean_text_value(value).replace("…", "...").strip()
            if not text:
                continue
            if not re.search(r"\.\.\.$|[, ]$", text):
                text = f"{text} ..."
            key = normalize_answer(text)
            if not key or key in seen:
                continue
            if any(term and term in key for term in blocked_terms):
                continue
            if len(text.split()) > 7:
                continue
            seen.add(key)
            starters.append(text)
            if len(starters) >= 6:
                break
        return starters

    def _normalize_starter_hints(self, raw_items: Any) -> list[dict[str, str]]:
        items = raw_items if isinstance(raw_items, list) else []
        hints: list[dict[str, str]] = []
        seen: set[str] = set()
        allowed_types = {"word", "phrase", "sentence_structure"}
        for item in items:
            if not isinstance(item, dict):
                continue
            label = self._clean_text_value(item.get("label") or item.get("word") or item.get("phrase"))
            meaning = self._clean_text_value(item.get("meaning") or item.get("meaning_simple"))
            example = self._clean_text_value(item.get("example"))
            hint_type = self._clean_text_value(item.get("type")).replace(" ", "_") or "phrase"
            if hint_type not in allowed_types:
                hint_type = "phrase"
            key = normalize_answer(label)
            if not label or not meaning or not example or not key or key in seen:
                continue
            meaning_key = normalize_answer(meaning)
            example_key = normalize_answer(example)
            generic_meaning_patterns = (
                "person or group",
                "thing in the scene",
                "object in the scene",
                "something in the scene",
                "you can describe in the scene",
                "a detail in the image",
            )
            generic_example = (
                example_key in {
                    f"the image shows {key}",
                    f"the image shows a {key}",
                    f"the image shows an {key}",
                    f"the picture shows {key}",
                    f"the picture shows a {key}",
                    f"the picture shows an {key}",
                    f"the scene shows {key}",
                    f"the scene shows a {key}",
                    f"the scene shows an {key}",
                    f"the image has {key}",
                    f"the image has a {key}",
                    f"the image has an {key}",
                    f"there is {key}",
                    f"there is a {key}",
                    f"there is an {key}",
                    f"there are {key}",
                }
                or (example_key.startswith("the image shows ") and len(example.split()) <= len(label.split()) + 3)
            )
            if any(pattern in meaning_key for pattern in generic_meaning_patterns) or generic_example:
                continue
            if len(label.split()) > 5 or len(meaning.split()) > 34 or len(example.split()) > 18:
                continue
            seen.add(key)
            hints.append(
                {
                    "label": label,
                    "type": hint_type,
                    "meaning": meaning,
                    "example": self._ensure_sentence_punctuation(example),
                }
            )
            if len(hints) >= 3:
                break
        return hints

    def _derive_starter_hints_from_ai_analysis(
        self,
        *,
        objects: list[dict[str, Any]],
        vocabulary: list[dict[str, Any]],
        phrases: list[dict[str, Any]],
        natural_explanation: str,
        simple_explanation: str,
    ) -> list[dict[str, str]]:
        hints: list[dict[str, str]] = []
        seen: set[str] = set()

        def push(label: str, hint_type: str, meaning: str, example: str, score: float = 0.0) -> None:
            cleaned_label = self._clean_text_value(label)
            cleaned_meaning = self._clean_text_value(meaning)
            cleaned_example = self._clean_text_value(example)
            key = normalize_answer(cleaned_label)
            if (
                not cleaned_label
                or not cleaned_meaning
                or not cleaned_example
                or not key
                or key in seen
                or len(cleaned_label.split()) > 5
                or len(cleaned_meaning.split()) > 34
                or len(cleaned_example.split()) > 18
            ):
                return
            seen.add(key)
            hints.append(
                {
                    "label": cleaned_label,
                    "type": hint_type if hint_type in {"word", "phrase", "sentence_structure"} else "phrase",
                    "meaning": cleaned_meaning,
                    "example": self._ensure_sentence_punctuation(cleaned_example),
                    "_score": score,
                }
            )

        for item in objects:
            label = self._clean_text_value(item.get("name"))
            meaning = self._clean_text_value(item.get("description"))
            example = self._starter_hint_general_example(label)
            try:
                score = float(item.get("importance") or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            push(label, "phrase" if len(label.split()) > 1 else "word", meaning, example, 100 + score)

        for item in vocabulary:
            label = self._clean_text_value(item.get("word"))
            meaning = self._clean_text_value(item.get("meaning_simple"))
            example = self._starter_hint_general_example(label)
            push(label, "word", meaning, example, 80)

        for item in phrases:
            label = self._clean_text_value(item.get("phrase"))
            meaning = self._clean_text_value(item.get("meaning_simple"))
            example = self._starter_hint_general_example(label)
            push(label, "phrase", meaning, example, 70)

        hints.sort(key=lambda item: float(item.pop("_score", 0.0)), reverse=True)
        return hints[:3]

    def _starter_hint_general_example(self, label: str) -> str:
        text = self._clean_text_value(label)
        key = normalize_answer(text)
        if not text or not key:
            return ""
        if "climbing vine" in key or "climbing vines" in key:
            return "The wall is covered with climbing vines."
        if "lined with" in key:
            return "The street is lined with small trees."
        if "roof overhang" in key:
            return "The roof overhang gives some shade."
        if "patches of shade" in key:
            return "Patches of shade cover the path."
        if "hanging" in key:
            return f"The {text} are hanging near the door."
        if "behind" in key:
            return f"The lamp is {text} the chair."
        if "next to" in key:
            return f"The bag is {text} the table."
        if "in front of" in key:
            return f"The bike is {text} the shop."
        if len(text.split()) >= 2:
            return f"The old house has {text} near the entrance."
        article = "an" if text[0].casefold() in {"a", "e", "i", "o", "u"} else "a"
        return f"There is {article} {text} near the window."

    def _derive_sentence_patterns(
        self,
        *,
        natural_explanation: str,
        phrases: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        sentences = self._split_sentences(natural_explanation)
        patterns: list[dict[str, Any]] = []

        def push(pattern: str, example: str, usage_note: str) -> None:
            if any(item["pattern"].casefold() == pattern.casefold() for item in patterns):
                return
            patterns.append(
                {
                    "pattern": pattern,
                    "example": example,
                    "usage_note": usage_note,
                }
            )

        for sentence in sentences[:6]:
            lowered = sentence.casefold()
            if " in the background" in lowered:
                push(
                    "In the background, ...",
                    sentence,
                    "Use it to describe details behind the main subject.",
                )
            if " next to " in lowered:
                push(
                    "... is next to ...",
                    sentence,
                    "Use it to show where two things are placed.",
                )
            if " in front of " in lowered:
                push(
                    "... is in front of ...",
                    sentence,
                    "Use it to describe front-back position.",
                )
            if lowered.startswith(("there is ", "there are ")):
                push(
                    "There is/are ...",
                    sentence,
                    "Use it to introduce something visible in the image.",
                )

        for phrase in phrases[:3]:
            example = str(phrase.get("example") or "").strip()
            text = str(phrase.get("phrase") or "").strip()
            if text and example:
                push(
                    f"Someone/something is {text}.",
                    example,
                    "Use it to describe the main action naturally.",
                )

        fallback_examples = sentences[:3] or ["There is something important in the image."]
        fallbacks = [
            (
                "The main subject is ...",
                fallback_examples[0],
                "Use it to begin with the most important person or thing.",
            ),
            (
                "I can see ...",
                fallback_examples[min(1, len(fallback_examples) - 1)],
                "Use it for a simple direct image description.",
            ),
            (
                "This scene looks ... because ...",
                fallback_examples[min(2, len(fallback_examples) - 1)],
                "Use it to add feeling or reason after describing facts.",
            ),
        ]
        for pattern, example, usage_note in fallbacks:
            if len(patterns) >= 5:
                break
            push(pattern, example, usage_note)
        return patterns[:5]

    def _build_reusable_language(
        self,
        *,
        phrases: list[dict[str, Any]],
        vocabulary: list[dict[str, Any]],
        sentence_patterns: list[dict[str, Any]],
        natural_explanation: str,
        primary_subject: str,
    ) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []

        for vocab_item in vocabulary[:6]:
            vocab_word = str(vocab_item.get("word") or "").strip()
            vocab_kind = str(vocab_item.get("part_of_speech") or "word").strip() or "word"
            if not should_surface_term(vocab_word, kind=vocab_kind):
                continue
            items.append(
                {
                    "text": vocab_word,
                    "kind": vocab_kind,
                    "definition": vocab_item["meaning_simple"],
                    "example": self._find_sentence_with_text(vocab_word, natural_explanation)
                    or str(vocab_item.get("example") or "").strip(),
                    "examples": list(vocab_item.get("examples") or []),
                    "why_it_matters": "This word gives the learner useful language for future descriptions.",
                }
            )

        for phrase_item in phrases[:8]:
            phrase = str(phrase_item.get("phrase") or "").strip()
            phrase_kind = str(phrase_item.get("collocation_type") or "phrase").strip() or "phrase"
            if not should_surface_term(phrase, kind=phrase_kind):
                continue
            items.append(
                {
                    "text": phrase,
                    "kind": phrase_kind,
                    "definition": phrase_item["meaning_simple"],
                    "example": self._find_sentence_with_text(phrase, natural_explanation)
                    or str(phrase_item.get("example") or "").strip(),
                    "examples": list(phrase_item.get("examples") or []),
                    "why_it_matters": "This phrase is useful to reuse in another real image description.",
                }
            )

        for extracted_item in self._extract_reusable_language_from_explanation(natural_explanation)[:6]:
            extracted_text = str(extracted_item.get("text") or "").strip()
            extracted_kind = str(extracted_item.get("kind") or "phrase").strip() or "phrase"
            if not should_surface_term(extracted_text, kind=extracted_kind):
                continue
            items.append(extracted_item)

        for pattern in sentence_patterns[:4]:
            pattern_text = str(pattern.get("pattern") or "").strip()
            if not should_surface_term(pattern_text, kind="sentence pattern"):
                continue
            items.append(
                {
                    "text": pattern_text,
                    "kind": "sentence pattern",
                    "definition": str(pattern.get("usage_note") or "").strip()
                    or "A useful sentence frame for natural description.",
                    "example": str(pattern.get("example") or "").strip(),
                    "examples": self._normalize_example_list(
                        pattern_text,
                        pattern.get("examples") or [],
                        fallback_examples=[str(pattern.get("example") or "").strip()],
                    ),
                    "why_it_matters": "This sentence pattern helps the learner build natural spoken English.",
                }
            )

        items = self._dedupe_reusable_language(items)
        items.sort(
            key=lambda item: self._reusable_language_sort_key(
                item,
                primary_subject=primary_subject,
            )
        )
        return items[:8]

    def _reusable_language_sort_key(
        self,
        item: dict[str, str],
        *,
        primary_subject: str,
    ) -> tuple[int, int, int, str]:
        text = str(item.get("text") or "").strip()
        kind = str(item.get("kind") or "").strip()
        normalized_text = normalize_answer(text)
        normalized_subject = normalize_answer(primary_subject)
        primary_bonus = 2 if normalized_subject and normalized_text == normalized_subject else 0
        kind_bonus = 1 if kind.casefold() in {"expression", "idiom", "sentence pattern"} else 0
        return (
            -(primary_bonus + kind_bonus),
            -term_surface_score(text, kind=kind),
            -len(text),
            text.casefold(),
        )

    def _phrase_in_text(self, phrase: str, text: str) -> bool:
        pattern = re.compile(rf"(?<!\w){re.escape(phrase.strip())}(?!\w)", re.IGNORECASE)
        return bool(pattern.search(text))

    def _word_in_text(self, word: str, text: str) -> bool:
        pattern = re.compile(rf"(?<!\w){re.escape(word.strip())}(?!\w)", re.IGNORECASE)
        return bool(pattern.search(text))

    def _find_sentence_with_text(self, text: str, explanation: str) -> str:
        matcher = self._phrase_in_text if " " in text.strip() else self._word_in_text
        for sentence in self._split_sentences(explanation):
            if matcher(text, sentence):
                return self._ensure_sentence_punctuation(sentence)
        return ""

    def _ensure_sentence_punctuation(self, text: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(text or "").strip())
        if not cleaned:
            return ""
        if cleaned.endswith((".", "!", "?")):
            return cleaned
        return f"{cleaned}."

    def _natural_action_sentence(self, subject: str, phrase: str) -> str:
        cleaned_phrase = re.sub(r"\s+", " ", str(phrase or "").strip())
        if not cleaned_phrase:
            return ""
        cleaned_subject = re.sub(r"\s+", " ", str(subject or "").strip()) or "Someone"
        words = cleaned_phrase.split()
        first = words[0].casefold()
        second = words[1].casefold() if len(words) > 1 else ""
        sentence_subjects = {"person", "man", "woman", "child", "someone", "somebody"}

        if first in sentence_subjects and second.endswith("s") and not second.endswith("ss"):
            return self._ensure_sentence_punctuation(cleaned_phrase[:1].upper() + cleaned_phrase[1:])
        if first in {"is", "are", "was", "were"}:
            return self._ensure_sentence_punctuation(f"{cleaned_subject} {cleaned_phrase}")
        if first.endswith("ing"):
            return self._ensure_sentence_punctuation(f"{cleaned_subject} is {cleaned_phrase}")
        if first.endswith("s") and not first.endswith("ss"):
            return self._ensure_sentence_punctuation(f"{cleaned_subject} {cleaned_phrase}")
        return self._ensure_sentence_punctuation(f"{cleaned_subject} seems to {cleaned_phrase}")

    def _synchronize_explanation_language(
        self,
        natural_explanation: str,
        *,
        vocabulary: list[dict[str, Any]],
        phrases: list[dict[str, Any]],
        objects: list[dict[str, Any]],
        actions: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
        explanation = self._expand_explanation_for_language_sync(
            natural_explanation,
            vocabulary=vocabulary,
            phrases=phrases,
            objects=objects,
            actions=actions,
        )
        synced_vocabulary = self._filter_vocabulary_to_explanation(vocabulary, explanation)
        synced_phrases = self._filter_phrases_to_explanation(phrases, explanation)

        synced_vocabulary = self._merge_vocabulary_lists(
            synced_vocabulary,
            self._derive_vocabulary_from_explanation(explanation),
            limit=10,
        )
        synced_phrases = self._merge_phrase_lists(
            synced_phrases,
            self._derive_phrases_from_explanation(explanation),
            limit=8,
        )

        synced_vocabulary = self._filter_vocabulary_to_explanation(synced_vocabulary, explanation)
        synced_phrases = self._filter_phrases_to_explanation(synced_phrases, explanation)
        return explanation, synced_vocabulary[:10], synced_phrases[:8]

    def _expand_explanation_for_language_sync(
        self,
        natural_explanation: str,
        *,
        vocabulary: list[dict[str, Any]],
        phrases: list[dict[str, Any]],
        objects: list[dict[str, Any]],
        actions: list[dict[str, Any]],
    ) -> str:
        additions: list[str] = []
        working_text = natural_explanation

        for item in phrases[:8]:
            phrase = str(item.get("phrase") or "").strip()
            if not phrase or self._phrase_in_text(phrase, working_text):
                continue
            sentence = self._build_phrase_support_sentence(item, actions=actions)
            if not sentence or not self._phrase_in_text(phrase, sentence):
                continue
            if sentence.casefold() in working_text.casefold():
                continue
            additions.append(sentence)
            working_text = f"{working_text} {sentence}".strip()

        for item in vocabulary[:10]:
            word = str(item.get("word") or "").strip()
            if not word or self._word_in_text(word, working_text):
                continue
            sentence = self._build_vocabulary_support_sentence(
                item,
                objects=objects,
                actions=actions,
            )
            if not sentence or not self._word_in_text(word, sentence):
                continue
            if sentence.casefold() in working_text.casefold():
                continue
            additions.append(sentence)
            working_text = f"{working_text} {sentence}".strip()

        if not additions:
            return natural_explanation
        return self._normalize_explanation(f"{natural_explanation}\n\n{' '.join(additions)}")

    def _build_phrase_support_sentence(
        self,
        item: dict[str, Any],
        *,
        actions: list[dict[str, Any]],
    ) -> str:
        phrase = str(item.get("phrase") or "").strip()
        example = self._find_sentence_with_text(phrase, str(item.get("example") or "").strip())
        if example:
            return example

        for action in actions:
            action_phrase = str(action.get("phrase") or "").strip()
            if action_phrase.casefold() != phrase.casefold():
                continue
            description = self._find_sentence_with_text(phrase, str(action.get("description") or "").strip())
            if description:
                return description
            subject = str(action.get("subject") or "Someone").strip()
            object_text = str(action.get("object") or "").strip()
            if not subject:
                subject = "Someone"
            if object_text and object_text.casefold() not in phrase.casefold():
                phrase = f"{phrase} {object_text}"
            return self._natural_action_sentence(subject, phrase)
        return ""

    def _build_vocabulary_support_sentence(
        self,
        item: dict[str, Any],
        *,
        objects: list[dict[str, Any]],
        actions: list[dict[str, Any]],
    ) -> str:
        word = str(item.get("word") or "").strip()
        example = self._find_sentence_with_text(word, str(item.get("example") or "").strip())
        if example:
            return example

        for obj in objects:
            if str(obj.get("name") or "").strip().casefold() != word.casefold():
                continue
            description = self._find_sentence_with_text(word, str(obj.get("description") or "").strip())
            if description:
                return description
            position = str(obj.get("position") or "").strip()
            if position:
                return self._ensure_sentence_punctuation(f"{word.capitalize()} appears {position}")
            return self._ensure_sentence_punctuation(f"{word.capitalize()} appears in the scene")

        for action in actions:
            if str(action.get("verb") or "").strip().casefold() != word.casefold():
                continue
            description = self._find_sentence_with_text(word, str(action.get("description") or "").strip())
            if description:
                return description
            subject = str(action.get("subject") or "Someone").strip() or "Someone"
            phrase = str(action.get("phrase") or "").strip()
            if phrase:
                return self._natural_action_sentence(subject, phrase)
            object_text = str(action.get("object") or "").strip()
            if object_text:
                return self._natural_action_sentence(subject, f"{word} {object_text}")
            return self._natural_action_sentence(subject, word)
        return ""

    def _filter_vocabulary_to_explanation(
        self,
        vocabulary: list[dict[str, Any]],
        explanation: str,
    ) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in vocabulary:
            word = str(item.get("word") or "").strip()
            key = word.casefold()
            if not word or key in seen or not self._word_in_text(word, explanation):
                continue
            seen.add(key)
            refreshed = dict(item)
            refreshed["example"] = self._find_sentence_with_text(word, explanation) or str(
                item.get("example") or ""
            ).strip()
            refreshed["examples"] = self._normalize_example_list(
                word,
                item.get("examples") or [],
                fallback_examples=[refreshed["example"]],
            )
            filtered.append(refreshed)
        return filtered

    def _filter_phrases_to_explanation(
        self,
        phrases: list[dict[str, Any]],
        explanation: str,
    ) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in phrases:
            phrase = str(item.get("phrase") or "").strip()
            key = phrase.casefold()
            if not phrase or key in seen or not self._phrase_in_text(phrase, explanation):
                continue
            seen.add(key)
            refreshed = dict(item)
            refreshed["example"] = self._find_sentence_with_text(phrase, explanation) or str(
                item.get("example") or ""
            ).strip()
            refreshed["examples"] = self._normalize_example_list(
                phrase,
                item.get("examples") or [],
                fallback_examples=[refreshed["example"]],
            )
            filtered.append(refreshed)
        return filtered

    def _merge_vocabulary_lists(
        self,
        primary: list[dict[str, Any]],
        fallback: list[dict[str, Any]],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for collection in (primary, fallback):
            for item in collection:
                word = str(item.get("word") or "").strip()
                key = word.casefold()
                if not word or key in seen:
                    continue
                seen.add(key)
                merged.append(item)
                if len(merged) >= limit:
                    return merged
        return merged

    def _merge_phrase_lists(
        self,
        primary: list[dict[str, Any]],
        fallback: list[dict[str, Any]],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for collection in (primary, fallback):
            for item in collection:
                phrase = str(item.get("phrase") or "").strip()
                key = phrase.casefold()
                if not phrase or key in seen:
                    continue
                seen.add(key)
                merged.append(item)
                if len(merged) >= limit:
                    return merged
        return merged

    def _top_up_vocabulary(
        self,
        vocabulary: list[dict[str, Any]],
        objects: list[dict[str, Any]],
        actions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        items = vocabulary[:]
        seen = {item["word"].casefold() for item in items}
        for obj in objects:
            word = obj["name"]
            if word.casefold() in seen or not should_surface_term(word, kind="noun"):
                continue
            items.append(
                {
                    "word": word,
                    "part_of_speech": "noun",
                    "meaning_simple": obj["description"],
                    "example": f'This image shows a {word}.',
                    "frequency_priority": "high",
                }
            )
            seen.add(word.casefold())
            if len(items) >= 10:
                return items
        for action in actions:
            word = action["verb"]
            if word.casefold() in seen:
                continue
            items.append(
                {
                    "word": word,
                    "part_of_speech": "verb",
                    "meaning_simple": action["description"],
                    "example": self._natural_action_sentence(
                        str(action.get("subject") or "Someone"),
                        str(action.get("phrase") or word),
                    ),
                    "frequency_priority": "high",
                }
            )
            seen.add(word.casefold())
            if len(items) >= 10:
                break
        return items

    def _derive_vocabulary_from_explanation(
        self, natural_explanation: str
    ) -> list[dict[str, Any]]:
        stopwords = {
            "this",
            "that",
            "with",
            "from",
            "into",
            "there",
            "their",
            "about",
            "because",
            "while",
            "where",
            "which",
            "would",
            "could",
            "should",
            "image",
            "scene",
            "person",
            "people",
            "thing",
            "very",
            "just",
            "more",
            "most",
            "some",
            "many",
            "each",
            "also",
            "than",
            "then",
            "they",
            "them",
            "have",
            "has",
            "been",
            "being",
            "were",
            "when",
            "what",
            "your",
            "over",
            "under",
            "near",
            "behind",
            "front",
        }
        counts: dict[str, int] = {}
        for word in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", natural_explanation):
            lowered = word.casefold()
            if lowered in stopwords:
                continue
            counts[lowered] = counts.get(lowered, 0) + 1

        items: list[dict[str, Any]] = []
        for word, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:8]:
            part_of_speech = "verb" if word.endswith("ing") else "word"
            if not should_surface_term(word, kind=part_of_speech):
                continue
            items.append(
                {
                    "word": word,
                    "part_of_speech": part_of_speech,
                    "meaning_simple": f'A useful word from the image description: "{word}".',
                    "example": next(
                        (
                            sentence
                            for sentence in self._split_sentences(natural_explanation)
                            if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", sentence, re.IGNORECASE)
                        ),
                        f'This scene includes the word "{word}".',
                    ),
                    "frequency_priority": "high",
                }
            )
        return items

    def _derive_phrases_from_explanation(
        self, natural_explanation: str
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for item in self._extract_reusable_language_from_explanation(natural_explanation)[:8]:
            items.append(
                {
                    "phrase": item["text"],
                    "meaning_simple": item["definition"],
                    "example": item["example"],
                    "reusable": True,
                    "collocation_type": item["kind"],
                }
            )
        return items

    def _top_up_phrases(
        self,
        phrases: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        natural_explanation: str,
    ) -> list[dict[str, Any]]:
        items = phrases[:]
        seen = {item["phrase"].casefold() for item in items}
        for action in actions:
            phrase = str(action.get("phrase") or "").strip()
            if not phrase or phrase.casefold() in seen:
                continue
            items.append(
                {
                    "phrase": phrase,
                    "meaning_simple": action["description"],
                    "example": self._natural_action_sentence(
                        str(action.get("subject") or "Someone"),
                        phrase,
                    ),
                    "reusable": True,
                    "collocation_type": "verb phrase",
                }
            )
            seen.add(phrase.casefold())
            if len(items) >= 8:
                return items

        for item in self._extract_reusable_language_from_explanation(natural_explanation):
            phrase = item["text"]
            if phrase.casefold() in seen:
                continue
            items.append(
                {
                    "phrase": phrase,
                    "meaning_simple": item["definition"],
                    "example": item["example"],
                    "reusable": True,
                    "collocation_type": item["kind"],
                }
            )
            seen.add(phrase.casefold())
            if len(items) >= 8:
                break
        return items

    def _extract_reusable_language_from_explanation(
        self, native_explanation: str
    ) -> list[dict[str, str]]:
        sentences = self._split_sentences(native_explanation)
        items: list[dict[str, str]] = []
        seen: set[str] = set()
        pattern_specs = [
            (re.compile(r"\b(?:in the foreground|in the background|in the center|in the distance)\b", re.IGNORECASE), "phrase"),
            (re.compile(r"\b(?:next to|in front of|behind|on the side of)\b", re.IGNORECASE), "phrase"),
            (re.compile(r"\b(?:looks like|seems to|appears to)\b", re.IGNORECASE), "expression"),
            (re.compile(r"\b(?:evoking a sense of|creating a sense of|giving a sense of)\b", re.IGNORECASE), "expression"),
        ]

        for pattern, kind in pattern_specs:
            for match in pattern.finditer(native_explanation):
                phrase = self._clean_phrase_candidate(match.group(0))
                if not phrase or phrase.casefold() in seen:
                    continue
                seen.add(phrase.casefold())
                example = next(
                    (sentence for sentence in sentences if self._phrase_in_text(phrase, sentence)),
                    f'You can reuse "{phrase}" in another image description.',
                )
                items.append(
                    {
                        "text": phrase,
                        "kind": kind,
                        "definition": self._describe_phrase_use(phrase),
                        "example": example,
                        "examples": self._normalize_example_list(
                            phrase,
                            [],
                            fallback_examples=[example],
                        ),
                        "why_it_matters": self._why_phrase_matters(phrase),
                    }
                )
        return items

    def _clean_phrase_candidate(self, phrase: str) -> str:
        cleaned = re.sub(r"\s+", " ", phrase.strip(" ,.;:!?")).strip()
        if not cleaned:
            return ""

        if cleaned.casefold() in {
            "evoking a sense of",
            "creating a sense of",
            "giving a sense of",
        }:
            return cleaned

        words = cleaned.split()
        while words and words[-1].casefold() in {
            "and",
            "but",
            "or",
            "with",
            "to",
            "of",
            "a",
            "an",
            "the",
        }:
            words.pop()

        cleaned = " ".join(words).strip()
        if len(cleaned.split()) < 2 or len(cleaned.split()) > 6:
            return ""
        if any(char.isdigit() for char in cleaned):
            return ""
        if any(
            blocked_word in cleaned.casefold().split()
            for blocked_word in {"what", "which", "that", "while", "because", "where", "when"}
        ):
            return ""
        if cleaned.casefold().startswith(("let's ", "we can ", "this image ", "this picture ")):
            return ""
        if "main subjects" in cleaned.casefold():
            return ""
        return cleaned

    def _describe_phrase_use(self, phrase: str) -> str:
        lowered = phrase.casefold()
        if lowered.startswith(("in the ", "at the ", "on the ", "behind the ", "near the ")):
            return "a natural way to describe where something appears in the scene"
        if any(word in lowered for word in {"foreground", "background", "center", "centre", "subject"}):
            return "useful for showing position and visual focus in an image"
        if any(word in lowered for word in {"standing", "facing", "wearing", "holding", "looking", "smiling"}):
            return "useful for describing posture, action, or appearance in a natural way"
        if any(word in lowered for word in {"glow", "light", "lighting", "shadow"}):
            return "useful for talking about light and the visual atmosphere of a scene"
        if any(word in lowered for word in {"smile", "expression", "eyes"}):
            return "useful for describing facial expression in a natural way"
        if any(word in lowered for word in {"calm", "peaceful", "dramatic", "confidence", "mood", "atmosphere"}):
            return "useful for describing the mood or feeling created by the image"
        if any(
            word in lowered
            for word in {
                "looks like",
                "appears to",
                "seems to",
                "you can tell",
                "gives the impression",
                "conveys a feeling of",
                "evoking a sense of",
                "creating a sense of",
                "giving a sense of",
            }
        ):
            return "useful when you want to make a natural interpretation based on what you can see"
        return "a natural phrase that helps you describe a photo more clearly in everyday English"

    def _why_phrase_matters(self, phrase: str) -> str:
        lowered = phrase.casefold()
        if any(
            word in lowered
            for word in {
                "looks like",
                "appears to",
                "seems to",
                "you can tell",
                "gives the impression",
                "evoking a sense of",
                "creating a sense of",
                "giving a sense of",
            }
        ):
            return "Native speakers use this kind of language when they describe what an image suggests."
        if any(word in lowered for word in {"foreground", "background", "center", "centre"}):
            return "It helps learners organize a visual description in a clear, natural order."
        if any(word in lowered for word in {"standing", "facing", "wearing", "smiling"}):
            return "It makes people descriptions sound more natural and specific."
        if any(word in lowered for word in {"glow", "calm", "peaceful", "dramatic", "confidence"}):
            return "It helps the learner talk about atmosphere instead of only naming objects."
        return "It is easy to reuse in many everyday image descriptions."

    def _top_up_scene_notes(
        self, scene_notes: list[str], native_explanation: str
    ) -> list[str]:
        notes = [item for item in scene_notes if item]
        if len(notes) >= 3:
            return notes[:6]

        sentences = [
            sentence.strip()
            for sentence in native_explanation.replace("!", ".").replace("?", ".").split(".")
            if sentence.strip()
        ]
        for sentence in sentences:
            note = sentence[:110].strip()
            if note and note not in notes:
                notes.append(note)
            if len(notes) >= 3:
                break

        fallback_notes = [
            "The lesson focuses on visual details the learner can describe out loud.",
            "The language is shaped to sound natural and reusable in daily English.",
            "The key goal is to notice shapes, positions, and the overall scene.",
        ]
        for note in fallback_notes:
            if note not in notes:
                notes.append(note)
            if len(notes) >= 3:
                break
        return notes[:6]

    def _dedupe_reusable_language(self, items: list[dict[str, str]]) -> list[dict[str, str]]:
        unique: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in items:
            text = str(item.get("text") or "").strip()
            key = text.casefold()
            if not text or key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    def _clean_string_list(self, values: Any, *, limit: int) -> list[str]:
        if not isinstance(values, list):
            return []
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = self._clean_text_value(value)
            key = text.casefold()
            if not text or key in seen:
                continue
            seen.add(key)
            cleaned.append(text)
            if len(cleaned) >= limit:
                break
        return cleaned

    def _clean_text_value(self, value: Any) -> str:
        if isinstance(value, dict):
            for key in ("text", "phrase", "value", "answer", "detail", "message"):
                if key in value:
                    return self._clean_text_value(value.get(key))
            return ""
        if isinstance(value, list):
            return ""
        text = re.sub(r"\s+", " ", str(value or "").strip())
        if not text:
            return ""
        lowered = text.casefold()
        if (
            (text.startswith("{") and text.endswith("}"))
            or (text.startswith("[") and text.endswith("]"))
            or re.search(r"\b(attempt|phrase|note|usedWell|tryNext|mainIssue)\s*[:=]", text)
            or lowered in {"{}", "[]", "null", "none"}
        ):
            return ""
        return text

    def _normalize_better_version(self, value: Any, *, fallback: str) -> str:
        text = self._clean_text_value(value)
        if not text:
            text = self._clean_text_value(fallback)
        if not text:
            return "Keep your main idea, then add one clearer detail and one reusable phrase."
        if len(text.split()) < 5 or not re.search(r"[A-Za-z]{2,}", text):
            return self._clean_text_value(fallback) or "Rewrite your answer with one clearer detail."
        if re.search(r"\b(undefined|null|NaN|function|console\.log|JSON)\b", text):
            return self._clean_text_value(fallback) or "Rewrite your answer with one clearer detail."
        return self._ensure_sentence_punctuation(text)

    def _dedupe_feedback_sections(self, feedback: dict[str, Any]) -> None:
        missing_keys = {normalize_answer(item) for item in feedback.get("missing_details", [])}
        fixes: list[str] = []
        seen_fixes: set[str] = set()
        for item in feedback.get("fix_this_to_improve", []):
            key = normalize_answer(item)
            if not key or key in seen_fixes:
                continue
            if key in missing_keys:
                continue
            seen_fixes.add(key)
            fixes.append(item)
        if not fixes:
            fixes = ["Add one specific visual detail.", "Use one stronger reusable phrase."]
        feedback["fix_this_to_improve"] = fixes[:3]

        details: list[str] = []
        seen_details: set[str] = set()
        fix_keys = {normalize_answer(item) for item in fixes}
        for item in feedback.get("missing_details", []):
            key = normalize_answer(item)
            if not key or key in seen_details or key in fix_keys:
                continue
            seen_details.add(key)
            details.append(item)
        feedback["missing_details"] = details[:3]

    def _demo_response(
        self,
        *,
        filename: str,
        difficulty_band: str,
        notes: str,
        fallback_reason: str = "",
    ) -> dict[str, Any]:
        analysis = self._fallback_scene_guidance()
        if notes.strip():
            analysis["starterHints"] = [
                {"label": notes.strip()[:48], "type": "phrase"},
                *analysis["starterHints"][:2],
            ]
        normalized = self._normalize_scene_guidance(analysis)
        normalized["demo_note"] = fallback_reason or f"Demo guidance for {filename}."
        normalized["source_mode"] = "demo"
        return normalized
