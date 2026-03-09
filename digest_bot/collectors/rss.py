from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import html
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import feedparser
import httpx

from digest_bot.collectors.base import Collector
from digest_bot.models import NewsItem, Source

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
}


class RSSCollector(Collector):
    def __init__(self, timeout_seconds: float = 20.0) -> None:
        self._timeout_seconds = timeout_seconds

    async def fetch(self, source: Source, since: datetime) -> list[NewsItem]:
        headers = dict(DEFAULT_HEADERS)
        headers.update(source.config.get("headers", {}))
        async with httpx.AsyncClient(
            timeout=self._timeout_seconds,
            follow_redirects=True,
            headers=headers,
        ) as client:
            response = await client.get(source.location)
            response.raise_for_status()

        feed = feedparser.parse(response.text)
        now = datetime.now(UTC)
        items: list[NewsItem] = []
        for entry in feed.entries[: source.config.get("max_items", 100)]:
            published_at = _parse_feed_datetime(entry, now)
            if published_at < since:
                continue

            summary_html = entry.get("summary", "")
            body_html = ""
            if entry.get("content"):
                body_html = entry["content"][0].get("value", "")
            text_summary = _strip_html(summary_html)
            text_body = _strip_html(body_html) or text_summary
            tags = list(source.tags)
            entry_tags = [tag.get("term") for tag in entry.get("tags", []) if tag.get("term")]
            tags.extend(str(tag) for tag in entry_tags)

            images = _extract_images(summary_html, entry)
            url = entry.get("link")
            external_id = entry.get("id") or url or entry.get("title", "")
            items.append(
                NewsItem(
                    source_key=source.key,
                    external_id=str(external_id),
                    title=html.unescape(str(entry.get("title", "")).strip()),
                    summary=text_summary[:700],
                    body=text_body[:4000],
                    url=str(url) if url else None,
                    published_at=published_at,
                    collected_at=now,
                    tags=list(dict.fromkeys(tag for tag in tags if tag)),
                    images=images,
                    raw={
                        "feed_url": source.location,
                        "domain": urlparse(url).netloc if url else None,
                    },
                )
            )
        return items


def _parse_feed_datetime(entry: dict, fallback: datetime) -> datetime:
    if entry.get("published_parsed"):
        return datetime(*entry.published_parsed[:6], tzinfo=UTC)
    if entry.get("updated_parsed"):
        return datetime(*entry.updated_parsed[:6], tzinfo=UTC)
    for key in ("published", "updated", "created"):
        if entry.get(key):
            try:
                value = parsedate_to_datetime(entry[key])
                if value.tzinfo is None:
                    return value.replace(tzinfo=UTC)
                return value.astimezone(UTC)
            except (TypeError, ValueError):
                continue
    return fallback


def _extract_images(summary_html: str, entry: dict) -> list[str]:
    images: list[str] = []
    for media_key in ("media_content", "media_thumbnail"):
        for media in entry.get(media_key, []):
            url = media.get("url")
            if url and url not in images:
                images.append(url)
    if summary_html:
        soup = BeautifulSoup(summary_html, "html.parser")
        for image in soup.find_all("img"):
            src = image.get("src")
            if src and src not in images:
                images.append(src)
    return images[:4]


def _strip_html(value: str) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(value, "html.parser")
    return " ".join(chunk.strip() for chunk in soup.stripped_strings)
