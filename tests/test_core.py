from __future__ import annotations

from datetime import timezone
import os
from pathlib import Path
import tempfile
import unittest
import asyncio
from unittest.mock import patch

from english_learner_app.assessment import evaluate_assessment
from english_learner_app.ai_service import AIAnalyzer
from english_learner_app.config import AppConfig
from english_learner_app.quiz_engine import build_session_assets, evaluate_quiz_response
from english_learner_app.review import (
    build_study_cards,
    calculate_next_review,
    select_quiz_cards,
)
from english_learner_app.server import build_highlight_terms
from english_learner_app.utils import from_iso, highlight_phrases


class AssessmentTests(unittest.TestCase):
    def test_assessment_band_easy(self) -> None:
        result = evaluate_assessment(
            {
                "listening_confidence": 1,
                "description_confidence": 2,
                "reading_frequency": 2,
                "phrase_familiarity": 2,
            }
        )
        self.assertEqual(result["difficulty_band"], "beginner")

    def test_assessment_band_extremely_hard(self) -> None:
        result = evaluate_assessment(
            {
                "listening_confidence": 5,
                "description_confidence": 5,
                "reading_frequency": 4,
                "phrase_familiarity": 5,
            }
        )
        self.assertEqual(result["difficulty_band"], "advancing")


