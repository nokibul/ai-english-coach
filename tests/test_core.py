from __future__ import annotations

from datetime import timezone
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
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
    build_learning_engines_payload,
    build_highlight_terms,
    build_quiz_xp_breakdown,
    learning_stage_from_feedback,
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


class LearningStageTests(unittest.TestCase):
    def test_first_feedback_uses_first_feedback_stage(self) -> None:
        feedback = {
            "coverage": {
                "coveragePercent": 90,
                "imageParts": [
                    {"type": "main_subject", "covered": True, "required": True},
                ],
            }
        }
        self.assertEqual(
            learning_stage_from_feedback(feedback, attempt_index=1),
            "first_feedback",
        )

    def test_learning_engines_keep_articulation_locked_until_coverage_complete(self) -> None:
        feedback = {
            "coverage": {
                "coveragePercent": 50,
                "imageParts": [
                    {"type": "main_subject", "name": "main subject", "covered": True, "required": True},
                    {"type": "background", "name": "background", "covered": False, "required": True},
                ],
            },
            "language_quality": {"score": 82},
        }
        engines = build_learning_engines_payload(feedback, learning_stage="coverage_layers")
        self.assertFalse(engines["coverage_engine"]["ready_for_articulation"])
        self.assertTrue(engines["articulation_engine"]["locked"])

    def test_later_feedback_stays_in_layers_until_coverage_is_ready(self) -> None:
        feedback = {
            "coverage": {
                "coveragePercent": 45,
                "imageParts": [
                    {"type": "main_subject", "covered": True, "required": True},
                    {"type": "background", "covered": False, "required": True},
                ],
            }
        }
        self.assertEqual(
            learning_stage_from_feedback(feedback, attempt_index=2),
            "coverage_layers",
        )

    def test_later_feedback_unlocks_coverage_complete_when_ready(self) -> None:
        feedback = {
            "readiness": {"ready": True},
            "coverage": {
                "coveragePercent": 82,
                "imageParts": [
                    {"type": "main_subject", "covered": True, "required": True},
                    {"type": "background", "coverageStatus": "partially_covered", "required": True},
                ],
            },
        }
        self.assertEqual(
            learning_stage_from_feedback(feedback, attempt_index=3),
            "coverage_complete",
        )

    def test_ready_flag_does_not_skip_missing_major_visual_area(self) -> None:
        feedback = {
            "readiness": {"ready": True},
            "coverage": {
                "coveragePercent": 88,
                "imageParts": [
                    {"type": "main_subject", "covered": True, "required": True},
                    {"type": "setting", "covered": True, "required": True},
                    {"type": "important_object", "covered": False, "required": True},
                ],
            },
        }
        self.assertEqual(
            learning_stage_from_feedback(feedback, attempt_index=3),
            "coverage_layers",
        )

    def test_ready_flag_does_not_complete_basic_subject_plus_one_detail(self) -> None:
        feedback = {
            "readiness": {
                "ready": True,
                "criteria": {
                    "mainSubject": True,
                    "mainAction": True,
                    "settingBackground": False,
                    "naturalEnglish": True,
                    "notAWordList": True,
                },
            },
            "coverage": {
                "coveragePercent": 82,
                "mainSubjectMentioned": True,
                "mainActionMentioned": True,
                "imageParts": [
                    {"type": "main_subject", "name": "large building", "coverageStatus": "covered", "required": True},
                    {"type": "important_object", "name": "people", "coverageStatus": "covered", "required": True},
                    {"type": "setting", "name": "surrounding greenery", "coverageStatus": "missing", "required": True},
                    {"type": "foreground", "name": "entrance area", "coverageStatus": "missing", "required": True},
                ],
            },
        }
        self.assertEqual(
            learning_stage_from_feedback(feedback, attempt_index=2),
            "coverage_layers",
        )


