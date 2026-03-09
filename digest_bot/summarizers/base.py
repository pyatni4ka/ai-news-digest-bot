from __future__ import annotations

from abc import ABC, abstractmethod

from digest_bot.models import NewsItem


class Summarizer(ABC):
    @abstractmethod
    async def summarize(
        self,
        slot: str,
        sectioned_items: dict[str, list[NewsItem]],
        paragraph_count: int,
    ) -> str:
        raise NotImplementedError

