from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import os

import yaml
from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    bot_token: str
    admin_chat_id: int
    tg_api_id: int
    tg_api_hash: str
    tg_phone: str
    tg_session_name: str
    tg_session_string: str | None
    interactive_bot: bool
    manual_digest_url: str | None
    timezone: str
    morning_hour: int
    evening_hour: int
    db_path: Path
    media_dir: Path
    sources_path: Path
    max_images_per_digest: int
    default_digest_paragraphs: int
    llm_backend: str = "none"
    llm_model: str = "stepfun/step-3.5-flash:free"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_fallback_models: list[str] | None = None
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    openrouter_api_key: str | None = None
    openrouter_model: str = "stepfun/step-3.5-flash:free"


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_settings() -> Settings:
    root = project_root()
    load_dotenv(root / ".env")

    db_path = _resolve_path(os.getenv("DB_PATH", "data/digest.db"), root)
    media_dir = _resolve_path(os.getenv("MEDIA_DIR", "data/media"), root)
    sources_path = _resolve_path(
        os.getenv("SOURCES_PATH", "config/default_sources.yaml"), root
    )

    media_dir.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    return Settings(
        bot_token=_required("BOT_TOKEN"),
        admin_chat_id=int(_required("ADMIN_CHAT_ID")),
        tg_api_id=int(_required("TG_API_ID")),
        tg_api_hash=_required("TG_API_HASH"),
        tg_phone=_required("TG_PHONE"),
        tg_session_name=os.getenv("TG_SESSION_NAME", "ai_news_digest"),
        tg_session_string=os.getenv("TG_SESSION_STRING"),
        interactive_bot=_get_bool("INTERACTIVE_BOT", default=True),
        manual_digest_url=os.getenv("MANUAL_DIGEST_URL"),
        timezone=os.getenv("TIMEZONE", "Europe/Moscow"),
        morning_hour=int(os.getenv("MORNING_HOUR", "9")),
        evening_hour=int(os.getenv("EVENING_HOUR", "19")),
        db_path=db_path,
        media_dir=media_dir,
        sources_path=sources_path,
        max_images_per_digest=int(os.getenv("MAX_IMAGES_PER_DIGEST", "10")),
        default_digest_paragraphs=int(os.getenv("DEFAULT_DIGEST_PARAGRAPHS", "5")),
        llm_backend=os.getenv("LLM_BACKEND", "none"),
        llm_model=os.getenv(
            "LLM_MODEL",
            os.getenv("OPENROUTER_MODEL", "stepfun/step-3.5-flash:free"),
        ),
        llm_base_url=os.getenv("LLM_BASE_URL"),
        llm_api_key=os.getenv("LLM_API_KEY"),
        llm_fallback_models=_split_csv(os.getenv("LLM_FALLBACK_MODELS")),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY"),
        openrouter_model=os.getenv("OPENROUTER_MODEL", "stepfun/step-3.5-flash:free"),
    )


def load_default_sources(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    return payload.get("sources", [])


def _required(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


def _resolve_path(value: str, root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return root / path


def _split_csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def _get_bool(key: str, default: bool) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
