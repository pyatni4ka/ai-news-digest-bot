from __future__ import annotations

import asyncio
from collections import Counter
from datetime import UTC, datetime, timedelta
from html import escape
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, InputMediaPhoto

from digest_bot.bot.keyboards import digest_inline_keyboard, digest_static_keyboard, links_keyboard
from digest_bot.collectors.rss import RSSCollector
from digest_bot.collectors.telegram import TelegramCollector
from digest_bot.collectors.webpage import WebpageCollector
from digest_bot.config import Settings, load_default_sources
from digest_bot.models import Digest, NewsItem, Source
from digest_bot.pipeline.classify import classify_items
from digest_bot.pipeline.dedup import deduplicate
from digest_bot.pipeline.digest_builder import (
    build_digest,
    build_story_sequence,
    compute_window_with_hours,
    gather_images,
    select_sections,
    truncate_at_word_boundary,
)
from digest_bot.storage import Repository
from digest_bot.summarizers.fallback import FallbackSummarizer
from digest_bot.summarizers.http_compat import OpenAICompatibleSummarizer


class DigestService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.repo = Repository(settings.db_path)
        self.repo.seed_sources(_load_sources(settings))
        self.bot = Bot(settings.bot_token)
        self.telegram_collector = TelegramCollector(settings)
        self.rss_collector = RSSCollector()
        self.webpage_collector = WebpageCollector()
        self.summarizer = self._build_summarizer()
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        await self.telegram_collector.close()
        await self.bot.session.close()

    def is_admin_chat(self, chat_id: int) -> bool:
        return chat_id == self.settings.admin_chat_id

    def add_source(self, handle: str) -> Source:
        return self.repo.add_telegram_source(handle)

    def latest_digest_id(self, slot: str | None = None) -> int | None:
        row = self.repo.get_latest_digest(slot)
        return None if row is None else int(row["id"])

    async def sync_sources(self, lookback_hours: int = 18) -> dict[str, int]:
        async with self._lock:
            sources = self.repo.list_sources(enabled_only=True)
            since = datetime.now(UTC) - timedelta(hours=lookback_hours)
            collected: list[NewsItem] = []
            stats: Counter[str] = Counter()
            for source in sources:
                try:
                    batch = await asyncio.wait_for(self._fetch_source(source, since), timeout=12)
                except TimeoutError:
                    stats[f"timeout:{source.key}"] += 1
                    continue
                except Exception:
                    stats[f"error:{source.key}"] += 1
                    continue
                classify_items(batch)
                for item in batch:
                    item.importance += source.priority * 0.6
                collected.extend(batch)
                stats[source.key] = len(batch)
            unique = deduplicate(collected)
            inserted = self.repo.save_news_items(unique)
            stats["inserted"] = inserted
            return dict(stats)

    async def build_digest(self, slot: str | None = None) -> int:
        selected_slot = slot or self.current_slot()
        now = datetime.now(UTC)
        start_at, end_at = compute_window_with_hours(
            selected_slot,
            now,
            self.settings.timezone,
            morning_hour=self.settings.morning_hour,
            evening_hour=self.settings.evening_hour,
        )
        items = [self._row_to_item(row) for row in self.repo.get_items_between(start_at, end_at)]
        classify_items(items)
        items = deduplicate(items)
        sectioned = select_sections(items, slot=selected_slot)
        story_sequence = build_story_sequence(
            selected_slot,
            sectioned,
            self._paragraph_count_for_slot(selected_slot),
        )
        paragraph_count = self._paragraph_count_for_slot(selected_slot)
        total_section_items = sum(len(section) for section in sectioned.values())
        if total_section_items < 2:
            summary = ""
        else:
            try:
                summary = await self.summarizer.summarize(
                    selected_slot,
                    {**sectioned, "story_order": story_sequence},
                    paragraph_count,
                )
            except Exception:
                fallback = FallbackSummarizer()
                summary = await fallback.summarize(
                    selected_slot,
                    sectioned,
                    paragraph_count,
                )
        digest = build_digest(
            selected_slot,
            items,
            now,
            self.settings.timezone,
            summary,
            paragraph_count,
            morning_hour=self.settings.morning_hour,
            evening_hour=self.settings.evening_hour,
        )
        return self.repo.save_digest(digest)

    async def refresh_and_build_current_digest(self) -> int:
        await self.sync_sources()
        return await self.build_digest(self.current_slot())

    async def run_scheduled_digest(self, slot: str) -> None:
        await self.sync_sources()
        digest_id = await self.build_digest(slot)
        await self.send_digest(digest_id)

    async def send_digest(self, digest_id: int) -> None:
        row = self.repo.get_digest(digest_id)
        if row is None:
            return
        text, payload = self.repo.hydrate_digest(row)
        reply_markup = (
            digest_inline_keyboard(int(row["id"]), payload)
            if self.settings.interactive_bot
            else digest_static_keyboard(payload, self.settings.manual_digest_url)
        )
        await self.bot.send_message(
            chat_id=self.settings.admin_chat_id,
            text=self._format_digest_html(str(row["title"]), text, str(row["slot"]), payload),
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
        await self._send_story_images(self.settings.admin_chat_id, payload.get("story_media", []))

    async def send_digest_section(self, chat_id: int, digest_id: int, section_key: str) -> None:
        row = self.repo.get_digest(digest_id)
        if row is None:
            await self.bot.send_message(chat_id=chat_id, text="Дайджест пока не найден.")
            return
        _, payload = self.repo.hydrate_digest(row)
        section = payload.get("sections", {}).get(section_key)
        if section is None:
            await self.bot.send_message(chat_id=chat_id, text="Для этого окна раздел пуст.")
            return
        images = self.get_section_images(digest_id, section_key)
        if images:
            await self._send_images(chat_id, images)
        await self.bot.send_message(
            chat_id=chat_id,
            text=truncate_at_word_boundary(section["paragraph"], 4000),
            reply_markup=links_keyboard(section.get("links", []), "Открыть"),
        )

    def render_digest_message(self, digest_id: int) -> tuple[str, dict]:
        row = self.repo.get_digest(digest_id)
        if row is None:
            return ("Дайджест пока не найден.", {})
        text, payload = self.repo.hydrate_digest(row)
        return (self._format_digest_html(str(row["title"]), text, str(row["slot"]), payload), payload)

    def render_digest_details(self, digest_id: int) -> str:
        row = self.repo.get_digest(digest_id)
        if row is None:
            return "Дайджест пока не найден."
        _, payload = self.repo.hydrate_digest(row)
        lines = [str(row["title"]), ""]
        for section in payload.get("sections", {}).values():
            lines.append(section["paragraph"])
            lines.append("")
        return truncate_at_word_boundary("\n".join(lines).strip(), 4000)

    def render_digest_section(self, digest_id: int, section_key: str) -> str:
        row = self.repo.get_digest(digest_id)
        if row is None:
            return "Дайджест пока не найден."
        _, payload = self.repo.hydrate_digest(row)
        section = payload.get("sections", {}).get(section_key)
        if section is None:
            return "Для этого окна раздел пуст."
        return truncate_at_word_boundary(section["paragraph"], 4000)

    def get_digest_links(self, digest_id: int, link_kind: str) -> tuple[str, list[str]]:
        row = self.repo.get_digest(digest_id)
        if row is None:
            return ("Ссылок пока нет.", [])
        _, payload = self.repo.hydrate_digest(row)
        summary_payload = payload.get("summary_payload", {})
        if link_kind == "resources":
            return ("Топ ссылок по приложениям и ресурсам.", summary_payload.get("resource_links", []))
        if link_kind == "models":
            return ("Топ ссылок по моделям и релизам.", summary_payload.get("model_links", []))
        return ("Ссылок пока нет.", [])

    def get_section_images(self, digest_id: int, section_key: str, limit: int = 6) -> list[str]:
        row = self.repo.get_digest(digest_id)
        if row is None:
            return []
        _, payload = self.repo.hydrate_digest(row)
        section = payload.get("sections", {}).get(section_key)
        if section is None:
            return []
        item_ids = [int(item_id) for item_id in section.get("item_ids", []) if item_id]
        rows = self.repo.get_news_items_by_ids(item_ids)
        items = [self._row_to_item(item_row) for item_row in rows]
        return gather_images(items, min(limit, self.settings.max_images_per_digest))

    def save_favorite(self, digest_id: int) -> None:
        self.repo.save_favorite(digest_id)

    def suppress_noise_for_digest(self, digest_id: int) -> int:
        row = self.repo.get_digest(digest_id)
        if row is None:
            return 0
        _, payload = self.repo.hydrate_digest(row)
        category = "general"
        counts = payload.get("summary_payload", {}).get("section_counts", {})
        for candidate in ("headline", "resources", "comparisons"):
            if counts.get(candidate):
                category = candidate
                break
        return self.repo.increment_suppression(category)

    def render_sources(self) -> str:
        sources = self.repo.list_sources(enabled_only=True)
        telegram = [source for source in sources if source.kind == "telegram"]
        open_sources = [source for source in sources if source.kind != "telegram"]
        lines = [
            f"Активно источников: {len(sources)}",
            f"Telegram: {len(telegram)}",
            f"Открытых источников: {len(open_sources)}",
            "",
        ]
        for source in sources[:40]:
            lines.append(f"• {source.name} [{source.kind}]")
        return truncate_at_word_boundary("\n".join(lines), 4000)

    def render_settings(self) -> str:
        return (
            "Текущие настройки\n"
            f"Часовой пояс: {self.settings.timezone}\n"
            f"Утро: {self.settings.morning_hour:02d}:00\n"
            f"Вечер: {self.settings.evening_hour:02d}:00\n"
            f"LLM backend: {self.settings.llm_backend}\n"
            f"LLM model: {self._active_model_label()}\n"
            f"Макс. изображений: {self.settings.max_images_per_digest}\n"
            f"Manual digest URL: {self.settings.manual_digest_url or '-'}\n"
            f"База: {self.settings.db_path}"
        )

    def current_slot(self) -> str:
        local_now = datetime.now(UTC).astimezone(ZoneInfo(self.settings.timezone))
        return "morning" if local_now.hour < self.settings.evening_hour else "evening"

    async def _send_images(self, chat_id: int, images: list[str]) -> None:
        if not images:
            return
        media: list[InputMediaPhoto] = []
        for image in images[: self.settings.max_images_per_digest]:
            photo_input = self._photo_input(image)
            if photo_input is not None:
                media.append(InputMediaPhoto(media=photo_input))
        if media:
            try:
                await self.bot.send_media_group(
                    chat_id=chat_id,
                    media=media[:10],
                )
            except TelegramBadRequest:
                # If one image is corrupted, send them one by one until Telegram accepts.
                for item in media[:10]:
                    try:
                        await self.bot.send_photo(
                            chat_id=chat_id,
                            photo=item.media,
                        )
                    except TelegramBadRequest:
                        continue

    async def _send_story_images(self, chat_id: int, story_media: list[dict]) -> None:
        if not story_media:
            return
        sent = 0
        for story in story_media:
            images = story.get("image_paths", [])
            if not images:
                continue
            photo_input = self._photo_input(images[0])
            if photo_input is None:
                continue
            caption = self._story_image_caption(str(story.get("title", "")), str(story.get("url", "") or ""))
            try:
                await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo_input,
                    caption=caption,
                    parse_mode="HTML",
                )
                sent += 1
            except TelegramBadRequest:
                continue
            if sent >= self.settings.max_images_per_digest:
                break

    def _photo_input(self, image: str):
        if image.startswith(("http://", "https://")):
            return image
        if Path(image).exists():
            return FSInputFile(image)
        return None

    async def _fetch_source(self, source: Source, since: datetime) -> list[NewsItem]:
        if source.kind == "telegram":
            return await self.telegram_collector.fetch(source, since)
        if source.kind == "rss":
            return await self.rss_collector.fetch(source, since)
        if source.kind == "webpage":
            return await self.webpage_collector.fetch(source, since)
        return []

    def _row_to_item(self, row) -> NewsItem:
        return NewsItem(
            db_id=int(row["id"]),
            source_key=str(row["source_key"]),
            external_id=str(row["external_id"]),
            title=str(row["title"]),
            summary=str(row["summary"]),
            body=str(row["body"]),
            url=str(row["url"]) if row["url"] else None,
            published_at=datetime.fromisoformat(str(row["published_at"])),
            collected_at=datetime.fromisoformat(str(row["collected_at"])),
            tags=json.loads(str(row["tags_json"])),
            categories=json.loads(str(row["categories_json"])),
            importance=float(row["importance"]),
            images=json.loads(str(row["images_json"])),
            raw=json.loads(str(row["raw_json"])),
            dedup_key=str(row["dedup_key"]),
        )

    def _build_summarizer(self):
        if self.settings.llm_backend == "openrouter" and self.settings.openrouter_api_key:
            return OpenAICompatibleSummarizer(
                api_key=self.settings.openrouter_api_key,
                model=self.settings.openrouter_model or "stepfun/step-3.5-flash:free",
                base_url="https://openrouter.ai/api/v1",
                fallback_models=self.settings.llm_fallback_models
                or [
                    "z-ai/glm-4.5-air:free",
                    "nvidia/nemotron-nano-9b-v2:free",
                ],
                referer="https://openrouter.ai",
                title="AI News Digest Bot",
            )
        if (
            self.settings.llm_backend == "compat"
            and self.settings.llm_api_key
            and self.settings.llm_base_url
        ):
            return OpenAICompatibleSummarizer(
                api_key=self.settings.llm_api_key,
                model=self.settings.llm_model,
                base_url=self.settings.llm_base_url,
                fallback_models=self.settings.llm_fallback_models,
            )
        if self.settings.llm_backend != "openai" or not self.settings.openai_api_key:
            return FallbackSummarizer()
        try:
            from digest_bot.summarizers.openai import OpenAISummarizer
        except ImportError:
            return FallbackSummarizer()
        return OpenAISummarizer(self.settings.openai_api_key, self.settings.openai_model)

    def _active_model_label(self) -> str:
        if self.settings.llm_backend == "openrouter":
            return self.settings.openrouter_model
        if self.settings.llm_backend == "compat":
            return self.settings.llm_model
        if self.settings.llm_backend == "openai" and self.settings.openai_api_key:
            return self.settings.openai_model
        return "fallback"

    def _paragraph_count_for_slot(self, slot: str) -> int:
        if slot == "monthly":
            return max(self.settings.default_digest_paragraphs, 10)
        return max(self.settings.default_digest_paragraphs, 6)

    def _format_digest_html(self, title: str, text: str, slot: str, payload: dict | None = None) -> str:
        raw_paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
        paragraphs = [self._normalize_paragraph(paragraph) for paragraph in raw_paragraphs]
        story_links = (payload or {}).get("summary_payload", {}).get("story_links", [])
        chunks = [f"<b>{escape(title)}</b>"]
        max_paragraphs = 12 if slot == "monthly" else 7
        for index, paragraph in enumerate(paragraphs[:max_paragraphs]):
            label, body = self._split_label(paragraph)
            if label is None:
                block = escape(paragraph)
            elif not body:
                block = f"<b>{escape(label)}</b>"
            else:
                block = f"<b>{escape(label)}</b>\n{escape(body)}"
            link = story_links[index] if index < len(story_links) else None
            if link:
                block = f"{block}\n<a href=\"{escape(link)}\">Читать →</a>"
            chunks.append(block)
        separator = "\n\n" + "─" * 20 + "\n\n"
        header = chunks[0]
        stories = chunks[1:]
        if stories:
            return _safe_join_chunks([header, separator.join(stories)], limit=4000)
        return header

    def _story_image_caption(self, title: str, url: str) -> str:
        if url:
            return f"<b>К новости:</b> {escape(title)}\n{escape(url)}"
        return f"<b>К новости:</b> {escape(title)}"

    def _split_label(self, paragraph: str) -> tuple[str | None, str]:
        for label in (
            "Главное",
            "Модели и релизы",
            "Сравнения",
            "Coding",
            "Dev tools",
            "Vibe coding",
            "Ресурсы",
        ):
            prefix = f"{label}:"
            if paragraph.startswith(prefix):
                return label, paragraph[len(prefix):].strip()
        if ":" in paragraph:
            label, body = paragraph.split(":", 1)
            if "\n" not in label and 2 <= len(label.strip()) <= 90:
                return label.strip(), body.strip()
        return None, paragraph

    def _normalize_paragraph(self, paragraph: str) -> str:
        label, body = self._split_label(paragraph)
        if label is None:
            return paragraph

        body = re.sub(
            r"^(?P<head>[A-ZА-Я0-9][A-ZА-Я0-9\-\s]{8,80}\s?):\s+",
            "",
            body,
        )

        clean_label = label
        words = [word for word in re.sub(r"^[^\wА-Яа-я]+", "", label).split() if word]
        if (
            len(words) >= 3
            and self._looks_like_caps(label)
            and not self._looks_like_model_release(f"{label} {body}")
        ):
            clean_label = self._smart_sentence_case(label)
        if self._looks_like_model_release(f"{clean_label} {body}"):
            clean_label = clean_label.upper()
        if self._looks_like_free_offer(f"{clean_label} {body}") and "АБСОЛЮТНО БЕСПЛАТНО" not in clean_label:
            clean_label = f"{clean_label} — АБСОЛЮТНО БЕСПЛАТНО"

        return f"{clean_label}: {body}" if body else clean_label

    def _looks_like_caps(self, text: str) -> bool:
        letters = [char for char in text if char.isalpha()]
        if len(letters) < 6:
            return False
        uppercase = sum(1 for char in letters if char.isupper())
        return uppercase / len(letters) > 0.8

    def _looks_like_model_release(self, text: str) -> bool:
        haystack = text.lower()
        release_cues = (
            "introducing",
            "announce",
            "announcing",
            "released",
            "launch",
            "available",
            "preview",
            "beta",
            "model",
            "weights",
            "checkpoint",
            "version",
            "released a new",
            "new model",
            "представила",
            "выпустила",
            "обновила",
            "новую модель",
            "новая модель",
            "версия",
        )
        model_cues = (
            "gpt",
            "claude",
            "gemini",
            "grok",
            "llama",
            "qwen",
            "deepseek",
            "mistral",
            "sonnet",
            "opus",
            "haiku",
        )
        return any(cue in haystack for cue in release_cues) and any(
            cue in haystack for cue in model_cues
        )

    def _looks_like_free_offer(self, text: str) -> bool:
        haystack = text.lower()
        free_cues = (
            "absolutely free",
            "completely free",
            "totally free",
            "free tier",
            "free plan",
            "free forever",
            "free access",
            "no cost",
            "бесплатно",
            "бесплатный",
            "бесплатная",
            "бесплатный доступ",
        )
        return any(cue in haystack for cue in free_cues)

    def _smart_sentence_case(self, text: str) -> str:
        acronyms = {"AI", "API", "CLI", "GPU", "IDE", "LLM", "ML", "RL", "SDK", "SOTA", "SWE"}
        proper_names = {name.lower(): name for name in (
            "OpenAI", "ChatGPT", "Anthropic", "Claude", "Google", "Gemini",
            "DeepMind", "Cursor", "Windsurf", "Copilot", "GitHub", "Codex",
            "Grok", "xAI", "Meta", "Llama", "Qwen", "Mistral", "DeepSeek",
            "Aider", "Replit", "Mozilla", "Alibaba", "OpenHands", "GPT",
            "SWE-Bench", "Together", "Firefox", "Telegram", "YouTube",
        )}
        normalized: list[str] = []
        for idx, raw_word in enumerate(text.split()):
            prefix = ""
            suffix = ""
            word = raw_word
            while word and not word[0].isalnum():
                prefix += word[0]
                word = word[1:]
            while word and not word[-1].isalnum():
                suffix = word[-1] + suffix
                word = word[:-1]
            if not word:
                normalized.append(raw_word)
                continue
            upper_word = word.upper()
            lower_word = word.lower()
            if upper_word in acronyms:
                normalized.append(f"{prefix}{upper_word}{suffix}")
            elif lower_word in proper_names:
                normalized.append(f"{prefix}{proper_names[lower_word]}{suffix}")
            elif idx == 0:
                normalized.append(f"{prefix}{lower_word.capitalize()}{suffix}")
            else:
                normalized.append(f"{prefix}{lower_word}{suffix}")
        return " ".join(normalized)


def _safe_join_chunks(chunks: list[str], limit: int, separator: str = "\n\n") -> str:
    result = ""
    for chunk in chunks:
        candidate = f"{result}{separator}{chunk}" if result else chunk
        if len(candidate) > limit:
            break
        result = candidate
    return result or chunks[0][:limit] if chunks else ""


def _load_sources(settings: Settings) -> list[Source]:
    payload = load_default_sources(settings.sources_path)
    return [
        Source(
            key=str(row["key"]),
            name=str(row["name"]),
            kind=str(row["kind"]),
            location=str(row["location"]),
            tags=list(row.get("tags", [])),
            priority=int(row.get("priority", 1)),
            enabled=bool(row.get("enabled", True)),
            config=dict(row.get("config", {})),
        )
        for row in payload
    ]
