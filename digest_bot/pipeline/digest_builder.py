from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
import re
from typing import Any
from zoneinfo import ZoneInfo

from digest_bot.image_selection import ImageCandidate, is_usable_image_reference, select_best_image_candidates
from digest_bot.models import Digest, DigestButton, DigestSection, NewsItem
from digest_bot.pipeline.classify import is_relevant_item


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
    r"Claude(?:\s+(?:Sonnet|Opus|Haiku)(?:\s+[A-Za-z0-9.\-]+)?)",
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

TITLE_TRANSLATION_PATTERNS = (
    (
        re.compile(r"^(?P<subject>[A-Za-z0-9.+’' -]+?)['’]s new app is an AI for customizing your feed$", re.IGNORECASE),
        lambda match: f"{match.group('subject').strip()} запустила AI-приложение для настройки ленты",
    ),
    (
        re.compile(
            r"^(?P<percent>\d+)% of codebases rely on open source, and AI slop is putting them at risk$",
            re.IGNORECASE,
        ),
        lambda match: f"AI-slop ставит под удар {match.group('percent')}% open-source проектов",
    ),
)

FEATURE_GROUPS = (
    (("coding", "code", "refactor", "debug"), "coding"),
    (("agent", "agents", "agentic"), "agents"),
    (("repo", "repository", "repositories"), "работу с репозиториями"),
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
    "beyond",
    "towards",
    "exploring",
    "understanding",
    "how",
    "why",
    "what",
    "the",
    "a",
    "an",
    "on",
    "in",
    "for",
    "with",
    "from",
    "about",
    "using",
    "building",
    "training",
    "scaling",
    "rethinking",
    "toward",
    "several",
    "here",
    "some",
}

GENERIC_TITLE_PREFIXES = (
    "это войдёт в историю",
    "вот это да",
    "важно",
    "срочно",
    "breaking",
)

TITLE_REPLACEMENTS = (
    ("Гений переписал", "Разработчик переписал"),
)

MIN_PARAGRAPH_MATCH_SCORE = 40

RELEASE_SOURCE_NAMES = {
    "rss:aider-releases": "Aider",
    "rss:anthropic-sdk-releases": "Anthropic Python SDK",
    "rss:claude-code-releases": "Claude Code",
    "rss:continue-releases": "Continue",
    "rss:crewai-releases": "CrewAI",
    "rss:langchain-releases": "LangChain",
    "rss:llamaindex-releases": "LlamaIndex",
    "rss:ollama-releases": "Ollama",
    "rss:openai-python-releases": "OpenAI Python SDK",
    "rss:openhands-releases": "OpenHands",
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
    elif slot == "weekly":
        end_local = local_now
        start_local = end_local - timedelta(days=7)
    elif slot == "today":
        end_local = local_now
        start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
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
    story_items = build_story_sequence(slot, sections, paragraph_count)
    resource_links = gather_links(sections["resources"], 5)
    model_links = gather_links(sections["models"], 3)
    dev_tool_links = gather_links(sections["dev_tools"], 3)
    image_paths = gather_images(items, 10)
    paragraphs = split_paragraphs(summary_text, paragraph_count)
    if not paragraphs:
        paragraphs = fallback_digest_paragraphs(slot, sections)
    story_indexes = extract_story_indexes(paragraphs)
    paragraphs = [strip_story_index(paragraph) for paragraph in paragraphs]
    if _is_direct_story_order(story_indexes, len(paragraphs), len(story_items)):
        matched_story_items = story_items[: len(paragraphs)]
        match_scores = [MIN_PARAGRAPH_MATCH_SCORE] * len(matched_story_items)
    else:
        matched_story_items, match_scores, match_indexes = match_story_items_with_scores(paragraphs, story_items)
        if _should_fallback_to_story_cards(paragraphs, matched_story_items, match_scores, match_indexes):
            paragraphs = fallback_digest_paragraphs(slot, sections)
            matched_story_items = story_items[: len(paragraphs)]
            match_scores = [MIN_PARAGRAPH_MATCH_SCORE] * len(matched_story_items)
    story_media = build_story_media_for_items(matched_story_items, max_items=4 if slot != "monthly" else 6)

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

    buttons = [DigestButton(text="Дайджест сейчас", action="refresh")]

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
            "story_links": [
                item.url if item and index < len(match_scores) and match_scores[index] >= MIN_PARAGRAPH_MATCH_SCORE else None
                for index, item in enumerate(matched_story_items[: len(paragraphs)])
            ],
            "generated_at": now.isoformat(),
        },
        buttons=buttons,
        section_map=section_map,
        image_paths=image_paths,
        story_media=story_media,
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
        "watchlist": 8 if slot == "monthly" else 5,
        "freebies": 6 if slot == "monthly" else 4,
        "resources": 6 if slot == "monthly" else 5,
    }
    return {
        "headline": unique_first(categorized["headline"], limits["headline"]),
        "models": unique_first(categorized["models"] + categorized["release"], limits["models"]),
        "comparisons": unique_first(categorized["comparisons"], limits["comparisons"]),
        "coding": unique_first(categorized["coding"], limits["coding"]),
        "vibe_coding": unique_first(categorized["vibe_coding"], limits["vibe_coding"]),
        "dev_tools": unique_first(categorized["dev_tools"], limits["dev_tools"]),
        "watchlist": unique_first(categorized["watchlist"], limits["watchlist"]),
        "freebies": unique_first(
            [item for item in relevant_items if _is_totally_free(item)],
            limits["freebies"],
        ),
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
    label = (
        "последний месяц"
        if slot == "monthly"
        else "сегодня"
        if slot == "today"
        else "текущее окно"
    )
    return [f"📭 За {label} почти не было релевантных AI-новостей."]


def split_paragraphs(text: str, limit: int) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    return paragraphs[:limit]


def extract_story_indexes(paragraphs: list[str]) -> list[int | None]:
    indexes: list[int | None] = []
    for paragraph in paragraphs:
        match = _STORY_INDEX_RE.match(paragraph)
        indexes.append(int(match.group(1)) if match else None)
    return indexes


def strip_story_index(paragraph: str) -> str:
    return _STORY_INDEX_RE.sub("", paragraph, count=1).strip()


def _is_direct_story_order(indexes: list[int | None], paragraph_count: int, story_count: int) -> bool:
    if paragraph_count == 0 or paragraph_count > story_count:
        return False
    if any(index is None for index in indexes):
        return False
    return [int(index) for index in indexes] == list(range(1, paragraph_count + 1))


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
        else "Недельный"
        if slot == "weekly"
        else "За сегодня"
        if slot == "today"
        else "Оперативный"
    )
    tz_abbr = "MSK" if "Moscow" in timezone_name else str(tz)
    return f"{label} AI digest • {local_end:%d.%m %H:%M} {tz_abbr}"


