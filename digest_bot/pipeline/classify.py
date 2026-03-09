from __future__ import annotations

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
        "app",
        "tool",
        "launch",
        "available",
        "beta",
        "plugin",
        "editor",
    ),
}


def classify_items(items: list[NewsItem]) -> list[NewsItem]:
    for item in items:
        categories = set(item.categories)
        haystack = _normalize(" ".join([item.title, item.summary, item.body, " ".join(item.tags)]))
        for category, keywords in KEYWORDS.items():
            if any(keyword in haystack for keyword in keywords):
                categories.add(category)
        if any(tag in item.tags for tag in ("official", "github_release", "sdk")):
            categories.add("release")
        if not categories:
            categories.add("general")
        if "coding" in categories and "vibe_coding" not in categories and "cursor" in haystack:
            categories.add("vibe_coding")
        item.categories = sorted(categories)
        item.importance = score_item(item)
    return items


def score_item(item: NewsItem) -> float:
    score = 0.0
    tags = set(item.tags)
    categories = set(item.categories)
    haystack = _normalize(" ".join([item.title, item.summary, item.body, " ".join(item.tags)]))
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
    if "resources" in categories:
        score += 1.0
    if any(keyword in haystack for keyword in ("cursor", "windsurf", "claude code", "copilot", "codex", "aider", "openhands", "continue", "replit", "lovable", "v0", "bolt")):
        score += 1.8
    if any(keyword in haystack for keyword in ("free", "free tier", "no cost", "open beta", "open-source", "open source")):
        score += 1.0
    score += min(len(item.body) / 1200, 2.5)
    score += min(len(item.summary) / 600, 1.5)
    return round(score, 3)


def _normalize(value: str) -> str:
    return value.lower().replace("-", " ")
