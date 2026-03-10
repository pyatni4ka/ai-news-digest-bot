from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from urllib.parse import parse_qs, unquote, urljoin, urlparse


BLOCKED_HINTS = (
    "placeholder",
    "logo",
    "icon",
    "favicon",
    "avatar",
    "profile",
    "badge",
    "sprite",
    "spinner",
    "loading",
    "pixel",
    "tracking",
    "analytics",
    "brandmark",
    "wordmark",
)

POSITIVE_HINTS = (
    "og",
    "opengraph",
    "social",
    "share",
    "cover",
    "hero",
    "featured",
    "preview",
    "banner",
    "card",
)

BLOCKED_PARENT_TAGS = {"header", "nav", "footer", "aside"}
CONTENT_PARENT_TAGS = {"article", "main", "section"}
BLOCKED_CONTEXT_HINTS = BLOCKED_HINTS + ("announcement-bar",)


@dataclass(slots=True, frozen=True)
class ImageCandidate:
    url: str
    source_hint: str = "img"
    alt: str = ""
    class_names: tuple[str, ...] = ()
    element_id: str = ""
    width: int | None = None
    height: int | None = None
    parent_tags: tuple[str, ...] = ()


def normalize_image_reference(value: str, base_url: str | None = None) -> str | None:
    candidate = value.strip()
    if not candidate or candidate.startswith("data:"):
        return None
    if base_url:
        candidate = urljoin(base_url, candidate)
    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"}:
        if parsed.path.endswith("/_next/image"):
            nested_url = parse_qs(parsed.query).get("url", [None])[0]
            if nested_url:
                candidate = urljoin(f"{parsed.scheme}://{parsed.netloc}", unquote(nested_url))
        return candidate
    if parsed.scheme:
        return None
    return candidate


def select_best_image_candidates(
    candidates: list[ImageCandidate],
    limit: int,
    *,
    base_url: str | None = None,
    min_score: int = 1,
) -> list[str]:
    scored: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for index, candidate in enumerate(candidates):
        normalized = normalize_image_reference(candidate.url, base_url=base_url)
        if normalized is None or normalized in seen:
            continue
        score = score_image_candidate(candidate, normalized)
        if score < min_score:
            continue
        seen.add(normalized)
        scored.append((score, index, normalized))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [normalized for _, _, normalized in scored[:limit]]


def is_usable_image_reference(value: str) -> bool:
    normalized = normalize_image_reference(value)
    if normalized is None:
        return False
    return score_image_candidate(ImageCandidate(url=normalized, source_hint="media"), normalized) >= 1


def score_image_candidate(candidate: ImageCandidate, normalized_url: str) -> int:
    lower_url = normalized_url.lower()
    if _has_blocked_hint(lower_url):
        return -100
    if lower_url.endswith((".svg", ".ico", ".gif")):
        return -100

    score = 0
    if _is_local_path(normalized_url):
        score += 120

    if candidate.source_hint == "meta":
        score += 55
    elif candidate.source_hint == "media":
        score += 45
    else:
        score += 10

    parent_tags = {tag.lower() for tag in candidate.parent_tags}
    if parent_tags & CONTENT_PARENT_TAGS:
        score += 18
    if {"figure", "picture"} & parent_tags:
        score += 12
    if parent_tags & BLOCKED_PARENT_TAGS:
        score -= 40

    if candidate.width or candidate.height:
        width = candidate.width or 0
        height = candidate.height or 0
        if width and height:
            if min(width, height) < 120 or width * height < 40_000:
                score -= 35
            elif min(width, height) >= 400:
                score += 18
            elif min(width, height) >= 200:
                score += 8
        elif max(width, height) and max(width, height) < 120:
            score -= 25

    if any(hint in lower_url for hint in POSITIVE_HINTS):
        score += 20

    context = " ".join(
        part
        for part in (
            candidate.alt,
            candidate.element_id,
            " ".join(candidate.class_names),
            " ".join(candidate.parent_tags),
        )
        if part
    ).lower()
    if any(hint in context for hint in BLOCKED_CONTEXT_HINTS):
        score -= 80
    if candidate.alt.strip() and len(candidate.alt.strip()) >= 8:
        score += 3

    if re.search(r"(?:^|[/_-])icon(?:[/-]|\d|$)", lower_url):
        score -= 80
    if re.search(r"\b(?:16|24|32|48|64)x(?:16|24|32|48|64)\b", lower_url):
        score -= 80

    return score


def _has_blocked_hint(value: str) -> bool:
    return any(hint in value for hint in BLOCKED_HINTS)


def _is_local_path(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        return False
    suffix = Path(parsed.path or value).suffix.lower()
    return suffix not in {".svg", ".ico", ".gif"}