def title_for_section(key: str) -> str:
    return {
        "headline": "Главное",
        "models": "Модели и релизы",
        "comparisons": "Сравнения",
        "coding": "Coding",
        "dev_tools": "Dev tools",
        "vibe_coding": "Vibe coding",
        "watchlist": "Watchlist",
        "freebies": "Бесплатно",
        "resources": "Ресурсы",
    }.get(key, key)


def fallback_section_details(title: str, items: list[NewsItem]) -> str:
    lines = [title]
    for item in items[:6]:
        lines.append("")
        lines.append(_story_card(item, limit=500))
    return "\n".join(lines)


def build_story_cards(
    slot: str,
    sections: dict[str, list[NewsItem]],
    limit: int,
) -> list[str]:
    return [_story_card(item) for item in build_story_sequence(slot, sections, limit)]


def build_story_sequence(
    slot: str,
    sections: dict[str, list[NewsItem]],
    limit: int,
) -> list[NewsItem]:
    selected_main, dev_items, minor_items = build_story_plan(slot, sections, max(limit, 6))
    sequence = unique_first(selected_main + dev_items + minor_items, limit)
    if len(sequence) < limit:
        pool = unique_first(
            sections.get("headline", [])
            + sections.get("models", [])
            + sections.get("coding", [])
            + sections.get("dev_tools", [])
            + sections.get("watchlist", [])
            + sections.get("resources", []),
            limit * 3,
        )
        existing = {item.dedup_key or item.title for item in sequence}
        for item in pool:
            key = item.dedup_key or item.title
            if key in existing:
                continue
            sequence.append(item)
            existing.add(key)
            if len(sequence) >= limit:
                break
    return sequence[:limit]


def build_story_plan(
    slot: str,
    sections: dict[str, list[NewsItem]],
    limit: int,
) -> tuple[list[NewsItem], list[NewsItem], list[NewsItem]]:
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
    return selected_main, dev_items, minor_items


def build_story_media(slot: str, sections: dict[str, list[NewsItem]], max_items: int) -> list[dict[str, Any]]:
    selected_main = build_story_sequence(slot, sections, max_items)
    return build_story_media_for_items(selected_main, max_items)


def build_story_media_for_items(items: list[NewsItem | None], max_items: int) -> list[dict[str, Any]]:
    story_media: list[dict[str, Any]] = []
    for item in items[:max_items]:
        if item is None:
            continue
        images = gather_images([item], 1)
        if not images:
            continue
        story_media.append(
            {
                "title": _story_media_title(item),
                "image_paths": images,
                "item_id": item.db_id,
                "url": item.url,
            }
        )
    return story_media


