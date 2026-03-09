from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import httpx

from digest_bot.collectors.base import Collector
from digest_bot.models import NewsItem, Source

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
}


class WebpageCollector(Collector):
    def __init__(self, timeout_seconds: float = 20.0) -> None:
        self._timeout_seconds = timeout_seconds

    async def fetch(self, source: Source, since: datetime) -> list[NewsItem]:
        listing_url = source.config.get("listing_url", source.location)
        include_patterns = source.config.get("include_patterns", [])
        exclude_patterns = source.config.get("exclude_patterns", [])
        max_items = int(source.config.get("max_items", 40))
        headers = dict(DEFAULT_HEADERS)
        headers.update(source.config.get("headers", {}))
        async with httpx.AsyncClient(
            timeout=self._timeout_seconds,
            follow_redirects=True,
            headers=headers,
        ) as client:
            response = await client.get(listing_url)
            response.raise_for_status()
            candidate_urls = _extract_article_urls(
                html=response.text,
                listing_url=listing_url,
                include_patterns=include_patterns,
                exclude_patterns=exclude_patterns,
                limit=max_items,
            )
            items: list[NewsItem] = []
            for article_url in candidate_urls:
                try:
                    article = await client.get(article_url)
                    article.raise_for_status()
                except httpx.HTTPError:
                    continue
                item = _parse_article(source, article_url, article.text)
                if item is None or item.published_at < since:
                    continue
                items.append(item)
        return items


def _extract_article_urls(
    html: str,
    listing_url: str,
    include_patterns: Iterable[str],
    exclude_patterns: Iterable[str],
    limit: int,
) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    domain = urlparse(listing_url).netloc
    urls: list[str] = []
    for anchor in soup.find_all("a", href=True):
        absolute = urljoin(listing_url, anchor["href"])
        if urlparse(absolute).netloc != domain:
            continue
        if include_patterns and not any(pattern in absolute for pattern in include_patterns):
            continue
        if exclude_patterns and any(pattern in absolute for pattern in exclude_patterns):
            continue
        if absolute not in urls:
            urls.append(absolute)
        if len(urls) >= limit:
            break
    return urls


def _parse_article(source: Source, article_url: str, html: str) -> NewsItem | None:
    soup = BeautifulSoup(html, "html.parser")
    title = (
        _meta_content(soup, "meta[property='og:title']")
        or _meta_content(soup, "meta[name='twitter:title']")
        or _text_of_first(soup, ["h1", "title"])
    )
    if not title:
        return None

    published_at = _parse_datetime(
        _meta_content(soup, "meta[property='article:published_time']")
        or _meta_content(soup, "meta[name='article:published_time']")
        or _tag_attr(soup, "time", "datetime")
    )
    published_at = published_at or datetime.now(UTC)

    body_text = _extract_body_text(soup)
    summary = body_text[:700]
    images = _extract_images(soup, article_url)
    now = datetime.now(UTC)
    return NewsItem(
        source_key=source.key,
        external_id=article_url,
        title=title.strip(),
        summary=summary,
        body=body_text[:5000],
        url=article_url,
        published_at=published_at,
        collected_at=now,
        tags=list(dict.fromkeys(source.tags)),
        images=images,
        raw={"listing_url": source.config.get("listing_url", source.location)},
    )


def _meta_content(soup: BeautifulSoup, selector: str) -> str | None:
    tag = soup.select_one(selector)
    if tag is None:
        return None
    content = tag.get("content")
    return str(content).strip() if content else None


def _text_of_first(soup: BeautifulSoup, selectors: list[str]) -> str | None:
    for selector in selectors:
        tag = soup.select_one(selector)
        if tag and tag.get_text(strip=True):
            return tag.get_text(" ", strip=True)
    return None


def _tag_attr(soup: BeautifulSoup, tag_name: str, attr: str) -> str | None:
    tag = soup.find(tag_name)
    if tag is None:
        return None
    value = tag.get(attr)
    return str(value).strip() if value else None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _extract_body_text(soup: BeautifulSoup) -> str:
    container = soup.find("article") or soup.find("main") or soup
    paragraphs = [tag.get_text(" ", strip=True) for tag in container.find_all("p")]
    dense = [paragraph for paragraph in paragraphs if len(paragraph) > 40]
    return "\n".join(dense[:14])


def _extract_images(soup: BeautifulSoup, article_url: str) -> list[str]:
    images: list[str] = []
    for selector in (
        "meta[property='og:image']",
        "meta[name='twitter:image']",
        "img",
    ):
        if selector == "img":
            for image in soup.find_all("img"):
                src = image.get("src")
                if src:
                    absolute = urljoin(article_url, src)
                    if absolute not in images:
                        images.append(absolute)
        else:
            meta = soup.select_one(selector)
            if meta and meta.get("content"):
                absolute = urljoin(article_url, str(meta["content"]))
                if absolute not in images:
                    images.append(absolute)
    return images[:4]
