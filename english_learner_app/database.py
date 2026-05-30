from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .learning import canonical_level


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