class ConfigTests(unittest.TestCase):
    def test_config_defaults_to_demo_without_api_key(self) -> None:
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

    def test_config_uses_openai_when_api_key_is_set(self) -> None:
        env = {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_MODEL": "gpt-test",
            "OPENAI_BASE_URL": "https://example.test/v1/",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, env, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        self.assertEqual(config.ai_backend, "openai")
        self.assertEqual(config.openai_api_key, "test-key")
        self.assertEqual(config.openai_model, "gpt-test")
        self.assertEqual(config.openai_base_url, "https://example.test/v1")

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


class StaticImproveHintTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for static Improve hint tests")
    def test_improve_hints_are_filtered_by_current_focus(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");
const context = {
  document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
  window: { setTimeout() {} },
  console,
};
vm.createContext(context);
vm.runInContext(code, context);

const session = {
  analysis: {
    objects: [{ name: "person" }, { name: "riding mower" }, { name: "palm trees" }],
    actions: [{ verb: "riding", phrase: "riding a mower across the lawn" }],
    environment: "sunny outdoor lawn",
    environment_details: ["green grass", "palm trees", "trimmed bushes", "sunny sky"],
    vocabulary: [{ word: "peaceful" }, { word: "lawn" }],
    phrases: [{ phrase: "in the background" }, { phrase: "riding across the lawn" }],
  },
};
const feedback = {
  specific_guidance: {
    nouns: ["person", "mower", "palm trees"],
    verbs: ["riding"],
    details: ["palm trees in the background", "peaceful atmosphere"],
    words: ["peaceful", "sunny"],
  },
  phrase_usage: { used: [], suggested: ["in the background", "riding across the lawn"] },
  reusable_sentence_structures: ["In the background, there are ___", "The scene feels ___"],
};
function flatHints(focus) {
  return context.buildImproveHintGroups(session, feedback, { focusAreas: [focus], additions: [] }, "A person is outside.")
    .flatMap((group) => group.items)
    .join(" | ")
    .toLowerCase();
}
function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}
const subjectHints = flatHints("main subject");
assert(subjectHints.includes("person"), "subject focus should include subject nouns");
assert(!subjectHints.includes("background"), "subject focus should hide background hints");
assert(!subjectHints.includes("peaceful"), "subject focus should hide atmosphere hints");

const backgroundHints = flatHints("background");
assert(backgroundHints.includes("palm trees"), "background focus should include environment nouns");
assert(backgroundHints.includes("in the background"), "background focus should include positioning phrases");
assert(!backgroundHints.includes("riding across"), "background focus should hide action phrases");

const atmosphereHints = flatHints("mood/atmosphere");
assert(atmosphereHints.includes("peaceful"), "atmosphere focus should include mood words");
assert(!atmosphereHints.includes("riding"), "atmosphere focus should hide action verbs");
assert(!atmosphereHints.includes("in the background"), "atmosphere focus should hide background phrases");
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for static Improve hint tests")
    def test_improve_focus_and_hints_escalate_when_stuck(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");
const context = {
  document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
  window: { setTimeout() {} },
  console,
};
vm.createContext(context);
vm.runInContext(code, context);

const session = {
  analysis: {
    objects: [{ name: "two people" }, { name: "paved path" }, { name: "trees" }],
    actions: [{ verb: "walking", phrase: "walking along the path" }],
    environment: "park path",
    environment_details: ["paved path", "trees"],
    vocabulary: [{ word: "peaceful" }],
    phrases: [{ phrase: "along the path" }],
  },
};
const feedback = {
  score: 30,
  coverage: {
    mainSubjectMentioned: false,
    mainActionMentioned: true,
    imageParts: [{ type: "main_subject", covered: false, coverageStatus: "missing" }],
  },
  readiness: { criteria: { mainSubject: false, mainAction: true, notAWordList: true } },
  missing_details: ["main subject"],
  specific_guidance: { nouns: ["people"], verbs: ["walking"], details: ["paved path"], words: [] },
};
const issue = context.buildFeedbackIssue(feedback, session);
const first = context.buildImproveEscalationContext(session, [{ text: "Walking outside", feedback, score: 30 }], issue);
const second = context.buildImproveEscalationContext(session, [
  { text: "Walking outside", feedback, score: 30 },
  { text: "Walking in a park", feedback, score: 31 },
], issue);
const third = context.buildImproveEscalationContext(session, [
  { text: "Walking outside", feedback, score: 30 },
  { text: "Walking in a park", feedback, score: 31 },
  { text: "On the path", feedback, score: 31 },
], issue);
function flatHints(escalation) {
  return context.buildImproveHintGroups(session, feedback, issue, "On the path", escalation)
    .flatMap((group) => group.items)
    .join(" | ")
    .toLowerCase();
}
function assert(condition, message) {
  if (!condition) throw new Error(message);
}
assert(first.level === 1, "first attempt should stay abstract");
assert(context.buildImproveCurrentFocus(issue, session, first) === "Describe the main subject", "first focus should be abstract");
assert(second.level === 2, "second miss should become guided but not explicit");
assert(context.buildImproveCurrentFocus(issue, session, second) === "Who is the image mainly focused on?", "second focus should narrow attention");
assert(third.level === 3, "third repeated miss should stay explicit");
assert(context.buildImproveCurrentFocus(issue, session, third).includes("two people"), "third focus should name the missing subject");
const firstHints = flatHints(first);
const thirdHints = flatHints(third);
assert(firstHints.includes("people"), "first hints should still include reusable subject chunks");
assert(!firstHints.includes("walking along the path"), "first hints should not reveal the contextual phrase");
assert(thirdHints.includes("two people walking along the path"), "third hints should reveal the missing concept directly");
assert(!thirdHints.includes("peaceful"), "subject escalation should still hide unrelated atmosphere hints");
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for static Improve hint tests")
    def test_improve_stage_moves_through_articulation_layers(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");
const context = {
  document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
  window: { setTimeout() {} },
  console,
};
vm.createContext(context);
vm.runInContext(code, context);

const session = {
  analysis: {
    objects: [{ name: "two people" }, { name: "paved path" }, { name: "palm trees" }],
    actions: [{ verb: "walking", phrase: "walking along the path" }],
    environment: "sunny park",
    environment_details: ["paved path", "palm trees", "trimmed bushes"],
    vocabulary: [{ word: "calm" }, { word: "well-kept" }],
    phrases: [{ phrase: "along the path" }, { phrase: "in the background" }],
  },
};
function assert(condition, message) {
  if (!condition) throw new Error(message);
}
function feedback(criteria, parts = [], words = []) {
  return {
    coverage: { imageParts: parts },
    readiness: { criteria: { ...criteria, notAWordList: true, naturalEnglish: true } },
    specific_guidance: { nouns: ["two people", "paved path", "palm trees"], verbs: ["walking"], details: ["palm trees"], words },
  };
}
const subjectOnly = feedback(
  { mainSubject: true, mainAction: false, settingBackground: false },
  [{ type: "main_subject", covered: true, coverageStatus: "covered" }]
);
let state = context.buildCoverageLayerState(subjectOnly, session, "Two people.");
assert(state.currentLayer.label.toLowerCase().includes("action"), "action should be the next coverage focus");
assert(/action|happening|walking/.test(context.buildLayerCurrentFocus(state.currentLayer, session, { level: 1 }).toLowerCase()), "action layer should use action wording");

const throughEnvironment = feedback(
  { mainSubject: true, mainAction: true, settingBackground: true },
  [
    { type: "main_subject", covered: true, coverageStatus: "covered" },
    { type: "main_action", covered: true, coverageStatus: "covered" },
    { type: "setting", covered: true, coverageStatus: "covered" },
  ]
);
state = context.buildCoverageLayerState(throughEnvironment, session, "Two people are walking along the path in a sunny park.");
assert(state.currentLayer, "coverage should continue until meaningful details are added");
assert(/detail|object|visual/i.test(state.currentLayer.label), "details should be next after environment");
const detailIssue = context.buildLayerFeedbackIssue(state.currentLayer, throughEnvironment, session);
const detailHints = context.buildImproveHintGroups(session, throughEnvironment, detailIssue, "Two people are walking along the path.", { level: 1 })
  .flatMap((group) => group.items)
  .join(" | ")
  .toLowerCase();
assert(detailHints.includes("paved path") || detailHints.includes("palm trees"), "detail layer should show object/detail hints");
assert(!detailHints.includes("calm"), "detail layer should not show atmosphere hints");

const complete = feedback(
  { mainSubject: true, mainAction: true, settingBackground: true },
  [
    { type: "main_subject", covered: true, coverageStatus: "covered" },
    { type: "main_action", covered: true, coverageStatus: "covered" },
    { type: "setting", covered: true, coverageStatus: "covered" },
    { type: "important_object", covered: true, coverageStatus: "covered" },
    { type: "foreground_detail", covered: true, coverageStatus: "covered" },
  ],
  ["calm", "well-kept"]
);
complete.coverage.coveragePercent = 90;
state = context.buildCoverageLayerState(
  complete,
  session,
  "Two people are walking along the paved path in a sunny park with palm trees. The area looks calm and well-kept."
);
assert(state.complete, "coverage should be complete before articulation polish");
assert(state.layers.length === 0, "completed coverage should not show more visual layers");
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for static coverage tests")
    def test_initial_enhancement_enters_guided_coverage_for_basic_building_description(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");
const context = {
  document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
  window: { setTimeout() {}, clearTimeout() {} },
  console,
};
vm.createContext(context);
vm.runInContext(code, context);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

vm.runInContext(`
state.sessionFlow.attempts = [{
  text: "The image shows a tall building covered with climbing vines and a group of people standing together.",
  feedback: {},
}];
`, context);

const session = {
  analysis: {
    objects: [
      { name: "large modern building", description: "covered with dense climbing vines", importance: 0.95 },
      { name: "group of people", description: "gathered near the building", position: "near the entrance", importance: 0.8 },
      { name: "tall trees", description: "trees around the building", importance: 0.78 },
      { name: "bushes and shrubs", description: "greenery around the building", importance: 0.74 },
    ],
    environment: "institutional outdoor area",
    environment_details: ["tall trees around the building", "bushes and shrubs", "bright sky"],
    vocabulary: [{ word: "calm" }],
    phrases: [{ phrase: "near the entrance" }],
  },
};
const feedback = {
  initial_attempt_feedback: {
    prepares_coverage_layers: true,
    covered_enhancement: "The image shows a large modern building covered with dense climbing vines, with a group of people gathered near it.",
    missing_visual_areas: [],
  },
  coverage: {
    coveragePercent: 82,
    mainSubjectMentioned: true,
    mainActionMentioned: true,
    imageParts: [
      { type: "main_subject", name: "large modern building", description: "covered with dense climbing vines", coverageStatus: "covered", covered: true, required: true },
      { type: "important_object", name: "group of people", description: "people gathered near it", coverageStatus: "covered", covered: true, required: true },
    ],
  },
  readiness: { ready: true, criteria: { mainSubject: true, mainAction: true, settingBackground: true, naturalEnglish: true, notAWordList: true } },
};
const text = feedback.initial_attempt_feedback.covered_enhancement;
const state = context.buildCoverageLayerState(feedback, session, text);
assert(!state.complete, "initial enhancement should not mark a basic description as covered");
assert(state.currentLayer, "guided coverage should show one next focus");
assert(state.layers.filter((layer) => layer.current).length === 1, "only one missing focus should be current");
const prompt = `${state.currentLayer.prompt} ${state.currentLayer.visualFocus}`.toLowerCase();
assert(/tree|bush|shrub|greenery|environment|setting/.test(prompt), "next focus should come from uncovered image areas");
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for static coverage tests")
    def test_atmosphere_focus_hints_stay_relevant_to_feeling_question(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");
const context = {
  document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
  window: { setTimeout() {}, clearTimeout() {}, addEventListener() {} },
  console,
};
vm.createContext(context);
vm.runInContext(code, context);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const analysis = {
  objects: [{ name: "building" }, { name: "apartment buildings" }],
  environment: "outdoor institutional area",
  environment_details: ["bright sky", "greenery around the building", "palm trees"],
  vocabulary: [{ word: "calm" }],
};
const target = {
  dynamic: true,
  category: "atmosphere",
  visualFocus: "what feeling the scene creates",
  label: "Describe the feeling of the scene",
  prompt: "What feeling does the scene create?",
  hints: ["buildings", "apartment buildings", "balconies", "concrete walls", "rise", "stand"],
  evidence: ["bright sky", "greenery around the building"],
};
const groups = context.buildDynamicTargetHintGroups(target, analysis, 1);
const hints = context.focusedMiniHints(groups);
const text = hints.join(" | ").toLowerCase();
assert(!/\\b(apartment buildings|balconies|concrete walls|rise|stand)\\b/.test(text), "object/architecture hints should not leak into atmosphere chips: " + text);
assert(/\\b(calm|bright|open|peaceful|fresh|sky|greenery|scene feels)\\b/.test(text), "atmosphere chips should help answer the feeling question: " + text);
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for static coverage tests")
    def test_dynamic_focus_questions_get_easier_incrementally(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");
const context = {
  document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
  window: { setTimeout() {}, clearTimeout() {}, addEventListener() {} },
  console,
};
vm.createContext(context);
vm.runInContext(code, context);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const greenery = {
  dynamic: true,
  category: "environment",
  prompt: "What other greenery do you notice around the building?",
  visualFocus: "tall trees around the building",
  hints: ["tall trees", "bushes", "shrubs"],
  evidence: ["tall trees, bushes, and shrubs around the building"],
};
const prompts = [1, 2, 3, 4, 5].map((level) => context.dynamicTargetPrompt(greenery, {}, level));
assert(prompts[0] === "What other greenery do you notice around the building?", "level 1 should keep the original question");
assert(prompts[1].includes("bottom and sides"), "level 2 should point where to look");
assert(prompts[2].includes("tall trees, bushes, or shrubs"), "level 3 should name answer options");
assert(prompts[3] === "There are ___ around the building.", "level 4 should be a fill-in frame");
assert(prompts[4] === "Try writing: There are tall trees, bushes, and shrubs around the building.", "level 5 should give a direct sentence");
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for static Improve hint tests")
    def test_articulation_upgrade_suggests_and_applies_small_replacements(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");
const context = {
  document: { addEventListener() {}, getElementById() { return { value: "The image shows grass and trees in a nice place." }; }, querySelectorAll() { return []; } },
  window: { setTimeout() {}, clearTimeout() {} },
  console,
};
vm.createContext(context);
vm.runInContext(code, context);

const session = {
  analysis: {
    objects: [{ name: "two people" }, { name: "tall palm trees" }],
    actions: [{ verb: "walking", phrase: "walking along the path" }],
    environment: "peaceful outdoor setting",
    environment_details: ["grassy lawn", "tall palm trees", "in the background"],
    vocabulary: [{ word: "peaceful" }],
    phrases: [{ phrase: "in the background" }],
  },
};
const feedback = {
  coverage: {
    coveragePercent: 90,
    imageParts: [
      { type: "main_subject", covered: true, coverageStatus: "covered" },
      { type: "main_action", covered: true, coverageStatus: "covered" },
      { type: "setting", covered: true, coverageStatus: "covered" },
      { type: "important_object", covered: true, coverageStatus: "covered" },
      { type: "foreground_detail", covered: true, coverageStatus: "covered" },
    ],
  },
  readiness: { criteria: { mainSubject: true, mainAction: true, settingBackground: true, naturalEnglish: true, notAWordList: true } },
  language_quality: { naturalness: 72 },
  specific_guidance: { words: ["peaceful"], nouns: ["grassy lawn", "tall palm trees"], verbs: ["walking"], details: ["in the background"] },
};
function assert(condition, message) {
  if (!condition) throw new Error(message);
}
const answer = "The image shows grass and trees in a nice place.";
const coverage = context.buildCoverageLayerState(feedback, session, answer);
assert(coverage.complete, "coverage layers should be complete before upgrade suggestions");
const suggestions = context.buildArticulationUpgradeSuggestions(session, feedback, answer);
assert(suggestions.length > 0 && suggestions.length <= 5, "upgrade stage should show a short list of suggestions");
assert(suggestions.every((item) => ["vocabulary", "verb", "positioning", "atmosphere", "sentence_flow", "visual_quality"].includes(item.type)), "polish upgrades should use the final upgrade type set");
assert(suggestions.every((item) => answer.toLowerCase().includes(item.oldText.toLowerCase())), "upgrades should target words already in the learner answer");
assert(suggestions.some((item) => item.oldText === "grass" && item.newText === "grassy lawn"), "should suggest a vocabulary upgrade tied to the sentence");
assert(suggestions.some((item) => item.oldText === "trees" && item.newText === "tall palm trees"), "should suggest reusable image language");
let upgradeState = context.normalizeArticulationUpgradeState(null, answer, suggestions);
const grassUpgrade = suggestions.find((item) => item.oldText === "grass");
const upgraded = context.replaceFirstTextOccurrence(upgradeState.answer, grassUpgrade.oldText, grassUpgrade.newText);
assert(upgraded.includes("grassy lawn"), "applying should update only the targeted phrase");
assert(!upgraded.includes("grass and"), "old phrase should be replaced");
assert(context.xpForUpgradeType(grassUpgrade.type) === 5, "vocabulary upgrades should award 5 XP");
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for static polish stage tests")
    def test_polish_stage_generates_controlled_full_answer_upgrades(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");
const context = {
  document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
  window: { setTimeout() {}, clearTimeout() {} },
  console,
};
vm.createContext(context);
vm.runInContext(code, context);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const session = {
  analysis: {
    objects: [{ name: "two people" }, { name: "tall buildings" }, { name: "green trees" }],
    actions: [{ verb: "walking", phrase: "walking along the road" }],
    environment: "quiet urban street",
    environment_details: ["green trees along the road", "tall buildings in the background"],
    vocabulary: [{ word: "quiet" }, { word: "shaded" }],
    phrases: [{ phrase: "along the road" }, { phrase: "in the background" }],
  },
};
const feedback = {
  coverage: {
    coveragePercent: 90,
    imageParts: [
      { type: "main_subject", covered: true, coverageStatus: "covered" },
      { type: "main_action", covered: true, coverageStatus: "covered" },
      { type: "setting", covered: true, coverageStatus: "covered" },
      { type: "important_object", covered: true, coverageStatus: "covered" },
      { type: "foreground_detail", covered: true, coverageStatus: "covered" },
    ],
  },
  readiness: { criteria: { mainSubject: true, mainAction: true, settingBackground: true, naturalEnglish: true, notAWordList: true } },
  specific_guidance: { nouns: ["two people", "tall buildings", "green trees"], verbs: ["walking"], details: ["in the background"], words: ["quiet", "shaded"] },
};
const answer = "There are people on a road. The place is nice and there are trees and buildings in the background.";
const coverage = context.buildCoverageLayerState(feedback, session, answer);
assert(coverage.complete, "polish should only run after coverage is complete");
const suggestions = context.buildArticulationUpgradeSuggestions(session, feedback, answer);
assert(suggestions.length >= 3 && suggestions.length <= 5, "full polish stage should generate 3-5 upgrades for a weak covered answer");
assert(new Set(suggestions.map((item) => item.type)).size >= 3, "polish should cover multiple articulation dimensions");
assert(suggestions.some((item) => item.type === "vocabulary"), "should include weak/simple noun upgrades");
assert(suggestions.some((item) => item.type === "atmosphere"), "should include atmosphere language when the answer is flat");
assert(suggestions.some((item) => item.type === "sentence_flow" || item.type === "positioning"), "should include flow or positioning opportunities");
assert(!suggestions.some((item) => /^(composition|impression|flow)$/.test(item.type)), "old upgrade categories should be normalized");
assert(suggestions.every((item) => answer.toLowerCase().includes(item.oldText.toLowerCase())), "the learner should stay in control through inline replacements");
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for inline upgrade UI tests")
    def test_inline_upgrade_markup_highlights_spans_and_keeps_popovers_closed(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");
const context = {
  document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
  window: { setTimeout() {}, clearTimeout() {} },
  console,
};
vm.createContext(context);
vm.runInContext(code, context);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const answer = "The image shows trees and it looks nice.";
const suggestions = [
  { id: "vocabulary-0-trees", oldText: "trees", newText: "leafy branches", type: "vocabulary", xp: 5 },
  { id: "atmosphere-1-looks-nice", oldText: "looks nice", newText: "creates a calm atmosphere", type: "atmosphere", xp: 10 },
];
const annotated = context.buildInlineUpgradeMarkup(answer, suggestions);
assert(annotated.count === 2, "two exact text spans should be highlighted");
assert(annotated.markup.includes("inline-upgrade-target"), "original phrases should be wrapped as clickable targets");
assert(annotated.markup.includes("inline-upgrade-original\">trees"), "the original phrase should remain visible");
assert(annotated.markup.includes("leafy branches"), "popover should contain the upgraded phrase");
assert(annotated.markup.includes("inline-upgrade-dismiss"), "popover should include an X dismiss button");
assert(annotated.markup.includes('aria-expanded="false"'), "popovers should start closed");
assert(annotated.markup.includes('tabindex="0"'), "targets should be keyboard reachable");
assert(context.replaceFirstTextOccurrence(answer, "trees", "leafy branches").includes("leafy branches"), "clicking an upgrade should replace only the target span");
assert(context.polishRewardLabel("vocabulary") === "stronger wording", "reward feedback should use friendly wording");
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for final reveal UI tests")
    def test_final_polished_reveal_shows_growth_language_reward_and_quiz_cta(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");
const context = {
  document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
  window: { setTimeout() {}, clearTimeout() {} },
  console,
};
vm.createContext(context);
vm.runInContext(code, context);
vm.runInContext('state.sessionFlow = { attempts: [{ text: "There is road and trees." }] };', context);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const suggestions = [
  { id: "vocabulary-0-trees", oldText: "trees", newText: "leafy branches", type: "vocabulary", xp: 5 },
  { id: "atmosphere-1-nice", oldText: "nice", newText: "calm atmosphere", type: "atmosphere", xp: 10 },
];
const upgradeState = {
  original: "The image shows a road, trees, and buildings.",
  answer: "The image shows a road, leafy branches, and buildings with a calm atmosphere.",
  applied: ["vocabulary-0-trees", "atmosphere-1-nice"],
  skipped: [],
  xp: 15,
  finalized: true,
};
const feedback = { phrase_usage: { suggested: ["in the background"] } };
const session = { analysis: { phrases: [{ phrase: "along the road" }] } };
const html = context.renderFinalPolishedReveal(upgradeState, suggestions, feedback, session);

assert(html.includes("Your description evolved"), "reveal should feel rewarding");
assert(html.includes("Your first attempt"), "should label the original first attempt");
assert(html.includes("There is road and trees."), "should show the actual first attempt");
assert(html.includes("Your final description"), "should label the evolved answer");
assert(html.includes("leafy branches"), "should show the final upgraded wording");
assert(html.includes("Reusable language you learned"), "should show reusable language learned");
assert(html.includes("3") && html.includes("Phrases Learned"), "progress should count learned reusable language");
assert(html.includes("XP"), "should show an XP reward");
assert(html.includes("Continue to Quiz"), "should include quiz CTA");
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for flow UX tests")
    def test_learning_flow_ui_keeps_current_focus_simple(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");
const context = {
  document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
  window: { setTimeout() {}, clearTimeout() {} },
  console,
};
vm.createContext(context);
vm.runInContext(code, context);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const coverage = {
  layers: [
    { key: "greenery", label: "Add more detail about the greenery", visualFocus: "greenery", category: "environment", completed: false, current: true },
    { key: "vehicles", label: "Describe the vehicles near the road", visualFocus: "vehicles near the road", category: "positioning", completed: false },
  ],
  currentIndex: 0,
  currentLayer: { key: "greenery", label: "Add more detail about the greenery", visualFocus: "greenery", category: "environment", completed: false, current: true },
};
const progress = context.renderCoverageLayerProgress(coverage);
assert(progress.includes("Focus 1 of 2"), "coverage progress should show current focus count");
assert(progress.includes("greenery"), "coverage progress should name the current visual focus");
assert(!progress.includes("Next:"), "coverage progress should hide upcoming-focus complexity");

const hintHtml = context.renderImproveHintsCard([
  { label: "Nouns", items: ["trees", "branches", "leaves", "road", "buildings"] },
  { label: "Verbs", items: ["stretching", "covering", "standing"] },
  { label: "Adjectives", items: ["green", "shaded", "quiet"] },
  { label: "Phrases", items: ["above the road"] },
]);
assert(hintHtml.includes("Focused hints"), "coverage hints should be labeled as focused");
const groupCount = (hintHtml.match(/improve-hint-group/g) || []).length;
assert(groupCount <= 3, "coverage should avoid long hint lists");

const polishHtml = context.renderArticulationUpgradeStage(
  { original: "There are trees.", answer: "There are trees.", applied: [], skipped: [], finalized: false },
  [{ id: "vocabulary-0-trees", oldText: "trees", newText: "leafy branches", type: "vocabulary", xp: 5 }]
);
assert(polishHtml.includes("Upgrade your articulation"), "polish stage should have a direct title");
assert(polishHtml.includes("inline-upgrade-target"), "polish stage should center the inline highlights");
assert(!polishHtml.includes("Manual edit"), "polish stage should hide extra form complexity");
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for static Improve hint tests")
    def test_coverage_layers_follow_missing_visual_areas(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");
const context = {
  document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
  window: { setTimeout() {}, clearTimeout() {} },
  console,
};
vm.createContext(context);
vm.runInContext(code, context);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const session = {
  analysis: {
    articulation_targets: [
      {
        id: "greenery",
        label: "Add more detail about the greenery",
        visual_focus: "greenery along the road",
        category: "environment",
        hints: ["trees", "leaves", "greenery along the roadside"],
        evidence: ["branches stretching over the road"],
      },
      {
        id: "vehicles",
        label: "Describe the vehicles near the road",
        visual_focus: "vehicles near the road",
        category: "positioning",
        hints: ["parked motorcycle", "moving car", "near the roadside"],
        evidence: ["traffic along the street"],
      },
      {
        id: "lighting",
        label: "Describe the lighting and shadows",
        visual_focus: "lighting and shadows",
        category: "lighting",
        hints: ["bright daylight", "shadows on the road"],
        evidence: ["sunlight through the trees"],
      },
    ],
    objects: [{ name: "road" }, { name: "buildings" }, { name: "trees" }, { name: "motorcycle" }],
    actions: [],
    environment: "urban road",
    environment_details: ["trees near the road", "vehicles near the roadside", "bright daylight"],
    phrases: [{ phrase: "near the roadside" }, { phrase: "in the background" }],
    sentence_patterns: [{ pattern: "In the background, there are ___" }],
  },
};

const feedback = {
  learning_flow: { missing_visual_areas: ["greenery", "vehicles near the road", "lighting and shadows"] },
  initial_attempt_feedback: { missing_visual_areas: ["greenery", "vehicles near the road", "lighting and shadows"] },
  coverage: {
    coveragePercent: 45,
    imageParts: [
      { name: "road", type: "setting", covered: true, coverageStatus: "covered" },
      { name: "greenery", type: "background", covered: false, coverageStatus: "missing" },
      { name: "vehicles near the road", type: "important_object", covered: false, coverageStatus: "missing" },
      { name: "lighting and shadows", type: "atmosphere", covered: false, coverageStatus: "missing" },
    ],
  },
};

const state = context.buildCoverageLayerState(feedback, session, "There is a road and buildings.");
assert(state.layers.length === 3, "coverage should build one layer per missing visual area");
assert(state.currentLayer.label === "Add more detail about the greenery", "first layer should focus on the first missing visual area");
assert(state.currentLayer.visualFocus.includes("greenery"), "current layer should keep an image-specific visual focus");

const issue = context.buildLayerFeedbackIssue(state.currentLayer, feedback, session);
const hints = context.buildImproveHintGroups(session, feedback, issue, "There is a road and buildings.", { level: 1 });
const hintText = hints.flatMap((group) => group.items).join(" | ").toLowerCase();
assert(hintText.includes("trees") || hintText.includes("greenery") || hintText.includes("leaves"), "greenery layer should show greenery hints");
assert(!hintText.includes("motorcycle"), "greenery layer should not show unrelated vehicle hints");
assert(hints.some((group) => /sentence/i.test(group.label) && group.items.some((item) => item.includes("___"))), "current layer should include sentence frames with blanks");

const nextFeedback = {
  learning_flow: { missing_visual_areas: ["vehicles near the road", "lighting and shadows"] },
  coverage: {
    coveragePercent: 62,
    imageParts: [
      { name: "greenery", type: "background", covered: true, coverageStatus: "covered" },
      { name: "vehicles near the road", type: "important_object", covered: false, coverageStatus: "missing" },
      { name: "lighting and shadows", type: "atmosphere", covered: false, coverageStatus: "missing" },
    ],
  },
};
const nextState = context.buildCoverageLayerState(nextFeedback, session, "There is a road and buildings with trees along the roadside.");
assert(nextState.currentLayer.label === "Describe the vehicles near the road", "covered greenery should advance to the next missing area");
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for static Improve hint tests")
    def test_coverage_layer_support_progresses_when_stuck(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");
const context = {
  document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
  window: { setTimeout() {}, clearTimeout() {} },
  console,
};
vm.createContext(context);
vm.runInContext(code, context);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const session = {
  analysis: {
    articulation_targets: [{
      id: "greenery",
      label: "Add more detail about the greenery",
      visual_focus: "tree branches and leaves above the road",
      category: "environment",
      hints: ["tree branches", "leaves", "create shade"],
      evidence: ["branches extend over the road"],
    }],
    objects: [{ name: "road" }, { name: "tree branches" }],
    environment: "road",
    environment_details: ["tree branches above the road", "leaves creating shade"],
  },
};
const feedback = {
  learning_flow: { missing_visual_areas: ["greenery"] },
  coverage: {
    coveragePercent: 45,
    imageParts: [
      { name: "greenery", type: "background", covered: false, coverageStatus: "missing" },
    ],
  },
};
const answer = "There is a road and buildings.";
const layer = context.buildCoverageLayerState(feedback, session, answer).currentLayer;
const attempts = Array.from({ length: 5 }, () => ({ text: answer, feedback, score: 40 }));

assert(context.dynamicTargetPrompt(layer, session, 1) === "Add more detail about the greenery.", "attempt 1 should use light guidance");
assert(context.dynamicTargetPrompt(layer, session, 2).includes("Notice"), "attempt 2 should use guided noticing");
assert(context.dynamicTargetPrompt(layer, session, 3).includes("Does this part feel"), "attempt 3 should use choices");
assert(context.dynamicTargetPrompt(layer, session, 4).includes("___"), "attempt 4 should use a sentence scaffold");
assert(context.dynamicTargetPrompt(layer, session, 5).startsWith("Try mentioning"), "attempt 5 should give direct short help");

const issue = context.buildLayerFeedbackIssue(layer, feedback, session);
const escalation = context.buildImproveEscalationContext(session, attempts, issue, layer);
assert(escalation.level === 5, "five attempts should produce level 5 support");
assert(escalation.canMoveForward === true, "level 5 should allow moving forward");
assert(!/wrong|failed/i.test(escalation.message), "support message should not use wrong/failed wording");

const hintGroups = context.buildImproveHintGroups(session, feedback, issue, answer, escalation);
const supportHtml = context.renderImproveEditor({
  rewriteDraft: "The image shows a quiet road.",
  currentFocus: context.dynamicTargetPrompt(layer, session, escalation.level),
  hintGroups,
  articulation: { currentLayer: layer, layers: [layer], currentIndex: 0 },
  escalation,
  session,
  latestText: answer,
  latestFeedback: feedback,
});
assert(supportHtml.includes("Let's make this easier."), "support state should show a supportive tone banner");
assert(supportHtml.includes("progressive-support-banner"), "support state should use the progressive support UI");
assert(supportHtml.includes("Try mentioning"), "direct support should be visible in the updated helper");
assert(!/wrong|failed/i.test(supportHtml), "support UI should not use punitive language");
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for static coverage gate tests")
    def test_coverage_completion_gate_unlocks_polish_without_stale_initial_missing_areas(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");
const context = {
  document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
  window: { setTimeout() {}, clearTimeout() {} },
  console,
};
vm.createContext(context);
vm.runInContext(code, context);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const session = {
  analysis: {
    objects: [{ name: "road" }, { name: "buildings" }],
    actions: [],
    environment: "urban road",
    environment_details: ["buildings along the road"],
  },
};
const feedback = {
  initial_attempt_feedback: { missing_visual_areas: ["trees", "vehicles"] },
  readiness: {
    ready: true,
    criteria: {
      mainSubject: true,
      mainAction: true,
      settingBackground: true,
      naturalEnglish: true,
      notAWordList: true,
    },
  },
  coverage: {
    coveragePercent: 80,
    imageParts: [
      { name: "urban road", type: "main_subject", covered: true, coverageStatus: "covered" },
      { name: "buildings", type: "setting", covered: true, coverageStatus: "covered" },
      { name: "roadside details", type: "important_object", covered: true, coverageStatus: "covered" },
    ],
  },
};

const gate = context.coverageCompletionGate(feedback, session);
const layers = context.buildCoverageLayerState(feedback, session, "The image shows an urban road lined with buildings and roadside details.");
assert(gate.complete === true, "gate should complete when the scene is reasonably covered");
assert(layers.complete === true, "coverage layers should unlock polish when the gate passes");
assert(layers.layers.length === 0, "stale first-attempt missing areas should not recreate layers after completion");
assert(context.isExplanationReady(feedback, session) === true, "ready helper should use the coverage completion gate");

const completeHtml = context.renderCoverageCompleteStage(feedback, session, layers);
assert(completeHtml.includes("Scene covered"), "coverage complete screen should announce scene coverage");
assert(completeHtml.includes("You described the important parts of the image."), "coverage complete screen should explain the accomplishment");
assert(completeHtml.includes("Upgrade My Articulation"), "coverage complete screen should transition into articulation polish");
assert(completeHtml.includes("Road") && completeHtml.includes("Buildings"), "coverage checklist should summarize covered visual areas");
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for static polish UI tests")
    def test_articulation_polish_requires_active_inline_upgrades(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");
const context = {
  document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
  window: { setTimeout() {}, clearTimeout() {} },
  console,
  state: { sessionFlow: { attempts: [{ text: "There is a road and buildings." }] } },
};
vm.createContext(context);
vm.runInContext(code, context);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const suggestions = [
  { id: "vocab-1", oldText: "buildings", newText: "tall residential buildings", type: "vocabulary", xp: 5 },
  { id: "atmo-1", oldText: "nice", newText: "calm and inviting", type: "atmosphere", xp: 10 },
];
const html = context.renderArticulationUpgradeStage({
  original: "There is a road and buildings. It looks nice.",
  answer: "There is a road and buildings. It looks nice.",
  applied: [],
  skipped: [],
  justApplied: false,
}, suggestions);

assert(html.includes("Upgrade your articulation"), "polish stage should use the requested headline");
assert(html.includes("Tap highlighted phrases to improve your description."), "polish stage should explain active tapping");
assert(html.includes("inline-upgrade-target"), "weak phrases should be highlighted inline");
assert(html.includes(">Apply<"), "popover should include an explicit Apply button");
assert(html.includes("Reveal Polished Version"), "learner should explicitly move to the reveal");
assert(!html.includes("textarea"), "polish stage should not be a rewrite form");
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for static Improve hint tests")
    def test_static_object_images_use_appearance_layers_not_action(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");
const context = {
  document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
  window: { setTimeout() {}, clearTimeout() {} },
  console,
};
vm.createContext(context);
vm.runInContext(code, context);

const session = {
  analysis: {
    objects: [{ name: "flower", description: "A bright pink flower with soft petals." }],
    actions: [],
    environment: "garden",
    environment_details: ["green leaves", "slightly blurred background"],
    vocabulary: [{ word: "bright pink" }, { word: "vivid" }, { word: "soft" }],
    phrases: [{ phrase: "in focus" }, { phrase: "surrounded by leaves" }],
  },
};
const feedback = {
  coverage: { imageParts: [{ type: "main_subject", covered: true, coverageStatus: "covered" }] },
  learning_flow: { missing_visual_areas: ["flower appearance"] },
  readiness: { criteria: { mainSubject: true, mainAction: false, settingBackground: false, notAWordList: true } },
  specific_guidance: {
    nouns: ["flower", "petals", "leaves"],
    verbs: ["walking"],
    details: ["green leaves", "slightly blurred background"],
    words: ["bright pink", "vivid", "soft"],
  },
};
function assert(condition, message) {
  if (!condition) throw new Error(message);
}
assert(context.classifyImproveImageType(session.analysis) === "object", "flower image should be object-focused");
const state = context.buildCoverageLayerState(feedback, session, "A flower.");
const keys = state.layers.map((layer) => layer.key).join("|");
assert(!keys.includes("action"), "object-focused layer set should not include action");
assert(state.currentLayer.category === "appearance", "after naming the flower, the next layer should be appearance");
assert(context.buildLayerCurrentFocus(state.currentLayer, session, { level: 1 }).toLowerCase().includes("flower appearance"), "static image prompt should ask for flower appearance");
const issue = context.buildLayerFeedbackIssue(state.currentLayer, feedback, session);
const hints = context.buildImproveHintGroups(session, feedback, issue, "A flower.", { level: 1 })
  .flatMap((group) => group.items)
  .join(" | ")
  .toLowerCase();
assert(hints.includes("bright pink") || hints.includes("soft"), "appearance hints should include visual adjectives");
assert(!hints.includes("walking"), "appearance hints should not include unrelated action verbs");
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for first feedback modal tests")
    def test_initial_feedback_modal_uses_original_sentence_and_manual_upgrades(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");
const context = {
  document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
  window: { setTimeout() {}, clearTimeout() {} },
  console,
};
vm.createContext(context);
vm.runInContext(code, context);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const original = "There is a road and buildings.";
const feedback = {
  better_version: "The image shows a quiet urban road lined with tall residential buildings.",
  initial_attempt_feedback: {
    covered_enhancement: "The image shows a quiet urban road lined with tall residential buildings.",
    reusable_language: {
      phrases: ["lined with"],
      nouns: ["urban road", "residential buildings"],
    },
  },
};
const items = context.buildInitialFeedbackModalUpgradeItems(original, feedback.initial_attempt_feedback, feedback);
const sentenceHtml = context.renderInitialModalSentenceMarkup(original, items);
const previewHtml = context.renderInitialPreviewMarkup(original, items);

assert(items.some((item) => item.oldText === "and" && item.newText === "lined with"), "modal should suggest manual positioning upgrade");
assert(sentenceHtml.includes("initial-modal-weak"), "original sentence should show weak phrase targets");
assert(sentenceHtml.includes("Upgrade suggestion"), "weak phrase should contain compact upgrade card");
assert(sentenceHtml.includes("Apply"), "upgrade card should include Apply");
assert(!sentenceHtml.includes("The image shows a quiet urban road lined with tall residential buildings."), "modal should not show the full AI rewrite immediately");
assert(previewHtml.includes("There is") && previewHtml.includes("and") && previewHtml.includes("buildings"), "preview should start from the learner's own sentence");
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for first feedback improvement card tests")
    def test_initial_feedback_uses_meaningful_improvement_cards(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");
const context = {
  document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
  window: { setTimeout() {}, clearTimeout() {} },
  console,
};
vm.createContext(context);
vm.runInContext(code, context);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const original = "The image shows a children close-up who has chipped his belly and behind him is blanket.";
const initialFeedback = {
  improvements: [
    {
      id: "subject-clarity-1",
      category: "subject_clarity",
      title: "Clearer subject",
      currentText: "a children close-up",
      suggestedText: "a close-up of a young child",
      whyItHelps: "This sounds more natural when describing someone shown closely.",
      example: "The image shows a close-up of a young child.",
      xpReward: 10,
    },
    {
      id: "flow-1",
      category: "sentence_flow",
      title: "Smoother sentence",
      currentText: "behind him is blanket",
      suggestedText: "with a blanket behind him",
      whyItHelps: "This connects the background detail more smoothly.",
      example: "The child is sitting with a blanket behind him.",
      xpReward: 10,
    },
  ],
};
const cards = context.buildInitialImprovementCards(original, initialFeedback, {});
assert(cards.length === 2, "should keep meaningful card improvements");
assert(cards[0].category === "subject_clarity", "card category should be preserved");
assert(cards[0].suggestedText === "a close-up of a young child", "suggestedText should be complete and safe");
const preview = context.applyInitialImprovementToText(original, cards[0]);
assert(preview.includes("a close-up of a young child"), "applying should update the preview");
assert(!preview.includes("children close-up"), "applying should remove the confusing segment");
const html = context.renderInitialImprovementCard(cards[0], 0, cards.length, original);
assert(html.includes("Clearer subject"), "card should render title");
assert(html.includes("Apply +10 XP"), "card should render apply reward");
assert(html.includes("Skip"), "card should render skip action");
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for first feedback improvement card tests")
    def test_initial_feedback_card_fallback_allows_no_major_upgrade(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");
const context = {
  document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
  window: { setTimeout() {}, clearTimeout() {} },
  console,
};
vm.createContext(context);
vm.runInContext(code, context);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const original = "The image shows a child sitting on a bed.";
const cards = context.buildInitialImprovementCards(original, {
  improvements: [],
  covered_enhancement: original,
}, { better_version: original });
assert(cards.length === 0, "frontend should not invent improvements when AI returns none");
const done = context.renderInitialImprovementCompleteState("Let’s make this more expressive.");
assert(done.includes("Let’s make this more expressive."), "empty state should avoid the old no-upgrade message");
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for new enhancement payload tests")
    def test_initial_feedback_cards_accept_new_enhancement_payload_shape(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");
const context = {
  document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
  window: { setTimeout() {}, clearTimeout() {} },
  console,
};
vm.createContext(context);
vm.runInContext(code, context);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const original = "The image shows a building with vines attached with the wall.";
const initialFeedback = {
  enhancement: {
    hasImprovements: true,
    improvedPreview: "The image shows a building covered with climbing vines attached to the wall.",
    upgrades: [
      {
        id: "u1",
        category: "better descriptive wording",
        targetText: "building with vines",
        replacementText: "building covered with climbing vines",
        reason: "This describes the same building and vines more clearly.",
        example: "The building is covered with climbing vines.",
        finalPreview: "The image shows a building covered with climbing vines attached with the wall.",
      },
      {
        id: "u2",
        category: "preposition correction",
        targetText: "attached with",
        replacementText: "attached to",
        reason: "This uses the natural preposition.",
        example: "The vines are attached to the wall.",
        finalPreview: "The image shows a building with vines attached to the wall.",
      },
    ],
  },
};
const cards = context.buildInitialImprovementCards(original, initialFeedback, {});
assert(cards.length === 2, "new enhancement.upgrades cards should survive normalization");
assert(cards[0].currentText === "building with vines", "targetText should become the highlighted text");
assert(cards[0].suggestedText === "building covered with climbing vines", "replacementText should become the upgrade");
assert(cards[0].targetText === cards[0].currentText, "card should keep targetText alias");
assert(cards[0].replacementText === cards[0].suggestedText, "card should keep replacementText alias");
assert(cards[0].category === "visual_clarity", "new category labels should map to UI categories");
const preview = context.applyInitialImprovementToText(original, cards[0]);
assert(preview === "The image shows a building covered with climbing vines attached with the wall.", "applying should use the atomic inline replacement");
assert(!preview.includes("trees") && !preview.includes("sky") && !preview.includes("people"), "enhancement should not add unrelated visual areas");
assert(cards[1].category === "grammar_fix", "preposition correction should map to grammar_fix");
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for initial starter hint tests")
    def test_initial_attempt_starter_ideas_are_minimal_and_high_signal(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");
const context = {
  document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
  window: { setTimeout() {}, clearTimeout() {} },
  console,
};
vm.createContext(context);
vm.runInContext(code, context);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const session = {
  analysis: {
    objects: [
      { name: "signboard" },
      { name: "palm trees" },
      { name: "tall columns" },
      { name: "climbing plants" },
      { name: "people near the entrance" },
    ],
    environment_details: ["tiny background window", "blue sky", "modern building"],
    sentence_starters: ["The image shows"],
  },
};
const hints = context.getStarterIdeaHints(session);
const labels = hints.map((item) => item.label);
assert(hints.length <= 3, "starter ideas should never show more than three hints");
assert(hints.every((item) => item.meaning && item.example), "each starter hint should include info popover content");
assert(labels.includes("palm trees"), "starter ideas should include visually dominant easy nouns");
assert(labels.includes("tall columns"), "starter ideas should include high-signal descriptive phrases");
assert(labels.includes("climbing plants"), "starter ideas should include beginner-friendly visual phrases");
assert(labels.indexOf("palm trees") < labels.indexOf("tall columns"), "main subject should be prioritized before setting/context hints");
assert(!labels.includes("signboard"), "starter ideas should avoid low-signal details");
assert(!labels.includes("people near the entrance"), "starter ideas should avoid longer answer-like phrases");
const climbing = hints.find((item) => item.label === "climbing plants");
assert(/grow upward|greenery attached/i.test(climbing.meaning), "phrase meaning should explain how the hint describes the image");
assert(climbing.example === "The building is covered with climbing plants.", "example should be visually meaningful and reusable");
const markup = context.renderStarterHintChip(climbing, 1);
assert(markup.includes("data-insert-hint"), "chip body should keep a separate insert action");
assert(markup.includes("data-starter-hint-info"), "chip should include a separate info action");
assert(markup.includes("starter-hint-popover"), "chip should render compact info popover markup");
assert(markup.includes("Meaning") && markup.includes("Example"), "popover should show meaning and example labels");

const childSession = {
  analysis: {
    starter_hints: [
      {
        label: "young child",
        type: "phrase",
        meaning: "A very small child, usually younger than a teenager. Use this when the person in the image looks very young.",
        example: "A young child is sitting on a soft bed surface.",
      },
    ],
    objects: [{ name: "young child" }, { name: "couch/bed surface" }],
  },
};
const childHint = context.getStarterIdeaHints(childSession)[0];
assert(childHint.type === "phrase", "AI starter hint type should be preserved");
assert(childHint.meaning.includes("looks very young"), "AI starter hint meaning should be specific, not generic");
assert(childHint.example === "A young child is sitting on a soft bed surface.", "AI starter hint example should be preserved");

const singleSubjectSession = {
  analysis: {
    objects: [{ name: "young child", importance: 0.95 }],
    environment_details: ["tiny background corner"],
  },
};
const singleSubjectHints = context.getStarterIdeaHints(singleSubjectSession).map((item) => item.label);
assert(singleSubjectHints.length === 1, "one strong main subject should not force extra hints");
assert(singleSubjectHints[0] === "young child", "single strong subject should be the only starter hint");

const streetSession = {
  analysis: {
    objects: [
      { name: "motorbike", importance: 0.95 },
      { name: "streetlight pole", importance: 0.7 },
    ],
    environment_details: ["power lines", "distant signboard"],
  },
};
const streetLabels = context.getStarterIdeaHints(streetSession).map((item) => item.label);
assert(streetLabels.length <= 3, "street hints should stay minimal");
assert(streetLabels[0] === "motorbike", "street main subject should come first");
assert(streetLabels.includes("streetlight pole"), "supporting subject should be included when useful");
assert(streetLabels.includes("power lines"), "setting/context hint should be included when useful");
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for starter popover tests")
    def test_starter_hint_popover_position_avoids_writing_controls(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");
const protectedRects = {
  ".writing-box-wrap": { left: 40, top: 140, right: 360, bottom: 430, width: 320, height: 290 },
  submitWritingButton: { left: 40, top: 450, right: 360, bottom: 510, width: 320, height: 60 },
};
const context = {
  document: {
    addEventListener() {},
    getElementById(id) {
      return protectedRects[id] ? { getBoundingClientRect() { return protectedRects[id]; } } : null;
    },
    querySelector(selector) {
      return protectedRects[selector] ? { getBoundingClientRect() { return protectedRects[selector]; } } : null;
    },
    querySelectorAll() { return []; },
    documentElement: { clientWidth: 400, clientHeight: 560 },
  },
  window: { innerWidth: 400, innerHeight: 560, setTimeout() {}, clearTimeout() {} },
  console,
};
vm.createContext(context);
vm.runInContext(code, context);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const placement = context.chooseStarterHintPopoverPlacement({
  anchorRect: { left: 300, top: 110, right: 324, bottom: 134, width: 24, height: 24 },
  width: 260,
  height: 180,
  viewportWidth: 400,
  viewportHeight: 560,
  safe: 12,
  gap: 10,
});
assert(placement.side !== "below", "popover should avoid opening down into the writing box when another side is safer");
assert(placement.left >= 12 && placement.left + 260 <= 388, "popover should stay inside horizontal viewport bounds");
assert(placement.top >= 12 && placement.top + 180 <= 548, "popover should stay inside vertical viewport bounds");
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for initial starter tests")
    def test_initial_attempt_prefills_soft_sentence_starter_once(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");
const context = {
  document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
  window: { setTimeout() {}, clearTimeout() {} },
  console,
};
vm.createContext(context);
vm.runInContext(code, context);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const session = { analysis: { sentence_starters: ["In this image..."] } };
const flow = { explanation: "", initialStarterText: "", initialStarterTouched: false };
const first = context.prepareInitialAttemptDraft(flow, session);
assert(first.isStarter, "first empty initial attempt should use a starter draft");
assert(first.text === "In this image ", "starter draft should be normalized for natural continuation");
assert(flow.initialStarterText === "In this image ", "flow should remember the starter text");

flow.initialStarterTouched = true;
const second = context.prepareInitialAttemptDraft(flow, session);
assert(!second.isStarter && second.text === "", "starter should not reappear after the learner interacts");

const written = context.prepareInitialAttemptDraft({ explanation: "A child is smiling.", initialStarterTouched: false }, session);
assert(!written.isStarter && written.text === "A child is smiling.", "existing learner text should remain owned by the learner");
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for theme toggle tests")
    def test_theme_toggle_updates_body_and_button_state(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");

function makeClassList() {
  const values = new Set();
  return {
    add(value) { values.add(value); },
    remove(value) { values.delete(value); },
    contains(value) { return values.has(value); },
    toggle(value, force) {
      const shouldAdd = force === undefined ? !values.has(value) : Boolean(force);
      if (shouldAdd) values.add(value);
      else values.delete(value);
      return shouldAdd;
    },
  };
}

const bodyClassList = makeClassList();
const rootClassList = makeClassList();
const icon = { textContent: "" };
const button = {
  attrs: {},
  setAttribute(name, value) { this.attrs[name] = value; },
  querySelector(selector) { return selector === ".theme-toggle-icon" ? icon : null; },
};
const storage = {};
const context = {
  document: {
    body: { classList: bodyClassList },
    documentElement: { classList: rootClassList },
    addEventListener() {},
    getElementById(id) { return id === "themeToggleButton" ? button : null; },
    querySelectorAll() { return []; },
  },
  window: { matchMedia() { return { matches: false }; } },
  localStorage: {
    getItem(key) { return storage[key] || null; },
    setItem(key, value) { storage[key] = value; },
  },
  console,
};
vm.createContext(context);
vm.runInContext(code, context);
context.cacheElements();

context.applyTheme("dark");
if (!bodyClassList.contains("dark-mode")) throw new Error("dark mode class should be applied");
if (button.attrs["aria-pressed"] !== "true") throw new Error("toggle should expose pressed dark state");
if (button.attrs["aria-label"] !== "Switch to light mode") throw new Error("toggle should describe the next mode");
if (storage.aiEnglishTheme !== "dark") throw new Error("dark preference should persist");

context.toggleTheme();
if (bodyClassList.contains("dark-mode")) throw new Error("toggle should remove dark mode");
if (button.attrs["aria-pressed"] !== "false") throw new Error("toggle should expose light state");
if (storage.aiEnglishTheme !== "light") throw new Error("light preference should persist");
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for first feedback modal tests")
    def test_initial_feedback_modal_targets_full_starter_for_structural_upgrade(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");
const context = {
  document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
  window: { setTimeout() {}, clearTimeout() {} },
  console,
};
vm.createContext(context);
vm.runInContext(code, context);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const original = "In the image there is a baby sitting and looking at the camera with striped curtains behind her back.";
const feedback = {
  better_version: "The image shows a baby sitting and looking at the camera with striped curtains behind her back.",
  initial_attempt_feedback: {
    covered_enhancement: "The image shows a baby sitting and looking at the camera with striped curtains behind her back.",
    reusable_language: {
      sentence_structures: ["The image shows"],
    },
  },
};
const items = context.buildInitialFeedbackModalUpgradeItems(original, feedback.initial_attempt_feedback, feedback);
const starterUpgrade = items.find((item) => item.replacementText === "The image shows");
assert(starterUpgrade, "modal should keep a safe structural starter upgrade");
assert(starterUpgrade.targetText === "In the image there is", "structural starter should target the full existing starter");
assert(starterUpgrade.finalPreview === "The image shows a baby sitting and looking at the camera with striped curtains behind her back.", "finalPreview should be the full safe sentence");
assert(!items.some((item) => /^the$/i.test(item.targetText) && item.replacementText === "The image shows"), "modal must not replace only 'the' with a sentence starter");
assert(!starterUpgrade.finalPreview.includes("In The image shows image"), "final preview must not contain the broken duplicate-subject phrase");
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for static polish stage tests")
    def test_upgrade_normalization_rejects_structurally_broken_replacement(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("english_learner_app/static/app.js", "utf8");
const context = {
  document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
  window: { setTimeout() {}, clearTimeout() {} },
  console,
};
vm.createContext(context);
vm.runInContext(code, context);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const answer = "In the image there is a baby.";
const bad = context.normalizeUpgradeSuggestion({ targetText: "the image", replacementText: "The image shows" }, answer);
const good = context.normalizeUpgradeSuggestion({ targetText: "In the image there is", replacementText: "The image shows" }, answer);
assert(bad === null, "partial structural replacements should be rejected");
assert(good && good.finalPreview === "The image shows a baby.", "full starter replacement should pass with a finalPreview");
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


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
        self.assertIn('"starter_hints"', prompt)
        self.assertIn("meaning must explain what the word/phrase means", prompt)
        self.assertIn("examples must be one short natural sentence", prompt)

    def test_analysis_normalizes_starter_hints_with_specific_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        normalized = analyzer._normalize_analysis(
            {
                "scene_summary_natural": "A young child is sitting on a soft bed surface.",
                "scene_summary_simple": "A child is sitting.",
                "objects": [{"name": "young child", "description": "A young child is visible.", "importance": 0.9}],
                "environment": {"setting": "room", "details": ["soft bed surface"]},
                "starter_hints": [
                    {
                        "label": "young child",
                        "type": "phrase",
                        "meaning": "A very small child, usually younger than a teenager. Use this when the person in the image looks very young.",
                        "example": "A young child is sitting on a soft bed surface.",
                    }
                ],
                "quiz_candidates": [
                    {
                        "quiz_type": "recognition",
                        "prompt": "Who is visible?",
                        "answer": "young child",
                        "distractors": ["car", "tree", "road"],
                        "explanation": "The image shows a child.",
                    }
                ],
            },
            difficulty_band="beginner",
        )

        self.assertEqual("young child", normalized["starter_hints"][0]["label"])
        self.assertEqual("phrase", normalized["starter_hints"][0]["type"])
        self.assertIn("looks very young", normalized["starter_hints"][0]["meaning"])
        self.assertEqual("A young child is sitting on a soft bed surface.", normalized["starter_hints"][0]["example"])

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
            attempt_index=2,
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

    def test_first_feedback_prompt_requires_covered_only_enhancement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        prompt = analyzer._build_explanation_feedback_prompt(
            learner_text="There is a road and buildings.",
            original_text="There is a road and buildings.",
            analysis={"natural_explanation": "A road has buildings, trees, vehicles, and shade."},
            learner_level="beginner",
            attempt_index=1,
        )

        self.assertIn("FIRST ATTEMPT FEEDBACK MODE", prompt)
        self.assertIn("enhance ONLY what the learner covered", prompt)
        self.assertIn("Do not add major missing details yet", prompt)
        self.assertIn("initialAttemptFeedback", prompt)
        self.assertIn("meaningful improvement cards", prompt)
        self.assertIn("inlineImprovements must be an empty array", prompt)
        self.assertIn("suggestedText must be a complete safe sentence segment", prompt)

    def test_initial_attempt_feedback_replaces_full_answer_with_covered_enhancement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        feedback = {
            "coverage": {
                "imageParts": [
                    {"name": "road", "covered": True, "coverageStatus": "covered"},
                    {"name": "buildings", "covered": True, "coverageStatus": "covered"},
                    {"name": "trees", "covered": False, "coverageStatus": "missing"},
                    {"name": "motorcycle", "covered": False, "coverageStatus": "missing"},
                ],
                "missingMajorParts": ["trees", "motorcycle"],
            },
            "better_version": "The image shows a road, buildings, trees, and a motorcycle.",
            "missing_details": ["trees", "motorcycle"],
        }
        analyzer._attach_initial_attempt_feedback(
            feedback,
            payload={
                "initialAttemptFeedback": {
                    "acknowledgement": "Nice start — you described the road and buildings.",
                    "coveredEnhancement": "The image shows a quiet urban road lined with tall buildings.",
                    "improvements": [
                        {
                            "id": "natural-1",
                            "category": "natural_phrasing",
                            "title": "More natural opening",
                            "currentText": "There is a road and buildings.",
                            "suggestedText": "The image shows a road with buildings nearby.",
                            "whyItHelps": "This sounds more natural for describing an image.",
                            "example": "The image shows a road with buildings nearby.",
                            "xpReward": 10,
                        }
                    ],
                    "reusableLanguageFromEnhancement": {
                        "nouns": ["road", "buildings"],
                        "phrases": ["lined with tall buildings"],
                    },
                    "missingVisualAreas": ["trees", "motorcycle"],
                }
            },
            learner_text="There is a road and buildings.",
            analysis={},
        )

        initial = feedback["initial_attempt_feedback"]
        self.assertEqual(
            "The image shows a quiet urban road lined with tall buildings.",
            initial["covered_enhancement"],
        )
        self.assertEqual(initial["covered_enhancement"], feedback["better_version"])
        self.assertEqual("natural_phrasing", initial["improvements"][0]["category"])
        self.assertEqual("The image shows a road with buildings nearby.", initial["improvements"][0]["suggestedText"])
        self.assertIn("road", initial["reusable_language"]["nouns"])
        self.assertEqual(["trees", "motorcycle"], initial["missing_visual_areas"])

    def test_initial_attempt_feedback_accepts_new_articulation_enhancement_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True):
                config = AppConfig.from_env(base_dir=Path(temp_dir))

        analyzer = AIAnalyzer(config)
        feedback = {
            "coverage": {
                "imageParts": [
                    {"name": "building", "covered": True, "coverageStatus": "covered"},
                    {"name": "vines", "covered": True, "coverageStatus": "covered"},
                    {"name": "surrounding greenery", "covered": False, "coverageStatus": "missing"},
                ],
                "missingMajorParts": ["surrounding greenery"],
            },
        }
        analyzer._attach_initial_attempt_feedback(
            feedback,
            payload={
                "initialAttemptFeedback": {
                    "enhancement": {
                        "hasImprovements": True,
                        "improvedPreview": "The image shows a building covered with climbing vines attached to the wall.",
                        "upgrades": [
                            {
                                "id": "u1",
                                "category": "better descriptive wording",
                                "targetText": "building with vines",
                                "replacementText": "building covered with climbing vines",
                                "reason": "This describes the same building and vines more clearly.",
                                "example": "The building is covered with climbing vines.",
                                "finalPreview": "The image shows a building covered with climbing vines attached with the wall.",
                            },
                            {
                                "id": "u2",
                                "category": "preposition correction",
                                "targetText": "attached with",
                                "replacementText": "attached to",
                                "reason": "This uses the natural preposition.",
                                "example": "The vines are attached to the wall.",
                                "finalPreview": "The image shows a building with vines attached to the wall.",
                            },
                        ],
                    }
                }
            },
            learner_text="The image shows a building with vines attached with the wall.",
            analysis={},
        )

        initial = feedback["initial_attempt_feedback"]
        self.assertTrue(initial["has_improvements"])
        self.assertEqual(
            "The image shows a building covered with climbing vines attached to the wall.",
            initial["enhancement"]["improvedPreview"],
        )
        self.assertEqual("building with vines", initial["upgrades"][0]["targetText"])
        self.assertEqual("building covered with climbing vines", initial["improvements"][0]["suggestedText"])
        self.assertEqual("visual_clarity", initial["improvements"][0]["category"])
        self.assertEqual("attached to", initial["enhancement"]["upgrades"][1]["replacementText"])
        self.assertNotIn("surrounding greenery", initial["improved_preview"])

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
