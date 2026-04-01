from __future__ import annotations

from openai import AsyncOpenAI

from digest_bot.models import NewsItem
from digest_bot.summarizers.http_compat import build_summary_payload, build_system_prompt
from digest_bot.summarizers.base import Summarizer


class OpenAISummarizer(Summarizer):
    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def summarize(
        self,
        slot: str,
        sectioned_items: dict[str, list[NewsItem]],
        paragraph_count: int,
        complexity_level: int = 1,
    ) -> str:
        story_count = len(sectioned_items.get("story_order", [])) or paragraph_count
        response = await self._client.responses.create(
            model=self._model,
            instructions=build_system_prompt(slot, story_count, complexity_level),
            input=build_summary_payload(slot, paragraph_count, sectioned_items),
            max_output_tokens=1200,
        )
        return response.output_text.strip()
