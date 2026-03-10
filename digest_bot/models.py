from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Source:
    key: str
    name: str
    kind: str
    location: str
    tags: list[str] = field(default_factory=list)
    priority: int = 1
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NewsItem:
    source_key: str
    external_id: str
    title: str
    published_at: datetime
    collected_at: datetime
    url: str | None = None
    summary: str = ""
    body: str = ""
    tags: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    importance: float = 0.0
    images: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    dedup_key: str | None = None
    db_id: int | None = None


@dataclass(slots=True)
class DigestSection:
    key: str
    title: str
    paragraph: str
    item_ids: list[int] = field(default_factory=list)
    links: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DigestButton:
    text: str
    action: str
    value: str | None = None
    url: str | None = None


@dataclass(slots=True)
class Digest:
    slot: str
    start_at: datetime
    end_at: datetime
    title: str
    paragraphs: list[str]
    summary_payload: dict[str, Any]
    buttons: list[DigestButton] = field(default_factory=list)
    section_map: dict[str, DigestSection] = field(default_factory=dict)
    image_paths: list[str] = field(default_factory=list)
    story_media: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class CollectedBatch:
    source: Source
    items: list[NewsItem]
