from __future__ import annotations

from functools import lru_cache
import re

from digest_bot.models import NewsItem


KEYWORDS: dict[str, tuple[str, ...]] = {
    "models": (
        "model",
        "release",
        "weights",
        "checkpoint",
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
    ),
    "comparisons": (
        "benchmark",
        "compare",
        "comparison",
        "versus",
        "leaderboard",
        "arena",
        "eval",
        "swe-bench",
        "score",
    ),
    "coding": (
        "coding",
        "code",
        "repo",
        "repository",
        "pull request",
        "cursor",
        "copilot",
        "windsurf",
        "aider",
        "codex",
        "ide",
        "agent",
        "terminal",
        "debug",
        "refactor",
        "commit",
        "vscode",
    ),
    "vibe_coding": (
        "vibe coding",
        "bolt",
        "lovable",
        "replit",
        "v0",
        "claude code",
        "cursor",
        "windsurf",
        "agentic ide",
        "prompt to app",
    ),
    "resources": (
        "open source",
        "github",
        "sdk",
        "dataset",
        "framework",
        "extension",
        "plugin",
        "cli",
        "api",
        "agent",
        "workflow",
        "llm",
    ),
    "dev_tools": (
        "cursor",
        "windsurf",
        "claude code",
        "copilot",
        "codex",
        "aider",
        "openhands",
        "continue",
        "replit",
        "lovable",
        "v0",
        "bolt",
        "dev tool",
        "developer tool",
        "editor",
        "extension",
        "plugin",
        "agentic ide",
        "coding agent",
        "ide",
    ),
    "watchlist": (
        "openai",
        "chatgpt",
        "anthropic",
        "claude",
        "gemini",
        "deepmind",
        "xai",
        "grok",
        "cursor",
        "windsurf",
        "claude code",
        "copilot",
        "codex",
        "github",
        "replit",
        "v0",
        "aider",
        "openhands",
    ),
}

NOISE_PATTERNS = (
    "prompt",
    "промпт",
    "про-совет",
    "лайфхак",
    "tips",
    "tip:",
    "top prompts",
    "best prompts",
    "подборка",
    "генерируем",
    "для учебы",
    "для учёбы",
    "скидка",
    "промокод",
    "ваканс",
    "курс",
    "курсы",
    "9 лучших",
    "10 лучших",
    "подборка сервисов",
    "подборка инструментов",
    "лучших промптов",
    "best tools",
    "top tools",
)

SIGNAL_PATTERNS = (
    "release",
    "released",
    "launch",
    "launched",
    "introducing",
    "announcing",
    "announce",
    "updated",
    "update",
    "new version",
    "preview",
    "beta",
    "версия",
    "обновил",
    "обновила",
    "выпустил",
    "выпустила",
    "релиз",
    "запустил",
    "запустила",
    "открыла исходники",
    "open source",
    "open-source",
)

AI_RELEVANCE_PATTERNS = (
    "artificial intelligence",
    "generative ai",
    "machine learning",
    "llm",
    "foundation model",
    "weights",
    "checkpoint",
    "inference",
    "reasoning",
    "multimodal",
    "coding agent",
    "openai",
    "chatgpt",
    "anthropic",
    "claude",
    "gemini",
    "deepmind",
    "xai",
    "grok",
    "mistral",
    "qwen",
    "deepseek",
    "llama",
    "cursor",
    "windsurf",
    "copilot",
    "codex",
    "openhands",
    "aider",
    "comfyui",
    "stable diffusion",
    "flux",
)

OFFTOPIC_PATTERNS = (
    "документальный фильм",
    "документалк",
    "фильм",
    "кино",
    "кинопрокат",
    "кинофестиваль",
    "сандэнс",
    "sundance",
    "documentary",
    "movie",
    "trailer",
    "series",
    "box office",
)


def classify_items(items: list[NewsItem], *, reset: bool = False) -> list[NewsItem]:
    for item in items:
        categories = set() if reset else set(item.categories)
        haystack = item_haystack(item)
        for category, keywords in KEYWORDS.items():
            if _contains_any_keyword(haystack, keywords):
                categories.add(category)
        if any(tag in item.tags for tag in ("official", "github_release", "sdk")):
            categories.add("release")
        if not categories:
            categories.add("general")
        if "coding" in categories and "vibe_coding" not in categories and _contains_keyword(haystack, "cursor"):
            categories.add("vibe_coding")
        if is_noise_item(item, haystack=haystack, categories=categories):
            categories.add("noise")
        item.categories = sorted(categories)
        item.importance = score_item(item)
    return items


