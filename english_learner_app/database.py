from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .learning import canonical_level
from .roadmap import normalize_roadmap_status


def phrase_mastery_state(*, mastery: float, correct_count: int = 0) -> str:
    mastery = float(mastery or 0.0)
    correct_count = int(correct_count or 0)
    if mastery >= 0.85 or correct_count >= 3:
        return "Mastered"
    if mastery >= 0.55 or correct_count >= 2:
        return "Used Correctly"
    if mastery >= 0.2 or correct_count >= 1:
        return "Practiced"
    return "Seen"


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    phone TEXT UNIQUE,
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

CREATE TABLE IF NOT EXISTS reusable_language_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    normalized_value TEXT NOT NULL,
    value TEXT NOT NULL,
    type TEXT NOT NULL,
    meaning TEXT NOT NULL DEFAULT '',
    example_sentence TEXT NOT NULL DEFAULT '',
    difficulty_level INTEGER NOT NULL DEFAULT 1,
    usefulness_score INTEGER NOT NULL DEFAULT 0,
    transferability_score INTEGER NOT NULL DEFAULT 0,
    roadmap_skill_key TEXT NOT NULL DEFAULT '',
    mastery_score REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT '',
    exposure_count INTEGER NOT NULL DEFAULT 0,
    correct_count INTEGER NOT NULL DEFAULT 0,
    wrong_count INTEGER NOT NULL DEFAULT 0,
    last_answered_at TEXT,
    recently_answered_wrong INTEGER NOT NULL DEFAULT 0,
    next_review_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, normalized_value, type)
);

CREATE TABLE IF NOT EXISTS roadmap_skill_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    skill_key TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    mastered_asset_count INTEGER NOT NULL DEFAULT 0,
    total_asset_count INTEGER NOT NULL DEFAULT 0,
    new_asset_count INTEGER NOT NULL DEFAULT 0,
    weak_asset_count INTEGER NOT NULL DEFAULT 0,
    due_review_count INTEGER NOT NULL DEFAULT 0,
    average_mastery_score REAL NOT NULL DEFAULT 0.0,
    last_practiced_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, skill_key)
);

CREATE TABLE IF NOT EXISTS session_reusable_language_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id INTEGER NOT NULL REFERENCES analysis_sessions(id) ON DELETE CASCADE,
    asset_id INTEGER NOT NULL REFERENCES reusable_language_assets(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    original_source_text TEXT NOT NULL DEFAULT '',
    image_url TEXT NOT NULL DEFAULT '',
    roadmap_applied_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, session_id, asset_id, source)
);

CREATE TABLE IF NOT EXISTS quiz_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id INTEGER NOT NULL REFERENCES analysis_sessions(id) ON DELETE CASCADE,
    language_asset_ids_json TEXT NOT NULL DEFAULT '[]',
    type TEXT NOT NULL,
    question_text TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL DEFAULT '',
    correct_answer TEXT NOT NULL DEFAULT '',
    options_json TEXT NOT NULL DEFAULT '[]',
    word_bank_json TEXT NOT NULL DEFAULT '[]',
    explanation TEXT NOT NULL DEFAULT '',
    difficulty_level INTEGER NOT NULL DEFAULT 1,
    expected_keywords_json TEXT NOT NULL DEFAULT '[]',
    used_in_immediate_quiz INTEGER NOT NULL DEFAULT 0,
    last_shown_at TEXT,
    times_shown INTEGER NOT NULL DEFAULT 0,
    correct_count INTEGER NOT NULL DEFAULT 0,
    wrong_count INTEGER NOT NULL DEFAULT 0,
    question_signature TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, session_id, question_signature)
);

