from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import html
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import feedparser
import httpx

from digest_bot.collectors.base import Collector
from digest_bot.image_selection import ImageCandidate, select_best_image_candidates
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
            published_at = _parse_feed_datetime(entry)
            if published_at is None:
                continue
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


def _parse_feed_datetime(entry: dict) -> datetime | None:
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
    return None


def _extract_images(summary_html: str, entry: dict) -> list[str]:
    candidates: list[ImageCandidate] = []
    for media_key in ("media_content", "media_thumbnail"):
        for media in entry.get(media_key, []):
            url = media.get("url")
            if url:
                candidates.append(
                    ImageCandidate(
                        url=str(url),
                        source_hint="media",
                        width=_parse_dimension(media.get("width")),
                        height=_parse_dimension(media.get("height")),
                    )
                )
    if summary_html:
        soup = BeautifulSoup(summary_html, "html.parser")
        for image in soup.find_all("img"):
            src = _image_source_from_tag(image)
            if not src:
                continue
            candidates.append(
                ImageCandidate(
                    url=src,
                    source_hint="img",
                    alt=str(image.get("alt", "")),
                    class_names=tuple(str(value) for value in image.get("class", []) if value),
                    element_id=str(image.get("id", "")),
                    width=_parse_dimension(image.get("width")),
                    height=_parse_dimension(image.get("height")),
                )
            )
    return select_best_image_candidates(candidates, limit=3, min_score=10)


def _strip_html(value: str) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(value, "html.parser")
    return " ".join(chunk.strip() for chunk in soup.stripped_strings)


def _image_source_from_tag(image) -> str | None:
    for attr in ("src", "data-src", "data-image"):
        value = image.get(attr)
        if value:
            return str(value)
    for attr in ("srcset", "data-srcset"):
        value = image.get(attr)
        if value:
            first = str(value).split(",")[0].strip().split(" ")[0]
            if first:
                return first
    return None


def _parse_dimension(value: object) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else None
