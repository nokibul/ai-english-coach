from __future__ import annotations

from datetime import timezone
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
import asyncio
from unittest.mock import patch

from english_learner_app.assessment import evaluate_assessment
from english_learner_app.ai_service import AIAnalyzer
from english_learner_app.config import AppConfig
from english_learner_app.database import Database, phrase_mastery_state
from english_learner_app.quiz_engine import (
    build_post_improve_quiz_rows,
    build_session_assets,
    evaluate_quiz_response,
)
from english_learner_app.review import (
    build_study_cards,
    calculate_next_review,
    select_quiz_cards,
)
from english_learner_app.server import (
    apply_progress_event,
    build_highlight_terms,
    build_quiz_xp_breakdown,
)
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


class DatabaseAuthTests(unittest.TestCase):
    def test_create_multiple_users_without_phone(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "app.sqlite3")
            db.initialize()

            first = db.create_user(
                full_name="First Learner",
                phone=None,
                email="first@example.com",
                password_hash="hash-one",
                difficulty_band="beginner",
                fluency_score=10,
                fluency_summary="Starting out.",
                assessment={},
                created_at="2026-05-04T00:00:00+00:00",
            )
            second = db.create_user(
                full_name="Second Learner",
                phone=None,
                email="second@example.com",
                password_hash="hash-two",
                difficulty_band="developing",
                fluency_score=20,
                fluency_summary="Building confidence.",
                assessment={},
                created_at="2026-05-04T00:00:00+00:00",
            )

        self.assertIsNone(first["phone"])
        self.assertIsNone(second["phone"])

    def test_existing_users_table_migrates_phone_to_optional(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "app.sqlite3"
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        full_name TEXT NOT NULL,
                        phone TEXT NOT NULL UNIQUE,
                        email TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        difficulty_band TEXT NOT NULL,
                        fluency_score INTEGER NOT NULL,
                        fluency_summary TEXT NOT NULL,
                        assessment_json TEXT NOT NULL,
                        is_verified INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO users (
                        full_name, phone, email, password_hash, difficulty_band,
                        fluency_score, fluency_summary, assessment_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "Existing Learner",
                        "+8801555123456",
                        "existing@example.com",
                        "hash",
                        "beginner",
                        10,
                        "Starting out.",
                        "{}",
                        "2026-05-04T00:00:00+00:00",
                    ),
                )

            db = Database(db_path)
            db.initialize()

            with sqlite3.connect(db_path) as conn:
                phone_column = next(
                    row for row in conn.execute("PRAGMA table_info(users)")
                    if row[1] == "phone"
                )

            self.assertEqual(0, phone_column[3])
            self.assertEqual(
                "existing@example.com",
                db.get_user_by_email("existing@example.com")["email"],
            )