def match_story_items_to_paragraphs(
    paragraphs: list[str],
    candidates: list[NewsItem],
) -> list[NewsItem | None]:
    matched, _, _ = match_story_items_with_scores(paragraphs, candidates)
    return matched


def match_story_items_with_scores(
    paragraphs: list[str],
    candidates: list[NewsItem],
) -> tuple[list[NewsItem | None], list[int], list[int | None]]:
    available = list(enumerate(candidates))
    matched: list[NewsItem | None] = []
    scores: list[int] = []
    indexes: list[int | None] = []
    for paragraph in paragraphs:
        best_available_index = -1
        best_original_index: int | None = None
        best_score = -1
        for available_index, (original_index, item) in enumerate(available):
            score = _score_paragraph_match(paragraph, item)
            if score > best_score:
                best_score = score
                best_available_index = available_index
                best_original_index = original_index
        if best_available_index >= 0 and best_score >= MIN_PARAGRAPH_MATCH_SCORE:
            _, matched_item = available.pop(best_available_index)
            matched.append(matched_item)
            scores.append(best_score)
            indexes.append(best_original_index)
        else:
            matched.append(None)
            scores.append(0)
            indexes.append(None)
    return matched, scores, indexes


def _should_fallback_to_story_cards(
    paragraphs: list[str],
    matched_story_items: list[NewsItem | None],
    match_scores: list[int],
    match_indexes: list[int | None],
) -> bool:
    if not paragraphs:
        return True
    strong_matches = sum(
        1
        for item, score in zip(matched_story_items, match_scores, strict=False)
        if item is not None and score >= MIN_PARAGRAPH_MATCH_SCORE
    )
    required_matches = max(2, int(len(paragraphs) * 0.7))
    if strong_matches < required_matches:
        return True
    ordered_matches = [index for index in match_indexes if index is not None]
    if len(ordered_matches) >= 2 and ordered_matches != sorted(ordered_matches):
        return True
    return False


def _story_card(item: NewsItem, limit: int = 500) -> str:
    title = _display_title(item)
    fragment = _localized_fragment(item, limit=limit)
    return f"{_emoji_for_item(item)} {title}\n{fragment}"


def _display_title(item: NewsItem) -> str:
    title = _localized_title(item)
    if _is_totally_free(item):
        title = f"{title} — АБСОЛЮТНО БЕСПЛАТНО"
    if _is_model_release(item):
        return title.upper()
    return title


def _story_media_title(item: NewsItem) -> str:
    original = _strip_leading_decoration(" ".join(item.title.split()))
    quoted_cli = re.search(r'CLI\s+["“]([^"”]+)["”]', original, flags=re.IGNORECASE)
    if quoted_cli:
        cli_name = quoted_cli.group(1).strip()
        if cli_name:
            return f"{cli_name[:1].upper() + cli_name[1:]} CLI"
    if _is_version_title(original):
        release_source = _release_source_name(item)
        if release_source:
            return f"{release_source} {original}"
    if ":" in original:
        prefix = original.split(":", 1)[0].strip()
        if len(prefix) >= 3:
            return prefix
    for pattern in MODEL_PATTERNS:
        match = re.search(pattern, f"{item.title} {item.summary}", flags=re.IGNORECASE)
        if match:
            return " ".join(match.group(0).split())
    conf_match = re.search(r"\bAI Native Conf\b", original, flags=re.IGNORECASE)
    if conf_match:
        return conf_match.group(0)
    if len(original) > 90:
        return truncate_at_word_boundary(original, 87)
    return original


def truncate_at_word_boundary(text: str, limit: int, suffix: str = "…") -> str:
    if len(text) <= limit:
        return text
    cut = limit - len(suffix)
    if cut <= 0:
        return text[:limit]
    space_pos = text.rfind(" ", 0, cut + 1)
    if space_pos > cut * 0.4:
        truncated = text[:space_pos]
    else:
        truncated = text[:cut]
    return truncated.rstrip(" -|,:;.") + suffix


def _compact_fragment(value: str, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    # Cut at the last sentence boundary — never mid-word with ellipsis
    for end_char in (".", "!", "?"):
        pos = text.rfind(end_char, 0, limit)
        if pos > limit * 0.3:
            return text[: pos + 1]
    # If no sentence boundary found, use full text up to limit at word boundary without ellipsis
    space_pos = text.rfind(" ", 0, limit)
    if space_pos > limit * 0.3:
        return text[:space_pos].rstrip(" -|,:;.") + "."
    return text[:limit]


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZА-ЯЁ0-9])")
_STORY_INDEX_RE = re.compile(r"^\[(\d+)]\s*")
_VERSION_TITLE_RE = re.compile(r"^v?\d+(?:\.\d+){1,3}(?:[-._a-z0-9]+)?$", flags=re.IGNORECASE)
_LEADING_LIST_RE = re.compile(r"^[\-\*\u2022]+\s*")

