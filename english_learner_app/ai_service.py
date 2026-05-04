from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import math
import re
import threading
from dataclasses import dataclass
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


@dataclass(slots=True)
class _QueuedVLLMRequest:
    payload: dict[str, Any]
    future: asyncio.Future[str]


class AIAnalyzer:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._vllm_runtime: VLLMVisionRuntime | None = None
        self._runtime_lock = threading.Lock()

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
        if self.config.ai_backend == "vllm":
            if image_path is None:
                raise ValueError("A local image path is required for the vLLM backend.")
            try:
                return await self._vllm_response(
                    image_path=image_path,
                    difficulty_band=difficulty_band,
                    notes=notes,
                )
            except Exception as exc:
                print(f"[ai-vllm-fallback] {type(exc).__name__}: {exc}")
                if not self.config.demo_mode:
                    raise
                return self._demo_response(
                    filename=filename,
                    difficulty_band=difficulty_band,
                    notes=notes,
                    fallback_reason=(
                        "The local vLLM server could not finish a structured lesson for this image, "
                        "so the app used a local fallback lesson instead."
                    ),
                )
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

    async def warmup_vllm_model(self) -> None:
        if self.config.ai_backend != "vllm":
            return
        runtime = self._get_local_runtime()
        await runtime.warmup()

    async def close(self) -> None:
        runtime = self._vllm_runtime
        if runtime is not None:
            await runtime.close()

    def _get_vllm_runtime(self) -> "VLLMVisionRuntime":
        with self._runtime_lock:
            if self._vllm_runtime is None:
                self._vllm_runtime = VLLMVisionRuntime(self.config, self._build_prompt)
            return self._vllm_runtime

    def _get_local_runtime(self) -> "VLLMVisionRuntime":
        return self._get_vllm_runtime()

    async def _vllm_response(
        self,
        *,
        image_path: Path,
        difficulty_band: str,
        notes: str,
    ) -> dict[str, Any]:
        runtime = self._get_local_runtime()
        output_text = await runtime.generate(
            image_path=image_path,
            prompt=self._build_prompt(difficulty_band=difficulty_band, notes=notes),
            max_new_tokens=self._analysis_max_new_tokens(),
            temperature=self.config.inference_temperature,
        )
        try:
            analysis = self._parse_analysis_output(output_text)
        except Exception:
            repaired_text = await runtime.repair_json(output_text=output_text)
            analysis = self._parse_analysis_output(repaired_text)
        normalized = self._normalize_analysis(analysis, difficulty_band=difficulty_band)
        normalized = await self._populate_generated_examples(
            normalized,
            difficulty_band=difficulty_band,
        )
        normalized["source_mode"] = "vllm"
        return normalized

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
        normalized = self._normalize_analysis(analysis, difficulty_band=difficulty_band)
        normalized = await self._populate_generated_examples(
            normalized,
            difficulty_band=difficulty_band,
        )
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

    # def _build_prompt(self, *, difficulty_band: str, notes: str) -> str:
    #     learner_level = canonical_level(difficulty_band)
    #     notes_block = (
    #         f"Learner note from the user: {notes.strip()}"
    #         if notes.strip()
    #         else "Learner note from the user: none."
    #     )
    #     return (
    #         "You are an expert in natural English usage and language learning.\n"
    #         "Analyze the image and return compact minified JSON only.\n"
    #         f"Learner level: {level_label(learner_level)}. {level_guidance(learner_level)}\n"
    #         "Be accurate and fast. No markdown. No text outside JSON. No example arrays.\n"
    #         # For short values
    #         # "Return this shape with short values:\n"
    #         # for longer values
    #         "Return this shape with useful beginner-friendly values:\n" 
    #         "{\n"
    #         '  "title": "",\n'
    #         '  "scene_summary_simple": "one short sentence",\n'
    #         '  "scene_summary_natural": "two short sentences describing the visible scene",\n'
    #         '  "objects": [{"name":"","description":"","importance":0.8}],\n'
    #         '  "actions": [{"verb":"","subject":"","phrase":"","importance":0.8}],\n'
    #         '  "environment": {"setting":"","details":[""]},\n'
    #         '  "vocabulary": [{"word":"","part_of_speech":"","meaning_simple":"","example":""}],\n'
    #         '  "phrases": [{"phrase":"","meaning_simple":"","example":""}],\n'
    #         '  "quiz_candidates": [{"quiz_type":"recognition","prompt":"","answer":"","distractors":["","",""],"explanation":""}],\n'
    #         '  "teaching_notes": [""]\n'
    #         "}\n"
    #         "Rules:\n"
    #         # // TODO: UPDATE HERE
    #         # "- Keep the whole JSON under 150 words.\n"
    #         # "- Use exactly 2 objects, 1 action, 2 vocabulary items, 1 phrase, and 2 quiz_candidates.\n"
    #         "- scene_summary_natural must directly describe the image; no lesson intro.\n"
    #         "- Focus only on natural, real-life English used by native speakers.\n"
    #         "- Prioritize the most important visible subject noun.\n"
    #         "- Do not include basic function words as vocabulary targets.\n"
    #         "- Prefer visible, high-value words and reusable phrases.\n"
    #         "- Keep examples under 8 words each.\n"
    #         "- Finish the JSON early. Do not trail off.\n"
    #         f"{notes_block}"
    #     )


    def _build_prompt(self, *, difficulty_band: str, notes: str) -> str:
        learner_level = canonical_level(difficulty_band)
        notes_block = (
            f"Learner note from the user: {notes.strip()}"
            if notes.strip()
            else "Learner note from the user: none."
        )

        return (
            "You are an expert English tutor teaching a beginner using real-world images.\n"
            "You are also an expert in natural English usage and language learning.\n"
            "Your goal is to turn the image into a useful English lesson with reusable language, not a list of obvious things.\n"
            "Return ONLY valid JSON. No markdown. No text outside JSON.\n\n"

            f"Learner level: {level_label(learner_level)}. {level_guidance(learner_level)}\n\n"

            "Return this JSON structure with detailed, useful, and reusable language:\n"
            "{\n"
            '  "title": "",\n'
            '  "scene_summary_simple": "1 very simple sentence (beginner level)",\n'
            '  "scene_summary_natural": "6-10 natural sentences describing the scene in detail",\n'
            '  "objects": [{"name":"","description":"","importance":0.8}],\n'
            '  "actions": [{"verb":"","subject":"","phrase":"","importance":0.8}],\n'
            '  "environment": {"setting":"","details":[""]},\n'
            '  "vocabulary": [{"word":"","part_of_speech":"","meaning_simple":"","example":"","frequency_priority":"high"}],\n'
            '  "phrases": [{"phrase":"","meaning_simple":"","example":"","collocation_type":"phrase","reusable":true}],\n'
            '  "sentence_patterns": [{"pattern":"","example":"","usage_note":"","examples":["","",""]}],\n'
            '  "quiz_candidates": [{"quiz_type":"recognition","prompt":"","answer":"","distractors":["","",""],"explanation":""}],\n'
            '  "teaching_notes": [""]\n'
            "}\n\n"

            "Rules:\n"
            "- scene_summary_simple must be very easy and clear.\n"
            "- scene_summary_natural must be detailed (6–10 sentences).\n"
            "- Describe what you see, what is happening, and how things relate.\n"
            "- Mention positions: left, right, background, near, far, in front of, behind.\n"
            "- Mention actions clearly (walking, holding, sitting, looking, etc).\n"
            "- Describe the situation like a real person explaining a photo.\n"
            "- Focus only on natural, real-life English used by native speakers.\n"
            "- Name obvious visible subjects in the explanation, but do not teach them as key vocabulary.\n"
            "- Do not include basic function words as vocabulary targets.\n"
            "- Do not use obvious known words as vocabulary targets, such as man, woman, person, sister, brother, park, road, tree, chair, table, shirt, hand, face, phone, or bag.\n"
            "- Vocabulary must be high-value for future speaking: precise actions, descriptive adjectives, scene words, relationship words, or natural collocations.\n"
            "- Prefer words like crowded, shaded, casual, leaning, crossing, gathered, pavement, railing, entrance, expression, posture, background, foreground, nearby, partially visible.\n"
            "- Include 6–10 useful vocabulary words that are worth learning, not just visible object names.\n"
            "- Include 5–8 useful phrases or sentence chunks that can be reused in many photos.\n"
            "- Phrases should be natural chunks like 'standing next to', 'in the background', 'appears to be', 'on the edge of', 'surrounded by', 'looking toward', 'partially hidden by', 'walking past'.\n"
            "- Include 3–5 rich reusable sentence_patterns for describing similar images.\n"
            "- Sentence patterns should help learners write better sentences, for example 'While ..., ...', 'The main subject appears to be ...', 'In the background, ...', 'The scene gives the impression that ...', 'One detail that stands out is ...'.\n"
            "- For each sentence_pattern, include 2–3 example sentences in examples when possible.\n"
            "- Focus on high-frequency, everyday English.\n"
            "- Avoid rare or academic words, but do not make the lesson babyish.\n"
            "- Examples should be short (8–12 words) but natural. But they need to be unique and meaningful.\n"
            "- Make the explanation teach the learner how to describe similar images.\n"
            "- Do NOT be short. This is a teaching explanation.\n"
            "- Keep everything clear and useful for speaking practice.\n"
            "- Finish with valid JSON only.\n\n"

            f"{notes_block}"
        )

    async def feedback_on_explanation(
        self,
        *,
        learner_text: str,
        original_text: str,
        analysis: dict[str, Any],
        learner_level: str,
    ) -> dict[str, Any]:
        validation_feedback = self._validate_learner_answer_for_feedback(
            learner_text=learner_text,
            analysis=analysis,
        )
        if validation_feedback is not None:
            return validation_feedback

        fallback = self._heuristic_explanation_feedback(
            learner_text=learner_text,
            original_text=original_text,
            analysis=analysis,
        )
        prompt = self._build_explanation_feedback_prompt(
            learner_text=learner_text,
            original_text=original_text,
            analysis=analysis,
            learner_level=learner_level,
        )
        try:
            output_text = await self._request_text_generation(
                prompt=prompt,
                max_output_tokens=520,
                temperature=0.2,
            )
            try:
                payload = extract_json_payload(output_text)
            except Exception:
                if self.config.ai_backend != "vllm":
                    raise
                repaired_text = await self._get_local_runtime().repair_json(output_text=output_text)
                payload = extract_json_payload(repaired_text)
            return self._normalize_explanation_feedback(payload, fallback=fallback)
        except Exception as exc:
            print(f"[feedback-fallback] {type(exc).__name__}: {exc}")
            return fallback

    def _build_explanation_feedback_prompt(
        self,
        *,
        learner_text: str,
        original_text: str,
        analysis: dict[str, Any],
        learner_level: str,
    ) -> str:
        visual_reference = {
            "title": analysis.get("title") or "",
            "reference_description": self._short_text(
                analysis.get("natural_explanation") or "",
                limit=520,
            ),
            "visible_objects": analysis.get("objects", [])[:4],
            "visible_actions": analysis.get("actions", [])[:3],
            "environment": analysis.get("environment") or "",
            "environment_details": analysis.get("environment_details", [])[:2],
            "vocabulary": analysis.get("vocabulary", [])[:4],
            "phrases": analysis.get("phrases", [])[:5],
            "reusable_phrase_texts": [
                str(item.get("phrase") or "").strip()
                for item in analysis.get("phrases", [])[:5]
                if str(item.get("phrase") or "").strip()
            ],
            "sentence_patterns": analysis.get("sentence_patterns", [])[:2],
        }
        return (
            "You are an English writing coach for image description practice.\n"
            f"Learner level: {level_label(canonical_level(learner_level))}.\n"
            "The reference description is only visual context, not the perfect answer and not a text to copy.\n"
            "Evaluate the learner's answer like a realistic human English coach.\n"
            "Score in this order: validity/relevance, main subject, setting/background, important visible details, mood/atmosphere or interpretation, English clarity/naturalness, then reusable language.\n"
            "Judge coverage of the whole image before language quality: main subject, setting/background, important objects/details, mood/atmosphere, and relationships/positions between things.\n"
            "The main subject of the image is mandatory for high scores. Good English must not compensate for missing the main subject.\n"
            "Then judge accuracy, clarity, vocabulary, sentence structure, depth of observation, important missing major parts, and how well the learner expresses their own version.\n"
            "Before normal feedback, validate that the answer is understandable English, long enough to evaluate, related to the uploaded image, and mentions visible image elements.\n"
            "If the answer is nonsense, random text, too short, or off-topic, return a low score, empty improvedVersion, and fixes that ask the learner to try again.\n"
            "Do not reward, polish, or preserve unrelated text.\n"
            "The feedback should feel like a personal coach: short, clear, specific, encouraging, and action-oriented.\n"
            "Return valid JSON only with this exact structured shape:\n"
            '{ "score": 0, "scores": {"vocabulary": 0, "structure": 0, "depth": 0, "clarity": 0}, '
            '"languageQuality": {"score": 0, "clarity": 0, "vocabulary": 0, "structure": 0, "grammar": 0, "naturalness": 0, "reusableLanguage": 0}, '
            '"answerValidation": {"valid": true, "reason": "", "retryMessage": ""}, '
            '"coverage": {"level": "low", "mainSubjectMentioned": false, "mainActionMentioned": false, "imageParts": [{"name": "", "description": "", "type": "main_subject", "required": true, "weight": 0, "coverageStatus": "missing", "covered": false, "evidence": ""}], "missingMajorParts": [], "coverageScore": 0, "coveragePercent": 0, "accuracyPenalty": 0, "scoreCapApplied": 0, "reason": ""}, '
            '"mainIssue": "", "whatWentWell": ["", ""], "fixes": ["", "", ""], '
            '"reusableLanguage": {"usedWell": [""], "tryNext": [""], "misused": [{"phrase": "", "note": ""}], "message": ""}, '
            '"missingDetails": ["", "", ""], '
            '"inlineImprovements": [{"old": "", "new": "", "why": ""}], '
            '"improvedVersion": "" }\n'
            "Rules:\n"
            "- First set answerValidation.valid to false if the answer is not understandable English, not relevant to the image, does not mention at least one visible element, is too short, random, or nonsense.\n"
            "- If answerValidation.valid is false: score must be 0-15, improvedVersion must be empty, inlineImprovements must be empty, whatWentWell must be empty, and fixes must tell the learner to mention the main subject, describe the setting, and add 1-2 visible details.\n"
            "- If answerValidation.valid is false: mainIssue should be a short justification such as 'Your answer does not clearly describe the image yet.'\n"
            "- For valid answers, first divide the image into major required parts before scoring: foreground, main subject, main action, setting/background, important objects, and mood/overall meaning.\n"
            "- In coverage.imageParts, list each required part with its weight, coverageStatus, whether the learner covered it, and short evidence from the learner answer. Omit a part only when it truly does not exist in the image, such as main action in a still object photo.\n"
            "- For every required part, classify coverageStatus strictly as covered, partially_covered, missing, or inaccurate. Do not assume coverage unless it is clearly stated in the learner answer.\n"
            "- Scoring by status: covered = full weight; partially_covered = 50% of weight; missing = 0; inaccurate = 0 and apply an accuracy penalty if the inaccuracy is serious.\n"
            "- Explicitly set coverage.mainSubjectMentioned and coverage.mainActionMentioned.\n"
            "- Calculate coverage.coverageScore as the sum of covered and partially covered weights, where partial coverage earns 50% of that part's weight. If the learner only mentions background and mood, coverageScore should be low, such as around 30/100.\n"
            "- Use weighted coverage as the base of the final score. Typical weights are: main subject 25%, main action 20%, setting/background 15%, important objects 15%, foreground/details 10%, mood/overall meaning 15%.\n"
            "- Total image-part weights must equal 100. Main subject and main action must have higher weight than background or mood.\n"
            "- Adjust weights based on the image. If there is no clear action, redistribute the main_action weight into main subject, important objects, and setting/background.\n"
            "- If mood is not important, reduce mood weight and redistribute that weight mostly to main subject and foreground/details.\n"
            "- The final score should feel proportional to image coverage. If 6 parts are required and the learner covers only 2, they should usually be around 30-45, depending on which parts they covered.\n"
            "- For valid answers, assign coverage.coveragePercent from coverageScore, then assign coverage.level: low, partial, overall, or strong.\n"
            "- Apply strict hard score caps AFTER coverage detection, and these caps override everything: nonsense/off-topic/too short = max 15; only one image part covered = max 30; only background described = max 25; only foreground described = max 25; main subject missing = max 40; main action missing when action is important = max 50; main subject mentioned only with no setting/context = max 55; main subject plus small context but missing major parts = max 70; overall image briefly covered = max 80; most parts covered clearly = max 90; complete answer with strong language = max 95.\n"
            "- If the learner does not mention the main subject, the score must not exceed 40 even if the writing is fluent or advanced.\n"
            "- If the main action is important and the learner misses it, the score usually must not exceed 50.\n"
            "- Put the actual cap you applied in coverage.scoreCapApplied. If no limiting cap is needed, use 95.\n"
            "- Only after coverage and hard caps, evaluate languageQuality. Use this weighting: clarity 25, vocabulary 20, structure 20, grammar 15, naturalness 10, reusableLanguage 10.\n"
            "- Good language can add only a small bonus inside the cap, but it can never override missing coverage or any hard cap.\n"
            "- Calculate languageBonus as 0-10 points from clarity, vocabulary, grammar, structure, naturalness, and reusable language.\n"
            "- Calculate final score mechanically as finalScore = min(round(coverageScore + languageBonus - accuracyPenalty), hard cap).\n"
            "- Do not give 90+ unless the answer covers the overall image clearly.\n"
            "- Do not let good English override poor coverage. Beautiful writing about only one part of the image must stay under the relevant cap.\n"
            "- Do not make scoring too harsh. If the learner mentions the main subject, setting/background, at least one important detail, and writes clearly, a score around 70-80 is appropriate even when the English is simple.\n"
            "- A complete but simple answer should beat an advanced but incomplete answer. Strong English plus partial coverage should not receive 80-90. Simple English plus good overall coverage can receive 70-80.\n"
            "- mainIssue or fixes must clearly explain score limits when coverage caps the score, for example: 'Your English is clear, but you only described the foreground and missed the background and overall setting, so your score is limited.'\n"
            "- Feedback must explain what image parts the learner covered, what major parts were missing, whether a score cap was applied, and why the score is limited.\n"
            "- Missing details must prioritize in this order: main subject, main action, setting/background, important objects, foreground, mood.\n"
            "- If the answer only covers background, say something like: 'Your English is clear, but you only described the background and missed the main subject and action.'\n"
            "- Only generate improvedVersion and inlineImprovements when answerValidation.valid is true.\n"
            "- For valid answers, the score is 1-100. Category scores are integers from 1 to 10.\n"
            "- main_issue must be one short sentence naming the biggest improvement area.\n"
            "- what_did_well must contain 1-2 specific positive points.\n"
            "- fix_this_to_improve must contain 2-3 concrete actions, not vague advice.\n"
            "- missing_details must contain up to 3 major missing parts the learner missed, not tiny details.\n"
            "- inlineImprovements must contain 1-3 direct upgrades from the learner's exact wording.\n"
            "- For each inlineImprovements item, old must be an exact word or phrase copied from the current learner explanation, so the UI can show it inline.\n"
            "- Good inlineImprovements examples: {'old':'busy','new':'heavily congested'} or {'old':'many cars','new':'dense traffic'}.\n"
            "- Do not use generic old values like 'simple wording', 'general word', or 'basic vocabulary'.\n"
            "- Every array must contain strings only, except misused and inlineImprovements which must contain objects with the requested keys.\n"
            "- Never put JSON text, markdown, or code inside string fields.\n"
            "- Do not penalize the learner for using different wording from the reference description.\n"
            "- Reward accurate, clear, natural, well-structured, and reasonably detailed writing even if it does not match the reference wording, but only within the coverage cap.\n"
            "- Use the learner's current answer as the foundation for the improved version.\n"
            "- Preserve the learner's original idea and wording where possible; make it more natural, articulate, and complete.\n"
            "- Do not replace the learner's answer with a totally different model answer.\n"
            "- The improved version must be achievable for this learner and must stay close to the learner's meaning.\n"
            "- The improved version must fix the learner's coverage problem: if the learner missed the main subject, include it; if the learner missed the setting/background, include it; remove or correct inaccurate details.\n"
            "- The improved version must include missing major parts, especially subject and action when missing, stay close to the learner level, and include 1-3 reusable phrases naturally when they fit.\n"
            "- Mention important missing major parts, such as main subject, setting, mood, background, positions, or relationships.\n"
            "- If a detail is not supported by the visual context, mark it as an accuracy issue gently.\n"
            "- For repeated improvements, focus on remaining issues and what improved instead of repeating all feedback.\n"
            "- Category scores are integers from 1 to 10.\n"
            "- Show words, phrases, and sentence structures the learner could use instead.\n"
            "- Always include a short phrase_usage section.\n"
            "- Detect whether the learner used any reusable phrases from reusable_phrase_texts.\n"
            "- If the learner used phrases correctly, say 'Good use of reusable language' and list those phrases.\n"
            "- If the learner used no reusable phrases, acknowledge clarity if applicable, then suggest 1-2 phrases that would fit naturally.\n"
            "- If the learner partially used a phrase, name the partial attempt and show the full stronger phrase.\n"
            "- If the learner misused a phrase, explain the issue and give a correct short example.\n"
            "- The improved version should include 1-3 reusable phrases only when they fit the learner's idea naturally.\n"
            "- Keep reusable language scoring small. It is only 10% of languageQuality and must never dominate the score.\n"
            "- Prefer language from the lesson when it fits.\n"
            "- Do not invent image details not supported by the lesson.\n"
            "- Final principle: a high score requires describing the whole image.\n"
            f"Visual context JSON:\n{json.dumps(visual_reference, ensure_ascii=True)}\n"
            f"First learner explanation, if any:\n{self._short_text(original_text, limit=360)}\n"
            f"Current learner explanation:\n{self._short_text(learner_text, limit=520)}"
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
        has_fresh_coverage = bool(fallback_coverage.get("imageParts"))
        validation_valid = validation_payload.get("valid")
        if (
            validation_valid is False
            or str(validation_valid).strip().casefold() == "false"
        ) and not has_fresh_coverage:
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
            if has_fresh_coverage
            else self._normalize_coverage(payload.get("coverage"))
        )
        score = (
            self._normalize_feedback_score(fallback.get("score"), fallback=fallback)
            if has_fresh_coverage
            else self._normalize_feedback_score(payload.get("score"), fallback=fallback)
        )
        if has_fresh_coverage and isinstance(fallback.get("scores"), dict):
            scores = {
                key: max(1, min(10, int(fallback["scores"].get(key, scores[key]))))
                for key in ("vocabulary", "structure", "depth", "clarity")
            }
        if has_fresh_coverage and isinstance(fallback.get("language_quality"), dict):
            language_quality = self._normalize_language_quality(fallback.get("language_quality"))
        score_cap = self._normalized_coverage_hard_cap(coverage)
        coverage["scoreCapApplied"] = score_cap
        if isinstance(score_cap, int) and score_cap > 0:
            score = min(score, score_cap)
        fresh_missing_details = (
            self._clean_string_list(coverage.get("missingMajorParts"), limit=3)
            if has_fresh_coverage
            else []
        )
        missing_details_source = (
            fresh_missing_details
            or ["No major visual detail is missing; focus on making the wording stronger."]
            if has_fresh_coverage
            else payload.get("missingDetails") or payload.get("missing_details") or fallback["missing_details"]
        )

        normalized = {
            "score": score,
            "scores": scores,
            "language_quality": language_quality,
            "coverage": coverage,
            "main_issue": (
                self._clean_text_value(fallback.get("main_issue"))
                if has_fresh_coverage
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
            "quiz_focus": self._clean_string_list(
                payload.get("quiz_focus") or fallback["quiz_focus"],
                limit=4,
            )
            or fallback["quiz_focus"],
        }
        self._dedupe_feedback_sections(normalized)
        return normalized

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
                item.get("use") or item.get("new") or item.get("better")
            )
            if not use:
                continue
            instead_of = self._clean_text_value(
                item.get("instead_of") or item.get("old") or item.get("weak")
            )
            cleaned.append(
                {
                    "instead_of": instead_of,
                    "use": use,
                    "why": self._clean_text_value(item.get("why"))
                    or "This sounds more natural for describing an image.",
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

    def _validate_learner_answer_for_feedback(
        self,
        *,
        learner_text: str,
        analysis: dict[str, Any],
    ) -> dict[str, Any] | None:
        text = re.sub(r"\s+", " ", learner_text.strip())
        words = re.findall(r"[A-Za-z][A-Za-z'-]*", text)
        meaningful_words = [word for word in words if len(word) >= 2]
        if len(meaningful_words) < 4:
            return self._retry_feedback(
                score=8,
                main_issue="Your answer is too short to evaluate clearly.",
                fixes=[
                    "Mention the main subject.",
                    "Describe the background or setting.",
                    "Add one visible detail from the image.",
                ],
            )

        if self._looks_like_nonsense_answer(text, meaningful_words):
            return self._retry_feedback(
                score=5,
                main_issue="Your answer does not look like understandable English yet.",
                fixes=[
                    "Write one complete sentence.",
                    "Mention something you can clearly see.",
                    "Use simple words before adding stronger phrases.",
                ],
            )

        visual_targets = self._feedback_visual_targets(
            objects=analysis.get("objects", [])[:8],
            actions=analysis.get("actions", [])[:6],
            environment_details=analysis.get("environment_details", [])[:6],
        )
        mentioned_targets = [
            item for item in visual_targets if self._feedback_target_in_text(item["text"], text)
        ]
        visual_keywords = self._feedback_visual_keywords(analysis=analysis, targets=visual_targets)
        answer_words = {normalize_answer(word) for word in meaningful_words}
        overlap = answer_words & visual_keywords
        generic_image_words = {"image", "picture", "photo", "scene"}
        has_only_generic_reference = bool(answer_words & generic_image_words) and not overlap

        if not mentioned_targets and len(overlap) < 1:
            return self._retry_feedback(
                score=8 if has_only_generic_reference else 10,
                main_issue="Your answer does not describe the image clearly.",
                fixes=[
                    "Mention the main subject.",
                    "Describe the background or setting.",
                    "Add one visible detail from the image.",
                ],
            )

        return None

    def _looks_like_nonsense_answer(self, text: str, words: list[str]) -> bool:
        if not re.search(r"[A-Za-z]", text):
            return True
        alpha_chars = sum(1 for char in text if char.isalpha())
        visible_chars = sum(1 for char in text if not char.isspace())
        if visible_chars and alpha_chars / visible_chars < 0.55:
            return True
        if re.search(r"(.)\1{4,}", text.casefold()):
            return True
        if len(words) >= 3:
            vowel_words = [word for word in words if re.search(r"[aeiouAEIOU]", word)]
            if len(vowel_words) / len(words) < 0.5:
                return True
        return False

    def _feedback_visual_keywords(
        self,
        *,
        analysis: dict[str, Any],
        targets: list[dict[str, str]],
    ) -> set[str]:
        stopwords = {
            "the",
            "and",
            "with",
            "this",
            "that",
            "there",
            "image",
            "picture",
            "photo",
            "scene",
            "visible",
            "main",
            "subject",
            "thing",
            "something",
            "person",
            "people",
        }
        terms: list[str] = []
        for item in targets:
            terms.append(str(item.get("text") or ""))
            terms.append(str(item.get("label") or ""))
        for item in analysis.get("vocabulary", [])[:8]:
            terms.append(str(item.get("word") or ""))
        for item in analysis.get("phrases", [])[:8]:
            terms.append(str(item.get("phrase") or ""))

        keywords: set[str] = set()
        for term in terms:
            for word in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", term):
                key = normalize_answer(word)
                if key and key not in stopwords:
                    keywords.add(key)

        if keywords & {"man", "woman", "child", "children", "boy", "girl"}:
            keywords.update({"person", "people", "man", "woman", "child", "children", "boy", "girl"})
        if keywords & {"road", "street", "pavement", "sidewalk"}:
            keywords.update({"road", "street", "pavement", "sidewalk"})
        if keywords & {"flower", "plant", "tree", "garden"}:
            keywords.update({"flower", "plant", "tree", "garden"})
        return keywords

    def _retry_feedback(
        self,
        *,
        score: int,
        main_issue: str,
        fixes: list[str],
    ) -> dict[str, Any]:
        score = max(1, min(15, int(score)))
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
                "scoreCapApplied": 15,
                "reason": main_issue,
            },
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
            "word_phrase_upgrades": [],
            "improvements": fixes[:3],
            "better_version": "",
            "alternatives": [],
            "weak_points": fixes[:3],
            "reusable_sentence_structures": [],
            "quiz_focus": ["Image description"],
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
            "quiz_focus": ["Reusable phrases", "Vocabulary", "Weak points", "Sentence improvement"],
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

    def build_quiz_generation_prompt(self, *, analysis: dict[str, Any], learner_level: str) -> str:
        return (
            "You are helping generate quiz seeds for an English learning app.\n"
            f"The learner level is {level_label(learner_level)}.\n"
            "Use the structured lesson JSON below and propose quiz items that practice recognition, phrase completion, "
            "situation understanding, sentence building, fill in the blank, typing recall, and memory recall.\n"
            "Return JSON only with this shape:\n"
            '{ "quiz_items": [ { "quiz_type": "", "prompt": "", "answer": "", "distractors": [], "explanation": "", "answer_mode": "multiple_choice or typing or reorder", "source_text": "" } ] }\n'
            f"Lesson JSON:\n{json.dumps(analysis, ensure_ascii=True)}"
        )

    def _normalize_analysis(
        self, raw: dict[str, Any], *, difficulty_band: str
    ) -> dict[str, Any]:
        learner_level = canonical_level(difficulty_band)
        natural_explanation = self._normalize_explanation(
            str(
                raw.get("scene_summary_natural")
                or raw.get("natural_explanation")
                or raw.get("native_explanation")
                or ""
            ).strip()
        )
        if not natural_explanation:
            raise ValueError("The AI response was missing the lesson explanation.")

        simple_explanation = self._normalize_simple_summary(
            str(raw.get("scene_summary_simple") or raw.get("simple_explanation") or "").strip(),
            fallback_text=natural_explanation,
        )
        objects = self._normalize_objects(raw.get("objects") or [])
        actions = self._normalize_actions(raw.get("actions") or [])
        environment_text, environment_details = self._normalize_environment(raw.get("environment"))
        vocabulary = self._normalize_vocabulary(raw.get("vocabulary") or [])
        phrases = self._normalize_phrases(
            raw.get("phrases") or [],
            raw.get("reusable_language") or [],
            natural_explanation,
        )
        sentence_patterns = self._normalize_sentence_patterns(raw.get("sentence_patterns") or [])
        teaching_notes = self._clean_string_list(
            raw.get("teaching_notes") or raw.get("scene_notes") or [],
            limit=6,
        )
        primary_subject = self._primary_subject_name(objects)

        vocabulary = self._top_up_vocabulary(vocabulary, objects, actions)
        phrases = self._top_up_phrases(phrases, actions, natural_explanation)
        if not vocabulary:
            vocabulary = self._derive_vocabulary_from_explanation(natural_explanation)
        if not phrases:
            phrases = self._derive_phrases_from_explanation(natural_explanation)
        if not sentence_patterns:
            sentence_patterns = self._derive_sentence_patterns(
                natural_explanation=natural_explanation,
                phrases=phrases,
            )

        natural_explanation, vocabulary, phrases = self._synchronize_explanation_language(
            natural_explanation,
            vocabulary=vocabulary,
            phrases=phrases,
            objects=objects,
            actions=actions,
        )

        quiz_candidates = self._normalize_quiz_candidates(
            raw.get("quiz_candidates") or raw.get("micro_quiz") or [],
            objects=objects,
            actions=actions,
            vocabulary=vocabulary,
            phrases=phrases,
            simple_explanation=simple_explanation,
            environment_text=environment_text,
        )
        title = self._normalize_title(
            str(raw.get("title") or "").strip(),
            objects=objects,
            actions=actions,
        )
        if not quiz_candidates:
            raise ValueError("The AI response did not include quiz candidates.")

        reusable_language = self._build_reusable_language(
            phrases=phrases,
            vocabulary=vocabulary,
            sentence_patterns=sentence_patterns,
            natural_explanation=natural_explanation,
            primary_subject=primary_subject,
        )

        micro_quiz = [
            {
                "question": item["prompt"],
                "answer": item["answer"],
                "hint": item.get("explanation", ""),
            }
            for item in quiz_candidates[:6]
        ]

        return {
            "title": title,
            "scene_summary_simple": simple_explanation,
            "scene_summary_natural": natural_explanation,
            "objects": objects,
            "actions": actions,
            "environment": environment_text,
            "environment_details": environment_details,
            "vocabulary": vocabulary,
            "phrases": phrases,
            "sentence_patterns": sentence_patterns,
            "quiz_candidates": quiz_candidates,
            "difficulty_recommendation": str(raw.get("difficulty_recommendation") or "").strip()
            or f"Use mostly {level_label(learner_level).lower()} follow-up quiz items first, then add harder recall after success.",
            "teaching_notes": self._top_up_scene_notes(teaching_notes, natural_explanation),
            "native_explanation": natural_explanation,
            "reusable_language": reusable_language,
            "micro_quiz": micro_quiz,
            "scene_notes": self._top_up_scene_notes(teaching_notes, natural_explanation),
            "difficulty_note": str(raw.get("difficulty_recommendation") or "").strip()
            or f"This lesson was adapted for a {level_label(learner_level)} learner.",
            "raw_analysis": raw,
        }

    async def _populate_generated_examples(
        self,
        analysis: dict[str, Any],
        *,
        difficulty_band: str,
    ) -> dict[str, Any]:
        targets = self._example_targets_from_analysis(
            analysis,
            only_missing_examples=True,
        )
        generated: dict[str, list[str]] = {}
        if targets:
            try:
                generated = await self._generate_item_examples(
                    targets=targets,
                    difficulty_band=difficulty_band,
                )
            except Exception as exc:
                print(f"[examples-fallback] {type(exc).__name__}: {exc}")
                generated = {}
        self._apply_generated_examples(analysis, generated)
        remaining_targets = self._example_targets_from_analysis(
            analysis,
            only_missing_examples=True,
        )
        for target in remaining_targets:
            try:
                generated.update(
                    await self._generate_item_examples(
                        targets=[target],
                        difficulty_band=difficulty_band,
                    )
                )
            except Exception as exc:
                print(f"[examples-fallback] {type(exc).__name__}: {exc}")
        if remaining_targets:
            self._apply_generated_examples(analysis, generated)
        return analysis

    def _example_targets_from_analysis(
        self,
        analysis: dict[str, Any],
        *,
        only_missing_examples: bool = False,
    ) -> list[dict[str, str]]:
        targets: list[dict[str, str]] = []
        seen: set[str] = set()

        for item in analysis.get("vocabulary", []):
            text = str(item.get("word") or "").strip()
            key = normalize_answer(text)
            if not text or not key or key in seen:
                continue
            if only_missing_examples and self._item_has_complete_examples(item, text):
                continue
            seen.add(key)
            targets.append(
                {
                    "text": text,
                    "kind": str(item.get("part_of_speech") or "word").strip() or "word",
                    "meaning_simple": str(item.get("meaning_simple") or "").strip(),
                }
            )

        for item in analysis.get("phrases", []):
            text = str(item.get("phrase") or "").strip()
            key = normalize_answer(text)
            if not text or not key or key in seen:
                continue
            if only_missing_examples and self._item_has_complete_examples(item, text):
                continue
            seen.add(key)
            targets.append(
                {
                    "text": text,
                    "kind": str(item.get("collocation_type") or "phrase").strip() or "phrase",
                    "meaning_simple": str(item.get("meaning_simple") or "").strip(),
                }
            )

        for item in analysis.get("sentence_patterns", []):
            text = str(item.get("pattern") or "").strip()
            key = normalize_answer(text)
            if not text or not key or key in seen:
                continue
            if only_missing_examples and self._sentence_pattern_has_complete_examples(item):
                continue
            seen.add(key)
            targets.append(
                {
                    "text": text,
                    "kind": "sentence pattern",
                    "meaning_simple": str(item.get("usage_note") or "").strip(),
                }
            )

        for item in analysis.get("reusable_language", []):
            text = str(item.get("text") or "").strip()
            kind = str(item.get("kind") or "phrase").strip() or "phrase"
            key = normalize_answer(text)
            if not text or not key or key in seen:
                continue
            if kind == "sentence pattern":
                continue
            if only_missing_examples and self._item_has_complete_examples(item, text):
                continue
            seen.add(key)
            targets.append(
                {
                    "text": text,
                    "kind": kind,
                    "meaning_simple": str(item.get("meaning_simple") or "").strip(),
                }
            )

        return targets

    def _item_has_complete_examples(self, item: dict[str, Any], target_text: str) -> bool:
        examples = self._normalize_example_list(
            target_text,
            item.get("examples") or [],
            fallback_examples=[str(item.get("example") or "").strip()],
        )
        return len(examples) >= 5

    def _sentence_pattern_has_complete_examples(self, item: dict[str, Any]) -> bool:
        examples = self._normalize_sentence_pattern_examples(
            item.get("examples") or [],
            fallback_examples=[str(item.get("example") or "").strip()],
        )
        return len(examples) >= 5

    async def _generate_item_examples(
        self,
        *,
        targets: list[dict[str, str]],
        difficulty_band: str,
    ) -> dict[str, list[str]]:
        prompt = self._build_examples_prompt(targets=targets, difficulty_band=difficulty_band)
        output_text = await self._request_text_generation(
            prompt=prompt,
            max_output_tokens=min(
                max(self.config.inference_max_new_tokens, 500 + len(targets) * 180),
                3600,
            ),
            temperature=0.2,
        )
        return self._parse_generated_examples(output_text, targets=targets)

    async def _request_text_generation(
        self,
        *,
        prompt: str,
        max_output_tokens: int,
        temperature: float,
    ) -> str:
        if self.config.ai_backend == "vllm":
            runtime = self._get_vllm_runtime()
            return await runtime.generate_text(
                prompt=prompt,
                max_tokens=max_output_tokens,
                temperature=temperature,
            )

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

        raise ValueError("No AI backend is available for generating example sentences.")

    def _build_examples_prompt(
        self,
        *,
        targets: list[dict[str, str]],
        difficulty_band: str,
    ) -> str:
        return (
            "You are generating English-learning example sentences.\n"
            f"The learner level is {level_label(canonical_level(difficulty_band))}.\n"
            "Return JSON only with this exact shape:\n"
            '{ "items": [ { "text": "target", "examples": ["", "", "", "", ""] } ] }\n'
            "Rules:\n"
            "- Generate exactly 5 examples for every target.\n"
            "- For word and phrase targets, every example must include the exact target text as written.\n"
            "- For sentence pattern targets, write complete natural sentences that follow the pattern; do not include literal ellipses.\n"
            "- The 5 examples for each target must be fully unique.\n"
            "- Keep the language simple, short, and easy to understand.\n"
            "- Prefer under 12 words per example.\n"
            "- Use natural everyday situations.\n"
            "- Avoid rare words, idioms, and complex grammar.\n"
            "- Avoid repeating the same sentence pattern across the 5 examples.\n"
            "- Do not skip any target.\n"
            "- Do not add markdown or explanation.\n"
            f"Targets JSON:\n{json.dumps({'items': targets}, ensure_ascii=True)}"
        )

    def _parse_generated_examples(
        self,
        output_text: str,
        *,
        targets: list[dict[str, str]] | None = None,
    ) -> dict[str, list[str]]:
        payload = extract_json_payload(output_text)
        items = payload.get("items") if isinstance(payload, dict) else []
        results: dict[str, list[str]] = {}
        if not isinstance(items, list):
            return results

        target_kinds = {
            normalize_answer(str(target.get("text") or "")): str(target.get("kind") or "").casefold()
            for target in targets or []
        }

        for item in items:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            key = normalize_answer(text)
            if not text or not key:
                continue
            if target_kinds.get(key) == "sentence pattern":
                results[key] = self._normalize_sentence_pattern_examples(
                    item.get("examples") or [],
                    fallback_examples=[],
                )
            else:
                results[key] = self._normalize_example_list(
                    text,
                    item.get("examples") or [],
                    fallback_examples=[],
                )
        return results

    def _apply_generated_examples(
        self,
        analysis: dict[str, Any],
        generated: dict[str, list[str]],
    ) -> None:
        for item in analysis.get("vocabulary", []):
            text = str(item.get("word") or "").strip()
            key = normalize_answer(text)
            examples = self._normalize_example_list(
                text,
                generated.get(key) or item.get("examples") or [],
                fallback_examples=[str(item.get("example") or "").strip()],
            )
            if examples:
                item["examples"] = examples[:5]
                item["example"] = examples[0]

        for item in analysis.get("phrases", []):
            text = str(item.get("phrase") or "").strip()
            key = normalize_answer(text)
            examples = self._normalize_example_list(
                text,
                generated.get(key) or item.get("examples") or [],
                fallback_examples=[str(item.get("example") or "").strip()],
            )
            if examples:
                item["examples"] = examples[:5]
                item["example"] = examples[0]

        for item in analysis.get("sentence_patterns", []):
            text = str(item.get("pattern") or "").strip()
            key = normalize_answer(text)
            examples = self._normalize_sentence_pattern_examples(
                generated.get(key) or item.get("examples") or [],
                fallback_examples=[str(item.get("example") or "").strip()],
            )
            if examples:
                item["examples"] = examples[:5]
                item["example"] = examples[0]

        for item in analysis.get("reusable_language", []):
            text = str(item.get("text") or "").strip()
            key = normalize_answer(text)
            if str(item.get("kind") or "").casefold() == "sentence pattern":
                examples = self._normalize_sentence_pattern_examples(
                    generated.get(key) or item.get("examples") or [],
                    fallback_examples=[str(item.get("example") or "").strip()],
                )
            else:
                examples = self._normalize_example_list(
                    text,
                    generated.get(key) or item.get("examples") or [],
                    fallback_examples=[str(item.get("example") or "").strip()],
                )
            if examples:
                item["examples"] = examples[:5]
                item["example"] = examples[0]

        pattern_examples = {
            normalize_answer(str(item.get("pattern") or "")): list(item.get("examples") or [])
            for item in analysis.get("sentence_patterns", [])
        }
        for item in analysis.get("reusable_language", []):
            if str(item.get("kind") or "").casefold() != "sentence pattern":
                continue
            examples = pattern_examples.get(normalize_answer(str(item.get("text") or ""))) or []
            if examples:
                item["examples"] = examples[:5]
                item["example"] = examples[0]

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
            "title": self._extract_field_value(stripped, "title") or "",
            "scene_summary_simple": self._extract_field_value(stripped, "scene_summary_simple") or "",
            "scene_summary_natural": self._extract_field_value(stripped, "scene_summary_natural") or "",
            "objects": self._extract_field_value(stripped, "objects") or [],
            "actions": self._extract_field_value(stripped, "actions") or [],
            "environment": self._extract_field_value(stripped, "environment") or "",
            "vocabulary": self._extract_field_value(stripped, "vocabulary") or [],
            "phrases": self._extract_field_value(stripped, "phrases") or [],
            "sentence_patterns": self._extract_field_value(stripped, "sentence_patterns") or [],
            "quiz_candidates": self._extract_field_value(stripped, "quiz_candidates") or [],
            "difficulty_recommendation": self._extract_field_value(
                stripped, "difficulty_recommendation"
            )
            or "",
            "teaching_notes": self._extract_field_value(stripped, "teaching_notes") or [],
        }

        if not str(raw.get("scene_summary_natural") or "").strip():
            return None

        if not raw["phrases"]:
            raw["reusable_language"] = self._extract_reusable_language_from_explanation(
                str(raw["scene_summary_natural"])
            )
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
            else:
                name = str(item).strip()
                description = ""
                color = ""
                position = ""
                importance = 0.6
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
                }
            )
        return objects

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
            else:
                phrase = str(item).strip()
                verb = phrase.split(" ", 1)[0] if phrase else ""
                subject = ""
                object_text = ""
                description = ""
                importance = 0.6
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
                }
            )
        return actions

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

    def _normalize_quiz_candidates(
        self,
        raw_items: list[Any],
        *,
        objects: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        vocabulary: list[dict[str, Any]],
        phrases: list[dict[str, Any]],
        simple_explanation: str,
        environment_text: str,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[str] = set()

        def push(candidate: dict[str, Any]) -> None:
            prompt = str(candidate.get("prompt") or "").strip()
            answer = str(candidate.get("answer") or "").strip()
            key = f"{candidate.get('quiz_type', '')}:{prompt.casefold()}"
            if not prompt or not answer or key in seen:
                return
            seen.add(key)
            items.append(
                {
                    "quiz_type": str(candidate.get("quiz_type") or "recognition").strip(),
                    "prompt": prompt,
                    "answer": answer,
                    "distractors": [
                        str(item).strip()
                        for item in candidate.get("distractors", [])
                        if str(item).strip()
                    ][:3],
                    "explanation": str(candidate.get("explanation") or "").strip(),
                    "source_text": str(candidate.get("source_text") or answer).strip(),
                }
            )

        for item in raw_items[:8]:
            if isinstance(item, dict):
                push(
                    {
                        "quiz_type": item.get("quiz_type") or "recognition",
                        "prompt": item.get("prompt") or item.get("question") or "",
                        "answer": item.get("answer") or item.get("correct_answer") or "",
                        "distractors": item.get("distractors") or [],
                        "explanation": item.get("explanation") or item.get("hint") or "",
                        "source_text": item.get("source_text") or item.get("answer") or "",
                    }
                )

        if not items and objects:
            object_names = [obj["name"] for obj in objects]
            for obj in objects[:2]:
                push(
                    {
                        "quiz_type": "recognition",
                        "prompt": "What is one key object in this image?",
                        "answer": obj["name"],
                        "distractors": [name for name in object_names if name != obj["name"]][:3],
                        "explanation": obj["description"],
                        "source_text": obj["name"],
                    }
                )

        if len(items) < 4 and phrases:
            for phrase in phrases[:3]:
                push(
                    {
                        "quiz_type": "phrase_completion",
                        "prompt": f'Which phrase means "{phrase["meaning_simple"]}"?',
                        "answer": phrase["phrase"],
                        "distractors": [item["phrase"] for item in phrases if item["phrase"] != phrase["phrase"]][:3],
                        "explanation": phrase.get("example", ""),
                        "source_text": phrase["phrase"],
                    }
                )

        if len(items) < 4 and simple_explanation:
            push(
                {
                    "quiz_type": "situation_understanding",
                    "prompt": "What is happening in this image?",
                    "answer": simple_explanation,
                    "distractors": [
                        "A person is sleeping in a private room.",
                        "The image mainly shows a close-up object with no action.",
                        "There is no clear scene to describe.",
                    ],
                    "explanation": environment_text,
                    "source_text": simple_explanation,
                }
            )

        if len(items) < 4 and vocabulary:
            for vocab in vocabulary[:2]:
                push(
                    {
                        "quiz_type": "recognition",
                        "prompt": f'Which word means "{vocab["meaning_simple"]}"?',
                        "answer": vocab["word"],
                        "distractors": [item["word"] for item in vocabulary if item["word"] != vocab["word"]][:3],
                        "explanation": vocab.get("example", ""),
                        "source_text": vocab["word"],
                    }
                )

        return items[:8]

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
        subject_hint = notes.strip() or f"the uploaded image called {filename}"
        explanation = (
            f"This is a demo lesson for {subject_hint}. The live version looks at the real image and "
            "turns it into a practical English study session.\n\n"
            "The learner first gets a fuller explanation of the scene with more detail about what is visible, "
            "how the parts of the image connect, and which words are useful in real life.\n\n"
            "After that, the app highlights common words, useful phrases, and natural sentence patterns inside "
            "the explanation itself so the learner can notice reusable English in context.\n\n"
            "Those same words and phrases become quiz questions, future review items, and part of a daily challenge."
        )
        analysis = {
            "title": "Demo lesson preview",
            "scene_summary_simple": "This is a demo lesson that shows how image-based English practice works.",
            "scene_summary_natural": explanation,
            "objects": [
                {
                    "name": "lesson",
                    "description": "The app turns one image into one saved learning session.",
                    "importance": 0.9,
                    "color": "",
                    "position": "center",
                },
                {
                    "name": "phrase",
                    "description": "Useful phrases are highlighted and saved for review.",
                    "importance": 0.8,
                    "color": "",
                    "position": "throughout the lesson",
                },
            ],
            "actions": [
                {
                    "verb": "study",
                    "subject": "the learner",
                    "object": "the scene",
                    "phrase": "study the scene",
                    "description": "The learner reads the explanation and notices useful English.",
                    "importance": 0.9,
                },
                {
                    "verb": "review",
                    "subject": "the learner",
                    "object": "key phrases",
                    "phrase": "review key phrases",
                    "description": "The same language comes back later in quizzes and review.",
                    "importance": 0.9,
                },
            ],
            "environment": "The app is in demo mode because no live AI key is configured.",
            "environment_details": [
                "You can still test saved sessions, quizzes, review scheduling, and progress tracking."
            ],
            "vocabulary": [
                {
                    "word": "lesson",
                    "part_of_speech": "noun",
                    "meaning_simple": "one focused piece of study content",
                    "example": "Each uploaded image becomes a lesson.",
                    "frequency_priority": "high",
                },
                {
                    "word": "review",
                    "part_of_speech": "verb",
                    "meaning_simple": "to study something again later",
                    "example": "The app asks you to review useful words later.",
                    "frequency_priority": "high",
                },
                {
                    "word": "practice",
                    "part_of_speech": "noun",
                    "meaning_simple": "repeated learning activity",
                    "example": "Daily practice helps you remember more English.",
                    "frequency_priority": "high",
                },
            ],
            "phrases": [
                {
                    "phrase": "study the scene",
                    "meaning_simple": "look carefully at the image and understand it",
                    "example": "First, study the scene and notice the main details.",
                    "reusable": True,
                    "collocation_type": "verb phrase",
                },
                {
                    "phrase": "review key phrases",
                    "meaning_simple": "practice useful phrases again later",
                    "example": "Later, review key phrases from the same session.",
                    "reusable": True,
                    "collocation_type": "verb phrase",
                },
                {
                    "phrase": "daily challenge",
                    "meaning_simple": "a short set of questions for today",
                    "example": "The daily challenge mixes old and new learning items.",
                    "reusable": True,
                    "collocation_type": "phrase",
                },
            ],
            "sentence_patterns": [
                {
                    "pattern": "This image shows ...",
                    "example": "This image shows a useful everyday scene.",
                    "usage_note": "Use this to begin a simple description.",
                }
            ],
            "quiz_candidates": [
                {
                    "quiz_type": "recognition",
                    "prompt": "Which word means one focused piece of study content?",
                    "answer": "lesson",
                    "distractors": ["corner", "window", "camera"],
                    "explanation": "A lesson is one saved learning session.",
                    "source_text": "lesson",
                },
                {
                    "quiz_type": "phrase_completion",
                    "prompt": 'Which phrase means "practice useful phrases again later"?',
                    "answer": "review key phrases",
                    "distractors": ["study the scene", "look at the background", "wait for the image"],
                    "explanation": "This phrase is useful for spaced review.",
                    "source_text": "review key phrases",
                },
                {
                    "quiz_type": "situation_understanding",
                    "prompt": "What is this app doing with the uploaded image?",
                    "answer": "It turns the image into a saved English lesson and quiz set.",
                    "distractors": [
                        "It only stores the image without teaching anything.",
                        "It sends the image to a public gallery.",
                        "It hides the image and only shows a score.",
                    ],
                    "explanation": "The app creates learning content from the image.",
                    "source_text": "lesson",
                },
            ],
            "difficulty_recommendation": (
                f"This demo lesson is shaped for a {level_label(difficulty_band)} learner and keeps the focus on practical English."
            ),
            "teaching_notes": [
                fallback_reason
                or "The app is running in demo mode because no live AI key is configured.",
                "You can still test sign-up, saved sessions, quizzes, and spaced repetition.",
                "Add a live AI backend later to analyze real image contents.",
            ],
        }
        normalized = self._normalize_analysis(analysis, difficulty_band=difficulty_band)
        self._apply_generated_examples(normalized, {})
        normalized["source_mode"] = "demo"
        return normalized


class VLLMVisionRuntime:
    def __init__(self, config: AppConfig, prompt_builder) -> None:
        self.config = config
        self.prompt_builder = prompt_builder
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[_QueuedVLLMRequest] | None = None
        self._semaphore: asyncio.Semaphore | None = None
        self._dispatcher_task: asyncio.Task[None] | None = None
        self._active_tasks: set[asyncio.Task[None]] = set()
        self._http_client: httpx.AsyncClient | None = None
        self._state_lock = threading.Lock()

    def _repair_max_new_tokens(self) -> int:
        return min(max(self.config.inference_max_new_tokens, 260), 360)

    async def warmup(self) -> None:
        from tempfile import NamedTemporaryFile

        from PIL import Image, ImageDraw

        self.config.uploads_dir.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            suffix=".png",
            dir=self.config.uploads_dir,
        ) as handle:
            image = Image.new("RGB", (96, 96), color=(223, 235, 255))
            draw = ImageDraw.Draw(image)
            draw.rectangle((16, 18, 80, 78), outline=(33, 66, 120), width=3)
            draw.ellipse((28, 30, 68, 70), fill=(201, 88, 65))
            image.save(handle.name, format="PNG")
            await self.generate(
                image_path=Path(handle.name),
                prompt=self.prompt_builder(
                    difficulty_band="beginner",
                    notes="Warm up the local vLLM vision-language model.",
                ),
                max_new_tokens=48,
                temperature=0.0,
            )

    async def close(self) -> None:
        with self._state_lock:
            dispatcher_task = self._dispatcher_task
            active_tasks = list(self._active_tasks)
            http_client = self._http_client
            self._dispatcher_task = None
            self._active_tasks = set()
            self._http_client = None
            self._queue = None
            self._semaphore = None
            self._loop = None

        if dispatcher_task is not None:
            dispatcher_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await dispatcher_task

        for task in active_tasks:
            task.cancel()
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)

        if http_client is not None:
            await http_client.aclose()

    async def generate(
        self,
        *,
        image_path: Path,
        prompt: str,
        max_new_tokens: int,
        temperature: float,
    ) -> str:
        resolved_path, temp_path = self._prepare_image_for_vllm(image_path)
        payload = {
            "model": self.config.vllm_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a careful English-learning coach. "
                        "Always return valid JSON and no markdown. "
                        "Do not use teacher-style meta wording such as 'let's look at' "
                        "inside the explanation."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"file://{resolved_path}"},
                        },
                    ],
                },
            ],
            "max_tokens": max_new_tokens,
            "temperature": temperature,
        }
        try:
            return await self._submit_chat_completion(payload)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    async def repair_json(self, *, output_text: str) -> str:
        payload = {
            "model": self.config.vllm_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You repair malformed JSON. "
                        "Return valid JSON only. "
                        "Do not add markdown or explanation. "
                        "Preserve the original meaning and keys as much as possible."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Fix the following malformed JSON so it becomes valid JSON. "
                        "Keep the same top-level structure and data whenever possible.\n\n"
                        f"{output_text}"
                    ),
                },
            ],
            "max_tokens": self._repair_max_new_tokens(),
            "temperature": 0.0,
        }
        return await self._submit_chat_completion(payload)

    async def generate_text(
        self,
        *,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        payload = {
            "model": self.config.vllm_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a careful English-learning coach. "
                        "Always return valid JSON and no markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        return await self._submit_chat_completion(payload)

    async def _submit_chat_completion(self, payload: dict[str, Any]) -> str:
        await self._ensure_dispatcher()
        queue = self._queue
        if queue is None:
            raise RuntimeError("The vLLM request queue is unavailable.")

        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        await queue.put(_QueuedVLLMRequest(payload=payload, future=future))
        return await future

    async def _ensure_dispatcher(self) -> None:
        loop = asyncio.get_running_loop()

        with self._state_lock:
            if self._loop is None:
                self._loop = loop
                self._queue = asyncio.Queue()
                self._semaphore = asyncio.Semaphore(self.config.vllm_max_concurrency)
            elif self._loop is not loop:
                raise RuntimeError("The vLLM runtime cannot be shared across multiple event loops.")

            if self._http_client is None:
                connection_limit = max(
                    self.config.vllm_max_concurrency * 2,
                    self.config.vllm_batch_max_size,
                )
                self._http_client = httpx.AsyncClient(
                    timeout=self.config.vllm_timeout_seconds,
                    limits=httpx.Limits(
                        max_connections=connection_limit,
                        max_keepalive_connections=self.config.vllm_max_concurrency,
                    ),
                )

            if self._dispatcher_task is None or self._dispatcher_task.done():
                self._dispatcher_task = asyncio.create_task(
                    self._dispatch_loop(),
                    name="vllm-dispatcher",
                )

    async def _dispatch_loop(self) -> None:
        queue = self._queue
        if queue is None:
            return

        batch_interval_seconds = self.config.vllm_batch_interval_ms / 1000
        batch_max_size = max(
            self.config.vllm_max_concurrency,
            self.config.vllm_batch_max_size,
        )
        loop = asyncio.get_running_loop()

        while True:
            request = await queue.get()
            if request.future.cancelled():
                continue

            batch = [request]
            if batch_interval_seconds <= 0:
                while len(batch) < batch_max_size:
                    try:
                        next_request = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if next_request.future.cancelled():
                        continue
                    batch.append(next_request)
            else:
                deadline = loop.time() + batch_interval_seconds
                while len(batch) < batch_max_size:
                    try:
                        timeout = deadline - loop.time()
                        if timeout <= 0:
                            break
                        next_request = await asyncio.wait_for(queue.get(), timeout=timeout)
                    except asyncio.TimeoutError:
                        break
                    if next_request.future.cancelled():
                        continue
                    batch.append(next_request)

            for item in batch:
                task = asyncio.create_task(self._run_request(item))
                self._track_task(task)

    def _track_task(self, task: asyncio.Task[None]) -> None:
        active_tasks = self._active_tasks
        active_tasks.add(task)
        task.add_done_callback(active_tasks.discard)

    async def _run_request(self, request: _QueuedVLLMRequest) -> None:
        semaphore = self._semaphore
        if semaphore is None:
            if not request.future.done():
                request.future.set_exception(RuntimeError("The vLLM concurrency limiter is unavailable."))
            return

        try:
            async with semaphore:
                content = await self._execute_chat_completion(request.payload)
        except Exception as exc:
            if not request.future.done():
                request.future.set_exception(exc)
            return

        if not request.future.done():
            request.future.set_result(content)

    async def _execute_chat_completion(self, payload: dict[str, Any]) -> str:
        client = self._http_client
        if client is None:
            raise RuntimeError("The vLLM HTTP client is unavailable.")

        headers = {
            "Authorization": f"Bearer {self.config.vllm_api_key}",
            "Content-Type": "application/json",
        }

        response = await client.post(
            f"{self.config.vllm_base_url}/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()

        data = response.json()
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("The vLLM response did not include any choices.")

        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise ValueError("The vLLM response was missing the assistant message.")

        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            text_parts: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text" and item.get("text"):
                    text_parts.append(str(item["text"]))
            if text_parts:
                return "\n".join(text_parts)
        raise ValueError("The vLLM response did not include any text output.")

    def _prepare_image_for_vllm(self, image_path: Path) -> tuple[Path, Path | None]:
        from PIL import Image

        with Image.open(image_path) as source:
            width, height = source.size
            pixel_count = width * height
            max_pixels = self.config.image_max_pixels
            if pixel_count <= max_pixels:
                return image_path.resolve(), None

            scale = math.sqrt(max_pixels / pixel_count)
            resized_width = max(28, int(width * scale))
            resized_height = max(28, int(height * scale))
            resized_width = max(28, resized_width - (resized_width % 28))
            resized_height = max(28, resized_height - (resized_height % 28))

            resized = source.convert("RGB")
            resized.thumbnail((resized_width, resized_height))

            self.config.uploads_dir.mkdir(parents=True, exist_ok=True)
            temp_path = image_path.with_name(f"{image_path.stem}-vllm.png")
            resized.save(temp_path, format="PNG")
            return temp_path.resolve(), temp_path
