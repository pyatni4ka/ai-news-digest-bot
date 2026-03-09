from __future__ import annotations

from textwrap import dedent

import httpx

from digest_bot.models import NewsItem
from digest_bot.pipeline.digest_builder import serialize_news_items
from digest_bot.summarizers.base import Summarizer


def build_system_prompt(slot: str, paragraph_count: int) -> str:
    time_scope = "за последний месяц" if slot == "monthly" else "за текущее окно"
    return dedent(
        f"""
        Ты редактор личного русскоязычного AI-дайджеста.
        Выбери {paragraph_count} самых важных новостей {time_scope}.
        Первые {max(paragraph_count - 1, 1)} абзацев должны описывать ровно по одной важной новости и начинаться в формате:
        <эмодзи> <короткий заголовок>:
        После двоеточия дай 1-2 плотных предложения на русском: что произошло и почему это важно.
        Последний абзац, если хватает материала, сделай блоком в формате:
        🗞 Короткой строкой:
        и затем 2-4 коротких второстепенных новости в одной строке.
        Делай акцент на релизах и апдейтах AI-моделей, сравнении моделей, coding, vibe coding, IDE, AI-агентах, новых приложениях для разработки и апдейтах таких приложений.
        Заголовок должен быть коротким, конкретным, новостным и звучать как кричащая плашка из новостей.
        В заголовке сразу дай суть: кто что выпустил, обновил или открыл.
        Примеры стиля заголовка:
        ChatGPT выпустили новую модель 5.4
        Claude обновили Opus до версии 4.6
        Windsurf открыл новый агент для IDE
        Если это релиз новой модели или крупный апдейт модели, сделай заголовок ПОЛНОСТЬЮ В ВЕРХНЕМ РЕГИСТРЕ.
        Если продукт или функция доступны полностью бесплатно, явно напиши в заголовке ПОЛНОСТЬЮ В ВЕРХНЕМ РЕГИСТРЕ: АБСОЛЮТНО БЕСПЛАТНО.
        Для всех остальных новостей не используй CAPS в заголовке.
        В каждом абзаце должен быть только один заголовок и только одно двоеточие в первой строке.
        Не добавляй вторую строку-подзаголовок, слоганы или дополнительные CAPS-фразы внутри абзаца.
        После двоеточия сразу идет обычный связный текст.
        Не вставляй URL в текст.
        Не используй markdown и списки.
        Не повторяй одну и ту же тему под разными формулировками.
        Отбрасывай слабые и мусорные новости.
        """
    ).strip()


class OpenAICompatibleSummarizer(Summarizer):
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        fallback_models: list[str] | None = None,
        referer: str | None = None,
        title: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._fallback_models = fallback_models or []
        self._referer = referer
        self._title = title

    async def summarize(
        self,
        slot: str,
        sectioned_items: dict[str, list[NewsItem]],
        paragraph_count: int,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self._referer:
            headers["HTTP-Referer"] = self._referer
        if self._title:
            headers["X-Title"] = self._title

        last_error: Exception | None = None
        models = [self._model, *self._fallback_models]
        async with httpx.AsyncClient(timeout=60.0) as client:
            for model in models:
                payload = {
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": build_system_prompt(slot, paragraph_count),
                        },
                        {
                            "role": "user",
                            "content": str(
                                {
                                    "slot": slot,
                                    "paragraph_count": paragraph_count,
                                    "sections": {
                                        key: serialize_news_items(items)
                                        for key, items in sectioned_items.items()
                                        if items
                                    },
                                }
                            ),
                        },
                    ],
                    "temperature": 0.3,
                }
                try:
                    response = await client.post(
                        f"{self._base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()
                    body = response.json()
                    content = (
                        body.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                        .strip()
                    )
                    if content:
                        return content
                except Exception as exc:
                    last_error = exc
                    continue
        if last_error is not None:
            raise last_error
        raise RuntimeError("No LLM response received.")