def score_item(item: NewsItem) -> float:
    score = 0.0
    tags = set(item.tags)
    categories = set(item.categories)
    haystack = item_haystack(item)
    if "official" in tags:
        score += 3.0
    if "telegram" in tags:
        score += 1.2
    if "models" in categories or "release" in categories:
        score += 2.5
    if "comparisons" in categories:
        score += 1.8
    if "coding" in categories:
        score += 2.2
    if "vibe_coding" in categories:
        score += 2.0
    if "dev_tools" in categories:
        score += 2.6
    if "watchlist" in categories:
        score += 2.0
    if "watchlist" in categories and {"models", "release", "dev_tools"} & categories:
        score += 1.3
    if "official" in tags and "watchlist" in categories:
        score += 0.8
    if "resources" in categories:
        score += 1.0
    if is_free_offer_item(item, haystack=haystack):
        score += 1.0
    if "noise" in categories:
        score -= 6.5
    if _looks_like_versioned_release(haystack):
        score += 1.5
    score += min(len(item.body) / 1200, 2.5)
    score += min(len(item.summary) / 600, 1.5)
    return round(score, 3)


def item_haystack(item: NewsItem) -> str:
    return _normalize(" ".join([item.title, item.summary, _body_excerpt(item.body)]))


def is_noise_item(
    item: NewsItem,
    haystack: str | None = None,
    categories: set[str] | None = None,
) -> bool:
    value = haystack or item_haystack(item)
    title = _normalize(item.title)
    item_categories = categories or set(item.categories)
    has_noise_pattern = any(pattern in value for pattern in NOISE_PATTERNS)
    if not has_noise_pattern and not _looks_like_listicle(title):
        return False
    if "comparisons" in item_categories:
        return False
    if "release" in item_categories or "models" in item_categories:
        return False
    if any(pattern in value for pattern in SIGNAL_PATTERNS):
        return False
    return True


def is_free_offer_item(item: NewsItem, haystack: str | None = None) -> bool:
    value = haystack or item_haystack(item)
    return any(
        _contains_keyword(value, keyword)
        for keyword in ("free", "free tier", "free plan", "free forever", "no cost", "бесплатно")
    )


def is_relevant_item(item: NewsItem, haystack: str | None = None) -> bool:
    value = haystack or item_haystack(item)
    front_value = item_front_haystack(item)
    categories = set(item.categories)
    tags = set(item.tags)
    core_categories = {"models", "release", "comparisons", "coding", "vibe_coding", "dev_tools", "watchlist"}
    if _looks_like_offtopic_item(item, front_value, categories):
        return False
    if "watchlist" in categories and _has_ai_relevance(front_value):
        return True
    if categories & core_categories and _has_ai_relevance(front_value):
        return True
    if "resources" in categories and _has_ai_relevance(front_value):
        return True
    if {"official", "github_release", "sdk"} & tags and _has_ai_relevance(front_value or value):
        return True
    return False


def _normalize(value: str) -> str:
    normalized = value.lower().replace("-", " ").replace("_", " ")
    return re.sub(r"\s+", " ", normalized).strip()


def item_front_haystack(item: NewsItem) -> str:
    return _normalize(" ".join([item.title, item.summary]))


def _body_excerpt(value: str, limit: int = 900) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit]


def _looks_like_offtopic_item(
    item: NewsItem,
    haystack: str | None = None,
    categories: set[str] | None = None,
) -> bool:
    value = haystack or item_front_haystack(item)
    item_categories = categories or set(item.categories)
    if not any(pattern in value for pattern in OFFTOPIC_PATTERNS):
        return False
    if item_categories & {"release", "comparisons", "coding", "vibe_coding", "dev_tools", "resources"}:
        return False
    return True


@lru_cache(maxsize=None)
def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    normalized = _normalize(keyword)
    parts = [re.escape(part) for part in normalized.split() if part]
    inner = r"\s+".join(parts)
    return re.compile(rf"(?<![a-zа-яё0-9]){inner}(?![a-zа-яё0-9])", re.IGNORECASE)


def _contains_keyword(haystack: str, keyword: str) -> bool:
    normalized = _normalize(keyword)
    if not normalized:
        return False
    return bool(_keyword_pattern(normalized).search(haystack))


def _contains_any_keyword(haystack: str, keywords: tuple[str, ...]) -> bool:
    return any(_contains_keyword(haystack, keyword) for keyword in keywords)


def _looks_like_versioned_release(haystack: str) -> bool:
    return bool(re.search(r"\b(v?\d+(\.\d+){1,3}|version \d+(\.\d+)*)\b", haystack))


def _looks_like_listicle(title: str) -> bool:
    return bool(re.search(r"\b\d+\s+(лучш|best|top)\w*\b", title))


def _has_ai_relevance(haystack: str) -> bool:
    if re.search(r"\bai\b", haystack):
        return True
    return any(_contains_keyword(haystack, pattern) for pattern in AI_RELEVANCE_PATTERNS)
