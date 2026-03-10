from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import httpx

from digest_bot.collectors.base import Collector
from digest_bot.image_selection import ImageCandidate, select_best_image_candidates
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
            candidate_articles = _extract_article_candidates(
                html=response.text,
                listing_url=listing_url,
                include_patterns=include_patterns,
                exclude_patterns=exclude_patterns,
                limit=max_items,
            )
            items: list[NewsItem] = []
            for article_url, listing_published_at in candidate_articles:
                try:
                    article = await client.get(article_url)
                    article.raise_for_status()
                except httpx.HTTPError:
                    continue
                item = _parse_article(source, article_url, article.text, listing_published_at)
                if item is None or item.published_at < since:
                    continue
                items.append(item)
        return items


def _extract_article_candidates(
    html: str,
    listing_url: str,
    include_patterns: Iterable[str],
    exclude_patterns: Iterable[str],
    limit: int,
) -> list[tuple[str, datetime | None]]:
    soup = BeautifulSoup(html, "html.parser")
    domain = urlparse(listing_url).netloc
    candidates: list[tuple[str, datetime | None]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        absolute = urljoin(listing_url, anchor["href"])
        if urlparse(absolute).netloc != domain:
            continue
        if include_patterns and not any(pattern in absolute for pattern in include_patterns):
            continue
        if exclude_patterns and any(pattern in absolute for pattern in exclude_patterns):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        candidates.append((absolute, _extract_listing_datetime(anchor)))
        if len(candidates) >= limit:
            break
    return candidates


def _parse_article(
    source: Source,
    article_url: str,
    html: str,
    listing_published_at: datetime | None = None,
) -> NewsItem | None:
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
        or _meta_content(soup, "meta[name='publish-date']")
        or _meta_content(soup, "meta[name='date']")
        or _tag_attr(soup, "time", "datetime")
        or _extract_jsonld_datetime(soup)
    )
    published_at = published_at or listing_published_at
    if published_at is None:
        return None

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


def _extract_jsonld_datetime(soup: BeautifulSoup) -> str | None:
    for script in soup.select("script[type='application/ld+json']"):
        content = script.string or script.get_text(" ", strip=True)
        if not content:
            continue
        match = re.search(r'"datePublished"\s*:\s*"([^"]+)"', content)
        if match:
            return match.group(1)
    return None


def _extract_listing_datetime(anchor) -> datetime | None:
    current = anchor
    for _ in range(4):
        if current is None:
            break
        text = current.get_text(" ", strip=True)
        parsed = _parse_human_datetime(text)
        if parsed is not None:
            return parsed
        current = current.parent
    return None


def _parse_human_datetime(value: str) -> datetime | None:
    iso_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", value)
    if iso_match:
        return _parse_datetime(iso_match.group(1))

    month_match = re.search(
        r"\b("
        r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
        r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
        r")\s+(\d{1,2}),\s*(20\d{2})\b",
        value,
        re.IGNORECASE,
    )
    if month_match:
        normalized = f"{month_match.group(1)} {month_match.group(2)} {month_match.group(3)}"
        try:
            parsed = datetime.strptime(normalized, "%b %d %Y")
        except ValueError:
            try:
                parsed = datetime.strptime(normalized, "%B %d %Y")
            except ValueError:
                return None
        return parsed.replace(tzinfo=UTC)
    return None


def _extract_body_text(soup: BeautifulSoup) -> str:
    container = soup.find("article") or soup.find("main") or soup
    paragraphs = [tag.get_text(" ", strip=True) for tag in container.find_all("p")]
    dense = [paragraph for paragraph in paragraphs if len(paragraph) > 40]
    return "\n".join(dense[:14])


def _extract_images(soup: BeautifulSoup, article_url: str) -> list[str]:
    candidates: list[ImageCandidate] = []
    for selector in ("meta[property='og:image']", "meta[name='twitter:image']"):
        meta = soup.select_one(selector)
        if meta and meta.get("content"):
            candidates.append(ImageCandidate(url=str(meta["content"]), source_hint="meta"))

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
                parent_tags=_ancestor_tags(image),
            )
        )

    return select_best_image_candidates(candidates, limit=3, base_url=article_url, min_score=10)


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


def _ancestor_tags(image, depth: int = 4) -> tuple[str, ...]:
    tags: list[str] = []
    current = image.parent
    for _ in range(depth):
        if current is None or not getattr(current, "name", None):
            break
        tags.append(str(current.name))
        current = current.parent
    return tuple(tags)


def _parse_dimension(value: object) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else None