_STAT_RE = re.compile(
    r"\d+[%xх×]"
    r"|\d+\.\d+"
    r"|\b\d{2,}\b"
    r"|\d+\s*(?:ms|tokens?|times?|faster|slower|params?|parameters?)"
)

_BOILERPLATE_RE = re.compile(
    r"^(?:read more|click here|subscribe|sign up|learn more|follow us|"
    r"check out|visit|see also|related|disclaimer|©|source:|via\b)",
    re.IGNORECASE,
)


def _extract_key_sentence(item: NewsItem) -> str | None:
    """Select the most informative sentence from body or summary.

    Uses simple heuristics: presence of numbers/stats, capitalized
    words (named entities), sentence length, and position.
    No external NLP libraries required.
    """
    text = item.body or item.summary
    if not text or len(text.strip()) < 30:
        return None

    candidates = _rank_informative_sentences(item, text)
    if not candidates:
        return None

    _, best_sentence, _ = max(candidates, key=lambda value: value[2])

    # Ensure it ends with punctuation
    if not best_sentence.endswith((".", "!", "?")):
        best_sentence = best_sentence.rstrip(" ,;:-—") + "."

    return best_sentence


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
    relevant: list[NewsItem] = []
    for item in items:
        categories = set(item.categories)
        if "noise" in categories:
            continue
        if not is_relevant_item(item):
            continue
        relevant.append(item)
    return relevant


def _localized_title(item: NewsItem) -> str:
    title = _clean_original_title(" ".join(item.title.split()))
    if ("…" in title or "..." in title) and _contains_cyrillic(item.summary):
        summary_title = _summary_title_candidate(item)
        if summary_title:
            title = summary_title
    if _contains_cyrillic(title) and not _should_rewrite_original_title(item, title):
        return _finalize_title(title)
    item_specific_title = _translate_known_item_title(item, title)
    if item_specific_title:
        return _finalize_title(item_specific_title)
    translated_title = _translate_known_title(title)
    if translated_title:
        return _finalize_title(translated_title)
    if _should_preserve_original_title(item, title) and not _should_rewrite_original_title(item, title):
        return _finalize_title(title)

    categories = set(item.categories)
    is_model_release = _is_model_release(item)

    subject = _extract_subject(item)
    verb = _select_verb(item)
    obj = _extract_object(item, subject)

    if subject and obj:
        return _finalize_title(f"{subject} {verb} {obj}")
    if subject and {"models", "release"} & categories and is_model_release:
        return _finalize_title(f"{subject} {verb} новую модель")
    if subject and "comparisons" in categories:
        return _finalize_title(f"{subject} показала новое сравнение моделей")
    if subject and {"dev_tools", "vibe_coding", "coding"} & categories:
        return _finalize_title(f"{subject} {verb} обновление для разработки")
    features = _extract_features(item)
    feature_hint = f" ({_join_features(features[:2])})" if features else ""
    if "comparisons" in categories:
        return _finalize_title(f"Вышло новое сравнение AI-моделей{feature_hint}")
    if {"models", "release"} & categories and is_model_release:
        model_match = _find_model_name(item)
        if model_match:
            return _finalize_title(f"Вышел {model_match}")
        return _finalize_title(f"Вышел новый релиз AI-модели{feature_hint}")
    if {"dev_tools", "vibe_coding", "coding"} & categories:
        return _finalize_title(f"Вышел новый апдейт для разработки{feature_hint}")
    if "resources" in categories:
        return _finalize_title(f"Появился новый AI-инструмент{feature_hint}")
    return _finalize_title(title)


def _should_preserve_original_title(item: NewsItem, title: str) -> bool:
    categories = set(item.categories)
    if _is_model_release(item):
        return False
    if _translate_known_title(title):
        return False
    if _find_model_name(item):
        return False
    if any(re.search(re.escape(name), title, flags=re.IGNORECASE) for name in WATCHLIST_NAMES):
        return False
    if "release" in categories:
        return False
    if len(title.split()) > 4:
        return False
    if re.search(r"[.!?]", title):
        return False
    if re.search(r"\b(is|are|for|with|using|new|updated?|released?|launch(?:ed|es)?|risk)\b", title, flags=re.IGNORECASE):
        return False
    return True


def _should_rewrite_original_title(item: NewsItem, title: str) -> bool:
    lowered = title.lower()
    if "показал, как" in lowered and len(title) <= 160:
        return False
    if len(title) > 92:
        return True
    if "…" in title or "..." in title:
        return True
    if any(lowered.startswith(prefix) for prefix in GENERIC_TITLE_PREFIXES):
        return True
    if title[:1].isdigit() or "%" in title[:10]:
        return True
    if item.source_key == "rss:simon-willison":
        return True
    return False


