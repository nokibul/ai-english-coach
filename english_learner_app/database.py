from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

from .learning import canonical_level
from .progress import improvement_percent
from .utils import from_iso, normalize_answer, to_iso


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
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
);

CREATE TABLE IF NOT EXISTS otp_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL,
    purpose TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    image_name TEXT NOT NULL,
    image_path TEXT NOT NULL,
    title TEXT NOT NULL,
    difficulty_band TEXT NOT NULL,
    simple_explanation TEXT NOT NULL DEFAULT '',
    natural_explanation TEXT NOT NULL DEFAULT '',
    narrative_text TEXT NOT NULL DEFAULT '',
    highlighted_html TEXT NOT NULL DEFAULT '',
    summary_json TEXT NOT NULL DEFAULT '{}',
    raw_analysis_json TEXT NOT NULL DEFAULT '{}',
    source_mode TEXT NOT NULL DEFAULT 'local',
    mastery_percent REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_vocabulary_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id INTEGER NOT NULL REFERENCES analysis_sessions(id) ON DELETE CASCADE,
    word TEXT NOT NULL,
    part_of_speech TEXT NOT NULL DEFAULT '',
    meaning_simple TEXT NOT NULL,
    example TEXT NOT NULL DEFAULT '',
    examples_json TEXT NOT NULL DEFAULT '[]',
    frequency_priority TEXT NOT NULL DEFAULT 'high',
    mastery REAL NOT NULL DEFAULT 0.0,
    correct_count INTEGER NOT NULL DEFAULT 0,
    wrong_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_phrase_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id INTEGER NOT NULL REFERENCES analysis_sessions(id) ON DELETE CASCADE,
    phrase TEXT NOT NULL,
    meaning_simple TEXT NOT NULL,
    example TEXT NOT NULL DEFAULT '',
    examples_json TEXT NOT NULL DEFAULT '[]',
    reusable INTEGER NOT NULL DEFAULT 1,
    collocation_type TEXT NOT NULL DEFAULT 'phrase',
    mastery REAL NOT NULL DEFAULT 0.0,
    correct_count INTEGER NOT NULL DEFAULT 0,
    wrong_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS study_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id INTEGER NOT NULL REFERENCES analysis_sessions(id) ON DELETE CASCADE,
    card_kind TEXT NOT NULL,
    prompt TEXT NOT NULL,
    answer TEXT NOT NULL,
    context_note TEXT NOT NULL,
    source_kind TEXT NOT NULL DEFAULT 'phrase',
    source_text TEXT NOT NULL DEFAULT '',
    acceptable_answers_json TEXT NOT NULL DEFAULT '[]',
    interval_minutes INTEGER NOT NULL DEFAULT 60,
    interval_step INTEGER NOT NULL DEFAULT 0,
    interval_days REAL NOT NULL DEFAULT 0.0416666667,
    ease_factor REAL NOT NULL DEFAULT 2.5,
    repetitions INTEGER NOT NULL DEFAULT 0,
    mastery REAL NOT NULL DEFAULT 0.0,
    difficulty REAL NOT NULL DEFAULT 0.2,
    correct_streak INTEGER NOT NULL DEFAULT 0,
    wrong_streak INTEGER NOT NULL DEFAULT 0,
    review_count INTEGER NOT NULL DEFAULT 0,
    last_quality INTEGER,
    last_result TEXT,
    last_response_ms INTEGER,
    last_confidence INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    due_at TEXT NOT NULL,
    last_reviewed_at TEXT,
    created_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS review_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER NOT NULL REFERENCES study_cards(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    answer_text TEXT NOT NULL,
    quality INTEGER NOT NULL,
    was_correct INTEGER NOT NULL,
    response_ms INTEGER,
    confidence INTEGER,
    feedback_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quiz_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id INTEGER NOT NULL REFERENCES analysis_sessions(id) ON DELETE CASCADE,
    review_card_id INTEGER REFERENCES study_cards(id) ON DELETE SET NULL,
    quiz_type TEXT NOT NULL,
    prompt TEXT NOT NULL,
    answer_mode TEXT NOT NULL DEFAULT 'multiple_choice',
    correct_answer TEXT NOT NULL,
    acceptable_answers_json TEXT NOT NULL DEFAULT '[]',
    distractors_json TEXT NOT NULL DEFAULT '[]',
    explanation TEXT NOT NULL DEFAULT '',
    difficulty REAL NOT NULL DEFAULT 0.3,
    skill_tag TEXT NOT NULL DEFAULT 'core',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    active INTEGER NOT NULL DEFAULT 1,
    times_shown INTEGER NOT NULL DEFAULT 0,
    correct_count INTEGER NOT NULL DEFAULT 0,
    wrong_count INTEGER NOT NULL DEFAULT 0,
    avg_response_ms REAL NOT NULL DEFAULT 0.0,
    last_seen_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quiz_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    run_mode TEXT NOT NULL DEFAULT 'mixed',
    session_id INTEGER REFERENCES analysis_sessions(id) ON DELETE SET NULL,
    challenge_id INTEGER,
    source_label TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    total_questions INTEGER NOT NULL DEFAULT 0,
    correct_count INTEGER NOT NULL DEFAULT 0,
    wrong_count INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS quiz_run_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES quiz_runs(id) ON DELETE CASCADE,
    quiz_item_id INTEGER REFERENCES quiz_items(id) ON DELETE SET NULL,
    card_id INTEGER REFERENCES study_cards(id) ON DELETE SET NULL,
    session_id INTEGER REFERENCES analysis_sessions(id) ON DELETE SET NULL,
    quiz_type TEXT NOT NULL DEFAULT 'recognition',
    answer_mode TEXT NOT NULL DEFAULT 'multiple_choice',
    prompt TEXT NOT NULL,
    context_note TEXT NOT NULL DEFAULT '',
    options_json TEXT NOT NULL DEFAULT '[]',
    acceptable_answers_json TEXT NOT NULL DEFAULT '[]',
    correct_answer TEXT NOT NULL,
    explanation TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    question_index INTEGER NOT NULL,
    selected_answer TEXT,
    was_correct INTEGER,
    score REAL,
    feedback_json TEXT,
    response_ms INTEGER,
    confidence INTEGER,
    answered_at TEXT
);

CREATE TABLE IF NOT EXISTS quiz_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quiz_item_id INTEGER REFERENCES quiz_items(id) ON DELETE SET NULL,
    card_id INTEGER REFERENCES study_cards(id) ON DELETE SET NULL,
    run_id INTEGER REFERENCES quiz_runs(id) ON DELETE SET NULL,
    challenge_id INTEGER,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id INTEGER REFERENCES analysis_sessions(id) ON DELETE SET NULL,
    quiz_type TEXT NOT NULL,
    answer_mode TEXT NOT NULL,
    selected_answer TEXT NOT NULL,
    was_correct INTEGER NOT NULL,
    score REAL NOT NULL DEFAULT 0.0,
    response_ms INTEGER,
    confidence INTEGER,
    feedback_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_challenges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    challenge_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ready',
    total_questions INTEGER NOT NULL DEFAULT 0,
    completed_questions INTEGER NOT NULL DEFAULT 0,
    correct_count INTEGER NOT NULL DEFAULT 0,
    xp_awarded INTEGER NOT NULL DEFAULT 0,
    summary_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(user_id, challenge_date)
);

