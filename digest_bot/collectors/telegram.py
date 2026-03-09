from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sqlite3

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.custom.message import Message

from digest_bot.collectors.base import Collector
from digest_bot.config import Settings, project_root
from digest_bot.models import NewsItem, Source


class TelegramCollector(Collector):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        if settings.tg_session_string:
            session: StringSession | str = StringSession(settings.tg_session_string)
        else:
            session_path = project_root() / f"{settings.tg_session_name}.session"
            session = str(session_path)
        self._client = TelegramClient(
            session,
            settings.tg_api_id,
            settings.tg_api_hash,
        )

    async def connect(self) -> None:
        if not self._client.is_connected():
            await self._client.connect()
        if not await self._client.is_user_authorized():
            raise RuntimeError(
                "Telegram session is not authorized. Run `ai-news-digest auth-telegram` first."
            )

    async def close(self) -> None:
        try:
            await self._client.disconnect()
        except sqlite3.OperationalError:
            # Another process may still hold the session sqlite file.
            pass

    async def interactive_auth(self) -> None:
        await self._client.start(phone=self._settings.tg_phone)

    async def export_session_string(self) -> str:
        await self.connect()
        return StringSession.save(self._client.session)

    async def fetch(self, source: Source, since: datetime) -> list[NewsItem]:
        await self.connect()
        entity = source.config.get("entity", source.location)
        max_items = int(source.config.get("max_items", 300))
        resolved = await self._client.get_entity(entity)
        username = getattr(resolved, "username", None)

        items: list[NewsItem] = []
        async for message in self._client.iter_messages(resolved, limit=max_items):
            if message.date is None:
                continue
            published_at = message.date.astimezone(UTC)
            if published_at < since:
                break
            item = await self._message_to_item(source, message, username)
            if item is not None:
                items.append(item)
        return items

    async def _message_to_item(
        self,
        source: Source,
        message: Message,
        username: str | None,
    ) -> NewsItem | None:
        text = (message.raw_text or "").strip()
        if not text and not message.photo and not message.document:
            return None

        title = _derive_title(text)
        now = datetime.now(UTC)
        url = f"https://t.me/{username}/{message.id}" if username else None
        images: list[str] = []
        if message.photo or (
            message.document and getattr(message.document, "mime_type", "").startswith("image/")
        ):
            path = await self._download_media(source.key, message)
            if path:
                images.append(path)

        return NewsItem(
            source_key=source.key,
            external_id=str(message.id),
            title=title,
            summary=text[:700],
            body=text[:5000],
            url=url,
            published_at=message.date.astimezone(UTC),
            collected_at=now,
            tags=list(dict.fromkeys(source.tags)),
            images=images,
            raw={"message_id": message.id},
        )

    async def _download_media(self, source_key: str, message: Message) -> str | None:
        safe_source = source_key.replace(":", "_").replace("@", "")
        target_dir = Path(self._settings.media_dir) / safe_source
        target_dir.mkdir(parents=True, exist_ok=True)
        base = target_dir / str(message.id)
        path = await self._client.download_media(message, file=str(base))
        return str(path) if path else None


def _derive_title(text: str) -> str:
    if not text:
        return "Telegram update"
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if len(first_line) > 120:
        return first_line[:117].rstrip() + "..."
    return first_line