def _localized_fragment(item: NewsItem, limit: int) -> str:
    source = item.summary or item.body or item.title
    if _contains_cyrillic(source):
        key_sentence = _extract_key_sentence(item)
        if key_sentence and _contains_cyrillic(key_sentence):
            suffixes = _fragment_suffixes(item, key_sentence)
            text = " ".join([key_sentence, *suffixes]).strip()
            return _compact_fragment(text, limit=limit)
        return _compact_fragment(_trim_repeated_title(item, source), limit=limit)

    translated_fragment = _translate_known_fragment(item)
    if translated_fragment:
        return _compact_fragment(translated_fragment, limit=limit)

    # Try to extract an informative sentence from the body/summary
    key_sentence = _extract_key_sentence(item)
    if key_sentence and _contains_cyrillic(key_sentence):
        suffixes = _fragment_suffixes(item, key_sentence)
        text = " ".join([key_sentence, *suffixes]).strip()
        return _compact_fragment(text, limit=limit)

    # Fall back to template phrases when no good sentence is found
    categories = set(item.categories)
    is_model_release = _is_model_release(item)
    features = _extract_features(item)
    details: list[str] = []
    if is_model_release:
        if features:
            details.append(f"Релиз сфокусирован на {_join_features(features)}.")
        else:
            details.append("Это заметный апдейт в линейке AI-моделей.")
    elif {"dev_tools", "vibe_coding", "coding"} & categories:
        if features:
            details.append(f"Апдейт затрагивает {_join_features(features)}.")
        else:
            details.append("Новость важна для IDE, AI-агентов и повседневной разработки.")
    elif "comparisons" in categories:
        if features:
            details.append(f"Сравнение смотрит на {_join_features(features)}.")
        else:
            details.append("Материал сравнивает актуальные AI-модели и их позиции.")
    elif "resources" in categories:
        if features:
            details.append(f"Инструмент делает упор на {_join_features(features)}.")
        else:
            details.append("Речь идет о новом AI-инструменте или приложении.")
    elif "models" in categories:
        details.append("Новость показывает, как AI-функции доходят до прикладного продукта.")
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
    haystack = f"{item.title} {item.summary}".lower()
    release_cues = (
        "introducing",
        "announce",
        "announcing",
        "released",
        "release",
        "ship",
        "ships",
        "launch",
        "launches",
        "launched",
        "available",
        "preview",
        "beta",
        "alpha",
        "version",
    )
    generic_model_cues = (
        "model",
        "models",
        "weights",
        "checkpoint",
        "version",
    )
    if not any(cue in haystack for cue in release_cues):
        return False
    return _find_model_name(item) is not None or any(cue in haystack for cue in generic_model_cues)


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


def _fragment_suffixes(item: NewsItem, text: str) -> list[str]:
    lowered = text.lower()
    suffixes: list[str] = []
    if _is_totally_free(item) and "бесплат" not in lowered and "free" not in lowered:
        suffixes.append("Доступ открыт бесплатно.")
    if _looks_open_source(item) and not any(token in lowered for token in ("open-source", "open source", "исходн", "github")):
        suffixes.append("Исходный код открыт.")
    return suffixes


def _looks_open_source(item: NewsItem) -> bool:
    haystack = f"{item.title} {item.summary} {item.body} {' '.join(item.tags)}".lower()
    return any(
        cue in haystack
        for cue in (
            "open-sourced",
            "open sourced",
            "source code",
            "available on github",
            "github repo",
            "github repository",
            "released the code",
            "открыла исходники",
            "открыл исходники",
            "открыли исходники",
            "открыла исходный код",
            "исходный код",
            "репозиторий на github",
        )
    )


def _find_model_name(item: NewsItem) -> str | None:
    text = f"{item.title} {item.summary}"
    for pattern in MODEL_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return " ".join(match.group(0).split())
    return None