CREATE TABLE IF NOT EXISTS quiz_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id INTEGER NOT NULL REFERENCES analysis_sessions(id) ON DELETE CASCADE,
    quiz_question_id INTEGER NOT NULL REFERENCES quiz_questions(id) ON DELETE CASCADE,
    quiz_type TEXT NOT NULL DEFAULT '',
    language_asset_ids_json TEXT NOT NULL DEFAULT '[]',
    mode TEXT NOT NULL,
    answer_mode TEXT NOT NULL DEFAULT '',
    selected_answer TEXT NOT NULL DEFAULT '',
    answer TEXT NOT NULL DEFAULT '',
    is_correct INTEGER NOT NULL DEFAULT 0,
    score REAL NOT NULL DEFAULT 0.0,
    xp_earned INTEGER NOT NULL DEFAULT 0,
    expected_keywords_json TEXT NOT NULL DEFAULT '[]',
    matched_keywords_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS roadmap_mission_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    skill_key TEXT NOT NULL,
    question_ids_json TEXT NOT NULL DEFAULT '[]',
    total_questions INTEGER NOT NULL DEFAULT 0,
    correct_count INTEGER NOT NULL DEFAULT 0,
    wrong_count INTEGER NOT NULL DEFAULT 0,
    xp_earned INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'started',
    started_at TEXT NOT NULL,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS describe_again_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id INTEGER NOT NULL REFERENCES analysis_sessions(id) ON DELETE CASCADE,
    selected_asset_ids_json TEXT NOT NULL DEFAULT '[]',
    description TEXT NOT NULL DEFAULT '',
    used_asset_ids_json TEXT NOT NULL DEFAULT '[]',
    missing_asset_ids_json TEXT NOT NULL DEFAULT '[]',
    score INTEGER NOT NULL DEFAULT 0,
    feedback TEXT NOT NULL DEFAULT '',
    improved_description TEXT NOT NULL DEFAULT '',
    xp_earned INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_progress (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    xp_points INTEGER NOT NULL DEFAULT 0,
    streak_days INTEGER NOT NULL DEFAULT 0,
    learner_level INTEGER NOT NULL DEFAULT 1,
    sessions_completed INTEGER NOT NULL DEFAULT 0,
    words_learned INTEGER NOT NULL DEFAULT 0,
    phrases_mastered INTEGER NOT NULL DEFAULT 0,
    last_active_on TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_otps_user_purpose ON otp_codes(user_id, purpose, expires_at);
CREATE INDEX IF NOT EXISTS idx_sessions_hash ON auth_sessions(session_token_hash);
CREATE INDEX IF NOT EXISTS idx_analysis_user_created ON analysis_sessions(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_session_vocab_session ON session_vocabulary_items(session_id, word);
CREATE INDEX IF NOT EXISTS idx_session_phrase_session ON session_phrase_items(session_id, phrase);
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
        self._migrate_users_phone_optional(conn)
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
            "reusable_language_assets": {
                "roadmap_skill_key": "TEXT NOT NULL DEFAULT ''",
                "mastery_score": "REAL NOT NULL DEFAULT 0.0",
                "status": "TEXT NOT NULL DEFAULT ''",
                "exposure_count": "INTEGER NOT NULL DEFAULT 0",
                "correct_count": "INTEGER NOT NULL DEFAULT 0",
                "wrong_count": "INTEGER NOT NULL DEFAULT 0",
                "last_answered_at": "TEXT",
                "recently_answered_wrong": "INTEGER NOT NULL DEFAULT 0",
                "next_review_at": "TEXT",
            },
            "session_reusable_language_assets": {
                "roadmap_applied_at": "TEXT",
            },
            "quiz_attempts": {
                "quiz_question_id": "INTEGER NOT NULL DEFAULT 0",
                "quiz_type": "TEXT NOT NULL DEFAULT ''",
                "language_asset_ids_json": "TEXT NOT NULL DEFAULT '[]'",
                "mode": "TEXT NOT NULL DEFAULT ''",
                "answer_mode": "TEXT NOT NULL DEFAULT ''",
                "selected_answer": "TEXT NOT NULL DEFAULT ''",
                "answer": "TEXT NOT NULL DEFAULT ''",
                "is_correct": "INTEGER NOT NULL DEFAULT 0",
                "score": "REAL NOT NULL DEFAULT 0.0",
                "xp_earned": "INTEGER NOT NULL DEFAULT 0",
                "expected_keywords_json": "TEXT NOT NULL DEFAULT '[]'",
                "matched_keywords_json": "TEXT NOT NULL DEFAULT '[]'",
                "created_at": "TEXT NOT NULL DEFAULT ''",
            },
            "roadmap_mission_attempts": {
                "question_ids_json": "TEXT NOT NULL DEFAULT '[]'",
                "total_questions": "INTEGER NOT NULL DEFAULT 0",
                "correct_count": "INTEGER NOT NULL DEFAULT 0",
                "wrong_count": "INTEGER NOT NULL DEFAULT 0",
                "xp_earned": "INTEGER NOT NULL DEFAULT 0",
                "status": "TEXT NOT NULL DEFAULT 'started'",
                "started_at": "TEXT NOT NULL DEFAULT ''",
                "completed_at": "TEXT",
                "created_at": "TEXT NOT NULL DEFAULT ''",
                "updated_at": "TEXT NOT NULL DEFAULT ''",
            },
            "describe_again_attempts": {
                "selected_asset_ids_json": "TEXT NOT NULL DEFAULT '[]'",
                "description": "TEXT NOT NULL DEFAULT ''",
                "used_asset_ids_json": "TEXT NOT NULL DEFAULT '[]'",
                "missing_asset_ids_json": "TEXT NOT NULL DEFAULT '[]'",
                "score": "INTEGER NOT NULL DEFAULT 0",
                "feedback": "TEXT NOT NULL DEFAULT ''",
                "improved_description": "TEXT NOT NULL DEFAULT ''",
                "xp_earned": "INTEGER NOT NULL DEFAULT 0",
                "created_at": "TEXT NOT NULL DEFAULT ''",
            },
        }

        for table_name, table_columns in column_specs.items():
            for column_name, definition in table_columns.items():
                self._ensure_column(conn, table_name, column_name, definition)

        index_specs = [
            (
                "idx_quiz_attempts_question",
                "quiz_attempts",
                ["user_id", "session_id", "quiz_question_id", "created_at"],
                "user_id, session_id, quiz_question_id, created_at DESC",
            ),
            (
                "idx_reusable_assets_user",
                "reusable_language_assets",
                ["user_id", "normalized_value", "type"],
                "user_id, normalized_value, type",
            ),
            (
                "idx_reusable_assets_roadmap_skill",
                "reusable_language_assets",
                ["user_id", "roadmap_skill_key"],
                "user_id, roadmap_skill_key",
            ),
            (
                "idx_reusable_assets_next_review",
                "reusable_language_assets",
                ["user_id", "next_review_at"],
                "user_id, next_review_at",
            ),
            (
                "idx_session_reusable_assets_session",
                "session_reusable_language_assets",
                ["session_id", "asset_id"],
                "session_id, asset_id",
            ),
            (
                "idx_quiz_questions_session",
                "quiz_questions",
                ["user_id", "session_id", "type"],
                "user_id, session_id, type",
            ),
            (
                "idx_roadmap_progress_user",
                "roadmap_skill_progress",
                ["user_id"],
                "user_id",
            ),
            (
                "idx_roadmap_progress_skill",
                "roadmap_skill_progress",
                ["user_id", "skill_key"],
                "user_id, skill_key",
            ),
            (
                "idx_roadmap_missions_user_skill",
                "roadmap_mission_attempts",
                ["user_id", "skill_key", "created_at"],
                "user_id, skill_key, created_at DESC",
            ),
            (
                "idx_describe_again_attempts_user_session",
                "describe_again_attempts",
                ["user_id", "session_id", "created_at"],
                "user_id, session_id, created_at DESC",
            ),
        ]
        for index_name, table_name, columns, expression in index_specs:
            self._ensure_index(conn, index_name, table_name, columns, expression)

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

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
        definition: str,
    ) -> None:
        columns = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
        if column_name not in columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    def _ensure_index(
        self,
        conn: sqlite3.Connection,
        index_name: str,
        table_name: str,
        columns: list[str],
        expression: str,
    ) -> None:
        existing_columns = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
        if not existing_columns or any(column not in existing_columns for column in columns):
            return
        conn.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name}({expression})")

    def _migrate_users_phone_optional(self, conn: sqlite3.Connection) -> None:
        columns = conn.execute("PRAGMA table_info(users)").fetchall()
        if not columns:
            return
        phone_column = next((row for row in columns if str(row["name"]) == "phone"), None)
        if not phone_column or int(phone_column["notnull"]) == 0:
            return

        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("PRAGMA legacy_alter_table = ON")
        conn.execute("ALTER TABLE users RENAME TO users_legacy")
        conn.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                phone TEXT UNIQUE,
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
                id, full_name, phone, email, password_hash, difficulty_band,
                fluency_score, fluency_summary, assessment_json, is_verified, created_at
            )
            SELECT
                id, full_name, phone, email, password_hash, difficulty_band,
                fluency_score, fluency_summary, assessment_json, is_verified, created_at
            FROM users_legacy
            """
        )
        conn.execute("DROP TABLE users_legacy")
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.execute("PRAGMA foreign_keys = ON")

    def _json_load(self, value: str | None, fallback: Any) -> Any:
        if not value:
            return fallback
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback

    def create_user(
        self,
        *,
        full_name: str,
        phone: str | None,
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
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    full_name,
                    phone or None,
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
                    sessions_completed, words_learned, phrases_mastered,
                    created_at, updated_at
                )
                VALUES (?, 0, 0, 1, 0, 0, 0, ?, ?)
                """,
                (user_id, created_at, created_at),
            )
        user = self.get_user_by_id(user_id)
        if not user:
            raise RuntimeError("User could not be created.")
        return user

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def get_user_by_phone(self, phone: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE phone = ?", (phone,)).fetchone()
        return dict(row) if row else None

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE lower(email) = lower(?)", (email,)).fetchone()
        return dict(row) if row else None

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
                """
                INSERT INTO otp_codes (user_id, code_hash, purpose, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, code_hash, purpose, expires_at, created_at),
            )

    def get_active_otp(self, *, user_id: int, purpose: str, now_iso: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM otp_codes
                WHERE user_id = ? AND purpose = ? AND consumed_at IS NULL AND expires_at >= ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_id, purpose, now_iso),
            ).fetchone()
        return dict(row) if row else None

    def consume_otp(self, otp_id: int, consumed_at: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE otp_codes SET consumed_at = ? WHERE id = ?", (consumed_at, otp_id))

    def create_auth_session(
        self,
        *,
        user_id: int,
        session_token_hash: str,
        expires_at: str,
        created_at: str,
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
            conn.execute("DELETE FROM auth_sessions WHERE session_token_hash = ?", (session_token_hash,))

    def get_user_by_session_hash(self, *, session_token_hash: str, now_iso: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT users.*
                FROM auth_sessions
                JOIN users ON users.id = auth_sessions.user_id
                WHERE auth_sessions.session_token_hash = ?
                  AND auth_sessions.expires_at >= ?
                LIMIT 1
                """,
                (session_token_hash, now_iso),
            ).fetchone()
        return dict(row) if row else None

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
                    highlighted_html, summary_json, raw_analysis_json, source_mode, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    example, examples_json, frequency_priority, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item["user_id"],
                        item["session_id"],
                        item["word"],
                        item.get("part_of_speech", ""),
                        item.get("meaning_simple", ""),
                        item.get("example", ""),
                        json.dumps(item.get("examples", [])),
                        item.get("frequency_priority", "high"),
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
                    examples_json, reusable, collocation_type, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item["user_id"],
                        item["session_id"],
                        item["phrase"],
                        item.get("meaning_simple", ""),
                        item.get("example", ""),
                        json.dumps(item.get("examples", [])),
                        1 if item.get("reusable", True) else 0,
                        item.get("collocation_type", "phrase"),
                        item["created_at"],
                    )
                    for item in items
                ],
            )

    def list_sessions(self, user_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, title, image_name, difficulty_band, source_mode, mastery_percent, created_at
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

    def list_past_sessions(self, user_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    analysis_sessions.id,
                    analysis_sessions.user_id,
                    analysis_sessions.title,
                    analysis_sessions.image_name,
                    analysis_sessions.difficulty_band,
                    analysis_sessions.source_mode,
                    analysis_sessions.mastery_percent,
                    analysis_sessions.created_at,
                    COUNT(DISTINCT session_reusable_language_assets.asset_id) AS phrases_learned_count,
                    SUM(
                        CASE
                            WHEN reusable_language_assets.status = 'new'
                              OR reusable_language_assets.mastery_score <= 0.25 THEN 1
                            ELSE 0
                        END
                    ) AS new_asset_count,
                    SUM(
                        CASE
                            WHEN reusable_language_assets.status = 'weak'
                              OR reusable_language_assets.wrong_count > reusable_language_assets.correct_count
                              OR reusable_language_assets.recently_answered_wrong = 1 THEN 1
                            ELSE 0
                        END
                    ) AS weak_asset_count,
                    AVG(reusable_language_assets.mastery_score) AS average_mastery_score
                FROM analysis_sessions
                LEFT JOIN session_reusable_language_assets
                  ON session_reusable_language_assets.session_id = analysis_sessions.id
                 AND session_reusable_language_assets.user_id = analysis_sessions.user_id
                LEFT JOIN reusable_language_assets
                  ON reusable_language_assets.id = session_reusable_language_assets.asset_id
                 AND reusable_language_assets.user_id = analysis_sessions.user_id
                WHERE analysis_sessions.user_id = ?
                GROUP BY analysis_sessions.id
                ORDER BY analysis_sessions.created_at DESC
                """,
                (user_id,),
            ).fetchall()
        sessions = [dict(row) for row in rows]
        for session in sessions:
            session["difficulty_band"] = canonical_level(session.get("difficulty_band"))
        return sessions

    def session_learning_summary(self, *, user_id: int, session_id: int) -> dict[str, Any]:
        with self._connect() as conn:
            phrase_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM session_reusable_language_assets
                WHERE user_id = ? AND session_id = ?
                """,
                (user_id, session_id),
            ).fetchone()[0]
            quiz_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM quiz_questions
                WHERE user_id = ? AND session_id = ?
                """,
                (user_id, session_id),
            ).fetchone()[0]
            due_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM session_reusable_language_assets
                JOIN reusable_language_assets
                  ON reusable_language_assets.id = session_reusable_language_assets.asset_id
                WHERE session_reusable_language_assets.user_id = ?
                  AND session_reusable_language_assets.session_id = ?
                  AND (
                    reusable_language_assets.mastery_score < 0.55
                    OR reusable_language_assets.recently_answered_wrong = 1
                    OR reusable_language_assets.next_review_at IS NULL
                    OR reusable_language_assets.next_review_at <= strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now')
                  )
                """,
                (user_id, session_id),
            ).fetchone()[0]
            mastery = conn.execute(
                """
                SELECT AVG(reusable_language_assets.mastery_score)
                FROM session_reusable_language_assets
                JOIN reusable_language_assets
                  ON reusable_language_assets.id = session_reusable_language_assets.asset_id
                WHERE session_reusable_language_assets.user_id = ?
                  AND session_reusable_language_assets.session_id = ?
                """,
                (user_id, session_id),
            ).fetchone()[0]
            attempts = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) AS correct
                FROM quiz_attempts
                WHERE user_id = ? AND session_id = ?
                """,
                (user_id, session_id),
            ).fetchone()
        total_attempts = int(attempts["total"] or 0)
        correct_attempts = int(attempts["correct"] or 0)
        accuracy_percent = round((correct_attempts / total_attempts) * 100) if total_attempts else 0
        mastery_percent = round(float(mastery or 0.0) * 100)
        return {
            "phrases_learned": int(phrase_count),
            "quiz_questions_available": int(quiz_count),
            "practice_due_count": int(due_count),
            "mastery_percent": mastery_percent,
            "accuracy_percent": accuracy_percent,
            "status": (
                "Practice Due"
                if int(due_count)
                else "Mastered"
                if mastery_percent >= 85 and int(phrase_count)
                else "Completed"
            ),
        }

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

    def get_session_by_id(self, session_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM analysis_sessions
                WHERE id = ?
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        if not row:
            return None
        session = dict(row)
        session["difficulty_band"] = canonical_level(session.get("difficulty_band"))
        return session

    def list_session_vocabulary(self, *, user_id: int, session_id: int) -> list[dict[str, Any]]:
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
            item["mastery_state"] = phrase_mastery_state(
                mastery=float(item.get("mastery") or 0.0),
                correct_count=int(item.get("correct_count") or 0),
            )
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
            item["mastery_state"] = phrase_mastery_state(
                mastery=float(item.get("mastery") or 0.0),
                correct_count=int(item.get("correct_count") or 0),
            )
        return items

    def upsert_reusable_language_assets(
        self,
        *,
        user_id: int,
        session_id: int,
        image_url: str,
        assets: list[dict[str, Any]],
        created_at: str,
    ) -> list[dict[str, Any]]:
        if not assets:
            return []

        stored: list[dict[str, Any]] = []
        with self._connect() as conn:
            for asset in assets:
                normalized_value = str(asset.get("normalizedValue") or asset.get("normalized_value") or "").strip()
                value = str(asset.get("value") or "").strip()
                asset_type = str(asset.get("type") or "").strip()
                if not normalized_value or not value or not asset_type:
                    continue

                existing = conn.execute(
                    """
                    SELECT *
                    FROM reusable_language_assets
                    WHERE user_id = ? AND normalized_value = ? AND type = ?
                    LIMIT 1
                    """,
                    (user_id, normalized_value, asset_type),
                ).fetchone()

                if existing:
                    asset_id = int(existing["id"])
                    roadmap_skill_key = str(
                        existing["roadmap_skill_key"] or asset.get("roadmapSkillKey") or asset.get("roadmap_skill_key") or ""
                    )
                    status = normalize_roadmap_status(existing["status"] or asset.get("status") or "")
                    mastery_score = float(existing["mastery_score"] or 0.0)
                    initial_mastery = float(asset.get("masteryScore") or asset.get("mastery_score") or 0.0)
                    if mastery_score <= 0.0 and initial_mastery > 0.0:
                        mastery_score = max(0.0, min(1.0, initial_mastery))
                    usefulness_score = max(
                        int(existing["usefulness_score"] or 0),
                        int(asset.get("usefulnessScore") or asset.get("usefulness_score") or 0),
                    )
                    transferability_score = max(
                        int(existing["transferability_score"] or 0),
                        int(asset.get("transferabilityScore") or asset.get("transferability_score") or 0),
                    )
                    conn.execute(
                        """
                        UPDATE reusable_language_assets
                        SET
                            value = ?,
                            meaning = CASE WHEN COALESCE(meaning, '') = '' THEN ? ELSE meaning END,
                            example_sentence = CASE
                                WHEN COALESCE(example_sentence, '') = '' THEN ?
                                ELSE example_sentence
                            END,
                            difficulty_level = MIN(difficulty_level, ?),
                            usefulness_score = ?,
                            transferability_score = ?,
                            roadmap_skill_key = ?,
                            mastery_score = ?,
                            status = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            value,
                            str(asset.get("meaning") or ""),
                            str(asset.get("exampleSentence") or asset.get("example_sentence") or ""),
                            int(asset.get("difficultyLevel") or asset.get("difficulty_level") or 1),
                            usefulness_score,
                            transferability_score,
                            roadmap_skill_key,
                            mastery_score,
                            status,
                            created_at,
                            asset_id,
                        ),
                    )
                else:
                    initial_mastery = float(asset.get("masteryScore") or asset.get("mastery_score") or 0.0)
                    cursor = conn.execute(
                        """
                        INSERT INTO reusable_language_assets (
                            user_id, normalized_value, value, type, meaning, example_sentence,
                            difficulty_level, usefulness_score, transferability_score, roadmap_skill_key,
                            mastery_score, status, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            user_id,
                            normalized_value,
                            value,
                            asset_type,
                            str(asset.get("meaning") or ""),
                            str(asset.get("exampleSentence") or asset.get("example_sentence") or ""),
                            int(asset.get("difficultyLevel") or asset.get("difficulty_level") or 1),
                            int(asset.get("usefulnessScore") or asset.get("usefulness_score") or 0),
                            int(asset.get("transferabilityScore") or asset.get("transferability_score") or 0),
                            str(asset.get("roadmapSkillKey") or asset.get("roadmap_skill_key") or ""),
                            max(0.0, min(1.0, initial_mastery)),
                            normalize_roadmap_status(asset.get("status") or ""),
                            created_at,
                            created_at,
                        ),
                    )
                    asset_id = int(cursor.lastrowid)

                conn.execute(
                    """
                    INSERT OR IGNORE INTO session_reusable_language_assets (
                        user_id, session_id, asset_id, source, original_source_text, image_url, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        session_id,
                        asset_id,
                        str(asset.get("source") or ""),
                        str(asset.get("originalSourceText") or asset.get("original_source_text") or ""),
                        image_url,
                        created_at,
                    ),
                )

                row = conn.execute(
                    """
                    SELECT
                        reusable_language_assets.*,
                        reusable_language_assets.created_at AS asset_created_at,
                        session_reusable_language_assets.session_id,
                        session_reusable_language_assets.source,
                        session_reusable_language_assets.original_source_text,
                        session_reusable_language_assets.image_url,
                        session_reusable_language_assets.created_at AS session_asset_created_at,
                        session_reusable_language_assets.roadmap_applied_at
                    FROM reusable_language_assets
                    JOIN session_reusable_language_assets
                      ON session_reusable_language_assets.asset_id = reusable_language_assets.id
                    WHERE reusable_language_assets.id = ?
                      AND session_reusable_language_assets.user_id = ?
                      AND session_reusable_language_assets.session_id = ?
                    LIMIT 1
                    """,
                    (asset_id, user_id, session_id),
                ).fetchone()
                if row:
                    stored.append(dict(row))
        return stored

    def list_session_reusable_language_assets(
        self,
        *,
        user_id: int,
        session_id: int,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    reusable_language_assets.*,
                    reusable_language_assets.created_at AS asset_created_at,
                    session_reusable_language_assets.session_id,
                    session_reusable_language_assets.source,
                    session_reusable_language_assets.original_source_text,
                    session_reusable_language_assets.image_url,
                    session_reusable_language_assets.created_at AS session_asset_created_at,
                    session_reusable_language_assets.roadmap_applied_at
                FROM reusable_language_assets
                JOIN session_reusable_language_assets
                  ON session_reusable_language_assets.asset_id = reusable_language_assets.id
                WHERE session_reusable_language_assets.user_id = ?
                  AND session_reusable_language_assets.session_id = ?
                ORDER BY
                    reusable_language_assets.usefulness_score + reusable_language_assets.transferability_score DESC,
                    reusable_language_assets.value ASC
                """,
                (user_id, session_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_reusable_language_asset_roadmap_defaults(
        self,
        *,
        user_id: int,
        asset_id: int,
        roadmap_skill_key: str,
        status: str,
        mastery_score: float,
        updated_at: str,
    ) -> dict[str, Any] | None:
        roadmap_skill_key = str(roadmap_skill_key or "").strip()
        if not roadmap_skill_key:
            return None
        status = normalize_roadmap_status(status)
        mastery_score = max(0.0, min(1.0, float(mastery_score or 0.0)))
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE reusable_language_assets
                SET
                    roadmap_skill_key = ?,
                    mastery_score = CASE
                        WHEN mastery_score <= 0 THEN ?
                        ELSE mastery_score
                    END,
                    status = CASE
                        WHEN COALESCE(status, '') = '' THEN ?
                        ELSE status
                    END,
                    updated_at = ?
                WHERE user_id = ? AND id = ?
                """,
                (roadmap_skill_key, mastery_score, status, updated_at, user_id, asset_id),
            )
            row = conn.execute(
                """
                SELECT *
                FROM reusable_language_assets
                WHERE user_id = ? AND id = ?
                LIMIT 1
                """,
                (user_id, asset_id),
            ).fetchone()
        return dict(row) if row else None

    def mark_session_reusable_assets_roadmap_applied(
        self,
        *,
        user_id: int,
        session_id: int,
        asset_ids: list[int],
        applied_at: str,
    ) -> None:
        if not asset_ids:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                UPDATE session_reusable_language_assets
                SET roadmap_applied_at = COALESCE(roadmap_applied_at, ?)
                WHERE user_id = ? AND session_id = ? AND asset_id = ?
                """,
                [(applied_at, user_id, session_id, int(asset_id)) for asset_id in asset_ids],
            )

    def recalculate_roadmap_skill_progress(
        self,
        *,
        user_id: int,
        skill_key: str,
        skill_name: str,
        calculated_at: str,
    ) -> dict[str, Any]:
        skill_key = str(skill_key or "").strip()
        if not skill_key:
            raise ValueError("Roadmap skill key is required.")
        with self._connect() as conn:
            stats = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_asset_count,
                    SUM(
                        CASE
                            WHEN status = 'mastered' OR mastery_score >= 0.91 THEN 1
                            ELSE 0
                        END
                    ) AS mastered_asset_count,
                    SUM(CASE WHEN status = 'new' THEN 1 ELSE 0 END) AS new_asset_count,
                    SUM(
                        CASE
                            WHEN status = 'weak' OR wrong_count > correct_count THEN 1
                            ELSE 0
                        END
                    ) AS weak_asset_count,
                    SUM(
                        CASE
                            WHEN next_review_at IS NOT NULL AND next_review_at <= ? THEN 1
                            ELSE 0
                        END
                    ) AS due_review_count,
                    AVG(mastery_score) AS average_mastery_score,
                    MAX(last_answered_at) AS last_practiced_at
                FROM reusable_language_assets
                WHERE user_id = ? AND roadmap_skill_key = ?
                """,
                (calculated_at, user_id, skill_key),
            ).fetchone()
            total_asset_count = int(stats["total_asset_count"] or 0)
            mastered_asset_count = int(stats["mastered_asset_count"] or 0)
            new_asset_count = int(stats["new_asset_count"] or 0)
            weak_asset_count = int(stats["weak_asset_count"] or 0)
            due_review_count = int(stats["due_review_count"] or 0)
            average_mastery_score = float(stats["average_mastery_score"] or 0.0)
            last_practiced_at = stats["last_practiced_at"]
            conn.execute(
                """
                INSERT INTO roadmap_skill_progress (
                    user_id, skill_key, skill_name, mastered_asset_count, total_asset_count,
                    new_asset_count, weak_asset_count, due_review_count, average_mastery_score,
                    last_practiced_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, skill_key) DO UPDATE SET
                    skill_name = excluded.skill_name,
                    mastered_asset_count = excluded.mastered_asset_count,
                    total_asset_count = excluded.total_asset_count,
                    new_asset_count = excluded.new_asset_count,
                    weak_asset_count = excluded.weak_asset_count,
                    due_review_count = excluded.due_review_count,
                    average_mastery_score = excluded.average_mastery_score,
                    last_practiced_at = excluded.last_practiced_at,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    skill_key,
                    skill_name,
                    mastered_asset_count,
                    total_asset_count,
                    new_asset_count,
                    weak_asset_count,
                    due_review_count,
                    average_mastery_score,
                    last_practiced_at,
                    calculated_at,
                    calculated_at,
                ),
            )
            row = conn.execute(
                """
                SELECT *
                FROM roadmap_skill_progress
                WHERE user_id = ? AND skill_key = ?
                LIMIT 1
                """,
                (user_id, skill_key),
            ).fetchone()
        return dict(row) if row else {}

    def list_roadmap_skill_progress(self, *, user_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM roadmap_skill_progress
                WHERE user_id = ?
                ORDER BY skill_name ASC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_roadmap_skill_assets(
        self,
        *,
        user_id: int,
        skill_key: str,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    reusable_language_assets.*,
                    (
                        SELECT session_id
                        FROM session_reusable_language_assets
                        WHERE session_reusable_language_assets.user_id = reusable_language_assets.user_id
                          AND session_reusable_language_assets.asset_id = reusable_language_assets.id
                        ORDER BY created_at ASC, session_id ASC
                        LIMIT 1
                    ) AS source_session_id,
                    (
                        SELECT created_at
                        FROM session_reusable_language_assets
                        WHERE session_reusable_language_assets.user_id = reusable_language_assets.user_id
                          AND session_reusable_language_assets.asset_id = reusable_language_assets.id
                        ORDER BY created_at ASC, session_id ASC
                        LIMIT 1
                    ) AS learned_at,
                    EXISTS (
                        SELECT 1
                        FROM session_reusable_language_assets
                        WHERE session_reusable_language_assets.user_id = reusable_language_assets.user_id
                          AND session_reusable_language_assets.asset_id = reusable_language_assets.id
                          AND (
                            session_reusable_language_assets.source = 'guided_coverage_hint'
                            OR lower(session_reusable_language_assets.original_source_text) LIKE '%level 3%'
                            OR lower(session_reusable_language_assets.original_source_text) LIKE '%support 3%'
                          )
                    ) AS learned_through_support
                FROM reusable_language_assets
                WHERE user_id = ? AND roadmap_skill_key = ?
                ORDER BY mastery_score ASC, next_review_at ASC, created_at ASC
                """,
                (user_id, skill_key),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_daily_review_assets(
        self,
        *,
        user_id: int,
        now_iso: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    reusable_language_assets.*,
                    (
                        SELECT session_id
                        FROM session_reusable_language_assets
                        WHERE session_reusable_language_assets.user_id = reusable_language_assets.user_id
                          AND session_reusable_language_assets.asset_id = reusable_language_assets.id
                        ORDER BY created_at ASC, session_id ASC
                        LIMIT 1
                    ) AS source_session_id,
                    (
                        SELECT created_at
                        FROM session_reusable_language_assets
                        WHERE session_reusable_language_assets.user_id = reusable_language_assets.user_id
                          AND session_reusable_language_assets.asset_id = reusable_language_assets.id
                        ORDER BY created_at ASC, session_id ASC
                        LIMIT 1
                    ) AS learned_at,
                    EXISTS (
                        SELECT 1
                        FROM session_reusable_language_assets
                        WHERE session_reusable_language_assets.user_id = reusable_language_assets.user_id
                          AND session_reusable_language_assets.asset_id = reusable_language_assets.id
                          AND (
                            session_reusable_language_assets.source = 'guided_coverage_hint'
                            OR lower(session_reusable_language_assets.original_source_text) LIKE '%level 3%'
                            OR lower(session_reusable_language_assets.original_source_text) LIKE '%support 3%'
                          )
                    ) AS learned_through_support
                FROM reusable_language_assets
                WHERE user_id = ?
                  AND next_review_at IS NOT NULL
                  AND next_review_at <= ?
                ORDER BY
                    CASE
                        WHEN status = 'weak' THEN 0
                        WHEN recently_answered_wrong = 1 THEN 1
                        WHEN wrong_count > correct_count THEN 2
                        ELSE 3
                    END,
                    mastery_score ASC,
                    next_review_at ASC,
                    last_answered_at ASC,
                    created_at ASC
                LIMIT ?
                """,
                (user_id, now_iso, int(limit or 20)),
            ).fetchall()
        return [dict(row) for row in rows]

    def bulk_upsert_quiz_questions(
        self,
        *,
        user_id: int,
        session_id: int,
        questions: list[dict[str, Any]],
        created_at: str,
    ) -> list[dict[str, Any]]:
        if not questions:
            return []

        stored: list[dict[str, Any]] = []
        with self._connect() as conn:
            for question in questions:
                signature = str(question.get("questionSignature") or question.get("question_signature") or "").strip()
                question_type = str(question.get("type") or "").strip()
                if not signature or not question_type:
                    continue

                conn.execute(
                    """
                    INSERT INTO quiz_questions (
                        user_id, session_id, language_asset_ids_json, type, question_text,
                        prompt, correct_answer, options_json, word_bank_json, explanation,
                        difficulty_level, expected_keywords_json, used_in_immediate_quiz,
                        question_signature, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, session_id, question_signature) DO UPDATE SET
                        language_asset_ids_json = excluded.language_asset_ids_json,
                        question_text = excluded.question_text,
                        prompt = excluded.prompt,
                        correct_answer = excluded.correct_answer,
                        options_json = excluded.options_json,
                        word_bank_json = excluded.word_bank_json,
                        explanation = excluded.explanation,
                        difficulty_level = excluded.difficulty_level,
                        expected_keywords_json = excluded.expected_keywords_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        user_id,
                        session_id,
                        json.dumps([str(item) for item in question.get("languageAssetIds", [])]),
                        question_type,
                        str(question.get("questionText") or ""),
                        str(question.get("prompt") or ""),
                        str(question.get("correctAnswer") or ""),
                        json.dumps(question.get("options") or []),
                        json.dumps(question.get("wordBank") or []),
                        str(question.get("explanation") or ""),
                        int(question.get("difficultyLevel") or 1),
                        json.dumps(question.get("expectedKeywords") or []),
                        1 if question.get("usedInImmediateQuiz") else 0,
                        signature,
                        created_at,
                        created_at,
                    ),
                )
                row = conn.execute(
                    """
                    SELECT *
                    FROM quiz_questions
                    WHERE user_id = ? AND session_id = ? AND question_signature = ?
                    LIMIT 1
                    """,
                    (user_id, session_id, signature),
                ).fetchone()
                if row:
                    stored.append(self._hydrate_quiz_question(dict(row)))
        return stored

    def list_session_quiz_questions(
        self,
        *,
        user_id: int,
        session_id: int,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM quiz_questions
                WHERE user_id = ? AND session_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (user_id, session_id),
            ).fetchall()
        return [self._hydrate_quiz_question(dict(row)) for row in rows]

    def list_quiz_questions_for_language_assets(
        self,
        *,
        user_id: int,
        asset_ids: list[int],
    ) -> list[dict[str, Any]]:
        if not asset_ids:
            return []
        asset_id_strings = {str(int(asset_id)) for asset_id in asset_ids}
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM quiz_questions
                WHERE user_id = ?
                ORDER BY
                    used_in_immediate_quiz ASC,
                    times_shown ASC,
                    last_shown_at IS NOT NULL ASC,
                    created_at ASC,
                    id ASC
                """,
                (user_id,),
            ).fetchall()
        questions: list[dict[str, Any]] = []
        for row in rows:
            question = self._hydrate_quiz_question(dict(row))
            if asset_id_strings & {str(item) for item in question.get("language_asset_ids", [])}:
                questions.append(question)
        return questions

    def mark_quiz_questions_shown(
        self,
        *,
        user_id: int,
        session_id: int,
        question_ids: list[int],
        shown_at: str,
        used_in_immediate_quiz: bool = True,
    ) -> None:
        if not question_ids:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                UPDATE quiz_questions
                SET
                    used_in_immediate_quiz = CASE
                        WHEN ? = 1 THEN 1
                        ELSE used_in_immediate_quiz
                    END,
                    last_shown_at = ?,
                    times_shown = times_shown + 1,
                    updated_at = ?
                WHERE user_id = ? AND session_id = ? AND id = ?
                """,
                [
                    (
                        1 if used_in_immediate_quiz else 0,
                        shown_at,
                        shown_at,
                        user_id,
                        session_id,
                        int(question_id),
                    )
                    for question_id in question_ids
                ],
            )

    def mark_quiz_questions_shown_for_user(
        self,
        *,
        user_id: int,
        question_ids: list[int],
        shown_at: str,
    ) -> None:
        if not question_ids:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                UPDATE quiz_questions
                SET
                    last_shown_at = ?,
                    times_shown = times_shown + 1,
                    updated_at = ?
                WHERE user_id = ? AND id = ?
                """,
                [(shown_at, shown_at, user_id, int(question_id)) for question_id in question_ids],
            )

    def create_roadmap_mission_attempt(
        self,
        *,
        user_id: int,
        skill_key: str,
        question_ids: list[int],
        started_at: str,
    ) -> dict[str, Any]:
        question_ids_json = json.dumps([str(question_id) for question_id in question_ids])
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO roadmap_mission_attempts (
                    user_id, skill_key, question_ids_json, total_questions,
                    correct_count, wrong_count, xp_earned, status,
                    started_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 0, 0, 0, 'started', ?, ?, ?)
                """,
                (
                    user_id,
                    skill_key,
                    question_ids_json,
                    len(question_ids),
                    started_at,
                    started_at,
                    started_at,
                ),
            )
            row = conn.execute(
                """
                SELECT *
                FROM roadmap_mission_attempts
                WHERE id = ?
                LIMIT 1
                """,
                (int(cursor.lastrowid),),
            ).fetchone()
        mission = dict(row) if row else {}
        if mission:
            mission["question_ids"] = self._json_load(mission.get("question_ids_json"), [])
        return mission

    def get_roadmap_mission_attempt(
        self,
        *,
        user_id: int,
        mission_id: int,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM roadmap_mission_attempts
                WHERE user_id = ? AND id = ?
                LIMIT 1
                """,
                (user_id, mission_id),
            ).fetchone()
        if not row:
            return None
        mission = dict(row)
        mission["question_ids"] = self._json_load(mission.get("question_ids_json"), [])
        return mission

    def update_roadmap_mission_after_answer(
        self,
        *,
        user_id: int,
        mission_id: int,
        is_correct: bool,
        xp_earned: int,
        answered_at: str,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            current = conn.execute(
                """
                SELECT *
                FROM roadmap_mission_attempts
                WHERE user_id = ? AND id = ?
                LIMIT 1
                """,
                (user_id, mission_id),
            ).fetchone()
            if not current:
                return None
            next_correct = int(current["correct_count"] or 0) + (1 if is_correct else 0)
            next_wrong = int(current["wrong_count"] or 0) + (0 if is_correct else 1)
            total_questions = int(current["total_questions"] or 0)
            completed = total_questions > 0 and (next_correct + next_wrong) >= total_questions
            next_status = "completed" if completed else str(current["status"] or "started")
            completed_at = answered_at if completed and not current["completed_at"] else current["completed_at"]
            conn.execute(
                """
                UPDATE roadmap_mission_attempts
                SET
                    correct_count = ?,
                    wrong_count = ?,
                    xp_earned = xp_earned + ?,
                    status = ?,
                    completed_at = ?,
                    updated_at = ?
                WHERE user_id = ? AND id = ?
                """,
                (
                    next_correct,
                    next_wrong,
                    int(xp_earned or 0),
                    next_status,
                    completed_at,
                    answered_at,
                    user_id,
                    mission_id,
                ),
            )
            row = conn.execute(
                """
                SELECT *
                FROM roadmap_mission_attempts
                WHERE user_id = ? AND id = ?
                LIMIT 1
                """,
                (user_id, mission_id),
            ).fetchone()
        mission = dict(row) if row else {}
        if mission:
            mission["question_ids"] = self._json_load(mission.get("question_ids_json"), [])
        return mission or None

    def update_language_asset_mastery_for_roadmap_practice(
        self,
        *,
        user_id: int,
        asset_id: int,
        is_correct: bool,
        mastery_delta: float,
        status: str,
        reviewed_at: str,
        next_review_at: str,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            current = conn.execute(
                """
                SELECT *
                FROM reusable_language_assets
                WHERE user_id = ? AND id = ?
                LIMIT 1
                """,
                (user_id, asset_id),
            ).fetchone()
            if not current:
                return None
            old_mastery = float(current["mastery_score"] or 0.0)
            next_mastery = max(0.0, min(1.0, old_mastery + float(mastery_delta or 0.0)))
            conn.execute(
                """
                UPDATE reusable_language_assets
                SET
                    mastery_score = ?,
                    status = ?,
                    exposure_count = exposure_count + 1,
                    correct_count = correct_count + ?,
                    wrong_count = wrong_count + ?,
                    last_answered_at = ?,
                    recently_answered_wrong = ?,
                    next_review_at = ?,
                    updated_at = ?
                WHERE user_id = ? AND id = ?
                """,
                (
                    next_mastery,
                    status,
                    1 if is_correct else 0,
                    0 if is_correct else 1,
                    reviewed_at,
                    0 if is_correct else 1,
                    next_review_at,
                    reviewed_at,
                    user_id,
                    asset_id,
                ),
            )
            row = conn.execute(
                """
                SELECT *
                FROM reusable_language_assets
                WHERE user_id = ? AND id = ?
                LIMIT 1
                """,
                (user_id, asset_id),
            ).fetchone()
        if not row:
            return None
        updated = dict(row)
        updated["old_mastery_score"] = old_mastery
        return updated

    def create_describe_again_attempt(
        self,
        *,
        user_id: int,
        session_id: int,
        selected_asset_ids: list[int],
        description: str,
        used_asset_ids: list[int],
        missing_asset_ids: list[int],
        score: int,
        feedback: str,
        improved_description: str,
        xp_earned: int,
        created_at: str,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO describe_again_attempts (
                    user_id, session_id, selected_asset_ids_json, description,
                    used_asset_ids_json, missing_asset_ids_json, score, feedback,
                    improved_description, xp_earned, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    session_id,
                    json.dumps([str(asset_id) for asset_id in selected_asset_ids]),
                    description,
                    json.dumps([str(asset_id) for asset_id in used_asset_ids]),
                    json.dumps([str(asset_id) for asset_id in missing_asset_ids]),
                    int(score or 0),
                    feedback,
                    improved_description,
                    int(xp_earned or 0),
                    created_at,
                ),
            )
            row = conn.execute(
                """
                SELECT *
                FROM describe_again_attempts
                WHERE id = ?
                LIMIT 1
                """,
                (int(cursor.lastrowid),),
            ).fetchone()
        attempt = dict(row) if row else {}
        if attempt:
            attempt["selected_asset_ids"] = self._json_load(attempt.get("selected_asset_ids_json"), [])
            attempt["used_asset_ids"] = self._json_load(attempt.get("used_asset_ids_json"), [])
            attempt["missing_asset_ids"] = self._json_load(attempt.get("missing_asset_ids_json"), [])
        return attempt

    def get_reusable_language_asset(
        self,
        *,
        user_id: int,
        asset_id: int,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM reusable_language_assets
                WHERE user_id = ? AND id = ?
                LIMIT 1
                """,
                (user_id, asset_id),
            ).fetchone()
        return dict(row) if row else None

    def get_quiz_question(
        self,
        *,
        user_id: int,
        session_id: int,
        quiz_question_id: int,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM quiz_questions
                WHERE user_id = ? AND session_id = ? AND id = ?
                LIMIT 1
                """,
                (user_id, session_id, quiz_question_id),
            ).fetchone()
        return self._hydrate_quiz_question(dict(row)) if row else None

    def get_quiz_question_for_user(
        self,
        *,
        user_id: int,
        quiz_question_id: int,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM quiz_questions
                WHERE user_id = ? AND id = ?
                LIMIT 1
                """,
                (user_id, quiz_question_id),
            ).fetchone()
        return self._hydrate_quiz_question(dict(row)) if row else None

    def record_quiz_attempt(
        self,
        *,
        user_id: int,
        session_id: int,
        quiz_question_id: int,
        quiz_type: str,
        language_asset_ids: list[str],
        mode: str,
        answer: str,
        is_correct: bool,
        score: float,
        xp_earned: int,
        expected_keywords: list[str],
        matched_keywords: list[str],
        created_at: str,
        next_review_at: str,
        update_assets: bool = True,
    ) -> dict[str, Any]:
        score = max(0.0, min(1.0, float(score or 0.0)))
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE quiz_questions
                SET
                    correct_count = correct_count + ?,
                    wrong_count = wrong_count + ?,
                    updated_at = ?
                WHERE user_id = ? AND session_id = ? AND id = ?
                """,
                (
                    1 if is_correct else 0,
                    0 if is_correct else 1,
                    created_at,
                    user_id,
                    session_id,
                    quiz_question_id,
                ),
            )
            cursor = conn.execute(
                *self._quiz_attempt_insert_sql_and_values(
                    conn,
                    user_id=user_id,
                    session_id=session_id,
                    quiz_question_id=quiz_question_id,
                    quiz_type=quiz_type,
                    language_asset_ids=language_asset_ids,
                    mode=mode,
                    answer=answer,
                    is_correct=is_correct,
                    score=score,
                    xp_earned=xp_earned,
                    expected_keywords=expected_keywords,
                    matched_keywords=matched_keywords,
                    created_at=created_at,
                )
            )
            for asset_id in (language_asset_ids if update_assets else []):
                current = conn.execute(
                    """
                    SELECT *
                    FROM reusable_language_assets
                    WHERE user_id = ? AND id = ?
                    LIMIT 1
                    """,
                    (user_id, int(asset_id)),
                ).fetchone()
                if not current:
                    continue
                current_mastery = float(current["mastery_score"] or 0.0)
                mastery_delta = 0.18 if score >= 1.0 else 0.08 if score >= 0.5 else -0.12
                next_mastery = max(0.0, min(1.0, current_mastery + mastery_delta))
                if score < 0.5:
                    next_status = "weak"
                elif next_mastery >= 0.91:
                    next_status = "mastered"
                elif next_mastery >= 0.75:
                    next_status = "strong"
                elif next_mastery >= 0.45:
                    next_status = "familiar"
                else:
                    next_status = "learning"
                conn.execute(
                    """
                    UPDATE reusable_language_assets
                    SET
                        mastery_score = ?,
                        status = ?,
                        correct_count = correct_count + ?,
                        wrong_count = wrong_count + ?,
                        last_answered_at = ?,
                        recently_answered_wrong = ?,
                        next_review_at = ?,
                        updated_at = ?
                    WHERE user_id = ? AND id = ?
                    """,
                    (
                        next_mastery,
                        next_status,
                        1 if score >= 0.5 else 0,
                        0 if score >= 0.5 else 1,
                        created_at,
                        0 if score >= 0.5 else 1,
                        next_review_at,
                        created_at,
                        user_id,
                        int(asset_id),
                    ),
                )
            row = conn.execute("SELECT * FROM quiz_attempts WHERE id = ?", (int(cursor.lastrowid),)).fetchone()
        attempt = dict(row) if row else {}
        if attempt:
            attempt["language_asset_ids"] = self._json_load(attempt.get("language_asset_ids_json"), [])
            attempt["expected_keywords"] = self._json_load(attempt.get("expected_keywords_json"), [])
            attempt["matched_keywords"] = self._json_load(attempt.get("matched_keywords_json"), [])
        return attempt

    def _quiz_attempt_insert_sql_and_values(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        session_id: int,
        quiz_question_id: int,
        quiz_type: str,
        language_asset_ids: list[str],
        mode: str,
        answer: str,
        is_correct: bool,
        score: float,
        xp_earned: int,
        expected_keywords: list[str],
        matched_keywords: list[str],
        created_at: str,
    ) -> tuple[str, tuple[Any, ...]]:
        language_asset_ids_json = json.dumps([str(item) for item in language_asset_ids])
        expected_keywords_json = json.dumps(expected_keywords)
        matched_keywords_json = json.dumps(matched_keywords)
        correct_value = 1 if is_correct else 0
        wrong_value = 0 if is_correct else 1
        known_values: dict[str, Any] = {
            "user_id": user_id,
            "userId": user_id,
            "session_id": session_id,
            "sessionId": session_id,
            "quiz_question_id": quiz_question_id,
            "quizQuestionId": quiz_question_id,
            "question_id": quiz_question_id,
            "questionId": quiz_question_id,
            "quiz_type": quiz_type,
            "question_type": quiz_type,
            "type": quiz_type,
            "language_asset_ids_json": language_asset_ids_json,
            "languageAssetIds": language_asset_ids_json,
            "language_asset_ids": language_asset_ids_json,
            "mode": mode,
            "quiz_mode": mode,
            "quizMode": mode,
            "answer_mode": mode,
            "answerMode": mode,
            "selected_answer": answer,
            "selectedAnswer": answer,
            "selected_option": answer,
            "selectedOption": answer,
            "selected_option_id": answer,
            "selectedOptionId": answer,
            "submitted_answer": answer,
            "submittedAnswer": answer,
            "user_answer": answer,
            "userAnswer": answer,
            "answer_text": answer,
            "answerText": answer,
            "response": answer,
            "response_text": answer,
            "responseText": answer,
            "answer": answer,
            "is_correct": correct_value,
            "isCorrect": correct_value,
            "correct": correct_value,
            "was_correct": correct_value,
            "wasCorrect": correct_value,
            "score": score,
            "score_value": score,
            "xp_earned": int(xp_earned or 0),
            "xpEarned": int(xp_earned or 0),
            "expected_keywords_json": expected_keywords_json,
            "expectedKeywords": expected_keywords_json,
            "expected_keywords": expected_keywords_json,
            "matched_keywords_json": matched_keywords_json,
            "matchedKeywords": matched_keywords_json,
            "matched_keywords": matched_keywords_json,
            "created_at": created_at,
            "createdAt": created_at,
            "answered_at": created_at,
            "answeredAt": created_at,
            "submitted_at": created_at,
            "submittedAt": created_at,
            "updated_at": created_at,
            "updatedAt": created_at,
            "correct_count": correct_value,
            "wrong_count": wrong_value,
        }

        table_columns = conn.execute("PRAGMA table_info(quiz_attempts)").fetchall()
        insert_columns: list[str] = []
        values: list[Any] = []
        for column in table_columns:
            name = str(column["name"])
            if int(column["pk"] or 0):
                continue
            if name in known_values:
                insert_columns.append(name)
                values.append(known_values[name])
                continue
            has_default = column["dflt_value"] is not None
            is_required = bool(column["notnull"])
            if is_required and not has_default:
                insert_columns.append(name)
                values.append(self._legacy_quiz_attempt_fallback_value(str(column["type"] or "")))

        placeholders = ", ".join("?" for _ in insert_columns)
        quoted_columns = ", ".join(self._quote_sqlite_identifier(column) for column in insert_columns)
        return (
            f"INSERT INTO quiz_attempts ({quoted_columns}) VALUES ({placeholders})",
            tuple(values),
        )

    def _quote_sqlite_identifier(self, value: str) -> str:
        return '"' + value.replace('"', '""') + '"'

    def _legacy_quiz_attempt_fallback_value(self, column_type: str) -> Any:
        lowered = column_type.casefold()
        if "int" in lowered:
            return 0
        if any(kind in lowered for kind in ("real", "float", "double", "numeric")):
            return 0.0
        return ""

    def list_quiz_attempts_for_question(
        self,
        *,
        user_id: int,
        session_id: int,
        quiz_question_id: int,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM quiz_attempts
                WHERE user_id = ? AND session_id = ? AND quiz_question_id = ?
                ORDER BY created_at DESC
                """,
                (user_id, session_id, quiz_question_id),
            ).fetchall()
        attempts = [dict(row) for row in rows]
        for attempt in attempts:
            attempt["language_asset_ids"] = self._json_load(attempt.get("language_asset_ids_json"), [])
            attempt["expected_keywords"] = self._json_load(attempt.get("expected_keywords_json"), [])
            attempt["matched_keywords"] = self._json_load(attempt.get("matched_keywords_json"), [])
        return attempts

    def _hydrate_quiz_question(self, row: dict[str, Any]) -> dict[str, Any]:
        row["language_asset_ids"] = self._json_load(row.get("language_asset_ids_json"), [])
        row["options"] = self._json_load(row.get("options_json"), [])
        row["word_bank"] = self._json_load(row.get("word_bank_json"), [])
        row["expected_keywords"] = self._json_load(row.get("expected_keywords_json"), [])
        return row

    def update_phrase_mastery(
        self,
        *,
        user_id: int,
        session_id: int,
        phrase: str,
        mastery: float,
        was_correct: bool,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            current = conn.execute(
                """
                SELECT *
                FROM session_phrase_items
                WHERE user_id = ? AND session_id = ? AND lower(phrase) = lower(?)
                """,
                (user_id, session_id, phrase),
            ).fetchone()
            if not current:
                return {}

            correct_count = int(current["correct_count"] or 0) + (1 if was_correct else 0)
            wrong_count = int(current["wrong_count"] or 0) + (0 if was_correct else 1)
            mastery_value = max(float(current["mastery"] or 0.0), max(0.0, min(1.0, float(mastery))))
            conn.execute(
                """
                UPDATE session_phrase_items
                SET mastery = ?, correct_count = ?, wrong_count = ?
                WHERE id = ?
                """,
                (mastery_value, correct_count, wrong_count, current["id"]),
            )
            row = conn.execute("SELECT * FROM session_phrase_items WHERE id = ?", (current["id"],)).fetchone()

        item = dict(row) if row else {}
        if item:
            item["examples"] = self._json_load(item.get("examples_json"), [])
            item["mastery_state"] = phrase_mastery_state(
                mastery=float(item.get("mastery") or 0.0),
                correct_count=int(item.get("correct_count") or 0),
            )
        return item

    def ensure_user_progress(self, *, user_id: int, now_iso: str) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO user_progress (
                    user_id, xp_points, streak_days, learner_level,
                    sessions_completed, words_learned, phrases_mastered,
                    created_at, updated_at
                )
                VALUES (?, 0, 0, 1, 0, 0, 0, ?, ?)
                """,
                (user_id, now_iso, now_iso),
            )
            row = conn.execute("SELECT * FROM user_progress WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else {}

    def save_user_progress(
        self,
        *,
        user_id: int,
        xp_points: int,
        streak_days: int,
        learner_level: int,
        sessions_completed: int,
        words_learned: int,
        phrases_mastered: int,
        last_active_on: str,
        updated_at: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE user_progress
                SET xp_points = ?, streak_days = ?, learner_level = ?,
                    sessions_completed = ?, words_learned = ?, phrases_mastered = ?,
                    last_active_on = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (
                    xp_points,
                    streak_days,
                    learner_level,
                    sessions_completed,
                    words_learned,
                    phrases_mastered,
                    last_active_on,
                    updated_at,
                    user_id,
                ),
            )

    def get_user_progress(self, *, user_id: int) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM user_progress WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else {}

    def get_mastery_counts(self, *, user_id: int) -> dict[str, int]:
        with self._connect() as conn:
            word_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM session_vocabulary_items
                WHERE user_id = ? AND (mastery >= 0.55 OR correct_count > 0)
                """,
                (user_id,),
            ).fetchone()[0]
            phrase_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM session_phrase_items
                WHERE user_id = ? AND (mastery >= 0.55 OR correct_count > 0)
                """,
                (user_id,),
            ).fetchone()[0]
        return {
            "words_learned": int(word_count),
            "phrases_mastered": int(phrase_count),
            "mastered_total": int(word_count) + int(phrase_count),
        }

    def get_stats(self, *, user_id: int, now_iso: str) -> dict[str, int]:
        with self._connect() as conn:
            sessions_count = conn.execute(
                "SELECT COUNT(*) FROM analysis_sessions WHERE user_id = ?",
                (user_id,),
            ).fetchone()[0]
        mastery = self.get_mastery_counts(user_id=user_id)
        return {
            "sessions_count": int(sessions_count),
            "words_learned": mastery["words_learned"],
            "phrases_mastered": mastery["phrases_mastered"],
        }

    def get_progress_dashboard(self, *, user_id: int, now_iso: str) -> dict[str, Any]:
        progress = self.get_user_progress(user_id=user_id)
        mastery_counts = self.get_mastery_counts(user_id=user_id)
        stats = self.get_stats(user_id=user_id, now_iso=now_iso)
        return {
            "xp_points": int(progress.get("xp_points", 0)),
            "streak_days": int(progress.get("streak_days", 0)),
            "learner_level": int(progress.get("learner_level", 1)),
            "sessions_completed": int(progress.get("sessions_completed", 0)),
            "words_learned": mastery_counts["words_learned"],
            "phrases_mastered": mastery_counts["phrases_mastered"],
            "overall_accuracy_percent": 0,
            "overall_mastery_percent": min(100, mastery_counts["mastered_total"] * 10),
            "stats": stats,
            "recent_runs": [],
            "weekly_summary": {"accuracy_percent": 0, "improvement_percent": 0},
        }
