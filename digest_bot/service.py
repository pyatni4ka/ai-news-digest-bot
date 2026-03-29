from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from html import escape
import json
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto

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

    # --- Follow companies ---

    def follow_company(self, name: str) -> list[str]:
        companies = self._get_followed_set()
        companies.add(name.lower().strip())
        self._save_followed_set(companies)
        return sorted(companies)

    def unfollow_company(self, name: str) -> list[str]:
        companies = self._get_followed_set()
        companies.discard(name.lower().strip())
        self._save_followed_set(companies)
        return sorted(companies)

    def list_followed(self) -> list[str]:
        return sorted(self._get_followed_set())

    def _get_followed_set(self) -> set[str]:
        raw = self.repo.get_preference("followed_companies")
        if not raw:
            return set()
        return {c.strip() for c in raw.split(",") if c.strip()}

    def _save_followed_set(self, companies: set[str]) -> None:
        self.repo.set_preference("followed_companies", ",".join(sorted(companies)))

    # --- Rating-based recommendations ---

    def _apply_rating_boosts(self, items: list[NewsItem]) -> None:
        boosts = self._get_category_boosts()
        if not boosts:
            return
        for item in items:
            for cat in item.categories:
                if cat in boosts:
                    item.importance += boosts[cat] * 0.5

    def _get_category_boosts(self) -> dict[str, float]:
        raw = self.repo.get_preference("category_boosts")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}

    def _update_category_boosts(self, digest_id: int, rating: int) -> None:
        row = self.repo.get_digest(digest_id)
        if row is None:
            return
        _, payload = self.repo.hydrate_digest(row)
        section_counts = payload.get("summary_payload", {}).get("section_counts", {})
        if not section_counts:
            return
        boosts = self._get_category_boosts()
        delta = 0.3 if rating > 0 else -0.3
        for cat, count in section_counts.items():
            if count > 0 and cat not in ("noise",):
                boosts[cat] = max(-3.0, min(3.0, boosts.get(cat, 0.0) + delta))
        self.repo.set_preference("category_boosts", json.dumps(boosts))

    def latest_digest_id(self, slot: str | None = None) -> int | None:
        row = self.repo.get_latest_digest(slot)
        return None if row is None else int(row["id"])

    async def sync_sources(
        self,
        lookback_hours: int = 18,
        on_progress: Callable[[int, int, str], Any] | None = None,
    ) -> dict[str, int]:
        async with self._lock:
            sources = self.repo.list_sources(enabled_only=True)
            total = len(sources)
            since = datetime.now(UTC) - timedelta(hours=lookback_hours)
            collected: list[NewsItem] = []
            breaking: list[NewsItem] = []
            stats: Counter[str] = Counter()
            done_count = 0
            semaphore = asyncio.Semaphore(8)

            async def _fetch_one(source: Source) -> tuple[Source, list[NewsItem] | None, str | None]:
                nonlocal done_count
                async with semaphore:
                    timeout_seconds = float(
                        source.config.get(
                            "timeout_seconds",
                            25.0 if source.kind == "webpage" else 15.0,
                        )
                    )
                    try:
                        batch = await asyncio.wait_for(
                            self._fetch_source(source, since),
                            timeout=timeout_seconds,
                        )
                        done_count += 1
                        if on_progress is not None:
                            try:
                                await on_progress(done_count, total, source.name)
                            except Exception:
                                pass
                        return source, batch, None
                    except TimeoutError:
                        done_count += 1
                        return source, None, "timeout"
                    except Exception:
                        done_count += 1
                        return source, None, "error"

            results = await asyncio.gather(*[_fetch_one(s) for s in sources])

            for source, batch, error in results:
                if error:
                    stats[f"{error}:{source.key}"] += 1
                    continue
                if batch is None:
                    continue
                classify_items(batch, reset=True)
                for item in batch:
                    item.importance += source.priority * 0.6
                    if item.importance >= 10.0:
                        breaking.append(item)
                collected.extend(batch)
                stats[source.key] = len(batch)
            unique = deduplicate(collected)
            inserted = self.repo.save_news_items(unique)
            stats["inserted"] = inserted
            for item in breaking:
                await self._try_send_breaking(item)
            # Send notifications for followed companies
            followed = self._get_followed_set()
            if followed and inserted > 0:
                for item in unique:
                    await self._try_send_follow_alert(item, followed)
            return dict(stats)

    def get_complexity_level(self) -> int:
        val = self.repo.get_preference("complexity_level")
        return int(val) if val else 1

    def set_complexity_level(self, level: int) -> None:
        self.repo.set_preference("complexity_level", str(max(1, min(10, level))))

    def _auto_advance_complexity(self) -> int:
        level = self.get_complexity_level()
        count_str = self.repo.get_preference("digests_at_current_level")
        count = int(count_str) if count_str else 0
        count += 1
        if count >= 7 and level < 10:
            level += 1
            self.set_complexity_level(level)
            count = 0
        self.repo.set_preference("digests_at_current_level", str(count))
        return level

    def is_quiet_hours(self) -> bool:
        tz = ZoneInfo(self.settings.timezone)
        local_hour = datetime.now(UTC).astimezone(tz).hour
        start = self.settings.quiet_start
        end = self.settings.quiet_end
        if start <= end:
            return start <= local_hour < end
        return local_hour >= start or local_hour < end

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
        classify_items(items, reset=True)
        self._apply_rating_boosts(items)
        items = deduplicate(items)
        sectioned = select_sections(items, slot=selected_slot)
        story_sequence = build_story_sequence(
            selected_slot,
            sectioned,
            self._paragraph_count_for_slot(selected_slot),
        )
        paragraph_count = self._paragraph_count_for_slot(selected_slot)
        complexity_level = self._auto_advance_complexity()
        total_section_items = sum(len(section) for section in sectioned.values())
        if total_section_items < 2:
            summary = ""
        else:
            try:
                summary = await self.summarizer.summarize(
                    selected_slot,
                    {**sectioned, "story_order": story_sequence},
                    paragraph_count,
                    complexity_level,
                )
            except Exception:
                fallback = FallbackSummarizer()
                summary = await fallback.summarize(
                    selected_slot,
                    sectioned,
                    paragraph_count,
                    complexity_level,
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

    async def refresh_and_build_current_digest(
        self,
        on_progress: Callable[[int, int, str], Any] | None = None,
    ) -> int:
        await self.sync_sources(on_progress=on_progress)
        return await self.build_digest(self.current_slot())

    async def run_scheduled_digest(self, slot: str) -> None:
        if self.is_quiet_hours():
            return
        await self.sync_sources()
        digest_id = await self.build_digest(slot)
        await self.send_digest(digest_id)

    async def send_digest(self, digest_id: int) -> None:
        row = self.repo.get_digest(digest_id)
        if row is None:
            return
        text, payload = self.repo.hydrate_digest(row)
        story_media = payload.get("story_media", [])
        reply_markup = (
            digest_inline_keyboard(int(row["id"]), payload)
            if self.settings.interactive_bot
            else digest_static_keyboard(payload, self.settings.manual_digest_url)
        )
        await self._send_story_images(self.settings.admin_chat_id, story_media)
        await self.bot.send_message(
            chat_id=self.settings.admin_chat_id,
            text=self._format_digest_html(str(row["title"]), text, str(row["slot"]), payload),
            parse_mode="HTML",
            reply_markup=reply_markup,
        )

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
        level = self.get_complexity_level()
        quiet = f"{self.settings.quiet_start:02d}:00–{self.settings.quiet_end:02d}:00"
        return (
            "Текущие настройки\n"
            f"Часовой пояс: {self.settings.timezone}\n"
            f"Утро: {self.settings.morning_hour:02d}:00\n"
            f"Вечер: {self.settings.evening_hour:02d}:00\n"
            f"Тихие часы: {quiet}\n"
            f"Уровень сложности: {level}/10\n"
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

    def rate_digest(self, digest_id: int, rating: int) -> None:
        self.repo.save_rating(digest_id, rating)
        self._update_category_boosts(digest_id, rating)

    async def explain_simpler(self, digest_id: int) -> str:
        row = self.repo.get_digest(digest_id)
        if row is None:
            return "Дайджест не найден."
        text, _ = self.repo.hydrate_digest(row)
        if not hasattr(self.summarizer, "simplify"):
            return "Упрощение недоступно без LLM."
        return await self.summarizer.simplify(text)

    async def render_trends(self, days: int = 7) -> str:
        rows = self.repo.get_items_last_n_days(days)
        if not rows:
            return "Нет данных за последние дни."
        items = [self._row_to_item(row) for row in rows]
        classify_items(items, reset=True)
        category_counts: Counter[str] = Counter()
        keyword_counts: Counter[str] = Counter()
        for item in items:
            for cat in item.categories:
                if cat != "noise":
                    category_counts[cat] += 1
            for tag in item.tags:
                keyword_counts[tag.lower()] += 1
        lines = [f"Тренды за {days} дней ({len(items)} новостей)", ""]
        lines.append("Популярные темы:")
        for cat, count in category_counts.most_common(5):
            lines.append(f"  • {cat}: {count}")
        lines.append("")
        lines.append("Частые упоминания:")
        for keyword, count in keyword_counts.most_common(10):
            lines.append(f"  • {keyword}: {count}")
        return "\n".join(lines)

    async def compare_models(self, model_a: str, model_b: str) -> str:
        rows_a = self.repo.search_items_by_keyword(model_a)
        rows_b = self.repo.search_items_by_keyword(model_b)
        items_a = [{"title": str(r["title"]), "summary": str(r["summary"])} for r in rows_a[:10]]
        items_b = [{"title": str(r["title"]), "summary": str(r["summary"])} for r in rows_b[:10]]
        if not items_a and not items_b:
            return f"Нет данных для сравнения {model_a} и {model_b}."
        if not hasattr(self.summarizer, "compare"):
            return "Сравнение недоступно без LLM."
        return await self.summarizer.compare(items_a, items_b, model_a, model_b)

    def _paragraph_count_for_slot(self, slot: str) -> int:
        if slot == "monthly":
            return max(self.settings.default_digest_paragraphs, 10)
        if slot == "weekly":
            return max(self.settings.default_digest_paragraphs, 4)
        if slot in ("morning", "evening"):
            return max(self.settings.default_digest_paragraphs, 5)
        return max(self.settings.default_digest_paragraphs, 6)

    def _format_digest_html(self, title: str, text: str, slot: str, payload: dict | None = None) -> str:
        raw_paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
        paragraphs = [self._normalize_paragraph(paragraph) for paragraph in raw_paragraphs]
        # Deduplicate paragraphs by headline
        seen_headlines: set[str] = set()
        deduped_paragraphs: list[str] = []
        for paragraph in paragraphs:
            label, _ = self._split_label(paragraph)
            headline_key = (label or paragraph[:60]).lower().strip()
            if headline_key in seen_headlines:
                continue
            seen_headlines.add(headline_key)
            deduped_paragraphs.append(paragraph)
        paragraphs = deduped_paragraphs
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
        header = chunks[0]
        stories = chunks[1:]
        if stories:
            story_count = len(stories)
            counter = f"\n\n{story_count} {_pluralize_news(story_count)} в выпуске"
            body = "\n\n".join(stories) + counter
            return _safe_join_chunks([header, body], limit=4000)
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
        # Support newline separator (new _story_card format)
        if "\n" in paragraph:
            first_line, rest = paragraph.split("\n", 1)
            if 2 <= len(first_line.strip()) <= 90:
                return first_line.strip(), rest.strip()
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

    _BREAKING_WHITELIST = {"cursor", "anthropic", "openai", "gemini", "google"}

    async def _try_send_breaking(self, item: NewsItem) -> None:
        now = datetime.now(UTC)
        if self.is_quiet_hours():
            return
        # Only send breaking for whitelisted companies
        haystack = f"{item.title} {item.summary} {item.source_key}".lower()
        if not any(name in haystack for name in self._BREAKING_WHITELIST):
            return
        # Filter out GitHub noise (PRs, commits, CI)
        noise_patterns = (
            "merge pull request", "pull request", "commit", "ci/cd",
            "dependabot", "bump version", "changelog", "release notes",
            "arXiv", "arxiv", "paper:", "preprint",
        )
        if any(p in haystack for p in noise_patterns):
            return
        if not hasattr(self, "_breaking_sent"):
            self._breaking_sent: list[tuple[str, datetime]] = []
        # Deduplicate by dedup_key
        key = item.dedup_key or item.title
        if any(k == key for k, _ in self._breaking_sent):
            return
        # Max 3 alerts per day
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_count = sum(1 for _, ts in self._breaking_sent if ts >= day_start)
        if today_count >= 3:
            return
        # Cooldown 2 hours between alerts
        if self._breaking_sent:
            last_ts = max(ts for _, ts in self._breaking_sent)
            if now - last_ts < timedelta(hours=2):
                return
        # Build and send the alert
        from digest_bot.pipeline.digest_builder import _display_title, _emoji_for_item, _localized_fragment, gather_images
        emoji = _emoji_for_item(item)
        title = _display_title(item)
        fragment = _localized_fragment(item, limit=200)
        text = f"🚨 Breaking\n\n{emoji} <b>{escape(title)}</b>\n{escape(fragment)}"
        if item.url:
            text += f'\n<a href="{escape(item.url)}">Читать →</a>'
        images = gather_images([item], 1)
        sent = False
        if images:
            photo_input = self._photo_input(images[0])
            if photo_input is not None:
                try:
                    await self.bot.send_photo(
                        chat_id=self.settings.admin_chat_id,
                        photo=photo_input,
                        caption=text,
                        parse_mode="HTML",
                    )
                    sent = True
                except TelegramBadRequest:
                    pass
        if not sent:
            try:
                await self.bot.send_message(
                    chat_id=self.settings.admin_chat_id,
                    text=text,
                    parse_mode="HTML",
                )
            except TelegramBadRequest:
                return
        self._breaking_sent.append((key, now))

    async def _try_send_follow_alert(self, item: NewsItem, followed: set[str]) -> None:
        if self.is_quiet_hours():
            return
        haystack = f"{item.title} {item.summary} {item.source_key}".lower()
        # Filter GitHub noise
        noise_patterns = (
            "merge pull request", "pull request", "commit", "ci/cd",
            "dependabot", "bump version", "changelog",
        )
        if any(p in haystack for p in noise_patterns):
            return
        matched = [name for name in followed if name in haystack]
        if not matched:
            return
        # Deduplicate with breaking alerts
        if not hasattr(self, "_follow_sent"):
            self._follow_sent: set[str] = set()
        key = item.dedup_key or item.title
        if key in self._follow_sent:
            return
        # Also skip if already sent as breaking
        if hasattr(self, "_breaking_sent") and any(k == key for k, _ in self._breaking_sent):
            return
        # Max 5 follow alerts per sync
        if len(self._follow_sent) >= 5:
            return
        from digest_bot.pipeline.digest_builder import _display_title, _emoji_for_item, _localized_fragment
        emoji = _emoji_for_item(item)
        title = _display_title(item)
        fragment = _localized_fragment(item, limit=200)
        company = ", ".join(matched)
        text = f"📌 {company}\n\n{emoji} <b>{escape(title)}</b>\n{escape(fragment)}"
        if item.url:
            text += f'\n<a href="{escape(item.url)}">Читать →</a>'
        try:
            await self.bot.send_message(
                chat_id=self.settings.admin_chat_id,
                text=text,
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            return
        self._follow_sent.add(key)

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


def _pluralize_news(count: int) -> str:
    if 11 <= count % 100 <= 19:
        return "новостей"
    last = count % 10
    if last == 1:
        return "новость"
    if 2 <= last <= 4:
        return "новости"
    return "новостей"


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