class ProgressRewardTests(unittest.TestCase):
    def test_phrase_mastery_states_and_updates(self) -> None:
        self.assertEqual("Seen", phrase_mastery_state(mastery=0.0, correct_count=0))
        self.assertEqual("Practiced", phrase_mastery_state(mastery=0.35, correct_count=0))
        self.assertEqual("Used Correctly", phrase_mastery_state(mastery=0.6, correct_count=0))
        self.assertEqual("Mastered", phrase_mastery_state(mastery=0.8, correct_count=3))

        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "app.sqlite3")
            db.initialize()
            user = db.create_user(
                full_name="Phrase Learner",
                phone=None,
                email="phrase@example.com",
                password_hash="hash",
                difficulty_band="beginner",
                fluency_score=10,
                fluency_summary="Starting out.",
                assessment={},
                created_at="2026-05-04T00:00:00+00:00",
            )
            session_id = db.create_analysis_session(
                user_id=user["id"],
                image_name="image.jpg",
                image_path="uploads/image.jpg",
                title="Phrase test",
                difficulty_band="beginner",
                simple_explanation="A cyclist is on the street.",
                natural_explanation="Cars are in the background.",
                highlighted_html="",
                summary={},
                raw_analysis={},
                source_mode="demo",
                created_at="2026-05-04T00:00:00+00:00",
            )
            db.bulk_create_session_phrase_items(
                [
                    {
                        "user_id": user["id"],
                        "session_id": session_id,
                        "phrase": "in the background",
                        "meaning_simple": "behind the main subject",
                        "example": "Cars are in the background.",
                        "examples": [],
                        "reusable": 1,
                        "collocation_type": "phrase",
                        "mastery": 0.0,
                        "correct_count": 0,
                        "wrong_count": 0,
                        "created_at": "2026-05-04T00:00:00+00:00",
                    }
                ]
            )

            practiced = db.update_phrase_mastery(
                user_id=user["id"],
                session_id=session_id,
                phrase="in the background",
                mastery=0.35,
                was_correct=True,
            )
            used = db.update_phrase_mastery(
                user_id=user["id"],
                session_id=session_id,
                phrase="in the background",
                mastery=0.75,
                was_correct=True,
            )

        self.assertEqual("Practiced", practiced["mastery_state"])
        self.assertEqual("Used Correctly", used["mastery_state"])
        self.assertEqual(2, used["correct_count"])

    def test_quiz_xp_breakdown_applies_base_and_bonuses(self) -> None:
        breakdown = build_quiz_xp_breakdown(
            item={
                "quiz_type": "use_it_or_lose_it",
                "metadata": {
                    "difficulty": 0.72,
                    "related_reusable_phrase": "in the background",
                },
            },
            selected_answer="Cars are in the background while the cyclist rides.",
            correct=True,
            almost_correct=False,
            response_ms=4500,
            completion_bonuses={"complete_all_types_bonus": 20, "perfect_quiz_bonus": 30},
        )

        self.assertEqual("micro", breakdown["difficulty"])
        self.assertEqual(15, breakdown["base_xp"])
        self.assertEqual(0, breakdown["first_try_bonus"])
        self.assertEqual(0, breakdown["phrase_bonus"])
        self.assertEqual(0, breakdown["fast_bonus"])
        self.assertEqual(20, breakdown["complete_all_types_bonus"])
        self.assertEqual(0, breakdown["perfect_quiz_bonus"])
        self.assertEqual(35, breakdown["total_before_combo"])

        almost = build_quiz_xp_breakdown(
            item={"quiz_type": "fix_the_sentence", "metadata": {}},
            selected_answer="The man riding mower grass.",
            correct=False,
            almost_correct=True,
            response_ms=4500,
            completion_bonuses={"complete_all_types_bonus": 0, "perfect_quiz_bonus": 0},
        )
        self.assertEqual(5, almost["base_xp"])
        self.assertEqual(5, almost["total_before_combo"])

    def test_combo_rules_for_correct_almost_and_wrong(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "app.sqlite3")
            db.initialize()
            user = db.create_user(
                full_name="Combo Learner",
                phone=None,
                email="combo@example.com",
                password_hash="hash",
                difficulty_band="beginner",
                fluency_score=10,
                fluency_summary="Starting out.",
                assessment={},
                created_at="2026-05-04T00:00:00+00:00",
            )
            now = from_iso("2026-05-04T00:00:00+00:00")

            progress, reward = apply_progress_event(
                db, user_id=user["id"], now=now, xp_delta=5, activity_correct=True
            )
            self.assertEqual(1, reward["combo_streak"])

            progress, reward = apply_progress_event(
                db, user_id=user["id"], now=now, xp_delta=5, activity_correct=None
            )
            self.assertEqual(1, reward["combo_streak"])

            progress, reward = apply_progress_event(
                db, user_id=user["id"], now=now, xp_delta=0, activity_correct=False
            )
            self.assertEqual(0, reward["combo_streak"])
            self.assertEqual(1, progress["best_combo"])

    def test_combo_x3_bonus_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "app.sqlite3")
            db.initialize()
            user = db.create_user(
                full_name="Bonus Learner",
                phone=None,
                email="bonus@example.com",
                password_hash="hash",
                difficulty_band="beginner",
                fluency_score=10,
                fluency_summary="Starting out.",
                assessment={},
                created_at="2026-05-04T00:00:00+00:00",
            )
            now = from_iso("2026-05-04T00:00:00+00:00")

            rewards = []
            for _ in range(5):
                _, reward = apply_progress_event(
                    db, user_id=user["id"], now=now, xp_delta=5, activity_correct=True
                )
                rewards.append(reward)

        self.assertEqual(10, rewards[2]["combo_bonus"])
        self.assertEqual(0, rewards[4]["combo_bonus"])
        self.assertEqual(5, rewards[4]["best_combo"])


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

    def test_feedback_prompt_caps_scores_by_image_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        prompt = analyzer._build_explanation_feedback_prompt(
            learner_text="The man is smiling.",
            original_text="",
            analysis={"natural_explanation": "A man is smiling in a busy cafe."},
            learner_level="beginner",
        )

        self.assertIn("Judge coverage of the whole image before language quality", prompt)
        self.assertIn("foreground, main subject, main action, setting/background", prompt)
        self.assertIn("main subject 25%, main action 20%", prompt)
        self.assertIn("main subject missing = max 40", prompt)
        self.assertIn("only background described = max 25", prompt)
        self.assertIn("Calculate final score mechanically", prompt)
        self.assertIn("If the learner does not mention the main subject", prompt)
        self.assertIn("Do not let good English override poor coverage", prompt)
        self.assertIn('"coverage": {"level": "low"', prompt)

    def test_extract_required_image_parts_from_reference_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        parts = analyzer._extract_required_image_parts(
            {
                "objects": [
                    {
                        "name": "person",
                        "description": "A person is riding a mower in the foreground.",
                        "importance": 0.95,
                    },
                    {
                        "name": "riding mower",
                        "description": "The mower is cutting the grass.",
                        "importance": 0.9,
                    },
                    {
                        "name": "palm trees",
                        "description": "Palm trees stand in the background.",
                        "importance": 0.5,
                    },
                ],
                "actions": [{"phrase": "mowing the lawn", "description": "The person is mowing the lawn."}],
                "environment": "sunny yard",
                "environment_details": ["foreground grass", "palm trees", "blue sky"],
                "natural_explanation": "A person is mowing a sunny yard with a tidy, calm feeling.",
            }
        )

        types = {part["type"] for part in parts}
        self.assertIn("main_subject", types)
        self.assertIn("main_action", types)
        self.assertIn("foreground", types)
        self.assertIn("setting", types)
        self.assertIn("important_object", types)
        self.assertIn("mood", types)
        self.assertAlmostEqual(100.0, sum(float(part["weight"]) for part in parts), places=1)
        for part in parts:
            self.assertTrue(part["name"])
            self.assertTrue(part["description"])

    def test_required_image_part_weights_adapt_to_missing_action_and_weak_mood(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        parts = analyzer._extract_required_image_parts(
            {
                "objects": [
                    {"name": "vase", "description": "A vase sits on a table.", "importance": 0.9},
                    {"name": "flowers", "description": "Flowers are inside the vase.", "importance": 0.8},
                    {"name": "table", "description": "A table is near the front.", "importance": 0.6},
                ],
                "actions": [],
                "environment": "bright indoor room",
                "environment_details": ["front table", "window light"],
                "natural_explanation": "A vase with flowers sits on a front table in a bright indoor room.",
            }
        )

        weights = {part["type"]: float(part["weight"]) for part in parts}
        self.assertAlmostEqual(100.0, sum(weights.values()), places=1)
        self.assertNotIn("main_action", weights)
        self.assertGreater(weights["main_subject"], weights["setting"])
        self.assertGreater(weights["main_subject"], weights.get("mood", 0.0))
        self.assertGreater(weights["important_object"], weights.get("mood", 0.0))

        weak_mood_parts = analyzer._extract_required_image_parts(
            {
                "objects": [
                    {"name": "person", "description": "A person stands on the grass.", "importance": 0.9},
                    {"name": "ball", "description": "A ball is near the person.", "importance": 0.8},
                ],
                "actions": [{"phrase": "standing on the grass"}],
                "environment": "sunny field",
                "environment_details": ["grass in front", "open field"],
                "natural_explanation": "A person stands on the grass in a sunny field.",
            }
        )
        weak_weights = {part["type"]: float(part["weight"]) for part in weak_mood_parts}
        self.assertAlmostEqual(100.0, sum(weak_weights.values()), places=1)
        self.assertLess(weak_weights["mood"], 10.0)
        self.assertGreater(weak_weights["main_subject"], weak_weights["setting"])
        self.assertGreater(weak_weights["main_action"], weak_weights["mood"])

    def test_heuristic_feedback_caps_background_only_without_main_subject(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        analysis = {
            "objects": [
                {"name": "person", "description": "A person is sitting near the river.", "importance": 0.9},
                {"name": "bridge", "description": "A bridge is in the background.", "importance": 0.5},
                {"name": "trees", "description": "Trees stand near the river.", "importance": 0.5},
            ],
            "actions": [{"phrase": "sitting near the river"}],
            "environment": "outdoor river scene",
            "environment_details": ["river", "trees", "bridge"],
            "vocabulary": [],
            "phrases": [],
            "sentence_patterns": [],
        }

        incomplete = analyzer._heuristic_explanation_feedback(
            learner_text="The background reveals lush greenery and a distant bridge, creating a peaceful atmosphere.",
            original_text="",
            analysis=analysis,
        )
        complete = analyzer._heuristic_explanation_feedback(
            learner_text=(
                "The image shows a man sitting near a river. "
                "There are trees, a bridge, and a calm outdoor setting."
            ),
            original_text="",
            analysis=analysis,
        )

        self.assertLessEqual(incomplete["score"], 40)
        self.assertEqual("low", incomplete["coverage"]["level"])
        self.assertIn("main subject", incomplete["main_issue"])
        self.assertGreaterEqual(complete["score"], 70)
        self.assertGreater(complete["score"], incomplete["score"])

    def test_heuristic_feedback_scores_by_weighted_image_parts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        analysis = {
            "objects": [
                {"name": "person", "description": "A person is on a riding mower.", "importance": 0.95},
                {"name": "riding mower", "description": "The mower is on the grass.", "importance": 0.9},
                {"name": "grass", "description": "Foreground grass fills the yard.", "importance": 0.7},
                {"name": "palm trees", "description": "Palm trees stand in the background.", "importance": 0.5},
            ],
            "actions": [{"phrase": "mowing the lawn"}],
            "environment": "sunny lawn or yard setting",
            "environment_details": ["yard", "palm trees", "bushes", "sky"],
            "vocabulary": [],
            "phrases": [],
            "sentence_patterns": [],
        }

        partial = analyzer._heuristic_explanation_feedback(
            learner_text="The far background has palm trees, blue sky, and a sunny tidy atmosphere.",
            original_text="",
            analysis=analysis,
        )

        self.assertLessEqual(partial["score"], 45)
        self.assertLess(partial["coverage"]["coveragePercent"], 50)
        self.assertEqual(partial["coverage"]["coverageScore"], partial["coverage"]["coveragePercent"])
        self.assertLessEqual(partial["coverage"]["coverageScore"], 40)
        missing_parts = partial["coverage"]["missingMajorParts"]
        self.assertTrue(any("main subject" in part for part in missing_parts))
        self.assertTrue(any("main action" in part for part in missing_parts))
        self.assertTrue(partial["coverage"]["imageParts"])

    def test_heuristic_feedback_classifies_part_coverage_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        analysis = {
            "objects": [
                {"name": "person", "description": "A person is on a riding mower.", "importance": 0.95},
                {"name": "riding mower", "description": "The mower is on the grass.", "importance": 0.9},
                {"name": "grass", "description": "Foreground grass fills the yard.", "importance": 0.7},
            ],
            "actions": [{"phrase": "mowing the lawn"}],
            "environment": "sunny lawn or yard setting",
            "environment_details": ["yard", "grass in front"],
            "natural_explanation": "A person is mowing a sunny yard.",
            "vocabulary": [],
            "phrases": [],
            "sentence_patterns": [],
        }

        feedback = analyzer._heuristic_explanation_feedback(
            learner_text="A person is mowing grass in a yard.",
            original_text="",
            analysis=analysis,
        )

        by_type = {part["type"]: part for part in feedback["coverage"]["imageParts"]}
        self.assertTrue(feedback["coverage"]["mainSubjectMentioned"])
        self.assertTrue(feedback["coverage"]["mainActionMentioned"])
        self.assertEqual("covered", by_type["main_subject"]["coverageStatus"])
        self.assertEqual("covered", by_type["main_action"]["coverageStatus"])
        self.assertEqual("covered", by_type["setting"]["coverageStatus"])
        self.assertEqual("partially_covered", by_type["important_object"]["coverageStatus"])
        self.assertIn(by_type["foreground"]["coverageStatus"], {"missing", "partially_covered", "covered"})
        self.assertGreater(feedback["coverage"]["coveragePercent"], 50)
        self.assertEqual(feedback["coverage"]["coverageScore"], feedback["coverage"]["coveragePercent"])

    def test_heuristic_feedback_marks_serious_inaccuracy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        analysis = {
            "objects": [{"name": "person", "description": "A person is sitting indoors.", "importance": 0.9}],
            "actions": [{"phrase": "sitting"}],
            "environment": "indoor room",
            "environment_details": ["room"],
            "natural_explanation": "A person is sitting in an indoor room.",
            "vocabulary": [],
            "phrases": [],
            "sentence_patterns": [],
        }

        feedback = analyzer._heuristic_explanation_feedback(
            learner_text="A person is standing outside.",
            original_text="",
            analysis=analysis,
        )

        by_type = {part["type"]: part for part in feedback["coverage"]["imageParts"]}
        self.assertEqual("inaccurate", by_type["main_action"]["coverageStatus"])
        self.assertEqual("inaccurate", by_type["setting"]["coverageStatus"])
        self.assertGreater(feedback["coverage"]["accuracyPenalty"], 0)

    def test_heuristic_feedback_applies_action_and_brief_overall_caps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        analysis = {
            "objects": [
                {"name": "person", "description": "A person is using a mower.", "importance": 0.95},
                {"name": "mower", "description": "A mower is in the yard.", "importance": 0.85},
                {"name": "grass", "description": "Grass is in the foreground.", "importance": 0.7},
            ],
            "actions": [{"phrase": "mowing the lawn"}],
            "environment": "yard setting",
            "environment_details": ["yard", "foreground grass"],
            "natural_explanation": "A person is mowing a calm yard with a mower.",
            "vocabulary": [],
            "phrases": [],
            "sentence_patterns": [],
        }

        missing_action = analyzer._heuristic_explanation_feedback(
            learner_text="A person is with a mower in the yard.",
            original_text="",
            analysis=analysis,
        )
        brief_overall = analyzer._heuristic_explanation_feedback(
            learner_text="A person is mowing grass in a yard with a mower.",
            original_text="",
            analysis=analysis,
        )

        self.assertLessEqual(missing_action["score"], 50)
        self.assertEqual(50, missing_action["coverage"]["scoreCapApplied"])
        self.assertLessEqual(brief_overall["score"], 80)
        self.assertEqual(80, brief_overall["coverage"]["scoreCapApplied"])

    def test_language_quality_is_downstream_of_coverage_caps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        analysis = {
            "objects": [
                {"name": "person", "description": "A person is sitting near the river.", "importance": 0.95},
                {"name": "bridge", "description": "A bridge is in the background.", "importance": 0.6},
            ],
            "actions": [{"phrase": "sitting near the river"}],
            "environment": "outdoor river scene",
            "environment_details": ["river", "bridge", "trees"],
            "natural_explanation": "A person is sitting near a river with a bridge in the background.",
            "phrases": [{"phrase": "in the background"}],
            "vocabulary": [],
            "sentence_patterns": [],
        }

        fluent_partial = analyzer._heuristic_explanation_feedback(
            learner_text=(
                "In the background, the distant bridge and calm river create a peaceful, "
                "well-balanced outdoor atmosphere."
            ),
            original_text="",
            analysis=analysis,
        )

        self.assertLessEqual(fluent_partial["score"], 40)
        self.assertGreaterEqual(fluent_partial["language_quality"]["score"], 50)
        self.assertLessEqual(fluent_partial["language_quality"]["reusableLanguage"], 100)

    def test_final_score_uses_coverage_dominant_formula_and_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        analysis = {
            "objects": [
                {"name": "person", "description": "A person is sitting near the river.", "importance": 0.95},
                {"name": "bridge", "description": "A bridge is in the background.", "importance": 0.6},
                {"name": "trees", "description": "Trees are near the river.", "importance": 0.5},
            ],
            "actions": [{"phrase": "sitting near the river"}],
            "environment": "outdoor river scene",
            "environment_details": ["river", "bridge", "trees"],
            "natural_explanation": "A person is sitting near a calm river with trees and a bridge.",
            "phrases": [{"phrase": "in the background"}],
            "vocabulary": [],
            "sentence_patterns": [],
        }

        fluent_partial = analyzer._heuristic_explanation_feedback(
            learner_text=(
                "In the background, the distant bridge and calm river create a peaceful, "
                "well-balanced outdoor atmosphere."
            ),
            original_text="",
            analysis=analysis,
        )
        simple_complete = analyzer._heuristic_explanation_feedback(
            learner_text="A person is sitting near a calm river with trees and a bridge.",
            original_text="",
            analysis=analysis,
        )

        self.assertLess(fluent_partial["score"], simple_complete["score"])
        self.assertLessEqual(fluent_partial["score"], fluent_partial["coverage"]["scoreCapApplied"])
        self.assertLessEqual(simple_complete["score"], simple_complete["coverage"]["scoreCapApplied"])

    def test_feedback_generation_explains_covered_missing_and_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        analysis = {
            "objects": [
                {"name": "person", "description": "A person is riding a mower.", "importance": 0.95},
                {"name": "riding mower", "description": "The mower is on the grass.", "importance": 0.9},
                {"name": "grass", "description": "Foreground grass fills the yard.", "importance": 0.7},
                {"name": "palm trees", "description": "Palm trees stand in the background.", "importance": 0.5},
            ],
            "actions": [{"phrase": "mowing the lawn", "description": "The person is mowing the lawn."}],
            "environment": "sunny yard setting",
            "environment_details": ["palm trees", "blue sky", "foreground grass"],
            "natural_explanation": "A person is mowing a sunny yard with palm trees in the background.",
            "phrases": [{"phrase": "in the background"}],
            "vocabulary": [],
            "sentence_patterns": [],
        }

        feedback = analyzer._heuristic_explanation_feedback(
            learner_text="In the background, palm trees and blue sky create a sunny atmosphere.",
            original_text="",
            analysis=analysis,
        )

        self.assertIn("covered", feedback["main_issue"].lower())
        self.assertIn("missed", feedback["main_issue"].lower())
        self.assertIn("main subject", feedback["main_issue"].lower())
        self.assertIn("main action", feedback["main_issue"].lower())
        self.assertIn("capped", feedback["main_issue"].lower())
        self.assertLessEqual(feedback["score"], 40)
        self.assertTrue(feedback["what_did_well"][0].startswith("You covered"))

    def test_improved_version_adds_missing_subject_and_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        analysis = {
            "objects": [
                {"name": "person", "description": "A person is riding a mower.", "importance": 0.95},
                {"name": "mower", "description": "A mower is on the grass.", "importance": 0.9},
            ],
            "actions": [{"phrase": "mowing the lawn", "description": "The person is mowing the lawn."}],
            "environment": "yard setting",
            "environment_details": ["yard", "grass"],
            "natural_explanation": "A person is mowing the lawn in a yard.",
            "phrases": [{"phrase": "in the yard"}],
            "vocabulary": [],
            "sentence_patterns": [],
        }

        feedback = analyzer._heuristic_explanation_feedback(
            learner_text="The yard is green.",
            original_text="",
            analysis=analysis,
        )

        better = feedback["better_version"].lower()
        self.assertIn("person", better)
        self.assertIn("mowing", better)

    def test_score_realism_adjustment_stays_within_five_points(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        positive = analyzer._score_realism_adjustment(
            coverage={"coverageScore": 85, "scoreCapApplied": 80, "mainSubjectMentioned": True},
            language_score=70,
            word_count=10,
        )
        negative = analyzer._score_realism_adjustment(
            coverage={"coverageScore": 30, "scoreCapApplied": 40, "mainSubjectMentioned": False},
            language_score=85,
            word_count=18,
        )

        self.assertLessEqual(abs(positive), 5)
        self.assertLessEqual(abs(negative), 5)
        self.assertEqual(5, positive)
        self.assertEqual(-5, negative)

    def test_language_quality_weights_reusable_language_lightly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        quality = analyzer._normalize_language_quality(
            {
                "clarity": 80,
                "vocabulary": 70,
                "structure": 70,
                "grammar": 60,
                "naturalness": 60,
                "reusableLanguage": 100,
            }
        )

        expected = round((80 * 25 + 70 * 20 + 70 * 20 + 60 * 15 + 60 * 10 + 100 * 10) / 100)
        self.assertEqual(expected, quality["score"])
        self.assertEqual(100, quality["reusableLanguage"])

    def test_feedback_normalization_applies_coverage_score_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        fallback = analyzer._heuristic_explanation_feedback(
            learner_text="A man is smiling in the picture.",
            original_text="",
            analysis={
                "objects": [{"name": "man", "description": "A man is visible."}],
                "actions": [],
                "environment_details": ["busy cafe background"],
                "vocabulary": [],
                "phrases": [],
            },
        )
        normalized = analyzer._normalize_explanation_feedback(
            {
                "score": 88,
                "scores": {"vocabulary": 9, "structure": 9, "depth": 8, "clarity": 9},
                "coverage": {
                    "level": "partial",
                    "imageParts": [
                        {
                            "name": "main subject",
                            "description": "the visible person",
                            "type": "main_subject",
                            "required": True,
                            "weight": 25,
                            "coverageStatus": "partially_covered",
                            "covered": True,
                            "evidence": "man",
                        }
                    ],
                    "missingMajorParts": ["background and overall setting"],
                    "coverageScore": 55,
                    "coveragePercent": 55,
                    "scoreCapApplied": 55,
                    "reason": "Main subject only.",
                },
                "languageQuality": {
                    "clarity": 90,
                    "vocabulary": 90,
                    "structure": 90,
                    "grammar": 90,
                    "naturalness": 90,
                    "reusableLanguage": 100,
                },
                "mainIssue": "Your English is clear, but you only described the main subject.",
                "whatWentWell": ["Your sentence is clear."],
                "fixes": ["Add the background and setting."],
                "missingDetails": ["background and overall setting"],
                "reusableLanguage": {"usedWell": [], "tryNext": [], "misused": [], "message": ""},
                "inlineImprovements": [],
                "improvedVersion": "A man is smiling in a busy cafe.",
            },
            fallback=fallback,
        )

        self.assertEqual(30, normalized["score"])
        self.assertEqual("low", normalized["coverage"]["level"])
        self.assertEqual(30, normalized["coverage"]["scoreCapApplied"])
        self.assertEqual(61, normalized["coverage"]["coverageScore"])
        self.assertEqual("main_subject", normalized["coverage"]["imageParts"][0]["type"])
        self.assertEqual("A man is visible.", normalized["coverage"]["imageParts"][0]["description"])
        self.assertEqual("covered", normalized["coverage"]["imageParts"][0]["coverageStatus"])
        self.assertTrue(normalized["coverage"]["imageParts"][0]["covered"])
        self.assertEqual(56, normalized["language_quality"]["score"])

    def test_feedback_normalization_enforces_missing_subject_hard_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        fallback = analyzer._heuristic_explanation_feedback(
            learner_text="The background has a bridge and peaceful trees.",
            original_text="",
            analysis={
                "objects": [{"name": "person", "description": "A person is visible.", "importance": 0.9}],
                "actions": [{"phrase": "sitting"}],
                "environment": "outdoor river scene",
                "environment_details": ["bridge", "trees"],
                "vocabulary": [],
                "phrases": [],
            },
        )
        normalized = analyzer._normalize_explanation_feedback(
            {
                "score": 94,
                "scores": {"vocabulary": 9, "structure": 9, "depth": 9, "clarity": 9},
                "coverage": {
                    "level": "strong",
                    "mainSubjectMentioned": False,
                    "mainActionMentioned": False,
                    "imageParts": [
                        {
                            "name": "person",
                            "description": "the main person",
                            "type": "main_subject",
                            "required": True,
                            "weight": 25,
                            "coverageStatus": "missing",
                        },
                        {
                            "name": "setting/background",
                            "description": "bridge and trees",
                            "type": "setting",
                            "required": True,
                            "weight": 15,
                            "coverageStatus": "covered",
                        },
                        {
                            "name": "mood",
                            "description": "peaceful atmosphere",
                            "type": "mood",
                            "required": True,
                            "weight": 15,
                            "coverageStatus": "covered",
                        },
                    ],
                    "coverageScore": 30,
                    "coveragePercent": 30,
                    "scoreCapApplied": 95,
                    "reason": "The answer sounds fluent.",
                },
                "mainIssue": "The answer sounds fluent.",
                "whatWentWell": ["The sentence is clear."],
                "fixes": ["Mention the main subject."],
                "missingDetails": ["main subject"],
                "reusableLanguage": {"usedWell": [], "tryNext": [], "misused": [], "message": ""},
                "inlineImprovements": [],
                "improvedVersion": "A person is sitting near a bridge and trees.",
            },
            fallback=fallback,
        )

        self.assertLessEqual(normalized["score"], 40)
        self.assertLessEqual(normalized["coverage"]["scoreCapApplied"], 40)

    def test_feedback_normalization_scores_rewrite_with_fresh_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        analysis = {
            "objects": [
                {"name": "person", "description": "A person is riding a lawn mower.", "importance": 0.9},
                {"name": "lawn mower", "description": "A mower is cutting the grass.", "importance": 0.8},
            ],
            "actions": [{"phrase": "mowing the grass", "verb": "mowing", "subject": "person"}],
            "environment": "green yard",
            "environment_details": ["palm trees", "bushes", "sunny sky"],
            "vocabulary": [],
            "phrases": [],
        }
        fresh_fallback = analyzer._heuristic_explanation_feedback(
            learner_text=(
                "A person is mowing the grass on a lawn mower in a green yard "
                "with palm trees, bushes, and a sunny calm feeling."
            ),
            original_text="The yard is sunny with palm trees.",
            analysis=analysis,
        )

        normalized = analyzer._normalize_explanation_feedback(
            {
                "score": 40,
                "scores": {"vocabulary": 8, "structure": 8, "depth": 8, "clarity": 8},
                "coverage": {
                    "level": "low",
                    "mainSubjectMentioned": False,
                    "mainActionMentioned": False,
                    "imageParts": [
                        {
                            "name": "person",
                            "type": "main_subject",
                            "weight": 25,
                            "coverageStatus": "missing",
                        },
                        {
                            "name": "mowing the grass",
                            "type": "main_action",
                            "weight": 20,
                            "coverageStatus": "missing",
                        },
                        {
                            "name": "setting",
                            "type": "setting",
                            "weight": 15,
                            "coverageStatus": "covered",
                        },
                    ],
                    "coverageScore": 15,
                    "coveragePercent": 15,
                    "scoreCapApplied": 40,
                    "missingMajorParts": ["the main subject (person)", "the main action (mowing)"],
                },
                "mainIssue": "Your answer missed the main subject.",
                "missingDetails": ["the main subject (person)", "the main action (mowing)"],
                "fixes": ["Mention the person."],
                "reusableLanguage": {"usedWell": [], "tryNext": [], "misused": [], "message": ""},
                "inlineImprovements": [],
                "improvedVersion": "A person is mowing the grass in a green yard.",
            },
            fallback=fresh_fallback,
        )

        self.assertGreater(normalized["score"], 40)
        self.assertGreater(normalized["coverage"]["scoreCapApplied"], 40)
        self.assertTrue(normalized["coverage"]["mainSubjectMentioned"])
        self.assertTrue(normalized["coverage"]["mainActionMentioned"])
        self.assertNotIn("the main subject (person)", normalized["missing_details"])

    def test_partial_image_descriptions_cannot_score_high(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        analysis = {
            "objects": [
                {"name": "person", "description": "A person is riding a mower.", "importance": 0.95},
                {"name": "mower", "description": "A riding mower is on the grass.", "importance": 0.9},
                {"name": "grass", "description": "Foreground grass fills the yard.", "importance": 0.7},
                {"name": "palm trees", "description": "Palm trees are in the background.", "importance": 0.6},
                {"name": "bushes", "description": "Bushes are in the yard.", "importance": 0.5},
            ],
            "actions": [{"phrase": "mowing the lawn", "verb": "mowing"}],
            "environment": "sunny yard setting",
            "environment_details": ["foreground grass", "palm trees", "bushes", "bright sky"],
            "natural_explanation": (
                "A person is riding a mower across a grassy lawn. Palm trees, bushes, "
                "and bright daylight are in the background, making the scene look tidy and sunny."
            ),
            "vocabulary": [],
            "phrases": [],
        }

        background_only = analyzer._heuristic_explanation_feedback(
            learner_text="The sky is bright and there are trees in the background.",
            original_text="",
            analysis=analysis,
        )
        action_only = analyzer._heuristic_explanation_feedback(
            learner_text="A person is mowing the lawn.",
            original_text="",
            analysis=analysis,
        )
        full_description = analyzer._heuristic_explanation_feedback(
            learner_text=(
                "A person is riding a mower across a grassy lawn. There are palm trees, "
                "bushes, and bright daylight in the background, making the scene look tidy and sunny."
            ),
            original_text="",
            analysis=analysis,
        )

        self.assertLessEqual(background_only["score"], 30)
        self.assertLessEqual(background_only["coverage"]["scoreCapApplied"], 25)
        self.assertLessEqual(action_only["score"], 60)
        self.assertGreater(action_only["score"], background_only["score"])
        self.assertGreaterEqual(full_description["score"], 85)
        self.assertGreater(full_description["score"], action_only["score"])

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

    def test_feedback_validation_caps_keyword_lists_and_broken_fragments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        analysis = {
            "objects": [
                {"name": "broken sticks", "description": "Broken sticks are on sand.", "importance": 0.8},
                {"name": "tall structure", "description": "A tall structure is in the background.", "importance": 0.7},
            ],
            "actions": [{"verb": "lying", "phrase": "lying on the sand", "importance": 0.8}],
            "environment_details": ["sand", "background", "foreground"],
            "vocabulary": [{"word": "debris"}],
            "phrases": [{"phrase": "in the background"}],
        }

        keyword_feedback = analyzer._validate_learner_answer_for_feedback(
            learner_text="sand debris background foreground tall structure",
            analysis=analysis,
        )
        self.assertIsNotNone(keyword_feedback)
        self.assertTrue(keyword_feedback["retry_required"])
        self.assertLessEqual(keyword_feedback["score"], 15)
        self.assertIn("not yet a clear sentence", keyword_feedback["main_issue"])

        broken_feedback = analyzer._validate_learner_answer_for_feedback(
            learner_text=(
                "Broken stick pieces are debrising lies on the sandsmall debris "
                "tall structure in the background"
            ),
            analysis=analysis,
        )
        self.assertIsNotNone(broken_feedback)
        self.assertTrue(broken_feedback["retry_required"])
        self.assertLessEqual(broken_feedback["score"], 40)

        coherent_feedback = analyzer._validate_learner_answer_for_feedback(
            learner_text=(
                "There are broken sticks and small debris lying on the sand, "
                "with a tall structure in the background."
            ),
            analysis=analysis,
        )
        self.assertIsNone(coherent_feedback)

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

    def test_progressive_feedback_includes_specific_image_hints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        analysis = {
            "natural_explanation": (
                "A person is riding a mower across a grassy lawn. "
                "Palm trees and trimmed bushes are in the sunny background."
            ),
            "objects": [
                {"name": "person", "description": "A person is on a red riding mower."},
                {"name": "riding mower", "description": "A red mower is on the grass."},
                {"name": "palm trees", "description": "Palm trees are in the background."},
                {"name": "trimmed bushes", "description": "Trimmed bushes are behind the lawn."},
            ],
            "actions": [{"verb": "riding", "phrase": "riding a mower across the lawn"}],
            "environment": "sunny outdoor lawn",
            "environment_details": ["green grass", "palm trees", "trimmed bushes", "sunny sky"],
            "vocabulary": [{"word": "lawn"}],
            "phrases": [{"phrase": "in the background"}],
        }
        feedback = {
            "score": 34,
            "scores": {"vocabulary": 4, "structure": 5, "depth": 3, "clarity": 5},
            "language_quality": {"score": 45, "vocabulary": 40, "structure": 50, "naturalness": 40},
            "coverage": {
                "mainSubjectMentioned": True,
                "mainActionMentioned": False,
                "imageParts": [
                    {"type": "main_subject", "coverageStatus": "covered", "covered": True},
                    {"type": "main_action", "coverageStatus": "missing", "covered": False},
                    {"type": "setting", "coverageStatus": "missing", "covered": False},
                ],
                "coveragePercent": 35,
            },
            "readiness": {
                "criteria": {
                    "mainSubject": True,
                    "mainAction": False,
                    "settingBackground": False,
                    "twoImportantDetails": False,
                    "naturalEnglish": False,
                    "notAWordList": True,
                }
            },
            "what_did_well": ["Good start — you mentioned the person."],
            "missing_details": ["the main action", "the setting or background"],
            "phrase_usage": {"used": [], "suggested": ["in the background"]},
        }

        coached = analyzer._apply_progressive_coaching(
            feedback,
            analysis=analysis,
            learner_text="A man is outside.",
            original_text="A man is outside.",
            attempt_index=1,
        )

        self.assertEqual(["main action", "background/setting"], coached["focus_areas"])
        guidance = coached["specific_guidance"]
        self.assertIn("riding mower", guidance["words"])
        self.assertIn("riding", guidance["verbs"])
        self.assertIn("palm trees", guidance["words"])
        self.assertIn("riding a mower across the lawn", guidance["sentence_starter"])
        self.assertNotIn("Add more detail", " ".join(guidance["actionable_suggestions"]))
        self.assertFalse(coached["is_ready"])

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
    def test_post_improve_quiz_uses_feedback_context_and_required_types(self) -> None:
        rows = build_post_improve_quiz_rows(
            user_id=1,
            session_id=2,
            learner_level="developing",
            created_at="2026-05-04T00:00:00+00:00",
            learner_text="A man is in the street.",
            improved_text="A cyclist is riding down a busy street with cars in the background.",
            feedback={
                "better_version": "A cyclist is riding down a busy street with cars in the background.",
                "missing_details": ["cars in the background"],
                "fix_this_to_improve": ["Mention the cyclist and the street action."],
                "phrase_usage": {
                    "suggested": ["in the background"],
                    "message": "Use the full phrase in the background.",
                },
            },
            analysis={
                "scene_summary_natural": "A cyclist is riding down a busy street with cars in the background.",
                "scene_summary_simple": "A cyclist is riding on a street.",
                "objects": [
                    {"name": "cyclist", "description": "A cyclist is visible."},
                    {"name": "cars", "description": "Cars are in the background."},
                ],
                "actions": [{"phrase": "riding down a busy street"}],
                "phrases": [
                    {
                        "phrase": "in the background",
                        "meaning_simple": "behind the main subject",
                        "example": "Cars are in the background.",
                    },
                    {
                        "phrase": "riding down",
                        "meaning_simple": "moving along a place on a bike",
                        "example": "A cyclist is riding down a busy street.",
                    }
                ],
                "vocabulary": [{"word": "cyclist"}],
            },
        )

        quiz_types = [row["quiz_type"] for row in rows]
        self.assertEqual(
            [
                "multiple_choice_comprehension",
                "matching_pairs",
                "fill_blank",
                "sentence_reconstruction",
            ],
            quiz_types,
        )
        self.assertEqual(4, len(rows))
        self.assertEqual(
            ["multiple_choice", "matching", "typing", "reorder"],
            [row["answer_mode"] for row in rows],
        )
        self.assertTrue(
            all("_____" in row["prompt"] for row in rows if row["quiz_type"] == "fill_blank")
        )
        matching = next(row for row in rows if row["quiz_type"] == "matching_pairs")
        self.assertGreaterEqual(len(matching["metadata"]["pairs"]), 2)
        reconstruction = next(row for row in rows if row["quiz_type"] == "sentence_reconstruction")
        self.assertTrue(reconstruction["metadata"]["tokens"])
        self.assertTrue(all(row["session_id"] == 2 for row in rows))
        for row in rows:
            self.assertIn("prompt", row)
            self.assertIn("correct_answer", row)
            self.assertTrue(row["explanation"])
            self.assertGreater(row["difficulty"], 0)
            self.assertGreater(row["metadata"]["xp_value"], 0)
            self.assertTrue(row["metadata"]["post_improve"])
            if row["metadata"]["related_reusable_phrase"]:
                self.assertIn(
                    row["metadata"]["related_reusable_phrase"],
                    {"in the background", "riding down", "riding down a busy street", "riding"},
                )

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

    def test_phrase_snap_typing_accepts_close_answer_as_almost_correct(self) -> None:
        result = evaluate_quiz_response(
            item={
                "quiz_type": "phrase_snap",
                "answer_mode": "typing",
                "correct_answer": "in the background",
                "acceptable_answers": ["in the background"],
                "metadata": {},
            },
            selected_answer="in background",
            response_ms=3000,
            confidence=2,
        )

        self.assertFalse(result["correct"])
        self.assertEqual("Almost Correct", result["result_type"])
        self.assertGreater(result["score"], 0.5)

    def test_fill_blank_uses_direct_and_close_matching(self) -> None:
        item = {
            "quiz_type": "fill_blank",
            "answer_mode": "typing",
            "correct_answer": "riding",
            "acceptable_answers": ["riding", "ride"],
            "metadata": {},
        }

        direct = evaluate_quiz_response(
            item=item,
            selected_answer="ride",
            response_ms=2000,
            confidence=2,
        )
        close = evaluate_quiz_response(
            item=item,
            selected_answer="ridng",
            response_ms=2000,
            confidence=2,
        )

        self.assertTrue(direct["correct"])
        self.assertEqual("Correct", direct["result_type"])
        self.assertFalse(close["correct"])
        self.assertEqual("Almost Correct", close["result_type"])
        self.assertTrue(close["feedback"]["corrected_example"])

    def test_fix_the_sentence_accepts_natural_alternative_and_partial(self) -> None:
        item = {
            "quiz_type": "fix_the_sentence",
            "answer_mode": "typing",
            "correct_answer": "The man is riding a mower on the grass.",
            "acceptable_answers": ["The man is riding a mower on the grass."],
            "metadata": {
                "weak_sentence": "The man on mower grass.",
                "keywords": ["man", "riding", "mower", "grass"],
                "reference_answer": "The man is riding a mower on the grass.",
            },
        }

        natural = evaluate_quiz_response(
            item=item,
            selected_answer="A man is riding the mower across the grass.",
            response_ms=7000,
            confidence=2,
        )
        partial = evaluate_quiz_response(
            item=item,
            selected_answer="The man riding mower grass.",
            response_ms=7000,
            confidence=2,
        )

        self.assertTrue(natural["correct"])
        self.assertEqual("Correct", natural["result_type"])
        self.assertFalse(partial["correct"])
        self.assertEqual("Almost Correct", partial["result_type"])
        self.assertTrue(partial["feedback"]["corrected_example"])

    def test_sentence_upgrade_validates_meaning_strength_and_phrase_use(self) -> None:
        result = evaluate_quiz_response(
            item={
                "quiz_type": "sentence_upgrade_battle",
                "answer_mode": "typing",
                "correct_answer": "A cyclist is riding down a busy street with cars in the background.",
                "acceptable_answers": ["A cyclist is riding down a busy street with cars in the background."],
                "metadata": {
                    "weak_sentence": "A man is in the street.",
                    "related_reusable_phrase": "in the background",
                    "keywords": ["cyclist", "riding", "street", "cars", "in the background"],
                    "reference_answer": "A cyclist is riding down a busy street with cars in the background.",
                },
            },
            selected_answer="A cyclist is riding down the street with cars in the background.",
            response_ms=8000,
            confidence=3,
        )

        self.assertTrue(result["correct"])
        self.assertEqual("Correct", result["result_type"])

    def test_fix_the_mistake_allows_natural_alternative(self) -> None:
        result = evaluate_quiz_response(
            item={
                "quiz_type": "fix_the_mistake",
                "answer_mode": "typing",
                "correct_answer": "A cyclist is riding down a busy street with cars in the background.",
                "acceptable_answers": ["A cyclist is riding down a busy street with cars in the background."],
                "metadata": {
                    "keywords": ["cyclist", "riding", "street", "cars"],
                    "reference_answer": "A cyclist is riding down a busy street with cars in the background.",
                },
            },
            selected_answer="The cyclist is riding on a busy street near cars.",
            response_ms=9000,
            confidence=2,
        )

        self.assertTrue(result["correct"])
        self.assertEqual("Correct", result["result_type"])

    def test_use_it_or_lose_it_gives_partial_credit_for_weak_phrase_sentence(self) -> None:
        result = evaluate_quiz_response(
            item={
                "quiz_type": "use_it_or_lose_it",
                "answer_mode": "typing",
                "correct_answer": "Cars are in the background while a cyclist rides down the street.",
                "acceptable_answers": ["Cars are in the background while a cyclist rides down the street."],
                "metadata": {
                    "related_reusable_phrase": "in the background",
                    "keywords": ["in the background", "cyclist", "street"],
                    "reference_answer": "Cars are in the background while a cyclist rides down the street.",
                },
            },
            selected_answer="in the background cyclist",
            response_ms=5000,
            confidence=1,
        )

        self.assertFalse(result["correct"])
        self.assertEqual("Almost Correct", result["result_type"])
        self.assertGreaterEqual(result["score"], 0.5)
        self.assertTrue(result["feedback"]["corrected_example"])


if __name__ == "__main__":
    unittest.main()