class ConfigTests(unittest.TestCase):
    def test_config_defaults_to_vllm_model_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        self.assertEqual(config.ai_backend, "demo")
        self.assertEqual(config.data_dir, Path(temp_dir) / "app_data")
        self.assertEqual(config.uploads_dir, Path(temp_dir) / "app_data" / "uploads")
        self.assertEqual(
            config.database_path,
            Path(temp_dir) / "app_data" / "english_learner.sqlite3",
        )
        self.assertEqual(config.vllm_base_url, "http://127.0.0.1:8000/v1")
        self.assertEqual(config.vllm_api_key, "local-dev")
        self.assertEqual(config.vllm_model, "Qwen/Qwen2.5-VL-7B-Instruct-AWQ")
        self.assertEqual(config.vllm_max_concurrency, 8)
        self.assertEqual(config.vllm_batch_interval_ms, 30)
        self.assertEqual(config.vllm_batch_max_size, 8)

    def test_config_reads_vllm_settings_from_env(self) -> None:
        env = {
            "AI_BACKEND": "vllm",
            "VLLM_BASE_URL": "http://127.0.0.1:9000/v1/",
            "VLLM_API_KEY": "abc123",
            "VLLM_MODEL": "Qwen/custom",
            "VLLM_MAX_CONCURRENCY": "5",
            "VLLM_BATCH_INTERVAL_MS": "45",
            "VLLM_BATCH_MAX_SIZE": "6",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, env, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        self.assertEqual(config.ai_backend, "vllm")
        self.assertEqual(config.vllm_base_url, "http://127.0.0.1:9000/v1")
        self.assertEqual(config.vllm_api_key, "abc123")
        self.assertEqual(config.vllm_model, "Qwen/custom")
        self.assertEqual(config.vllm_max_concurrency, 5)
        self.assertEqual(config.vllm_batch_interval_ms, 45)
        self.assertEqual(config.vllm_batch_max_size, 6)

    def test_config_reads_runtime_data_paths_from_env(self) -> None:
        env = {
            "APP_DATA_DIR": "runtime-data",
            "UPLOADS_DIR": "runtime-uploads",
            "DATABASE_PATH": "runtime-db/app.sqlite3",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.dict(os.environ, env, clear=True):
                config = AppConfig.from_env(base_dir=root)

        self.assertEqual(config.data_dir, root / "runtime-data")
        self.assertEqual(config.uploads_dir, root / "runtime-uploads")
        self.assertEqual(config.database_path, root / "runtime-db" / "app.sqlite3")


class AIAnalyzerTests(unittest.TestCase):
    def test_prompt_emphasizes_natural_english_and_reusable_language(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        prompt = analyzer._build_prompt(difficulty_band="beginner", notes="")

        self.assertIn("expert in natural English usage and language learning", prompt)
        self.assertIn("Focus only on natural, real-life English used by native speakers", prompt)
        self.assertIn("do not teach them as key vocabulary", prompt)
        self.assertIn("Sentence patterns should help learners write better sentences", prompt)
        self.assertIn("Do not include basic function words", prompt)

    def test_vllm_error_raises_when_demo_mode_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "AI_BACKEND": "vllm",
                "DEMO_MODE": "false",
            }
            with patch.dict(os.environ, env, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)

        async def boom(**kwargs):
            raise RuntimeError("vllm down")

        analyzer._vllm_response = boom  # type: ignore[method-assign]

        with self.assertRaises(RuntimeError):
            asyncio.run(
                analyzer.analyze_image(
                    image_bytes=b"fake",
                    mime_type="image/png",
                    filename="test.png",
                    image_path=Path("/tmp/test.png"),
                    difficulty_band="beginner",
                    notes="",
                )
            )

    def test_large_vllm_image_is_downscaled_before_request(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "AI_BACKEND": "vllm",
                "DEMO_MODE": "false",
                "IMAGE_MAX_PIXELS": "200704",
            }
            with patch.dict(os.environ, env, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        runtime = analyzer._get_local_runtime()
        uploads_dir = config.uploads_dir
        uploads_dir.mkdir(parents=True, exist_ok=True)
        image_path = uploads_dir / "large.png"
        Image.new("RGB", (4000, 3000), color=(200, 120, 80)).save(image_path)

        prepared_path, temp_path = runtime._prepare_image_for_vllm(image_path)

        self.assertIsNotNone(temp_path)
        self.assertTrue(prepared_path.exists())
        with Image.open(prepared_path) as prepared:
            self.assertLessEqual(prepared.width * prepared.height, config.image_max_pixels)
        temp_path.unlink(missing_ok=True)

    def test_vllm_json_repair_is_used_when_first_parse_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "AI_BACKEND": "vllm",
                "DEMO_MODE": "false",
            }
            with patch.dict(os.environ, env, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)

        class FakeRuntime:
            async def generate(self, **kwargs):
                return '{"title":"Bad "quote","scene_summary_simple":"x"}'

            async def repair_json(self, *, output_text: str):
                return (
                    '{"title":"Recovered lesson","scene_summary_simple":"Simple summary.",'
                    '"scene_summary_natural":"First sentence.\\n\\nSecond sentence.",'
                    '"objects":[{"name":"book","description":"A book.","importance":0.8,"color":"","position":"center"}],'
                    '"actions":[{"verb":"hold","subject":"A person","object":"a book","phrase":"hold a book","description":"A person holds a book.","importance":0.8}],'
                    '"environment":{"setting":"room","details":["indoor scene"],"mood":"calm"},'
                    '"vocabulary":[{"word":"book","part_of_speech":"noun","meaning_simple":"something you read","example":"This is a book.","frequency_priority":"high"},'
                    '{"word":"hold","part_of_speech":"verb","meaning_simple":"keep something in your hand","example":"She can hold it.","frequency_priority":"high"}],'
                    '"phrases":[{"phrase":"hold a book","meaning_simple":"keep a book in your hand","example":"He can hold a book.","reusable":true,"collocation_type":"phrase"}],'
                    '"sentence_patterns":[{"pattern":"There is a ...","example":"There is a book on the table.","usage_note":"Use it to describe what you see."}],'
                    '"quiz_candidates":[{"quiz_type":"recognition","prompt":"What object is visible?","answer":"book","distractors":["chair","table","lamp"],"explanation":"The book is visible.","source_text":"book"},'
                    '{"quiz_type":"phrase_completion","prompt":"Which phrase means keep a book in your hand?","answer":"hold a book","distractors":["open a door","sit on a chair","look at a wall"],"explanation":"It describes the action.","source_text":"hold a book"},'
                    '{"quiz_type":"situation_understanding","prompt":"What is happening?","answer":"A person is holding a book.","distractors":["A person is sleeping.","A person is running.","A person is cooking."],"explanation":"The action is visible.","source_text":"A person is holding a book."},'
                    '{"quiz_type":"recognition","prompt":"Which word means something you read?","answer":"book","distractors":["lamp","window","floor"],"explanation":"Book is the correct word.","source_text":"book"}],'
                    '"difficulty_recommendation":"Keep the next practice simple.",'
                    '"teaching_notes":["Focus on the main object first."]}'
                )

        analyzer._get_local_runtime = lambda: FakeRuntime()  # type: ignore[method-assign]

        result = asyncio.run(
            analyzer.analyze_image(
                image_bytes=b"fake",
                mime_type="image/png",
                filename="test.png",
                image_path=Path("/tmp/test.png"),
                difficulty_band="beginner",
                notes="",
            )
        )

        self.assertEqual(result["title"], "Recovered lesson")
        self.assertEqual(result["source_mode"], "vllm")

    def test_normalize_analysis_syncs_explanation_with_phrases_and_words(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        analysis = analyzer._normalize_analysis(
            {
                "title": "Reading by the window",
                "scene_summary_simple": "A woman sits by a window.",
                "scene_summary_natural": (
                    "A woman sits quietly by a window while soft light fills the room.\n\n"
                    "The room feels calm, and her posture suggests a peaceful moment."
                ),
                "objects": [
                    {
                        "name": "book",
                        "description": "A book rests in her hands.",
                        "importance": 0.8,
                        "color": "",
                        "position": "near her lap",
                    }
                ],
                "actions": [
                    {
                        "verb": "hold",
                        "subject": "The woman",
                        "object": "a book",
                        "phrase": "hold a book",
                        "description": "The woman seems to hold a book.",
                        "importance": 0.8,
                    }
                ],
                "environment": {"setting": "indoors", "details": ["soft light"], "mood": "calm"},
                "vocabulary": [
                    {
                        "word": "book",
                        "part_of_speech": "noun",
                        "meaning_simple": "pages you can read",
                        "example": "A book rests in her hands.",
                        "examples": [
                            "This book is on the desk.",
                            "I carry this book to class.",
                            "Her book looks very new.",
                            "The book stays in my bag.",
                            "We open the book together.",
                        ],
                        "frequency_priority": "high",
                    }
                ],
                "phrases": [
                    {
                        "phrase": "hold a book",
                        "meaning_simple": "keep a book in your hands",
                        "example": "The woman seems to hold a book.",
                        "examples": [
                            "I hold a book on the bus.",
                            "She can hold a book easily.",
                            "They hold a book for the photo.",
                            "We hold a book during class.",
                            "He will hold a book today.",
                        ],
                        "reusable": True,
                        "collocation_type": "verb phrase",
                    }
                ],
                "sentence_patterns": [],
                "quiz_candidates": [
                    {
                        "quiz_type": "recognition",
                        "prompt": "What is the woman holding?",
                        "answer": "a book",
                        "distractors": ["a lamp", "a bag", "a cup"],
                        "explanation": "The woman seems to hold a book.",
                        "source_text": "hold a book",
                    }
                ],
                "teaching_notes": [],
            },
            difficulty_band="beginner",
        )

        explanation = analysis["scene_summary_natural"]
        self.assertIn("hold a book", explanation.lower())
        self.assertIn("book", explanation.lower())

        for item in analysis["phrases"]:
            self.assertIn(item["phrase"].lower(), explanation.lower())
            self.assertIn(item["phrase"].lower(), item["example"].lower())
            self.assertGreaterEqual(len(item["examples"]), 1)

        for item in analysis["vocabulary"]:
            self.assertIn(item["word"].lower(), explanation.lower())
            self.assertIn(item["word"].lower(), item["example"].lower())
            self.assertGreaterEqual(len(item["examples"]), 1)

        reusable_texts = {item["text"].lower(): item for item in analysis["reusable_language"]}
        self.assertIn("hold a book", reusable_texts)
        self.assertIn("hold a book", reusable_texts["hold a book"]["example"].lower())
        self.assertGreaterEqual(len(reusable_texts["hold a book"]["examples"]), 1)
        self.assertIn("book", reusable_texts)
        self.assertIn("book", reusable_texts["book"]["example"].lower())
        self.assertGreaterEqual(len(reusable_texts["book"]["examples"]), 1)

    def test_apply_generated_examples_sets_five_examples_per_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        analysis = {
            "vocabulary": [{"word": "book", "example": "This is a book.", "examples": []}],
            "phrases": [{"phrase": "hold a book", "example": "I hold a book.", "examples": []}],
            "sentence_patterns": [
                {
                    "pattern": "While ..., ...",
                    "example": "While she reads, the room stays quiet.",
                    "examples": [],
                }
            ],
            "reusable_language": [
                {"text": "book", "example": "This is a book.", "examples": []},
                {"text": "hold a book", "example": "I hold a book.", "examples": []},
                {
                    "text": "While ..., ...",
                    "kind": "sentence pattern",
                    "example": "While she reads, the room stays quiet.",
                    "examples": [],
                },
            ],
        }

        analyzer._apply_generated_examples(
            analysis,
            {
                "book": [
                    "This book is on my desk.",
                    "I open the book after dinner.",
                    "Her book stays in the bag.",
                    "We share the book in class.",
                    "The book looks very new.",
                ],
                "hold a book": [
                    "I hold a book on the bus.",
                    "She can hold a book easily.",
                    "They hold a book for class.",
                    "We hold a book in the photo.",
                    "He will hold a book today.",
                ],
                "while": [
                    "While she reads, the room stays quiet.",
                    "While the children play, their parents watch nearby.",
                    "While he waits, he looks toward the entrance.",
                    "While the sun sets, people walk along the road.",
                    "While one person speaks, the others listen carefully.",
                ],
            },
        )

        self.assertEqual(5, len(analysis["vocabulary"][0]["examples"]))
        self.assertEqual(5, len(analysis["phrases"][0]["examples"]))
        self.assertEqual(5, len(analysis["sentence_patterns"][0]["examples"]))
        self.assertEqual(5, len(analysis["reusable_language"][0]["examples"]))
        self.assertEqual(5, len(analysis["reusable_language"][1]["examples"]))
        self.assertEqual(5, len(analysis["reusable_language"][2]["examples"]))

    def test_feedback_normalization_strips_raw_json_objects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        fallback = {
            "score": 50,
            "scores": {"vocabulary": 5, "structure": 5, "depth": 5, "clarity": 5},
            "main_issue": "Add clearer detail.",
            "what_did_well": ["Your answer is understandable."],
            "missing_details": [],
            "phrase_usage": {
                "used": [],
                "suggested": ["in the background"],
                "partial": [],
                "misused": [],
                "rewardable_count": 0,
                "message": "Try one learned phrase.",
            },
            "fix_this_to_improve": ["Add one specific visual detail."],
            "word_phrase_upgrades": [],
            "improvements": [],
            "better_version": "The man is sitting calmly near the water.",
            "alternatives": [],
            "weak_points": [],
            "reusable_sentence_structures": [],
            "quiz_focus": [],
        }
        payload = {
            "score": 62,
            "mainIssue": {"attempt": "", "phrase": "", "note": ""},
            "whatWentWell": [{"text": "Your answer is easy to understand."}],
            "fixes": ["Add the background detail.", "Add the background detail."],
            "reusableLanguage": {
                "usedWell": [{"attempt": "", "phrase": "", "note": ""}],
                "tryNext": [{"phrase": "in the background"}],
                "misused": [{"phrase": {"bad": "object"}, "note": "{}"}],
                "message": "{ attempt: \"\", phrase: \"\", note: \"\" }",
            },
            "missingDetails": ["background trees"],
            "inlineImprovements": [{"old": "nice", "new": "peaceful", "why": {"note": "bad"}}],
            "improvedVersion": "{ broken: true }",
        }

        normalized = analyzer._normalize_explanation_feedback(payload, fallback=fallback)

        self.assertEqual("Add clearer detail.", normalized["main_issue"])
        self.assertEqual(["Your answer is easy to understand."], normalized["what_did_well"])
        self.assertEqual([], normalized["phrase_usage"]["used"])
        self.assertEqual(["in the background"], normalized["phrase_usage"]["suggested"])
        self.assertNotIn("{", normalized["phrase_usage"]["message"])
        self.assertEqual("nice", normalized["word_phrase_upgrades"][0]["instead_of"])
        self.assertEqual("peaceful", normalized["word_phrase_upgrades"][0]["use"])
        self.assertEqual(fallback["better_version"], normalized["better_version"])

    def test_feedback_validation_rejects_too_short_or_off_topic_answers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        analysis = {
            "objects": [{"name": "flower", "description": "A flower is visible.", "importance": 0.9}],
            "actions": [],
            "environment_details": ["outdoor garden"],
            "vocabulary": [{"word": "petal"}],
            "phrases": [{"phrase": "in the garden"}],
        }

        short_feedback = analyzer._validate_learner_answer_for_feedback(
            learner_text="booring image",
            analysis=analysis,
        )
        self.assertIsNotNone(short_feedback)
        self.assertTrue(short_feedback["retry_required"])
        self.assertEqual("", short_feedback["better_version"])
        self.assertLessEqual(short_feedback["score"], 15)

        off_topic_feedback = analyzer._validate_learner_answer_for_feedback(
            learner_text="The street has many cars and tall buildings.",
            analysis=analysis,
        )
        self.assertIsNotNone(off_topic_feedback)
        self.assertTrue(off_topic_feedback["retry_required"])

        relevant_feedback = analyzer._validate_learner_answer_for_feedback(
            learner_text="The flower is outside in a small garden.",
            analysis=analysis,
        )
        self.assertIsNone(relevant_feedback)

    def test_ai_feedback_validation_payload_maps_to_retry_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        fallback = analyzer._retry_feedback(
            score=8,
            main_issue="Your answer does not clearly describe the image yet.",
            fixes=["Mention the main subject."],
        )
        normalized = analyzer._normalize_explanation_feedback(
            {
                "score": 2,
                "answerValidation": {
                    "valid": False,
                    "reason": "Your answer does not clearly describe the image yet.",
                    "retryMessage": "Try again with visible details.",
                },
                "mainIssue": "Do not use this over the validation reason.",
                "fixes": [
                    "Mention the main subject.",
                    "Describe the setting.",
                    "Add 1-2 visible details.",
                ],
                "improvedVersion": "This should not appear.",
                "inlineImprovements": [{"old": "bad", "new": "better"}],
            },
            fallback=fallback,
        )

        self.assertTrue(normalized["retry_required"])
        self.assertEqual(2, normalized["score"])
        self.assertEqual("", normalized["better_version"])
        self.assertEqual([], normalized["word_phrase_upgrades"])
        self.assertEqual("Try Again", normalized["cta_label"])

    def test_reusable_language_prefers_high_value_expression_over_common_word(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        analysis = analyzer._normalize_analysis(
            {
                "title": "Nature mood",
                "scene_summary_simple": "The scene feels calm.",
                "scene_summary_natural": (
                    "The overall mood is peaceful and inviting, evoking a sense of calm and "
                    "connection with nature."
                ),
                "objects": [],
                "actions": [],
                "environment": {"setting": "outdoors", "details": [], "mood": "peaceful"},
                "vocabulary": [
                    {
                        "word": "inviting",
                        "part_of_speech": "adjective",
                        "meaning_simple": "pleasant and welcoming",
                        "example": "The space feels inviting.",
                        "frequency_priority": "high",
                    }
                ],
                "phrases": [],
                "sentence_patterns": [],
                "quiz_candidates": [
                    {
                        "quiz_type": "recognition",
                        "prompt": "What phrase suggests mood?",
                        "answer": "evoking a sense of",
                        "distractors": ["peaceful and inviting", "overall mood", "connection with"],
                        "explanation": "It introduces an interpretation of the atmosphere.",
                        "source_text": "evoking a sense of",
                    }
                ],
                "teaching_notes": [],
            },
            difficulty_band="beginner",
        )

        reusable_texts = [item["text"].lower() for item in analysis["reusable_language"]]
        self.assertIn("evoking a sense of", reusable_texts)
        self.assertNotIn("inviting", reusable_texts)

        highlight_terms = build_highlight_terms(
            phrases=analysis["phrases"],
            vocabulary=analysis["vocabulary"],
            reusable_language=analysis["reusable_language"],
        )
        lowered_terms = [term.lower() for term in highlight_terms]
        self.assertIn("evoking a sense of", lowered_terms)
        self.assertNotIn("inviting", lowered_terms)

        highlighted = highlight_phrases(analysis["scene_summary_natural"], highlight_terms)
        self.assertIn("evoking a sense of", highlighted.lower())
        self.assertIn("phrase-highlight", highlighted)
        self.assertNotIn('data-phrase="inviting"', highlighted.lower())

    def test_reusable_language_drops_function_words(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        analysis = analyzer._normalize_analysis(
            {
                "title": "Street scene",
                "scene_summary_simple": "People are near a market.",
                "scene_summary_natural": (
                    "The people are walking near a market, and the overall view feels busy.\n\n"
                    "In the background, several stalls create a lively street atmosphere."
                ),
                "objects": [],
                "actions": [],
                "environment": {"setting": "street", "details": [], "mood": "busy"},
                "vocabulary": [
                    {
                        "word": "are",
                        "part_of_speech": "verb",
                        "meaning_simple": "a common form of be",
                        "example": "The people are walking.",
                        "frequency_priority": "high",
                    },
                    {
                        "word": "the",
                        "part_of_speech": "article",
                        "meaning_simple": "a common article",
                        "example": "The street is busy.",
                        "frequency_priority": "high",
                    },
                    {
                        "word": "market",
                        "part_of_speech": "noun",
                        "meaning_simple": "a place where people buy and sell things",
                        "example": "The market looks busy.",
                        "frequency_priority": "high",
                    },
                ],
                "phrases": [],
                "sentence_patterns": [],
                "quiz_candidates": [
                    {
                        "quiz_type": "recognition",
                        "prompt": "Where are the people?",
                        "answer": "near a market",
                        "distractors": ["in a room", "on a beach", "by a river"],
                        "explanation": "The people are walking near a market.",
                        "source_text": "near a market",
                    }
                ],
                "teaching_notes": [],
            },
            difficulty_band="beginner",
        )

        reusable_texts = [item["text"].lower() for item in analysis["reusable_language"]]
        self.assertNotIn("are", reusable_texts)
        self.assertNotIn("the", reusable_texts)
        self.assertIn("in the background", reusable_texts)

        highlight_terms = [term.lower() for term in build_highlight_terms(
            phrases=analysis["phrases"],
            vocabulary=analysis["vocabulary"],
            reusable_language=analysis["reusable_language"],
        )]
        self.assertNotIn("are", highlight_terms)
        self.assertNotIn("the", highlight_terms)
        self.assertIn("in the background", highlight_terms)

    def test_reusable_language_prioritizes_main_subject_and_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        analysis = analyzer._normalize_analysis(
            {
                "title": "Cat by the window",
                "scene_summary_simple": "A cat sits by a window.",
                "scene_summary_natural": (
                    "A cat sits quietly by the window and becomes the clearest part of the scene.\n\n"
                    "The cat looks calm, and the soft light makes the room feel gentle.\n\n"
                    "There is a peaceful pause in the room, and the overall mood is easy to describe."
                ),
                "objects": [
                    {
                        "name": "cat",
                        "description": "A cat is the main visible subject.",
                        "importance": 0.95,
                        "color": "",
                        "position": "by the window",
                    },
                    {
                        "name": "window",
                        "description": "A window lets in soft light.",
                        "importance": 0.5,
                        "color": "",
                        "position": "behind the cat",
                    },
                ],
                "actions": [],
                "environment": {"setting": "indoors", "details": ["soft light"], "mood": "calm"},
                "vocabulary": [
                    {
                        "word": "cat",
                        "part_of_speech": "noun",
                        "meaning_simple": "a small pet animal",
                        "example": "A cat sits quietly by the window.",
                        "frequency_priority": "high",
                    }
                ],
                "phrases": [
                    {
                        "phrase": "looks calm",
                        "meaning_simple": "seems peaceful",
                        "example": "The cat looks calm.",
                        "reusable": True,
                        "collocation_type": "expression",
                    }
                ],
                "sentence_patterns": [
                    {
                        "pattern": "There is a ...",
                        "example": "There is a peaceful pause in the room.",
                        "usage_note": "Use it to introduce what is present in a scene.",
                    }
                ],
                "quiz_candidates": [
                    {
                        "quiz_type": "recognition",
                        "prompt": "What is the main visible subject?",
                        "answer": "cat",
                        "distractors": ["table", "lamp", "door"],
                        "explanation": "The cat is the clearest part of the scene.",
                        "source_text": "cat",
                    }
                ],
                "teaching_notes": [],
            },
            difficulty_band="beginner",
        )

        reusable_items = analysis["reusable_language"]
        self.assertGreaterEqual(len(reusable_items), 3)
        self.assertEqual(reusable_items[0]["text"].lower(), "cat")
        self.assertIn("there is a ...", [item["text"].lower() for item in reusable_items])


class VLLMRuntimeQueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from PIL import Image

        self.temp_dir = tempfile.TemporaryDirectory()
        env = {
            "AI_BACKEND": "vllm",
            "DEMO_MODE": "false",
            "VLLM_MAX_CONCURRENCY": "2",
            "VLLM_BATCH_INTERVAL_MS": "40",
            "VLLM_BATCH_MAX_SIZE": "4",
        }
        self.env_patcher = patch.dict(os.environ, env, clear=True)
        self.env_patcher.start()

        self.config = AppConfig.from_env(base_dir=Path(self.temp_dir.name))
        analyzer = AIAnalyzer(self.config)
        self.runtime = analyzer._get_local_runtime()
        self.config.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.image_path = self.config.uploads_dir / "queue-test.png"
        Image.new("RGB", (128, 128), color=(120, 160, 200)).save(self.image_path)

    async def asyncTearDown(self) -> None:
        await self.runtime.close()
        self.env_patcher.stop()
        self.temp_dir.cleanup()

    async def test_runtime_bursts_requests_after_batch_interval(self) -> None:
        start_times: list[float] = []
        base_time = asyncio.get_running_loop().time()

        async def fake_execute(payload: dict[str, object]) -> str:
            start_times.append(asyncio.get_running_loop().time() - base_time)
            await asyncio.sleep(0.01)
            return '{"title":"Queued"}'

        self.runtime._execute_chat_completion = fake_execute  # type: ignore[method-assign]

        await asyncio.gather(
            self.runtime.generate(
                image_path=self.image_path,
                prompt="first",
                max_new_tokens=32,
                temperature=0.0,
            ),
            self.runtime.generate(
                image_path=self.image_path,
                prompt="second",
                max_new_tokens=32,
                temperature=0.0,
            ),
        )

        self.assertEqual(len(start_times), 2)
        self.assertGreaterEqual(start_times[0], 0.03)
        self.assertLess(abs(start_times[0] - start_times[1]), 0.03)

    async def test_runtime_caps_inflight_vllm_requests(self) -> None:
        running = 0
        max_running = 0

        async def fake_execute(payload: dict[str, object]) -> str:
            nonlocal running, max_running
            running += 1
            max_running = max(max_running, running)
            await asyncio.sleep(0.05)
            running -= 1
            return '{"title":"Queued"}'

        self.runtime._execute_chat_completion = fake_execute  # type: ignore[method-assign]

        await asyncio.gather(
            self.runtime.generate(
                image_path=self.image_path,
                prompt="first",
                max_new_tokens=32,
                temperature=0.0,
            ),
            self.runtime.generate(
                image_path=self.image_path,
                prompt="second",
                max_new_tokens=32,
                temperature=0.0,
            ),
            self.runtime.generate(
                image_path=self.image_path,
                prompt="third",
                max_new_tokens=32,
                temperature=0.0,
            ),
        )

        self.assertEqual(max_running, 2)


class HighlightTests(unittest.TestCase):
    def test_highlight_wraps_common_phrases(self) -> None:
        html = highlight_phrases(
            "In the foreground, a bright object stands out against the background.",
            ["in the foreground", "stands out"],
        )
        self.assertIn("phrase-highlight", html)
        self.assertIn("stands out", html)

    def test_highlight_preserves_paragraphs(self) -> None:
        html = highlight_phrases(
            "A soft glow appears behind him.\n\nHe has a faint smile on his face.",
            ["soft glow", "faint smile"],
        )
        self.assertGreaterEqual(html.count("<p>"), 2)
        self.assertIn("soft glow", html)
        self.assertIn("faint smile", html)


class ReviewTests(unittest.TestCase):
    def test_correct_answer_pushes_due_date_forward(self) -> None:
        now = from_iso("2026-04-14T12:00:00+00:00")
        schedule = calculate_next_review(
            card={
                "repetitions": 0,
                "ease_factor": 2.5,
                "interval_days": 0.0,
            },
            quality=4,
            now=now,
            first_review_minutes=5,
        )
        due = from_iso(schedule["due_at"]).astimezone(timezone.utc)
        self.assertGreater(due, now)

    def test_build_study_cards_creates_varied_phrase_cards(self) -> None:
        now = from_iso("2026-04-14T12:00:00+00:00")
        cards = build_study_cards(
            user_id=1,
            session_id=2,
            now=now,
            first_review_minutes=5,
            analysis={
                "reusable_language": [
                    {
                        "text": "in the foreground",
                        "definition": "It helps you point to the part of the image closest to the viewer.",
                        "example": "In the foreground, a bright red mug sits on the table.",
                        "why_it_matters": "It sounds natural when you guide someone through the scene.",
                    }
                ],
                "micro_quiz": [],
            },
        )
        kinds = {card["card_kind"] for card in cards}
        self.assertIn("phrase", kinds)
        self.assertIn("phrase_choice", kinds)
        self.assertIn("phrase_usage", kinds)
        self.assertGreaterEqual(len(cards), 3)

    def test_select_quiz_cards_prefers_variety(self) -> None:
        cards = [
            {"id": 1, "card_kind": "phrase"},
            {"id": 2, "card_kind": "phrase"},
            {"id": 3, "card_kind": "phrase_choice"},
            {"id": 4, "card_kind": "quiz"},
        ]
        selected = select_quiz_cards(cards, limit=3)
        self.assertEqual([card["id"] for card in selected], [1, 3, 4])

    def test_fast_correct_answer_advances_interval(self) -> None:
        now = from_iso("2026-04-14T12:00:00+00:00")
        schedule = calculate_next_review(
            card={
                "interval_step": 0,
                "interval_minutes": 60,
                "ease_factor": 2.5,
                "mastery": 0.0,
                "difficulty": 0.3,
                "correct_streak": 0,
                "wrong_streak": 0,
                "review_count": 0,
                "repetitions": 0,
            },
            quality=5,
            now=now,
            first_review_minutes=60,
            response_ms=5000,
            confidence=3,
        )
        self.assertGreaterEqual(schedule["interval_step"], 1)
        self.assertGreater(schedule["mastery"], 0.0)


class QuizEngineTests(unittest.TestCase):
    def test_build_session_assets_generates_multiple_quiz_types(self) -> None:
        assets = build_session_assets(
            user_id=1,
            session_id=2,
            learner_level="beginner",
            created_at="2026-04-14T12:00:00+00:00",
            first_review_minutes=60,
            analysis={
                "objects": [
                    {"name": "road", "description": "A road appears in the scene."},
                    {"name": "car", "description": "A car is visible nearby."},
                ],
                "actions": [
                    {
                        "verb": "crossing",
                        "subject": "A person",
                        "object": "the road",
                        "phrase": "crossing the road",
                        "description": "A person is moving across the road.",
                    }
                ],
                "vocabulary": [
                    {
                        "word": "cross",
                        "part_of_speech": "verb",
                        "meaning_simple": "to go from one side to the other",
                        "example": "He wants to cross the road.",
                        "examples": [
                            "I cross the road slowly.",
                            "We cross the road here.",
                            "They cross the road together.",
                            "She will cross the road soon.",
                            "People cross the road daily.",
                        ],
                        "frequency_priority": "high",
                    }
                ],
                "phrases": [
                    {
                        "phrase": "cross the road",
                        "meaning_simple": "go from one side of the road to the other",
                        "example": "People cross the road carefully.",
                        "examples": [
                            "I cross the road after lunch.",
                            "They cross the road at school.",
                            "We cross the road together.",
                            "She can cross the road now.",
                            "Please cross the road here.",
                        ],
                        "reusable": True,
                        "collocation_type": "verb phrase",
                    }
                ],
                "scene_summary_simple": "A person is crossing the road near a car.",
                "environment": "It looks like a street scene.",
            },
        )
        quiz_types = {item["quiz_type"] for item in assets["quiz_items"]}
        self.assertIn("recognition", quiz_types)
        self.assertIn("phrase_completion", quiz_types)
        self.assertIn("typing", quiz_types)
        self.assertEqual(5, len(assets["vocabulary"][0]["examples"]))
        self.assertEqual(5, len(assets["phrases"][0]["examples"]))

    def test_typing_evaluation_accepts_keyword_match(self) -> None:
        result = evaluate_quiz_response(
            item={
                "answer_mode": "typing",
                "correct_answer": "A man is crossing the road.",
                "acceptable_answers": ["A man is crossing the road."],
                "metadata": {
                    "keywords": ["man", "crossing", "road"],
                    "reference_answer": "A man is crossing the road.",
                },
            },
            selected_answer="The man is crossing a road.",
            response_ms=7000,
            confidence=2,
        )
        self.assertTrue(result["correct"])
        self.assertGreaterEqual(result["score"], 0.55)


if __name__ == "__main__":
    unittest.main()