def _contains_cyrillic(value: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", value))


def _extract_subject(item: NewsItem) -> str | None:
    title = " ".join(item.title.split())
    tool_match = re.match(r"^(?:tool|app|project):\s*(.+)$", title, flags=re.IGNORECASE)
    if tool_match:
        cleaned = tool_match.group(1).strip(" :-—")
        if cleaned:
            return cleaned
    if _is_version_title(title):
        release_source = _release_source_name(item)
        if release_source:
            return release_source
    # 1. WATCHLIST_NAMES in title (highest priority)
    for name in WATCHLIST_NAMES:
        if re.search(re.escape(name), title, flags=re.IGNORECASE):
            return name
    # 2. Regex match from title
    match = re.match(r"([A-Z][A-Za-z0-9.+-]*(?:\s+[A-Z][A-Za-z0-9.+-]*){0,2})", title)
    if match:
        subject = match.group(1)
        words = subject.split()
        while words and words[0].lower() in GENERIC_SUBJECTS:
            words = words[1:]
        subject = " ".join(words)
        # Skip subjects that are too long (likely paper titles, not company names)
        if subject and subject.lower() not in GENERIC_SUBJECTS and len(subject.split()) <= 2:
            return subject
    match = re.match(r"([A-Z][A-Za-z0-9.+-]*(?:\s+[A-Z][A-Za-z0-9.+-]*){0,3})", title)
    if match:
        subject = match.group(1).strip()
        if subject and subject.lower() not in GENERIC_SUBJECTS and len(subject.split()) <= 4:
            return subject
    # 3. WATCHLIST_NAMES in summary/body only for short product-like titles.
    if len(title.split()) > 4:
        return None
    for source in (item.summary, item.body):
        text = " ".join(source.split())
        for name in WATCHLIST_NAMES:
            if re.search(re.escape(name), text, flags=re.IGNORECASE):
                return name
    return None


def _select_verb(item: NewsItem) -> str:
    haystack = f"{item.title} {item.summary} {item.body}".lower()
    categories = set(item.categories)
    if _looks_open_source(item):
        return "открыла исходный код"
    if " app " in f" {haystack} " or "assistant" in haystack:
        return "запустила"
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
    if _is_version_title(item.title):
        return f"релиз {item.title.strip()}"

    title_and_summary = " ".join(part for part in (item.title,) if part)
    for pattern in MODEL_PATTERNS:
        match = re.search(pattern, title_and_summary, flags=re.IGNORECASE)
        if match:
            found = " ".join(match.group(0).split())
            if not subject or found.lower() != subject.lower():
                return found

    if _is_model_release(item):
        title_and_summary = " ".join(part for part in (item.title, item.summary) if part)
        for pattern in MODEL_PATTERNS:
            match = re.search(pattern, title_and_summary, flags=re.IGNORECASE)
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

    lower_title = item.title.lower()
    if "customizing your feed" in lower_title:
        return "AI-приложение для настройки ленты"
    if "vulnerability lookup" in lower_title:
        return "инструмент для проверки Python-зависимостей"
    if "zero-day" in lower_title:
        return "поиск zero-day уязвимостей"
    if "ai slop" in lower_title and "open source" in lower_title:
        return "нагрузку на open-source мейнтейнеров"

    categories = set(item.categories)
    if {"models", "release"} & categories and _is_model_release(item):
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
    # Only return short clean phrases, not incomplete ones ending in conjunctions/prepositions
    trailing_words = {"and", "or", "the", "a", "an", "for", "with", "in", "on", "to", "of", "by"}
    if len(cleaned.split()) <= 4 and cleaned.isascii():
        last_word = cleaned.split()[-1].lower()
        if last_word not in trailing_words:
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
    if _is_model_release(item):
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
    if "models" in categories or "watchlist" in categories:
        return "🤖"
    return "📌"


def _translate_known_title(title: str) -> str | None:
    normalized = " ".join(title.split())
    for pattern, renderer in TITLE_TRANSLATION_PATTERNS:
        match = pattern.match(normalized)
        if match:
            return renderer(match)
    return None


def _translate_known_item_title(item: NewsItem, title: str) -> str | None:
    haystack = f"{item.title} {item.summary} {item.body}".lower()
    if title.lower() == "python vulnerability lookup" and "osv.dev" in haystack:
        return "Python Vulnerability Lookup проверяет Python-зависимости по OSV.dev"
    return None


def _translate_known_fragment(item: NewsItem) -> str | None:
    haystack = f"{item.title} {item.summary} {item.body}".lower()
    if (
        "build your own algorithm" in haystack
        or "create custom feeds using natural language" in haystack
        or "custom feeds using natural language" in haystack
    ):
        return (
            "Инструмент Attie помогает собирать собственные алгоритмические ленты на естественном языке. "
            "Сервис работает поверх AT Protocol и Claude, так что настройка выдачи становится обычным диалогом."
        )
    if "osv.dev" in haystack and ("pyproject.toml" in haystack or "requirements.txt" in haystack):
        return (
            "Инструмент проверяет pyproject.toml, requirements.txt и GitHub-репозитории по базе OSV.dev. "
            "На выходе он сразу показывает уязвимости в Python-зависимостях и упрощает проверку безопасности зависимостей."
        )
    if "maintainer workload" in haystack or "ai is ddo" in haystack or "contributors can’t explain" in haystack:
        return (
            "Поток низкокачественных AI-пулреквестов перегружает мейнтейнеров open-source проектов. "
            "Из-за этого команды ужесточают правила приёма внешних вкладов и тратят больше времени на ручную модерацию."
        )
    return None


def _score_paragraph_match(paragraph: str, item: NewsItem) -> int:
    paragraph_text = _normalize_match_text(paragraph)
    title = _normalize_match_text(item.title)
    summary = _normalize_match_text(item.summary)
    media_title = _normalize_match_text(_story_media_title(item))
    score = 0

    if media_title and media_title in paragraph_text:
        score += 120
    if title and title in paragraph_text:
        score += 100

    for pattern in MODEL_PATTERNS:
        match = re.search(pattern, f"{item.title} {item.summary}", flags=re.IGNORECASE)
        if match:
            normalized = _normalize_match_text(match.group(0))
            if normalized and normalized in paragraph_text:
                score += 140

    paragraph_tokens = set(_match_tokens(paragraph_text))
    item_tokens = set(_match_tokens(f"{title} {summary} {media_title}"))
    overlap = paragraph_tokens & item_tokens
    score += len(overlap) * 8

    for name in WATCHLIST_NAMES:
        normalized_name = _normalize_match_text(name)
        if normalized_name and normalized_name in paragraph_text and normalized_name in f"{title} {summary}":
            score += 25

    return score


def _normalize_match_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def _match_tokens(value: str) -> list[str]:
    tokens = re.findall(r"[a-zа-яё0-9][a-zа-яё0-9.+-]{2,}", value, flags=re.IGNORECASE)
    return [token for token in tokens if token not in {"with", "from", "this", "that", "news"}]


def _strip_leading_decoration(value: str) -> str:
    cleaned = re.sub(r"^[^\wА-Яа-яЁё]+", "", value).strip()
    return cleaned or value


def _is_version_title(value: str) -> bool:
    normalized = " ".join(value.split()).strip()
    return bool(_VERSION_TITLE_RE.fullmatch(normalized))


def _release_source_name(item: NewsItem) -> str | None:
    mapped = RELEASE_SOURCE_NAMES.get(item.source_key)
    if mapped:
        return mapped
    if item.url:
        match = re.search(r"github\.com/[^/]+/([^/]+)/releases/", item.url, flags=re.IGNORECASE)
        if match:
            repo = match.group(1).strip()
            if repo:
                return _humanize_release_slug(repo)
    if item.source_key.endswith("-releases"):
        slug = item.source_key.split(":", 1)[-1].removesuffix("-releases")
        if slug:
            return _humanize_release_slug(slug)
    return None


def _humanize_release_slug(slug: str) -> str:
    lowered = slug.lower()
    known = {
        "aider": "Aider",
        "anthropic-sdk": "Anthropic Python SDK",
        "claude-code": "Claude Code",
        "continue": "Continue",
        "crewai": "CrewAI",
        "langchain": "LangChain",
        "llamaindex": "LlamaIndex",
        "ollama": "Ollama",
        "openai-python": "OpenAI Python SDK",
        "openhands": "OpenHands",
    }
    if lowered in known:
        return known[lowered]
    parts = [part for part in re.split(r"[-_]+", slug) if part]
    if not parts:
        return slug
    normalized_parts: list[str] = []
    for part in parts:
        if part.lower() in {"ai", "sdk", "api", "llm"}:
            normalized_parts.append(part.upper())
            continue
        normalized_parts.append(part[:1].upper() + part[1:])
    return " ".join(normalized_parts)


def _split_into_candidate_sentences(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    chunks = re.split(r"\n\s*\n+|(?<=[.!?])\s+", normalized)
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def _is_low_signal_sentence(sentence: str) -> bool:
    lowered = sentence.lower().strip(" .!?,;:-—")
    if not lowered:
        return True
    if lowered in {"telegram update", "март 2026"}:
        return True
    if _LEADING_LIST_RE.match(sentence):
        return True
    if re.fullmatch(r"[\W_]+", sentence):
        return True
    if len(re.findall(r"[A-Za-zА-Яа-яЁё]", sentence)) < 8:
        return True
    if lowered.startswith(("исходный код", "source code", "github", "репозиторий на github")) and len(lowered.split()) <= 4:
        return True
    return False


def _rank_informative_sentences(item: NewsItem, text: str) -> list[tuple[int, str, float]]:
    normalized = text.strip()
    if not normalized:
        return []
    normalized = _trim_repeated_title(item, normalized)
    if len(normalized.strip()) < 25:
        return []

    candidates: list[tuple[int, str, float]] = []
    for idx, raw in enumerate(_split_into_candidate_sentences(normalized)):
        sentence = " ".join(raw.split()).strip().rstrip()
        if len(sentence) < 25 or len(sentence) > 320:
            continue
        if _BOILERPLATE_RE.search(sentence):
            continue
        if _is_low_signal_sentence(sentence):
            continue

        score = 0.0

        stat_matches = _STAT_RE.findall(sentence)
        score += len(stat_matches) * 3.0

        words = sentence.split()
        if len(words) > 1:
            caps = sum(
                1
                for word in words[1:]
                if word[:1].isupper() and len(word) > 1 and not word.isupper()
            )
            score += caps * 1.5
            acronyms = sum(1 for word in words if word.isupper() and len(word) >= 2 and word.isalpha())
            score += acronyms * 1.0

        length = len(sentence)
        if 50 <= length <= 150:
            score += 2.0
        elif 30 <= length < 50:
            score += 1.0
        elif 150 < length <= 220:
            score += 1.0

        if idx < 3:
            score += 2.0 - idx * 0.5

        if sentence.count(",") > 4:
            score -= 2.0
        if sentence.lower().startswith(("по его словам", "по словам автора")):
            score += 0.5

        if score >= 1.5:
            candidates.append((idx, sentence, score))

    return candidates


def _clean_original_title(value: str) -> str:
    title = _strip_leading_decoration(value)
    title = re.sub(r",\s+один из самых[^,]+,\s+", " ", title, flags=re.IGNORECASE)
    title = re.sub(
        r"\s+на\s+днях\s+показал(?:\s+на\s+[^,]+)?\,\s+как\s+",
        " показал, как ",
        title,
        flags=re.IGNORECASE,
    )
    lowered = title.lower()
    for prefix in GENERIC_TITLE_PREFIXES:
        if lowered.startswith(f"{prefix}:"):
            title = title.split(":", 1)[1].strip()
            lowered = title.lower()
            break
    for source, target in TITLE_REPLACEMENTS:
        if title.startswith(source):
            title = title.replace(source, target, 1)
    if title.lower().startswith("как "):
        title = title[4:].strip()
        if title:
            title = title[:1].upper() + title[1:]
    lowered = title.lower()
    show_match = re.search(r"показал(?:[^,\n]{0,40})?, как", lowered)
    tail_index = show_match.start() if show_match else -1
    comma_index = title.find(",")
    if tail_index > 0 and 0 <= comma_index < tail_index and "показал" not in title[:comma_index].lower():
        subject = title.split(",", 1)[0].strip()
        if subject:
            title = f"{subject} {title[tail_index:].strip()}"
    return title.strip()


def _summary_title_candidate(item: NewsItem) -> str | None:
    lines = [line.strip() for line in item.summary.splitlines() if line.strip()]
    if not lines:
        return None
    candidate = _clean_original_title(lines[0])
    original_clean = _clean_original_title(item.title)
    if not candidate or candidate == original_clean:
        return None
    if len(candidate) <= len(original_clean):
        return None
    return candidate


def _finalize_title(value: str, limit: int = 88) -> str:
    title = " ".join(value.split())
    title = re.sub(r"\s+([,.:;!?])", r"\1", title)
    title = title.rstrip(" .")
    if len(title) > limit:
        return truncate_at_word_boundary(title, limit, suffix="…")
    return title


def _trim_repeated_title(item: NewsItem, source: str) -> str:
    normalized_source = " ".join(source.split())
    title_candidates = [
        _strip_leading_decoration(" ".join(item.title.split())).rstrip(":.-—! "),
        _clean_original_title(" ".join(item.title.split())).rstrip(":.-—! "),
        (_summary_title_candidate(item) or "").rstrip(":.-—! "),
    ]
    for normalized_title in sorted({candidate for candidate in title_candidates if candidate}, key=len, reverse=True):
        if "…" in normalized_title or "..." in normalized_title:
            continue
        if normalized_title:
            match = re.match(
                rf"^{re.escape(normalized_title)}(?:[.:\-—!\"'«»\s]+)",
                normalized_source,
                flags=re.IGNORECASE,
            )
            if match:
                trimmed = normalized_source[match.end():].lstrip(" :.-—!\n")
                if trimmed:
                    return trimmed
    return normalized_source


def gather_links(items: list[NewsItem], limit: int) -> list[str]:
    links: list[str] = []
    for item in items:
        if item.url and item.url not in links:
            links.append(item.url)
        if len(links) >= limit:
            break
    return links


def gather_images(items: list[NewsItem], limit: int) -> list[str]:
    ordered = sorted(items, key=lambda row: (row.importance, row.published_at), reverse=True)
    primary: list[str] = []
    overflow: list[str] = []
    seen: set[str] = set()
    for item in ordered:
        ranked = select_best_image_candidates(
            [ImageCandidate(url=image, source_hint="media") for image in item.images],
            limit=3,
            min_score=1,
        )
        if not ranked:
            continue
        best = ranked[0]
        if best not in seen:
            primary.append(best)
            seen.add(best)
        for extra in ranked[1:]:
            if extra in seen:
                continue
            overflow.append(extra)
            seen.add(extra)
    images = primary[:limit]
    if len(images) < min(limit, 4):
        images = (primary + overflow)[:limit]
    return [image for image in images if _is_usable_image(image)]


def _is_usable_image(value: str) -> bool:
    return is_usable_image_reference(value)


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
