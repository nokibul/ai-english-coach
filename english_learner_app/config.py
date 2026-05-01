from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _parse_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_path(name: str, default: Path, *, root: Path) -> Path:
    value = os.getenv(name)
    if not value:
        return default
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


@dataclass(slots=True)
class AppConfig:
    base_dir: Path
    data_dir: Path
    static_dir: Path
    uploads_dir: Path
    database_path: Path
    app_name: str
    host: str
    port: int
    app_secret_key: str
    session_cookie_name: str
    session_ttl_hours: int
    otp_ttl_minutes: int
    first_review_minutes: int
    review_prompt_interval_seconds: int
    quiz_retake_minutes: int
    max_upload_bytes: int
    ai_backend: str
    vllm_base_url: str
    vllm_api_key: str
    vllm_model: str
    vllm_timeout_seconds: float
    vllm_max_concurrency: int
    vllm_batch_interval_ms: int
    vllm_batch_max_size: int
    openai_api_key: str | None
    openai_model: str
    openai_base_url: str
    demo_mode: bool
    inference_max_new_tokens: int
    inference_temperature: float
    image_min_pixels: int
    image_max_pixels: int
    smtp_host: str | None
    smtp_port: int
    smtp_username: str | None
    smtp_password: str | None
    smtp_sender: str | None
    smtp_use_starttls: bool
    smtp_use_ssl: bool
    cookie_secure: bool

    @classmethod
    def from_env(cls, base_dir: Path | None = None) -> "AppConfig":
        root = (base_dir or Path(__file__).resolve().parent.parent).resolve()
        _parse_env_file(root / ".env")

        data_dir = _env_path("APP_DATA_DIR", root / "app_data", root=root)
        uploads_dir = _env_path("UPLOADS_DIR", data_dir / "uploads", root=root)
        static_dir = root / "english_learner_app" / "static"
        database_path = _env_path(
            "DATABASE_PATH",
            data_dir / "english_learner.sqlite3",
            root=root,
        )
        openai_api_key = os.getenv("OPENAI_API_KEY")
        vllm_model = os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct-AWQ")
        vllm_max_concurrency = max(1, int(os.getenv("VLLM_MAX_CONCURRENCY", "8")))
        vllm_batch_interval_ms = max(0, int(os.getenv("VLLM_BATCH_INTERVAL_MS", "30")))
        vllm_batch_max_size = max(
            vllm_max_concurrency,
            int(os.getenv("VLLM_BATCH_MAX_SIZE", str(vllm_max_concurrency))),
        )
        explicit_backend = os.getenv("AI_BACKEND")
        if explicit_backend:
            ai_backend = explicit_backend.strip().lower()
        elif openai_api_key:
            ai_backend = "openai"
        else:
            ai_backend = "demo"

        return cls(
            base_dir=root,
            data_dir=data_dir,
            static_dir=static_dir,
            uploads_dir=uploads_dir,
            database_path=database_path,
            app_name=os.getenv("APP_NAME", "AI English Learner"),
            host=os.getenv("APP_HOST", "127.0.0.1"),
            port=int(os.getenv("APP_PORT", "8080")),
            app_secret_key=os.getenv("APP_SECRET_KEY", "change-me-in-production"),
            session_cookie_name=os.getenv("SESSION_COOKIE_NAME", "english_session"),
            session_ttl_hours=int(os.getenv("SESSION_TTL_HOURS", "168")),
            otp_ttl_minutes=int(os.getenv("OTP_TTL_MINUTES", "10")),
            first_review_minutes=int(os.getenv("FIRST_REVIEW_MINUTES", "60")),
            review_prompt_interval_seconds=int(
                os.getenv("REVIEW_PROMPT_INTERVAL_SECONDS", "90")
            ),
            quiz_retake_minutes=int(os.getenv("QUIZ_RETAKE_MINUTES", "20")),
            max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(8 * 1024 * 1024))),
            ai_backend=ai_backend,
            vllm_base_url=os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/"),
            vllm_api_key=os.getenv("VLLM_API_KEY", "local-dev"),
            vllm_model=vllm_model,
            vllm_timeout_seconds=float(os.getenv("VLLM_TIMEOUT_SECONDS", "120")),
            vllm_max_concurrency=vllm_max_concurrency,
            vllm_batch_interval_ms=vllm_batch_interval_ms,
            vllm_batch_max_size=vllm_batch_max_size,
            openai_api_key=openai_api_key,
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            openai_base_url=os.getenv(
                "OPENAI_BASE_URL", "https://api.openai.com/v1"
            ).rstrip("/"),
            demo_mode=_env_bool("DEMO_MODE", default=not bool(openai_api_key)),
            inference_max_new_tokens=int(os.getenv("INFERENCE_MAX_NEW_TOKENS", "180")),
            inference_temperature=float(os.getenv("INFERENCE_TEMPERATURE", "0.0")),
            image_min_pixels=int(os.getenv("IMAGE_MIN_PIXELS", str(128 * 28 * 28))),
            image_max_pixels=int(os.getenv("IMAGE_MAX_PIXELS", str(128 * 28 * 28))),
            smtp_host=os.getenv("SMTP_HOST"),
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_username=os.getenv("SMTP_USERNAME"),
            smtp_password=os.getenv("SMTP_PASSWORD"),
            smtp_sender=os.getenv("SMTP_SENDER"),
            smtp_use_starttls=_env_bool("SMTP_USE_STARTTLS", True),
            smtp_use_ssl=_env_bool("SMTP_USE_SSL", False),
            cookie_secure=_env_bool("COOKIE_SECURE", False),
        )
