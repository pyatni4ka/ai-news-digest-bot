from __future__ import annotations

from collections.abc import Iterable
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from digest_bot.models import NewsItem


TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "ref",
    "fbclid",
    "gclid",
}


def assign_dedup_keys(items: Iterable[NewsItem]) -> None:
    for item in items:
        if item.url:
            item.dedup_key = normalize_url(item.url)
        else:
            item.dedup_key = f"{item.source_key}:{normalize_title(item.title)}"


def deduplicate(items: list[NewsItem]) -> list[NewsItem]:
    assign_dedup_keys(items)
    kept: list[NewsItem] = []
    for item in sorted(items, key=lambda row: (row.importance, len(row.body)), reverse=True):
        duplicate = False
        for existing in kept:
            if item.dedup_key == existing.dedup_key:
                duplicate = True
                break
            similarity = SequenceMatcher(
                a=normalize_title(item.title),
                b=normalize_title(existing.title),
            ).ratio()
            if similarity > 0.92:
                duplicate = True
                break
        if not duplicate:
            kept.append(item)
    return kept


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    filtered_qs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in TRACKING_QUERY_KEYS
    ]
    normalized = parsed._replace(query=urlencode(filtered_qs), fragment="")
    return urlunparse(normalized)


def normalize_title(title: str) -> str:
    return " ".join(title.lower().replace("-", " ").split())