CREATE TABLE IF NOT EXISTS daily_challenge_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    challenge_id INTEGER NOT NULL REFERENCES daily_challenges(id) ON DELETE CASCADE,
    quiz_item_id INTEGER REFERENCES quiz_items(id) ON DELETE SET NULL,
    question_index INTEGER NOT NULL,
    prompt_snapshot_json TEXT NOT NULL DEFAULT '{}',
    selected_answer TEXT,
    was_correct INTEGER,
    score REAL,
    answered_at TEXT
);

CREATE TABLE IF NOT EXISTS user_progress (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    xp_points INTEGER NOT NULL DEFAULT 0,
    streak_days INTEGER NOT NULL DEFAULT 0,
    learner_level INTEGER NOT NULL DEFAULT 1,
    sessions_completed INTEGER NOT NULL DEFAULT 0,
    quizzes_completed INTEGER NOT NULL DEFAULT 0,
    words_learned INTEGER NOT NULL DEFAULT 0,
    phrases_mastered INTEGER NOT NULL DEFAULT 0,
    combo_streak INTEGER NOT NULL DEFAULT 0,
    best_combo INTEGER NOT NULL DEFAULT 0,
    last_active_on TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_otps_user_purpose ON otp_codes(user_id, purpose, expires_at);
CREATE INDEX IF NOT EXISTS idx_sessions_hash ON auth_sessions(session_token_hash);
CREATE INDEX IF NOT EXISTS idx_analysis_user_created ON analysis_sessions(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_session_vocab_session ON session_vocabulary_items(session_id, word);
CREATE INDEX IF NOT EXISTS idx_session_phrase_session ON session_phrase_items(session_id, phrase);
CREATE INDEX IF NOT EXISTS idx_cards_user_due ON study_cards(user_id, due_at);
CREATE INDEX IF NOT EXISTS idx_cards_user_session ON study_cards(user_id, session_id);
CREATE INDEX IF NOT EXISTS idx_quiz_items_user_session ON quiz_items(user_id, session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_quiz_items_review_card ON quiz_items(review_card_id);
CREATE INDEX IF NOT EXISTS idx_quiz_runs_user_started ON quiz_runs(user_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_quiz_runs_user_status ON quiz_runs(user_id, status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_quiz_items_run_index ON quiz_run_items(run_id, question_index);
CREATE INDEX IF NOT EXISTS idx_quiz_attempts_user_created ON quiz_attempts(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_challenges_user_date ON daily_challenges(user_id, challenge_date DESC);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
            self._run_migrations(conn)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _run_migrations(self, conn: sqlite3.Connection) -> None:
        self._migrate_quiz_run_items_schema(conn)

        column_specs: dict[str, dict[str, str]] = {
            "analysis_sessions": {
                "simple_explanation": "TEXT NOT NULL DEFAULT ''",
                "natural_explanation": "TEXT NOT NULL DEFAULT ''",
                "raw_analysis_json": "TEXT NOT NULL DEFAULT '{}'",
                "mastery_percent": "REAL NOT NULL DEFAULT 0.0",
            },
            "session_vocabulary_items": {
                "examples_json": "TEXT NOT NULL DEFAULT '[]'",
            },
            "session_phrase_items": {
                "examples_json": "TEXT NOT NULL DEFAULT '[]'",
            },
            "study_cards": {
                "source_kind": "TEXT NOT NULL DEFAULT 'phrase'",
                "source_text": "TEXT NOT NULL DEFAULT ''",
                "acceptable_answers_json": "TEXT NOT NULL DEFAULT '[]'",
                "interval_minutes": "INTEGER NOT NULL DEFAULT 60",
                "interval_step": "INTEGER NOT NULL DEFAULT 0",
                "mastery": "REAL NOT NULL DEFAULT 0.0",
                "difficulty": "REAL NOT NULL DEFAULT 0.2",
                "correct_streak": "INTEGER NOT NULL DEFAULT 0",
                "wrong_streak": "INTEGER NOT NULL DEFAULT 0",
                "review_count": "INTEGER NOT NULL DEFAULT 0",
                "last_quality": "INTEGER",
                "last_result": "TEXT",
                "last_response_ms": "INTEGER",
                "last_confidence": "INTEGER",
                "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
            },
            "review_attempts": {
                "response_ms": "INTEGER",
                "confidence": "INTEGER",
                "feedback_json": "TEXT NOT NULL DEFAULT '{}'",
            },
            "quiz_runs": {
                "run_mode": "TEXT NOT NULL DEFAULT 'mixed'",
                "session_id": "INTEGER REFERENCES analysis_sessions(id) ON DELETE SET NULL",
                "challenge_id": "INTEGER",
                "source_label": "TEXT NOT NULL DEFAULT ''",
            },
            "quiz_run_items": {
                "quiz_item_id": "INTEGER REFERENCES quiz_items(id) ON DELETE SET NULL",
                "session_id": "INTEGER REFERENCES analysis_sessions(id) ON DELETE SET NULL",
                "quiz_type": "TEXT NOT NULL DEFAULT 'recognition'",
                "answer_mode": "TEXT NOT NULL DEFAULT 'multiple_choice'",
                "acceptable_answers_json": "TEXT NOT NULL DEFAULT '[]'",
                "explanation": "TEXT NOT NULL DEFAULT ''",
                "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
                "score": "REAL",
                "feedback_json": "TEXT",
                "response_ms": "INTEGER",
                "confidence": "INTEGER",
            },
            "user_progress": {
                "combo_streak": "INTEGER NOT NULL DEFAULT 0",
                "best_combo": "INTEGER NOT NULL DEFAULT 0",
            },
        }

        for table_name, table_columns in column_specs.items():
            for column_name, definition in table_columns.items():
                self._ensure_column(conn, table_name, column_name, definition)

        conn.execute(
            """
            UPDATE users
            SET difficulty_band = CASE difficulty_band
                WHEN 'easy' THEN 'beginner'
                WHEN 'hard' THEN 'developing'
                WHEN 'extremely hard' THEN 'advancing'
                ELSE difficulty_band
            END
            """
        )
        conn.execute(
            """
            UPDATE analysis_sessions
            SET difficulty_band = CASE difficulty_band
                WHEN 'easy' THEN 'beginner'
                WHEN 'hard' THEN 'developing'
                WHEN 'extremely hard' THEN 'advancing'
                ELSE difficulty_band
            END
            """
        )
        conn.execute(
            """
            UPDATE analysis_sessions
            SET natural_explanation = CASE
                WHEN COALESCE(natural_explanation, '') = '' THEN narrative_text
                ELSE natural_explanation
            END
            """
        )
        conn.execute(
            """
            UPDATE analysis_sessions
            SET simple_explanation = CASE
                WHEN COALESCE(simple_explanation, '') = '' THEN natural_explanation
                ELSE simple_explanation
            END
            """
        )
        conn.execute(
            """
            UPDATE study_cards
            SET source_text = CASE
                WHEN COALESCE(source_text, '') = '' THEN answer
                ELSE source_text
            END
            """
        )
        conn.execute(
            """
            UPDATE study_cards
            SET interval_minutes = CASE
                WHEN COALESCE(interval_minutes, 0) <= 0 THEN CAST(ROUND(interval_days * 1440.0) AS INTEGER)
                ELSE interval_minutes
            END
            """
        )

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
        definition: str,
    ) -> None:
        columns = {
            str(row["name"])
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name in columns:
            return
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    def _migrate_quiz_run_items_schema(self, conn: sqlite3.Connection) -> None:
        columns = conn.execute("PRAGMA table_info(quiz_run_items)").fetchall()
        if not columns:
            return

        column_names = {str(row["name"]) for row in columns}
        needs_rebuild = "card_kind" in column_names or any(
            str(row["name"]) == "card_id" and int(row["notnull"]) == 1 for row in columns
        )
        if not needs_rebuild:
            return

        conn.execute("ALTER TABLE quiz_run_items RENAME TO quiz_run_items_legacy")
        conn.execute(
            """
            CREATE TABLE quiz_run_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES quiz_runs(id) ON DELETE CASCADE,
                quiz_item_id INTEGER REFERENCES quiz_items(id) ON DELETE SET NULL,
                card_id INTEGER REFERENCES study_cards(id) ON DELETE SET NULL,
                session_id INTEGER REFERENCES analysis_sessions(id) ON DELETE SET NULL,
                quiz_type TEXT NOT NULL DEFAULT 'recognition',
                answer_mode TEXT NOT NULL DEFAULT 'multiple_choice',
                prompt TEXT NOT NULL,
                context_note TEXT NOT NULL DEFAULT '',
                options_json TEXT NOT NULL DEFAULT '[]',
                acceptable_answers_json TEXT NOT NULL DEFAULT '[]',
                correct_answer TEXT NOT NULL,
                explanation TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                question_index INTEGER NOT NULL,
                selected_answer TEXT,
                was_correct INTEGER,
                score REAL,
                feedback_json TEXT,
                response_ms INTEGER,
                confidence INTEGER,
                answered_at TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO quiz_run_items (
                id, run_id, quiz_item_id, card_id, session_id, quiz_type, answer_mode,
                prompt, context_note, options_json, acceptable_answers_json,
                correct_answer, explanation, metadata_json, question_index,
                selected_answer, was_correct, score, feedback_json, response_ms,
                confidence, answered_at
            )
            SELECT
                id,
                run_id,
                quiz_item_id,
                card_id,
                session_id,
                COALESCE(quiz_type, 'recognition'),
                COALESCE(answer_mode, 'multiple_choice'),
                prompt,
                COALESCE(context_note, ''),
                COALESCE(options_json, '[]'),
                COALESCE(acceptable_answers_json, '[]'),
                correct_answer,
                COALESCE(explanation, ''),
                COALESCE(metadata_json, '{}'),
                question_index,
                selected_answer,
                was_correct,
                score,
                feedback_json,
                response_ms,
                confidence,
                answered_at
            FROM quiz_run_items_legacy
            """
        )
        conn.execute("DROP TABLE quiz_run_items_legacy")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_quiz_items_run_index ON quiz_run_items(run_id, question_index)"
        )

    def _json_load(self, value: str | None, fallback: Any) -> Any:
        if not value:
            return fallback
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback

    def _row_to_quiz_item(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        item = dict(row)
        item["acceptable_answers"] = self._json_load(item.get("acceptable_answers_json"), [])
        item["distractors"] = self._json_load(item.get("distractors_json"), [])
        item["metadata"] = self._json_load(item.get("metadata_json"), {})
        return item

    def _row_to_card(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        card = dict(row)
        card["acceptable_answers"] = self._json_load(card.get("acceptable_answers_json"), [])
        card["metadata"] = self._json_load(card.get("metadata_json"), {})
        return card

    def create_user(
        self,
        *,
        full_name: str,
        phone: str,
        email: str,
        password_hash: str,
        difficulty_band: str,
        fluency_score: int,
        fluency_summary: str,
        assessment: dict[str, Any],
        created_at: str,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO users (
                    full_name, phone, email, password_hash, difficulty_band,
                    fluency_score, fluency_summary, assessment_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    full_name,
                    phone,
                    email,
                    password_hash,
                    canonical_level(difficulty_band),
                    fluency_score,
                    fluency_summary,
                    json.dumps(assessment),
                    created_at,
                ),
            )
            user_id = int(cursor.lastrowid)
            conn.execute(
                """
                INSERT OR IGNORE INTO user_progress (
                    user_id, xp_points, streak_days, learner_level,
                    sessions_completed, quizzes_completed, words_learned,
                    phrases_mastered, combo_streak, best_combo,
                    last_active_on, created_at, updated_at
                ) VALUES (?, 0, 0, 1, 0, 0, 0, 0, 0, 0, NULL, ?, ?)
                """,
                (user_id, created_at, created_at),
            )
        return self.get_user_by_id(user_id)

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return None
        user = dict(row)
        user["difficulty_band"] = canonical_level(user.get("difficulty_band"))
        return user

    def get_user_by_phone(self, phone: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE phone = ?", (phone,)).fetchone()
        if not row:
            return None
        user = dict(row)
        user["difficulty_band"] = canonical_level(user.get("difficulty_band"))
        return user

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not row:
            return None
        user = dict(row)
        user["difficulty_band"] = canonical_level(user.get("difficulty_band"))
        return user

    def set_user_verified(self, user_id: int) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE users SET is_verified = 1 WHERE id = ?", (user_id,))

    def store_otp(
        self,
        *,
        user_id: int,
        code_hash: str,
        purpose: str,
        expires_at: str,
        created_at: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE otp_codes SET consumed_at = ? WHERE user_id = ? AND purpose = ? AND consumed_at IS NULL",
                (created_at, user_id, purpose),
            )
            conn.execute(
                """
                INSERT INTO otp_codes (user_id, code_hash, purpose, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, code_hash, purpose, expires_at, created_at),
            )

    def get_active_otp(
        self, *, user_id: int, purpose: str, now_iso: str
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM otp_codes
                WHERE user_id = ?
                  AND purpose = ?
                  AND consumed_at IS NULL
                  AND expires_at > ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (user_id, purpose, now_iso),
            ).fetchone()
        return dict(row) if row else None

    def consume_otp(self, otp_id: int, consumed_at: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE otp_codes SET consumed_at = ? WHERE id = ?",
                (consumed_at, otp_id),
            )

    def create_auth_session(
        self, *, user_id: int, session_token_hash: str, expires_at: str, created_at: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO auth_sessions (user_id, session_token_hash, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, session_token_hash, expires_at, created_at),
            )

    def delete_auth_session(self, session_token_hash: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM auth_sessions WHERE session_token_hash = ?",
                (session_token_hash,),
            )

    def get_user_by_session_hash(
        self, *, session_token_hash: str, now_iso: str
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT users.*
                FROM auth_sessions
                JOIN users ON users.id = auth_sessions.user_id
                WHERE auth_sessions.session_token_hash = ?
                  AND auth_sessions.expires_at > ?
                LIMIT 1
                """,
                (session_token_hash, now_iso),
            ).fetchone()
        if not row:
            return None
        user = dict(row)
        user["difficulty_band"] = canonical_level(user.get("difficulty_band"))
        return user

    def create_analysis_session(
        self,
        *,
        user_id: int,
        image_name: str,
        image_path: str,
        title: str,
        difficulty_band: str,
        simple_explanation: str,
        natural_explanation: str,
        highlighted_html: str,
        summary: dict[str, Any],
        raw_analysis: dict[str, Any],
        source_mode: str,
        created_at: str,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO analysis_sessions (
                    user_id, image_name, image_path, title, difficulty_band,
                    simple_explanation, natural_explanation, narrative_text,
                    highlighted_html, summary_json, raw_analysis_json,
                    source_mode, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    image_name,
                    image_path,
                    title,
                    canonical_level(difficulty_band),
                    simple_explanation,
                    natural_explanation,
                    natural_explanation,
                    highlighted_html,
                    json.dumps(summary),
                    json.dumps(raw_analysis),
                    source_mode,
                    created_at,
                ),
            )
            return int(cursor.lastrowid)

    def bulk_create_session_vocabulary_items(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO session_vocabulary_items (
                    user_id, session_id, word, part_of_speech, meaning_simple,
                    example, examples_json, frequency_priority, mastery, correct_count, wrong_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item["user_id"],
                        item["session_id"],
                        item["word"],
                        item["part_of_speech"],
                        item["meaning_simple"],
                        item["example"],
                        json.dumps(item.get("examples", [])),
                        item["frequency_priority"],
                        item["mastery"],
                        item["correct_count"],
                        item["wrong_count"],
                        item["created_at"],
                    )
                    for item in items
                ],
            )

    def bulk_create_session_phrase_items(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO session_phrase_items (
                    user_id, session_id, phrase, meaning_simple, example,
                    examples_json, reusable, collocation_type, mastery, correct_count, wrong_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item["user_id"],
                        item["session_id"],
                        item["phrase"],
                        item["meaning_simple"],
                        item["example"],
                        json.dumps(item.get("examples", [])),
                        item["reusable"],
                        item["collocation_type"],
                        item["mastery"],
                        item["correct_count"],
                        item["wrong_count"],
                        item["created_at"],
                    )
                    for item in items
                ],
            )

    def bulk_create_study_cards(self, cards: list[dict[str, Any]]) -> None:
        if not cards:
            return

        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO study_cards (
                    user_id, session_id, card_kind, prompt, answer, context_note,
                    source_kind, source_text, acceptable_answers_json, interval_minutes,
                    interval_step, interval_days, ease_factor, repetitions, mastery,
                    difficulty, correct_streak, wrong_streak, review_count,
                    metadata_json, due_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        card["user_id"],
                        card["session_id"],
                        card["card_kind"],
                        card["prompt"],
                        card["answer"],
                        card["context_note"],
                        card.get("source_kind", "phrase"),
                        card.get("source_text", card["answer"]),
                        json.dumps(card.get("acceptable_answers", [])),
                        card.get("interval_minutes", 60),
                        card.get("interval_step", 0),
                        card.get("interval_days", 60 / 1440),
                        card.get("ease_factor", 2.5),
                        card.get("repetitions", 0),
                        card.get("mastery", 0.0),
                        card.get("difficulty", 0.2),
                        card.get("correct_streak", 0),
                        card.get("wrong_streak", 0),
                        card.get("review_count", 0),
                        json.dumps(card.get("metadata", {})),
                        card["due_at"],
                        card["created_at"],
                    )
                    for card in cards
                ],
            )

    def get_session_review_card_map(self, *, user_id: int, session_id: int) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, source_text
                FROM study_cards
                WHERE user_id = ? AND session_id = ? AND active = 1
                """,
                (user_id, session_id),
            ).fetchall()
        return {
            normalize_answer(str(row["source_text"])): int(row["id"])
            for row in rows
            if normalize_answer(str(row["source_text"]))
        }

    def bulk_create_quiz_items(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO quiz_items (
                    user_id, session_id, review_card_id, quiz_type, prompt,
                    answer_mode, correct_answer, acceptable_answers_json,
                    distractors_json, explanation, difficulty, skill_tag,
                    metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item["user_id"],
                        item["session_id"],
                        item.get("review_card_id"),
                        item["quiz_type"],
                        item["prompt"],
                        item["answer_mode"],
                        item["correct_answer"],
                        json.dumps(item.get("acceptable_answers", [])),
                        json.dumps(item.get("distractors", [])),
                        item.get("explanation", ""),
                        item.get("difficulty", 0.3),
                        item.get("skill_tag", "core"),
                        json.dumps(item.get("metadata", {})),
                        item["created_at"],
                    )
                    for item in items
                ],
            )

    def list_sessions(self, user_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, image_name, difficulty_band, source_mode, mastery_percent, created_at
                FROM analysis_sessions
                WHERE user_id = ?
                ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
        sessions = [dict(row) for row in rows]
        for session in sessions:
            session["difficulty_band"] = canonical_level(session.get("difficulty_band"))
        return sessions

    def get_session(self, *, user_id: int, session_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM analysis_sessions
                WHERE id = ? AND user_id = ?
                LIMIT 1
                """,
                (session_id, user_id),
            ).fetchone()
        if not row:
            return None
        session = dict(row)
        session["difficulty_band"] = canonical_level(session.get("difficulty_band"))
        return session

    def list_session_vocabulary(
        self, *, user_id: int, session_id: int
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM session_vocabulary_items
                WHERE user_id = ? AND session_id = ?
                ORDER BY CASE frequency_priority
                    WHEN 'high' THEN 0
                    WHEN 'medium' THEN 1
                    ELSE 2
                END, word ASC
                """,
                (user_id, session_id),
            ).fetchall()
        items = [dict(row) for row in rows]
        for item in items:
            item["examples"] = self._json_load(item.get("examples_json"), [])
            if not item["examples"] and item.get("example"):
                item["examples"] = [item["example"]]
        return items

    def list_session_phrases(self, *, user_id: int, session_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM session_phrase_items
                WHERE user_id = ? AND session_id = ?
                ORDER BY reusable DESC, phrase ASC
                """,
                (user_id, session_id),
            ).fetchall()
        items = [dict(row) for row in rows]
        for item in items:
            item["examples"] = self._json_load(item.get("examples_json"), [])
            if not item["examples"] and item.get("example"):
                item["examples"] = [item["example"]]
        return items

    def list_session_quiz_items(
        self, *, user_id: int, session_id: int, limit: int = 12
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM quiz_items
                WHERE user_id = ? AND session_id = ? AND active = 1
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (user_id, session_id, limit),
            ).fetchall()
        return [self._row_to_quiz_item(row) for row in rows if row]

    def list_review_cards(
        self, *, user_id: int, now_iso: str, limit: int, manual_mode: bool
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT study_cards.*, analysis_sessions.title AS session_title
                FROM study_cards
                JOIN analysis_sessions ON analysis_sessions.id = study_cards.session_id
                WHERE study_cards.user_id = ?
                  AND study_cards.active = 1
                  AND study_cards.due_at <= ?
                ORDER BY study_cards.wrong_streak DESC,
                         study_cards.mastery ASC,
                         study_cards.due_at ASC
                LIMIT ?
                """,
                (user_id, now_iso, limit),
            ).fetchall()

            if rows or not manual_mode:
                return [self._row_to_card(row) | {"session_title": row["session_title"]} for row in rows]

            fallback_rows = conn.execute(
                """
                SELECT study_cards.*, analysis_sessions.title AS session_title
                FROM study_cards
                JOIN analysis_sessions ON analysis_sessions.id = study_cards.session_id
                WHERE study_cards.user_id = ?
                  AND study_cards.active = 1
                ORDER BY COALESCE(study_cards.last_reviewed_at, study_cards.created_at) ASC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [self._row_to_card(row) | {"session_title": row["session_title"]} for row in fallback_rows]

    def get_card(self, *, user_id: int, card_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT study_cards.*, analysis_sessions.title AS session_title
                FROM study_cards
                JOIN analysis_sessions ON analysis_sessions.id = study_cards.session_id
                WHERE study_cards.id = ?
                  AND study_cards.user_id = ?
                LIMIT 1
                """,
                (card_id, user_id),
            ).fetchone()
        if not row:
            return None
        card = self._row_to_card(row)
        card["session_title"] = row["session_title"]
        return card

    def get_distractor_answers(
        self, *, user_id: int, card_id: int, limit: int
    ) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT answer
                FROM study_cards
                WHERE user_id = ?
                  AND id != ?
                  AND active = 1
                ORDER BY RANDOM()
                LIMIT ?
                """,
                (user_id, card_id, limit),
            ).fetchall()
        return [str(row["answer"]) for row in rows]

    def update_study_card_schedule(
        self,
        *,
        card_id: int,
        interval_days: float,
        ease_factor: float,
        repetitions: int,
        due_at: str,
        last_reviewed_at: str,
        interval_minutes: int | None = None,
        interval_step: int | None = None,
        mastery: float | None = None,
        difficulty: float | None = None,
        correct_streak: int | None = None,
        wrong_streak: int | None = None,
        review_count: int | None = None,
        last_quality: int | None = None,
        last_result: str | None = None,
        last_response_ms: int | None = None,
        last_confidence: int | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE study_cards
                SET interval_days = ?, ease_factor = ?, repetitions = ?,
                    due_at = ?, last_reviewed_at = ?,
                    interval_minutes = COALESCE(?, interval_minutes),
                    interval_step = COALESCE(?, interval_step),
                    mastery = COALESCE(?, mastery),
                    difficulty = COALESCE(?, difficulty),
                    correct_streak = COALESCE(?, correct_streak),
                    wrong_streak = COALESCE(?, wrong_streak),
                    review_count = COALESCE(?, review_count),
                    last_quality = COALESCE(?, last_quality),
                    last_result = COALESCE(?, last_result),
                    last_response_ms = COALESCE(?, last_response_ms),
                    last_confidence = COALESCE(?, last_confidence)
                WHERE id = ?
                """,
                (
                    interval_days,
                    ease_factor,
                    repetitions,
                    due_at,
                    last_reviewed_at,
                    interval_minutes,
                    interval_step,
                    mastery,
                    difficulty,
                    correct_streak,
                    wrong_streak,
                    review_count,
                    last_quality,
                    last_result,
                    last_response_ms,
                    last_confidence,
                    card_id,
                ),
            )

    def record_review_attempt(
        self,
        *,
        card_id: int,
        user_id: int,
        answer_text: str,
        quality: int,
        was_correct: bool,
        created_at: str,
        response_ms: int | None = None,
        confidence: int | None = None,
        feedback: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO review_attempts (
                    card_id, user_id, answer_text, quality, was_correct,
                    response_ms, confidence, feedback_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card_id,
                    user_id,
                    answer_text,
                    quality,
                    1 if was_correct else 0,
                    response_ms,
                    confidence,
                    json.dumps(feedback or {}),
                    created_at,
                ),
            )

    def sync_source_item_progress(
        self,
        *,
        session_id: int,
        source_kind: str,
        source_text: str,
        mastery: float,
        was_correct: bool,
    ) -> None:
        normalized_text = normalize_answer(source_text)
        if not normalized_text:
            return

        with self._connect() as conn:
            if source_kind == "vocabulary":
                conn.execute(
                    """
                    UPDATE session_vocabulary_items
                    SET mastery = MAX(mastery, ?),
                        correct_count = correct_count + ?,
                        wrong_count = wrong_count + ?
                    WHERE session_id = ?
                      AND LOWER(REPLACE(word, ' ', '')) = LOWER(REPLACE(?, ' ', ''))
                    """,
                    (mastery, 1 if was_correct else 0, 0 if was_correct else 1, session_id, source_text),
                )
            elif source_kind in {"phrase", "action"}:
                conn.execute(
                    """
                    UPDATE session_phrase_items
                    SET mastery = MAX(mastery, ?),
                        correct_count = correct_count + ?,
                        wrong_count = wrong_count + ?
                    WHERE session_id = ?
                      AND LOWER(REPLACE(phrase, ' ', '')) = LOWER(REPLACE(?, ' ', ''))
                    """,
                    (mastery, 1 if was_correct else 0, 0 if was_correct else 1, session_id, source_text),
                )
        self.sync_session_mastery(session_id=session_id)

    def sync_session_mastery(self, *, session_id: int) -> None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(AVG(mastery), 0.0) AS mastery_average
                FROM study_cards
                WHERE session_id = ? AND active = 1
                """,
                (session_id,),
            ).fetchone()
            mastery_average = float(row["mastery_average"]) if row else 0.0
            conn.execute(
                "UPDATE analysis_sessions SET mastery_percent = ? WHERE id = ?",
                (round(mastery_average * 100, 2), session_id),
            )

    def list_candidate_quiz_items(
        self,
        *,
        user_id: int,
        session_id: int | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT
                quiz_items.*,
                analysis_sessions.title AS session_title,
                analysis_sessions.created_at AS session_created_at,
                COALESCE(study_cards.mastery, 0.0) AS review_mastery,
                COALESCE(study_cards.wrong_streak, 0) AS review_wrong_streak,
                COALESCE(study_cards.correct_streak, 0) AS review_correct_streak,
                study_cards.due_at AS review_due_at,
                study_cards.source_text AS review_source_text
            FROM quiz_items
            JOIN analysis_sessions ON analysis_sessions.id = quiz_items.session_id
            LEFT JOIN study_cards ON study_cards.id = quiz_items.review_card_id
            WHERE quiz_items.user_id = ?
              AND quiz_items.active = 1
        """
        params: list[Any] = [user_id]
        if session_id is not None:
            query += " AND quiz_items.session_id = ?"
            params.append(session_id)
        query += " ORDER BY analysis_sessions.created_at DESC, quiz_items.id DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_quiz_item(row) for row in rows if row]

    def get_quiz_item(self, *, user_id: int, quiz_item_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT quiz_items.*, analysis_sessions.title AS session_title
                FROM quiz_items
                JOIN analysis_sessions ON analysis_sessions.id = quiz_items.session_id
                WHERE quiz_items.user_id = ? AND quiz_items.id = ?
                LIMIT 1
                """,
                (user_id, quiz_item_id),
            ).fetchone()
        return self._row_to_quiz_item(row)

    def update_quiz_item_stats(
        self,
        *,
        quiz_item_id: int,
        was_correct: bool,
        response_ms: int | None,
        seen_at: str,
    ) -> None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT times_shown, correct_count, wrong_count, avg_response_ms
                FROM quiz_items
                WHERE id = ?
                LIMIT 1
                """,
                (quiz_item_id,),
            ).fetchone()
            if not row:
                return

            times_shown = int(row["times_shown"]) + 1
            correct_count = int(row["correct_count"]) + (1 if was_correct else 0)
            wrong_count = int(row["wrong_count"]) + (0 if was_correct else 1)
            current_avg = float(row["avg_response_ms"] or 0.0)
            if response_ms is None or response_ms <= 0:
                avg_response_ms = current_avg
            elif times_shown == 1:
                avg_response_ms = float(response_ms)
            else:
                avg_response_ms = ((current_avg * (times_shown - 1)) + response_ms) / times_shown

            conn.execute(
                """
                UPDATE quiz_items
                SET times_shown = ?, correct_count = ?, wrong_count = ?,
                    avg_response_ms = ?, last_seen_at = ?
                WHERE id = ?
                """,
                (
                    times_shown,
                    correct_count,
                    wrong_count,
                    avg_response_ms,
                    seen_at,
                    quiz_item_id,
                ),
            )

    def record_quiz_attempt(
        self,
        *,
        quiz_item_id: int | None,
        card_id: int | None,
        run_id: int | None,
        challenge_id: int | None,
        user_id: int,
        session_id: int | None,
        quiz_type: str,
        answer_mode: str,
        selected_answer: str,
        was_correct: bool,
        score: float,
        response_ms: int | None,
        confidence: int | None,
        feedback: dict[str, Any],
        created_at: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO quiz_attempts (
                    quiz_item_id, card_id, run_id, challenge_id, user_id,
                    session_id, quiz_type, answer_mode, selected_answer,
                    was_correct, score, response_ms, confidence, feedback_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    quiz_item_id,
                    card_id,
                    run_id,
                    challenge_id,
                    user_id,
                    session_id,
                    quiz_type,
                    answer_mode,
                    selected_answer,
                    1 if was_correct else 0,
                    score,
                    response_ms,
                    confidence,
                    json.dumps(feedback),
                    created_at,
                ),
            )

    def get_active_quiz_run(
        self, *, user_id: int, run_mode: str | None = None, challenge_id: int | None = None
    ) -> dict[str, Any] | None:
        query = """
            SELECT *
            FROM quiz_runs
            WHERE user_id = ?
              AND status = 'active'
        """
        params: list[Any] = [user_id]
        if run_mode is not None:
            query += " AND run_mode = ?"
            params.append(run_mode)
        if challenge_id is not None:
            query += " AND challenge_id = ?"
            params.append(challenge_id)
        query += " ORDER BY started_at DESC LIMIT 1"

        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        return dict(row) if row else None

    def get_last_completed_quiz_run(
        self, *, user_id: int, run_mode: str | None = None
    ) -> dict[str, Any] | None:
        query = """
            SELECT *
            FROM quiz_runs
            WHERE user_id = ?
              AND status = 'completed'
        """
        params: list[Any] = [user_id]
        if run_mode is not None:
            query += " AND run_mode = ?"
            params.append(run_mode)
        query += " ORDER BY completed_at DESC LIMIT 1"

        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        return dict(row) if row else None

    def get_quiz_run(self, *, user_id: int, run_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM quiz_runs
                WHERE id = ? AND user_id = ?
                LIMIT 1
                """,
                (run_id, user_id),
            ).fetchone()
        return dict(row) if row else None

    def list_quiz_run_items(self, *, run_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM quiz_run_items
                WHERE run_id = ?
                ORDER BY question_index ASC
                """,
                (run_id,),
            ).fetchall()

        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["options"] = self._json_load(item.get("options_json"), [])
            item["acceptable_answers"] = self._json_load(item.get("acceptable_answers_json"), [])
            item["feedback"] = self._json_load(item.get("feedback_json"), {})
            item["metadata"] = self._json_load(item.get("metadata_json"), {})
            items.append(item)
        return items

    def get_quiz_run_item(
        self, *, user_id: int, run_id: int, item_id: int
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT quiz_run_items.*
                FROM quiz_run_items
                JOIN quiz_runs ON quiz_runs.id = quiz_run_items.run_id
                WHERE quiz_run_items.id = ?
                  AND quiz_run_items.run_id = ?
                  AND quiz_runs.user_id = ?
                LIMIT 1
                """,
                (item_id, run_id, user_id),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["options"] = self._json_load(item.get("options_json"), [])
        item["acceptable_answers"] = self._json_load(item.get("acceptable_answers_json"), [])
        item["feedback"] = self._json_load(item.get("feedback_json"), {})
        item["metadata"] = self._json_load(item.get("metadata_json"), {})
        return item

    def create_quiz_run(
        self,
        *,
        user_id: int,
        run_mode: str,
        started_at: str,
        items: list[dict[str, Any]],
        challenge_id: int | None = None,
        session_id: int | None = None,
        source_label: str = "",
    ) -> dict[str, Any]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO quiz_runs (
                    user_id, run_mode, session_id, challenge_id, source_label,
                    status, total_questions, started_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (user_id, run_mode, session_id, challenge_id, source_label, len(items), started_at),
            )
            run_id = int(cursor.lastrowid)
            conn.executemany(
                """
                INSERT INTO quiz_run_items (
                    run_id, quiz_item_id, card_id, session_id, quiz_type, answer_mode,
                    prompt, context_note, options_json, acceptable_answers_json,
                    correct_answer, explanation, metadata_json, question_index
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        item.get("quiz_item_id"),
                        item.get("card_id"),
                        item.get("session_id"),
                        item.get("quiz_type", "recognition"),
                        item.get("answer_mode", "multiple_choice"),
                        item["prompt"],
                        item.get("context_note", ""),
                        json.dumps(item.get("options", [])),
                        json.dumps(item.get("acceptable_answers", [])),
                        item["correct_answer"],
                        item.get("explanation", ""),
                        json.dumps(item.get("metadata", {})),
                        item["question_index"],
                    )
                    for item in items
                ],
            )
        return self.get_quiz_run(user_id=user_id, run_id=run_id)

    def record_quiz_item_answer(
        self,
        *,
        item_id: int,
        selected_answer: str,
        was_correct: bool,
        score: float,
        feedback: dict[str, Any],
        response_ms: int | None,
        confidence: int | None,
        answered_at: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE quiz_run_items
                SET selected_answer = ?, was_correct = ?, score = ?, feedback_json = ?,
                    response_ms = ?, confidence = ?, answered_at = ?
                WHERE id = ?
                """,
                (
                    selected_answer,
                    1 if was_correct else 0,
                    score,
                    json.dumps(feedback),
                    response_ms,
                    confidence,
                    answered_at,
                    item_id,
                ),
            )

    def sync_quiz_run(
        self, *, user_id: int, run_id: int, completed_at: str
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            counts = conn.execute(
                """
                SELECT
                    quiz_runs.total_questions AS total_questions,
                    quiz_runs.completed_at AS existing_completed_at,
                    quiz_runs.challenge_id AS challenge_id,
                    COALESCE(SUM(CASE WHEN quiz_run_items.was_correct IS NOT NULL THEN 1 ELSE 0 END), 0) AS answered_count,
                    COALESCE(SUM(CASE WHEN quiz_run_items.was_correct = 1 THEN 1 ELSE 0 END), 0) AS correct_count,
                    COALESCE(SUM(CASE WHEN quiz_run_items.was_correct = 0 THEN 1 ELSE 0 END), 0) AS wrong_count
                FROM quiz_runs
                LEFT JOIN quiz_run_items ON quiz_run_items.run_id = quiz_runs.id
                WHERE quiz_runs.id = ?
                  AND quiz_runs.user_id = ?
                GROUP BY quiz_runs.id
                """,
                (run_id, user_id),
            ).fetchone()

            if not counts:
                return None

            total_questions = int(counts["total_questions"])
            answered_count = int(counts["answered_count"])
            correct_count = int(counts["correct_count"])
            wrong_count = int(counts["wrong_count"])
            is_completed = total_questions > 0 and answered_count >= total_questions
            final_completed_at = counts["existing_completed_at"] or completed_at if is_completed else None

            conn.execute(
                """
                UPDATE quiz_runs
                SET status = ?, correct_count = ?, wrong_count = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    "completed" if is_completed else "active",
                    correct_count,
                    wrong_count,
                    final_completed_at,
                    run_id,
                ),
            )

            if is_completed and counts["challenge_id"]:
                conn.execute(
                    """
                    UPDATE daily_challenges
                    SET status = 'completed',
                        completed_questions = ?,
                        correct_count = ?,
                        completed_at = COALESCE(completed_at, ?)
                    WHERE id = ?
                    """,
                    (answered_count, correct_count, final_completed_at, counts["challenge_id"]),
                )

        return self.get_quiz_run(user_id=user_id, run_id=run_id)

    def get_quiz_progress(self, *, user_id: int) -> dict[str, int]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN was_correct = 1 THEN 1 ELSE 0 END), 0) AS correct_count,
                    COALESCE(SUM(CASE WHEN was_correct = 0 THEN 1 ELSE 0 END), 0) AS wrong_count,
                    COUNT(DISTINCT CASE WHEN status = 'completed' THEN quiz_runs.id END) AS completed_runs
                FROM quiz_runs
                LEFT JOIN quiz_run_items ON quiz_run_items.run_id = quiz_runs.id
                WHERE quiz_runs.user_id = ?
                """,
                (user_id,),
            ).fetchone()

        correct_count = int(row["correct_count"]) if row else 0
        wrong_count = int(row["wrong_count"]) if row else 0
        return {
            "correct_count": correct_count,
            "wrong_count": wrong_count,
            "answered_count": correct_count + wrong_count,
            "completed_runs": int(row["completed_runs"]) if row else 0,
        }

    def ensure_user_progress(self, *, user_id: int, now_iso: str) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO user_progress (
                    user_id, xp_points, streak_days, learner_level,
                    sessions_completed, quizzes_completed, words_learned,
                    phrases_mastered, combo_streak, best_combo,
                    last_active_on, created_at, updated_at
                ) VALUES (?, 0, 0, 1, 0, 0, 0, 0, 0, 0, NULL, ?, ?)
                """,
                (user_id, now_iso, now_iso),
            )
            row = conn.execute(
                "SELECT * FROM user_progress WHERE user_id = ? LIMIT 1",
                (user_id,),
            ).fetchone()
        return dict(row)

    def save_user_progress(
        self,
        *,
        user_id: int,
        xp_points: int,
        streak_days: int,
        learner_level: int,
        sessions_completed: int,
        quizzes_completed: int,
        words_learned: int,
        phrases_mastered: int,
        combo_streak: int,
        best_combo: int,
        last_active_on: str | None,
        updated_at: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE user_progress
                SET xp_points = ?, streak_days = ?, learner_level = ?,
                    sessions_completed = ?, quizzes_completed = ?,
                    words_learned = ?, phrases_mastered = ?,
                    combo_streak = ?, best_combo = ?, last_active_on = ?,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (
                    xp_points,
                    streak_days,
                    learner_level,
                    sessions_completed,
                    quizzes_completed,
                    words_learned,
                    phrases_mastered,
                    combo_streak,
                    best_combo,
                    last_active_on,
                    updated_at,
                    user_id,
                ),
            )

    def get_user_progress(self, *, user_id: int) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM user_progress WHERE user_id = ? LIMIT 1",
                (user_id,),
            ).fetchone()
        return dict(row) if row else {}

    def get_mastery_counts(self, *, user_id: int) -> dict[str, int]:
        with self._connect() as conn:
            word_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM study_cards
                WHERE user_id = ?
                  AND active = 1
                  AND source_kind = 'vocabulary'
                  AND mastery >= 0.75
                """,
                (user_id,),
            ).fetchone()[0]
            phrase_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM study_cards
                WHERE user_id = ?
                  AND active = 1
                  AND source_kind IN ('phrase', 'action')
                  AND mastery >= 0.75
                """,
                (user_id,),
            ).fetchone()[0]
            total_mastered = conn.execute(
                """
                SELECT COUNT(*)
                FROM study_cards
                WHERE user_id = ?
                  AND active = 1
                  AND mastery >= 0.75
                """,
                (user_id,),
            ).fetchone()[0]
        return {
            "words_learned": int(word_count),
            "phrases_mastered": int(phrase_count),
            "mastered_total": int(total_mastered),
        }

    def get_learning_profile_snapshot(self, *, user_id: int, now_iso: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COALESCE(AVG(CASE WHEN was_correct = 1 THEN 1.0 ELSE 0.0 END), 0.0) AS recent_accuracy,
                    COALESCE(AVG(CASE WHEN was_correct = 1 AND COALESCE(response_ms, 999999) <= 7000 THEN 1.0 ELSE 0.0 END), 0.0) AS fast_correct_ratio
                FROM (
                    SELECT was_correct, response_ms
                    FROM quiz_attempts
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT 30
                )
                """,
                (user_id,),
            ).fetchone()
            weak_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM study_cards
                WHERE user_id = ?
                  AND active = 1
                  AND (wrong_streak >= 2 OR mastery < 0.35)
                """,
                (user_id,),
            ).fetchone()[0]
        return {
            "recent_accuracy": float(row["recent_accuracy"]) if row else 0.0,
            "fast_correct_ratio": float(row["fast_correct_ratio"]) if row else 0.0,
            "weak_item_count": int(weak_count),
        }

    def get_daily_challenge(self, *, user_id: int, challenge_date: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM daily_challenges
                WHERE user_id = ? AND challenge_date = ?
                LIMIT 1
                """,
                (user_id, challenge_date),
            ).fetchone()
        if not row:
            return None
        challenge = dict(row)
        challenge["summary"] = self._json_load(challenge.get("summary_json"), {})
        return challenge

    def create_daily_challenge(
        self,
        *,
        user_id: int,
        challenge_date: str,
        items: list[dict[str, Any]],
        summary: dict[str, Any],
        created_at: str,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO daily_challenges (
                    user_id, challenge_date, status, total_questions,
                    summary_json, created_at
                ) VALUES (?, ?, 'ready', ?, ?, ?)
                """,
                (user_id, challenge_date, len(items), json.dumps(summary), created_at),
            )
            challenge_id = int(cursor.lastrowid)
            conn.executemany(
                """
                INSERT INTO daily_challenge_items (
                    challenge_id, quiz_item_id, question_index, prompt_snapshot_json
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        challenge_id,
                        item.get("quiz_item_id"),
                        item["question_index"],
                        json.dumps(item),
                    )
                    for item in items
                ],
            )
        challenge = self.get_daily_challenge(user_id=user_id, challenge_date=challenge_date)
        if challenge:
            challenge["id"] = challenge_id
        return challenge or {}

    def list_daily_challenge_items(self, *, challenge_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM daily_challenge_items
                WHERE challenge_id = ?
                ORDER BY question_index ASC
                """,
                (challenge_id,),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["snapshot"] = self._json_load(item.get("prompt_snapshot_json"), {})
            items.append(item)
        return items

    def update_daily_challenge(
        self,
        *,
        challenge_id: int,
        status: str,
        completed_questions: int,
        correct_count: int,
        xp_awarded: int | None = None,
        completed_at: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE daily_challenges
                SET status = ?, completed_questions = ?, correct_count = ?,
                    xp_awarded = COALESCE(?, xp_awarded),
                    completed_at = COALESCE(?, completed_at)
                WHERE id = ?
                """,
                (
                    status,
                    completed_questions,
                    correct_count,
                    xp_awarded,
                    completed_at,
                    challenge_id,
                ),
            )

    def get_stats(self, *, user_id: int, now_iso: str) -> dict[str, int]:
        with self._connect() as conn:
            sessions_count = conn.execute(
                "SELECT COUNT(*) FROM analysis_sessions WHERE user_id = ?",
                (user_id,),
            ).fetchone()[0]
            cards_total = conn.execute(
                "SELECT COUNT(*) FROM study_cards WHERE user_id = ? AND active = 1",
                (user_id,),
            ).fetchone()[0]
            due_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM study_cards
                WHERE user_id = ?
                  AND active = 1
                  AND due_at <= ?
                """,
                (user_id, now_iso),
            ).fetchone()[0]
            reviews_completed = conn.execute(
                "SELECT COUNT(*) FROM review_attempts WHERE user_id = ?",
                (user_id,),
            ).fetchone()[0]
            quiz_items_total = conn.execute(
                "SELECT COUNT(*) FROM quiz_items WHERE user_id = ? AND active = 1",
                (user_id,),
            ).fetchone()[0]
            weak_items = conn.execute(
                """
                SELECT COUNT(*)
                FROM study_cards
                WHERE user_id = ?
                  AND active = 1
                  AND (wrong_streak >= 2 OR mastery < 0.35)
                """,
                (user_id,),
            ).fetchone()[0]
        return {
            "sessions_count": int(sessions_count),
            "cards_total": int(cards_total),
            "due_count": int(due_count),
            "reviews_completed": int(reviews_completed),
            "quiz_items_total": int(quiz_items_total),
            "weak_items": int(weak_items),
        }

    def get_progress_dashboard(self, *, user_id: int, now_iso: str) -> dict[str, Any]:
        progress = self.get_user_progress(user_id=user_id)
        mastery_counts = self.get_mastery_counts(user_id=user_id)
        stats = self.get_stats(user_id=user_id, now_iso=now_iso)
        quiz_progress = self.get_quiz_progress(user_id=user_id)
        now_dt = from_iso(now_iso)
        current_start = to_iso(now_dt - timedelta(days=7))
        previous_start = to_iso(now_dt - timedelta(days=14))

        with self._connect() as conn:
            weekly_current = conn.execute(
                """
                SELECT
                    COUNT(*) AS attempts_count,
                    COALESCE(AVG(CASE WHEN was_correct = 1 THEN 1.0 ELSE 0.0 END), 0.0) AS accuracy
                FROM quiz_attempts
                WHERE user_id = ?
                  AND created_at >= ?
                """,
                (user_id, current_start),
            ).fetchone()
            weekly_previous = conn.execute(
                """
                SELECT
                    COUNT(*) AS attempts_count,
                    COALESCE(AVG(CASE WHEN was_correct = 1 THEN 1.0 ELSE 0.0 END), 0.0) AS accuracy
                FROM quiz_attempts
                WHERE user_id = ?
                  AND created_at < ?
                  AND created_at >= ?
                """,
                (user_id, current_start, previous_start),
            ).fetchone()
            challenge = conn.execute(
                """
                SELECT *
                FROM daily_challenges
                WHERE user_id = ?
                ORDER BY challenge_date DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
            recent_runs = conn.execute(
                """
                SELECT run_mode, source_label, total_questions, correct_count, wrong_count, completed_at
                FROM quiz_runs
                WHERE user_id = ?
                  AND status = 'completed'
                ORDER BY completed_at DESC
                LIMIT 5
                """,
                (user_id,),
            ).fetchall()
            mastery_row = conn.execute(
                """
                SELECT COALESCE(AVG(mastery), 0.0) AS mastery_average
                FROM study_cards
                WHERE user_id = ?
                  AND active = 1
                """,
                (user_id,),
            ).fetchone()

        current_accuracy = float(weekly_current["accuracy"] or 0.0)
        previous_accuracy = float(weekly_previous["accuracy"] or 0.0)
        challenge_payload = dict(challenge) if challenge else None
        if challenge_payload:
            challenge_payload["summary"] = self._json_load(challenge_payload.get("summary_json"), {})
        mastery_average = float(mastery_row["mastery_average"] or 0.0) if mastery_row else 0.0

        return {
            "xp_points": int(progress.get("xp_points", 0)),
            "learner_level": int(progress.get("learner_level", 1)),
            "streak_days": int(progress.get("streak_days", 0)),
            "sessions_completed": int(progress.get("sessions_completed", 0)),
            "quizzes_completed": int(progress.get("quizzes_completed", 0)),
            "words_learned": mastery_counts["words_learned"],
            "phrases_mastered": mastery_counts["phrases_mastered"],
            "mastered_total": mastery_counts["mastered_total"],
            "combo_streak": int(progress.get("combo_streak", 0)),
            "best_combo": int(progress.get("best_combo", 0)),
            "due_count": stats["due_count"],
            "weak_items": stats["weak_items"],
            "overall_accuracy_percent": (
                round((quiz_progress["correct_count"] / quiz_progress["answered_count"]) * 100)
                if quiz_progress["answered_count"]
                else 0
            ),
            "overall_mastery_percent": round(mastery_average * 100),
            "weekly_summary": {
                "attempts_count": int(weekly_current["attempts_count"] or 0),
                "accuracy_percent": round(current_accuracy * 100),
                "improvement_percent": improvement_percent(current_accuracy, previous_accuracy),
            },
            "recent_runs": [
                {
                    "run_mode": str(row["run_mode"] or "mixed"),
                    "source_label": str(row["source_label"] or ""),
                    "total_questions": int(row["total_questions"] or 0),
                    "correct_count": int(row["correct_count"] or 0),
                    "wrong_count": int(row["wrong_count"] or 0),
                    "completed_at": row["completed_at"],
                }
                for row in recent_runs
            ],
            "daily_challenge": challenge_payload,
        }
