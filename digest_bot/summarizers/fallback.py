from __future__ import annotations

from digest_bot.models import NewsItem
from digest_bot.pipeline.digest_builder import build_story_cards
from digest_bot.summarizers.base import Summarizer


class FallbackSummarizer(Summarizer):
    async def summarize(
        self,
        slot: str,
        sectioned_items: dict[str, list[NewsItem]],
        paragraph_count: int,
        complexity_level: int = 1,
    ) -> str:
        limit = paragraph_count if slot == "monthly" else max(paragraph_count, 6)
        cards = build_story_cards(slot, sectioned_items, limit)
        return "\n\n".join(
            f"[{index}] {card}"
            for index, card in enumerate(cards, start=1)
        )
