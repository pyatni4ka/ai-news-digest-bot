from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from digest_bot.models import Digest, DigestButton, DigestSection, NewsItem


def compute_window(slot: str, now: datetime, timezone_name: str) -> tuple[datetime, datetime]:
    return compute_window_with_hours(slot, now, timezone_name, morning_hour=9, evening_hour=19)


def compute_window_with_hours(
    slot: str,
    now: datetime,
    timezone_name: str,
    morning_hour: int,
    evening_hour: int,
) -> tuple[datetime, datetime]:
    tz = ZoneInfo(timezone_name)
    local_now = now.astimezone(tz)
    if slot == "morning":
        end_local = local_now.replace(hour=morning_hour, minute=0, second=0, microsecond=0)
        if local_now < end_local:
            end_local = end_local - timedelta(days=1)
        start_local = end_local - timedelta(hours=14)
    elif slot == "evening":
        end_local = local_now.replace(hour=evening_hour, minute=0, second=0, microsecond=0)
        if local_now < end_local:
            end_local = end_local - timedelta(days=1)
        start_local = end_local - timedelta(hours=10)
    elif slot == "monthly":
        end_local = local_now
        start_local = end_local - timedelta(days=30)
    else:
        end_local = local_now
        start_local = end_local - timedelta(hours=12)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def build_digest(
    slot: str,
    items: list[NewsItem],
    now: datetime,
    timezone_name: str,
    summary_text: str,
    paragraph_count: int,
    morning_hour: int = 9,
    evening_hour: int = 19,
) -> Digest:
    start_at, end_at = compute_window_with_hours(
        slot,
        now,
        timezone_name,
        morning_hour=morning_hour,
        evening_hour=evening_hour,
    )
    sections = select_sections(items, slot=slot)
    resource_links = gather_links(sections["resources"], 5)
    model_links = gather_links(sections["models"], 3)
    image_paths = gather_images(items, 10)
    paragraphs = split_paragraphs(summary_text, paragraph_count)
    if not paragraphs:
        paragraphs = fallback_digest_paragraphs(slot, sections)

    section_map = {
        key: DigestSection(
            key=key,
            title=title_for_section(key),
            paragraph=fallback_section_details(title_for_section(key), section_items),
            item_ids=[getattr(item, "db_id", 0) for item in section_items],
            links=gather_links(section_items, 5),
        )
        for key, section_items in sections.items()
        if section_items
    }

    buttons = [
        DigestButton(text="Подробнее", action="more"),
        DigestButton(text="Только coding", action="section", value="coding"),
        DigestButton(text="Только vibe coding", action="section", value="vibe_coding"),
        DigestButton(text="Ресурсы", action="links", value="resources"),
        DigestButton(
            text="Открыть модель",
            action="open_model",
            url=model_links[0] if model_links else None,
        ),
        DigestButton(text="Сохранить", action="save"),
        DigestButton(text="Меньше такого", action="noise"),
        DigestButton(text="Обновить сейчас", action="refresh"),
    ]
    buttons = [button for button in buttons if button.url or button.action != "open_model"]

    return Digest(
        slot=slot,
        start_at=start_at,
        end_at=end_at,
        title=build_title(slot, start_at, end_at, timezone_name),
        paragraphs=paragraphs,
        summary_payload={
            "section_counts": {key: len(value) for key, value in sections.items()},
            "resource_links": resource_links,
            "model_links": model_links,
            "generated_at": now.isoformat(),
        },
        buttons=buttons,
        section_map=section_map,
        image_paths=image_paths,
    )


def select_sections(items: list[NewsItem], slot: str = "manual") -> dict[str, list[NewsItem]]:
    categorized: dict[str, list[NewsItem]] = defaultdict(list)
    for item in sorted(items, key=lambda row: (row.importance, row.published_at), reverse=True):
        categorized["headline"].append(item)
        for category in item.categories:
            categorized[category].append(item)
    limits = {
        "headline": 10 if slot == "monthly" else 6,
        "models": 8 if slot == "monthly" else 4,
        "comparisons": 6 if slot == "monthly" else 4,
        "coding": 8 if slot == "monthly" else 5,
        "vibe_coding": 8 if slot == "monthly" else 5,
        "resources": 6 if slot == "monthly" else 5,
    }
    return {
        "headline": unique_first(categorized["headline"], limits["headline"]),
        "models": unique_first(categorized["models"] + categorized["release"], limits["models"]),
        "comparisons": unique_first(categorized["comparisons"], limits["comparisons"]),
        "coding": unique_first(categorized["coding"], limits["coding"]),
        "vibe_coding": unique_first(categorized["vibe_coding"], limits["vibe_coding"]),
        "resources": unique_first(categorized["resources"], limits["resources"]),
    }


def unique_first(items: list[NewsItem], limit: int) -> list[NewsItem]:
    seen: set[str] = set()
    result: list[NewsItem] = []
    for item in items:
        key = item.dedup_key or item.title
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def fallback_digest_paragraphs(slot: str, sections: dict[str, list[NewsItem]]) -> list[str]:
    limit = 10 if slot == "monthly" else 6
    paragraphs = build_story_cards(slot, sections, limit)
    if paragraphs:
        return paragraphs
    label = "последний месяц" if slot == "monthly" else "текущее окно"
    return [f"📭 За {label} почти не было релевантных AI-новостей."]


def split_paragraphs(text: str, limit: int) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    return paragraphs[:limit]


