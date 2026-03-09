from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
import re
from typing import Any
from zoneinfo import ZoneInfo

from digest_bot.models import Digest, DigestButton, DigestSection, NewsItem


WATCHLIST_NAMES = (
    "Claude Code",
    "OpenHands",
    "Together AI",
    "ChatGPT",
    "Anthropic",
    "OpenAI",
    "Google",
    "Gemini",
    "DeepMind",
    "Cursor",
    "Windsurf",
    "Copilot",
    "GitHub",
    "Codex",
    "Claude",
    "Grok",
    "xAI",
    "Meta",
    "Llama",
    "Qwen",
    "Mistral",
    "DeepSeek",
    "Aider",
    "Replit",
    "Mozilla",
    "Alibaba",
)

MODEL_PATTERNS = (
    r"Claude(?:\s+(?:Sonnet|Opus|Haiku))?\s+[A-Za-z0-9.\-]+",
    r"GPT[-\s]?[A-Za-z0-9.\-]+",
    r"Gemini\s+[A-Za-z0-9.\-]+",
    r"Grok\s+[A-Za-z0-9.\-]+",
    r"Llama\s*[A-Za-z0-9.\-]+",
    r"Qwen\s*[A-Za-z0-9.\-]+",
    r"DeepSeek\s*[A-Za-z0-9.\-]+",
    r"Mistral\s*[A-Za-z0-9.\-]+",
    r"Codex(?:\s+[A-Za-z0-9.\-]+)?",
    r"Claude Code(?:\s+[A-Za-z0-9.\-]+)?",
)

OBJECT_REPLACEMENTS = (
    ("background coding agent", "background coding agent"),
    ("coding agent", "coding agent"),
    ("agentic ide", "agentic IDE"),
    ("ide agents", "IDE-агентов"),
    ("ide agent", "IDE-агента"),
    ("repo agent", "repo agent"),
    ("developer app", "developer app"),
    ("desktop app", "desktop app"),
    ("free plan", "бесплатный plan"),
    ("free tier", "free tier"),
    ("computer use", "computer use"),
    ("security", "security"),
    ("benchmark", "benchmark"),
    ("benchmarks", "benchmarks"),
    ("open source", "open-source"),
)

FEATURE_GROUPS = (
    (("coding", "code", "refactor", "debug"), "coding и работу с кодом"),
    (("agent", "agents", "agentic"), "agents"),
    (("repo", "repository", "repositories"), "работу по repo"),
    (("terminal",), "terminal"),
    (("ide", "editor", "vscode"), "IDE"),
    (("benchmark", "leaderboard", "swe-bench", "arena", "eval"), "benchmarks"),
    (("long context", "context window"), "long context"),
    (("computer use",), "computer use"),
    (("security", "zero-day", "vulnerability"), "security"),
    (("open source", "open-source"), "open-source"),
    (("free plan", "free tier", "free forever", "free access", "no cost", "бесплатно"), "бесплатный доступ"),
    (("tool use",), "tool use"),
    (("api", "sdk"), "API"),
)

GENERIC_SUBJECTS = {
    "new",
    "major",
    "latest",
    "introducing",
    "announcing",
    "breaking",
}


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
    dev_tool_links = gather_links(sections["dev_tools"], 3)
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
        DigestButton(text="Только dev tools", action="section", value="dev_tools"),
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
            "dev_tool_links": dev_tool_links,
            "generated_at": now.isoformat(),
        },
        buttons=buttons,
        section_map=section_map,
        image_paths=image_paths,
    )


