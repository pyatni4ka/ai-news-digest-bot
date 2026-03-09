from __future__ import annotations

from textwrap import dedent

from openai import AsyncOpenAI

from digest_bot.models import NewsItem
from digest_bot.pipeline.digest_builder import serialize_news_items
from digest_bot.summarizers.base import Summarizer


SYSTEM_PROMPT = dedent(
    """
    Ты редактор личного русскоязычного AI-дайджеста.
    Твоя задача: по сгруппированным новостям написать краткое, плотное, технически полезное summary.

    Правила:
    - Пиши только на русском.
    - От 3 до 7 абзацев.
    - Никаких буллитов, списков и markdown.
    - Первый абзац: реально главное.
    - Обязательно отдельный плотный абзац про модели и релизы.
    - Обязательно отдельный абзац про сравнения моделей, и отделяй факты от маркетинга.
    - Обязательно отдельный абзац про coding-модели.
    - Обязательно отдельный абзац про vibe coding, агентные IDE и практические инструменты.
    - Если для сравнения не хватает надежных данных, прямо скажи это.
    - Максимум технической конкретики в coding и vibe coding блоках.
    - Не вставляй URL в текст, ссылки будут кнопками.
    """
).strip()


class OpenAISummarizer(Summarizer):
    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def summarize(
        self,
        slot: str,
        sectioned_items: dict[str, list[NewsItem]],
        paragraph_count: int,
    ) -> str:
        payload = {
            "slot": slot,
            "paragraph_count": paragraph_count,
            "sections": {
                key: serialize_news_items(items)
                for key, items in sectioned_items.items()
                if items
            },
        }
        response = await self._client.responses.create(
            model=self._model,
            instructions=SYSTEM_PROMPT,
            input=str(payload),
            max_output_tokens=1200,
        )
        return response.output_text.strip()