def build_title(slot: str, start_at: datetime, end_at: datetime, timezone_name: str) -> str:
    tz = ZoneInfo(timezone_name)
    local_end = end_at.astimezone(tz)
    label = (
        "Утренний"
        if slot == "morning"
        else "Вечерний"
        if slot == "evening"
        else "Месячный"
        if slot == "monthly"
        else "Оперативный"
    )
    return f"{label} AI digest • {local_end:%d.%m %H:%M}"


def title_for_section(key: str) -> str:
    return {
        "headline": "Главное",
        "models": "Модели и релизы",
        "comparisons": "Сравнения",
        "coding": "Coding",
        "vibe_coding": "Vibe coding",
        "resources": "Ресурсы",
    }.get(key, key)


def fallback_section_details(title: str, items: list[NewsItem]) -> str:
    lines = [title]
    for item in items[:6]:
        lines.append("")
        lines.append(_story_card(item, limit=220))
    return "\n".join(lines)


def build_story_cards(
    slot: str,
    sections: dict[str, list[NewsItem]],
    limit: int,
) -> list[str]:
    main_limit = max(limit - 1, 1)
    pool = unique_first(
        sections.get("models", [])
        + sections.get("comparisons", [])
        + sections.get("coding", [])
        + sections.get("vibe_coding", [])
        + sections.get("resources", [])
        + sections.get("headline", []),
        main_limit,
    )
    paragraphs = [_story_card(item) for item in pool[:main_limit]]
    minor_items = _minor_items(sections, pool, 4 if slot == "monthly" else 3)
    if minor_items:
        paragraphs.append(_minor_block(minor_items))
    return paragraphs[:limit]


def _story_card(item: NewsItem, limit: int = 200) -> str:
    title = _display_title(item)
    fragment = _compact_fragment(item.summary or item.body or item.title, limit=limit)
    return f"{_emoji_for_item(item)} {title}: {fragment}"


def _display_title(item: NewsItem) -> str:
    title = " ".join(item.title.split())
    if len(title) > 78:
        title = title[:75].rstrip() + "..."
    if _is_totally_free(item):
        title = f"{title} — АБСОЛЮТНО БЕСПЛАТНО"
    if _is_model_release(item):
        return title.upper()
    return title


def _compact_fragment(value: str, limit: int) -> str:
    text = " ".join(value.split())
    return text[:limit].rstrip(" -|,:;")


def _minor_items(
    sections: dict[str, list[NewsItem]],
    main_items: list[NewsItem],
    limit: int,
) -> list[NewsItem]:
    main_keys = {item.dedup_key or item.title for item in main_items}
    pool = unique_first(
        sections.get("headline", [])
        + sections.get("resources", [])
        + sections.get("coding", [])
        + sections.get("vibe_coding", []),
        20,
    )
    result: list[NewsItem] = []
    for item in pool:
        key = item.dedup_key or item.title
        if key in main_keys:
            continue
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _minor_block(items: list[NewsItem]) -> str:
    parts = []
    for item in items:
        title = _display_title(item)
        fragment = _compact_fragment(item.summary or item.body or item.title, limit=90)
        parts.append(f"{title} — {fragment}")
    return "🗞 Короткой строкой: " + " | ".join(parts)


def _is_model_release(item: NewsItem) -> bool:
    categories = set(item.categories)
    if "models" not in categories and "release" not in categories:
        return False
    haystack = f"{item.title} {item.summary} {item.body} {' '.join(item.tags)}".lower()
    release_cues = (
        "introducing",
        "announce",
        "announcing",
        "released",
        "launch",
        "launches",
        "available",
        "preview",
        "beta",
        "alpha",
        "open source",
        "open-source",
        "model",
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
        "voxtral",
        "sam 3",
    )
    return any(cue in haystack for cue in release_cues) or any(cue in haystack for cue in model_cues)


def _is_totally_free(item: NewsItem) -> bool:
    haystack = f"{item.title} {item.summary} {item.body} {' '.join(item.tags)}".lower()
    free_cues = (
        "absolutely free",
        "completely free",
        "totally free",
        "free tier",
        "free plan",
        "free forever",
        "no cost",
        "free access",
        "free",
    )
    return any(cue in haystack for cue in free_cues)


def _emoji_for_item(item: NewsItem) -> str:
    categories = set(item.categories)
    haystack = f"{item.title} {item.summary} {item.body}".lower()
    if "models" in categories or "release" in categories:
        return "🚀"
    if "comparisons" in categories:
        return "⚖️"
    if "coding" in categories:
        return "💻"
    if "vibe_coding" in categories:
        return "🛠️"
    if "resources" in categories:
        return "🧰"
    if any(term in haystack for term in ("security", "vulnerability", "zero-day", "firefox")):
        return "🔐"
    if any(term in haystack for term in ("agent", "automation", "workflow", "computer use")):
        return "🤖"
    return "📌"


def gather_links(items: list[NewsItem], limit: int) -> list[str]:
    links: list[str] = []
    for item in items:
        if item.url and item.url not in links:
            links.append(item.url)
        if len(links) >= limit:
            break
    return links


def gather_images(items: list[NewsItem], limit: int) -> list[str]:
    images: list[str] = []
    for item in items:
        for image in item.images:
            if image not in images:
                images.append(image)
            if len(images) >= limit:
                return images
    return images


def serialize_news_items(items: list[NewsItem]) -> list[dict[str, Any]]:
    return [
        {
            "title": item.title,
            "summary": item.summary,
            "body": item.body[:1200],
            "url": item.url,
            "tags": item.tags,
            "categories": item.categories,
            "importance": item.importance,
            "published_at": item.published_at.isoformat(),
        }
        for item in items
    ]