def select_sections(items: list[NewsItem], slot: str = "manual") -> dict[str, list[NewsItem]]:
    relevant_items = _filter_relevant_items(items)
    categorized: dict[str, list[NewsItem]] = defaultdict(list)
    for item in sorted(relevant_items, key=lambda row: (row.importance, row.published_at), reverse=True):
        categorized["headline"].append(item)
        for category in item.categories:
            categorized[category].append(item)
    limits = {
        "headline": 10 if slot == "monthly" else 6,
        "models": 8 if slot == "monthly" else 4,
        "comparisons": 6 if slot == "monthly" else 4,
        "coding": 8 if slot == "monthly" else 5,
        "vibe_coding": 8 if slot == "monthly" else 5,
        "dev_tools": 8 if slot == "monthly" else 5,
        "resources": 6 if slot == "monthly" else 5,
    }
    return {
        "headline": unique_first(categorized["headline"], limits["headline"]),
        "models": unique_first(categorized["models"] + categorized["release"], limits["models"]),
        "comparisons": unique_first(categorized["comparisons"], limits["comparisons"]),
        "coding": unique_first(categorized["coding"], limits["coding"]),
        "vibe_coding": unique_first(categorized["vibe_coding"], limits["vibe_coding"]),
        "dev_tools": unique_first(categorized["dev_tools"], limits["dev_tools"]),
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
        "dev_tools": "Dev tools",
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
    dev_items = _dev_tool_items(sections, slot)
    reserved_slots = 1 if dev_items else 0
    main_limit = max(limit - reserved_slots - 1, 1)
    pool = unique_first(
        sections.get("models", [])
        + sections.get("comparisons", [])
        + sections.get("coding", [])
        + sections.get("vibe_coding", [])
        + sections.get("resources", [])
        + sections.get("headline", []),
        max(limit * 3, 12),
    )
    dev_keys = {item.dedup_key or item.title for item in dev_items}
    main_candidates = [item for item in pool if (item.dedup_key or item.title) not in dev_keys]
    if not main_candidates and dev_items:
        main_candidates = dev_items[:1]
        dev_items = dev_items[1:]
        reserved_slots = 1 if dev_items else 0
        main_limit = max(limit - reserved_slots - 1, 1)
    selected_main = main_candidates[:main_limit]
    minor_items = _minor_items(sections, selected_main + dev_items, 4 if slot == "monthly" else 3)
    if not minor_items:
        selected_main = main_candidates[: max(limit - reserved_slots, 1)]
    paragraphs = [_story_card(item) for item in selected_main]
    if dev_items:
        paragraphs.append(_dev_tools_block(dev_items))
    if minor_items:
        paragraphs.append(_minor_block(minor_items))
    return paragraphs[:limit]


def _story_card(item: NewsItem, limit: int = 200) -> str:
    title = _display_title(item)
    fragment = _localized_fragment(item, limit=limit)
    return f"{_emoji_for_item(item)} {title}: {fragment}"


def _display_title(item: NewsItem) -> str:
    title = _localized_title(item)
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
        + sections.get("dev_tools", [])
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
        fragment = _localized_fragment(item, limit=90)
        parts.append(f"{title} — {fragment}")
    return "🗞 Короткой строкой: " + " | ".join(parts)


def _dev_tool_items(sections: dict[str, list[NewsItem]], slot: str) -> list[NewsItem]:
    limit = 4 if slot == "monthly" else 3
    items = unique_first(
        sections.get("dev_tools", []) + sections.get("vibe_coding", []),
        limit,
    )
    return items if len(items) >= 2 else []


def _dev_tools_block(items: list[NewsItem]) -> str:
    parts = []
    for item in items:
        title = _display_title(item)
        fragment = _localized_fragment(item, limit=110)
        parts.append(f"{title} — {fragment}")
    return "🧑‍💻 Dev tools: " + " | ".join(parts)


def _filter_relevant_items(items: list[NewsItem]) -> list[NewsItem]:
    return [item for item in items if "noise" not in set(item.categories)]


def _localized_title(item: NewsItem) -> str:
    title = " ".join(item.title.split())
    if _contains_cyrillic(title):
        return title

    subject = _extract_subject(item)
    verb = _select_verb(item)
    obj = _extract_object(item, subject)
    categories = set(item.categories)

    if subject and obj:
        return f"{subject} {verb} {obj}"
    if subject and {"models", "release"} & categories:
        return f"{subject} {verb} новую модель"
    if subject and "comparisons" in categories:
        return f"{subject} показала новое сравнение моделей"
    if subject and {"dev_tools", "vibe_coding", "coding"} & categories:
        return f"{subject} {verb} обновление для разработки"
    if "comparisons" in categories:
        return "Вышло новое сравнение AI-моделей"
    if {"models", "release"} & categories:
        return "Вышел новый релиз AI-модели"
    if {"dev_tools", "vibe_coding", "coding"} & categories:
        return "Вышел новый апдейт для разработки"
    if "resources" in categories:
        return "Появился новый AI-инструмент"
    return title


def _localized_fragment(item: NewsItem, limit: int) -> str:
    source = item.summary or item.body or item.title
    if _contains_cyrillic(source):
        return _compact_fragment(source, limit=limit)

    categories = set(item.categories)
    features = _extract_features(item)
    details: list[str] = []
    if {"models", "release"} & categories:
        if features:
            details.append(f"Релиз сфокусирован на {_join_features(features)}.")
        else:
            details.append("Это заметный апдейт в линейке AI-моделей.")
    elif "comparisons" in categories:
        if features:
            details.append(f"Сравнение смотрит на {_join_features(features)}.")
        else:
            details.append("Материал сравнивает актуальные AI-модели и их позиции.")
    elif {"dev_tools", "vibe_coding", "coding"} & categories:
        if features:
            details.append(f"Апдейт затрагивает {_join_features(features)}.")
        else:
            details.append("Новость важна для IDE, AI-агентов и повседневной разработки.")
    elif "resources" in categories:
        if features:
            details.append(f"Инструмент делает упор на {_join_features(features)}.")
        else:
            details.append("Речь идет о новом AI-инструменте или приложении.")
    else:
        details.append("Источник сообщает о заметном AI-апдейте и его практической пользе.")

    if _is_totally_free(item):
        details.append("Доступ открыт бесплатно.")
    elif _looks_open_source(item):
        details.append("Проект вышел в open-source.")

    text = " ".join(details)
    return _compact_fragment(text, limit=limit)


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


def _looks_open_source(item: NewsItem) -> bool:
    haystack = f"{item.title} {item.summary} {item.body} {' '.join(item.tags)}".lower()
    return "open source" in haystack or "open-source" in haystack or "исходник" in haystack


def _contains_cyrillic(value: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", value))


def _extract_subject(item: NewsItem) -> str | None:
    title = " ".join(item.title.split())
    combined = f"{title} {item.summary} {item.body}"
    for name in WATCHLIST_NAMES:
        if re.search(re.escape(name), combined, flags=re.IGNORECASE):
            return name
    match = re.match(r"([A-Z][A-Za-z0-9.+-]*(?:\s+[A-Z][A-Za-z0-9.+-]*){0,2})", title)
    if match:
        subject = match.group(1)
        if subject.lower() not in GENERIC_SUBJECTS:
            return subject
    return None


def _select_verb(item: NewsItem) -> str:
    haystack = f"{item.title} {item.summary} {item.body}".lower()
    categories = set(item.categories)
    if "открыла исходники" in haystack or "open source" in haystack or "open-source" in haystack:
        return "открыла исходный код"
    if "free plan" in haystack or "free tier" in haystack or "free access" in haystack:
        return "открыла"
    if {"models", "release"} & categories and any(
        token in haystack
        for token in ("released", "release", "ships", "ship", "launch", "launched", "available")
    ):
        return "выпустила"
    if {"models", "release"} & categories and any(
        token in haystack for token in ("introducing", "announce", "announcing")
    ):
        return "представила"
    if any(token in haystack for token in ("updated", "update", "upgraded", "upgrade", "refresh")):
        return "обновила"
    if any(token in haystack for token in ("acquires", "acquired", "acquisition", "buy")):
        return "купила"
    if any(token in haystack for token in ("partner", "partnership")):
        return "запустила партнерство"
    if any(token in haystack for token in ("introducing", "announce", "announcing")):
        return "представила"
    if any(token in haystack for token in ("launch", "launched", "available")):
        return "запустила"
    if any(token in haystack for token in ("released", "release", "ships", "ship")):
        return "выпустила"
    if any(token in haystack for token in ("open", "opened")):
        return "открыла"
    return "обновила"


def _extract_object(item: NewsItem, subject: str | None) -> str | None:
    combined = " ".join(part for part in (item.title, item.summary, item.body) if part)
    for pattern in MODEL_PATTERNS:
        match = re.search(pattern, combined, flags=re.IGNORECASE)
        if match:
            found = " ".join(match.group(0).split())
            if not subject or found.lower() != subject.lower():
                return found

    title_tail = " ".join(item.title.split())
    if subject and title_tail.lower().startswith(subject.lower()):
        title_tail = title_tail[len(subject):].strip(" :-—")
    title_tail = re.sub(
        r"^(launch(?:es|ed)?|release(?:d|s)?|ships?|updates?|updated|upgrade[sd]?|introducing|announc(?:e|es|ed|ing)|opens?|opened|adds?|added|rolls out|partners? with|acquires?|acquired)\b",
        "",
        title_tail,
        flags=re.IGNORECASE,
    ).strip(" :-—")
    translated_tail = _translate_object_phrase(title_tail)
    if translated_tail:
        return translated_tail

    categories = set(item.categories)
    if {"models", "release"} & categories:
        return "новую модель"
    if "comparisons" in categories:
        return "сравнение моделей"
    if {"dev_tools", "vibe_coding"} & categories:
        return "новый dev tool"
    if "coding" in categories:
        return "апдейт для coding"
    if "resources" in categories:
        return "новый AI-инструмент"
    return None


def _translate_object_phrase(value: str) -> str | None:
    cleaned = " ".join(value.split())
    if not cleaned:
        return None
    for source, target in OBJECT_REPLACEMENTS:
        if source in cleaned.lower():
            return target
    if "model" in cleaned.lower():
        return re.sub(r"\bmodel\b", "модель", cleaned, flags=re.IGNORECASE)
    if len(cleaned.split()) <= 4 and cleaned.isascii():
        return cleaned
    return None


def _extract_features(item: NewsItem) -> list[str]:
    haystack = f"{item.title} {item.summary} {item.body} {' '.join(item.tags)}".lower()
    features: list[str] = []
    for keywords, label in FEATURE_GROUPS:
        if any(keyword in haystack for keyword in keywords) and label not in features:
            features.append(label)
        if len(features) >= 3:
            break
    return features


def _join_features(features: list[str]) -> str:
    if not features:
        return "ключевые AI-сценарии"
    if len(features) == 1:
        return features[0]
    if len(features) == 2:
        return f"{features[0]} и {features[1]}"
    return f"{', '.join(features[:-1])} и {features[-1]}"


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
