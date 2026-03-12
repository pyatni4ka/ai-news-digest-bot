from __future__ import annotations

import re
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

        ДАННЫЕ И ПОРЯДОК:
        В данных есть раздел `story_order`. Используй именно новости из `story_order` строго в том порядке, в котором они даны. Не добавляй новости вне `story_order` и не меняй порядок.

        ЯЗЫК:
        Весь текст, заголовки и пояснения — строго на русском.
        На английском оставляй только названия продуктов, моделей, компаний и короткие термины (benchmark, coding agent, long context, IDE, API).
        Не копируй английские заголовки как есть. Переписывай смысл на русском.

        ФОРМАТ АБЗАЦА:
        Каждый абзац — ровно одна новость. Формат:
        <эмодзи> <заголовок на русском>: <1-2 предложения: что произошло и почему важно>

        ЗАГОЛОВОК — ПРАВИЛА:
        Заголовок должен быть коротким, конкретным и информативным.
        В заголовке сразу дай суть: кто + что сделал.
        НЕ ИСПОЛЬЗУЙ Title Case (Каждое Слово С Большой Буквы). Пиши обычным sentence case: только первое слово с большой буквы, остальные — с маленькой (кроме имён собственных: OpenAI, Claude, Cursor и т.д.).
        Примеры правильных заголовков:
        - OpenAI выпустила GPT-5.2 с улучшенным reasoning
        - Anthropic обновила Claude Sonnet до версии 4.6
        - Cursor добавил фоновый coding agent
        Примеры ПЛОХИХ заголовков (запрещены):
        - "Вышел новый релиз AI-модели" (слишком общий, нет субъекта)
        - "Новая Модель Для Разработки" (Title Case)
        - "Introducing GPT-5.2 Preview" (английский заголовок)
        Если это релиз новой модели — заголовок ПОЛНОСТЬЮ В ВЕРХНЕМ РЕГИСТРЕ.
        Если продукт бесплатен — добавь в заголовок АБСОЛЮТНО БЕСПЛАТНО (в верхнем регистре).
        Для остальных новостей НЕ используй CAPS.

        СТРУКТУРА:
        Не делай сводных блоков ("Dev tools", "Короткой строкой"). Каждая новость — отдельный абзац.
        В абзаце только один заголовок и одно двоеточие.
        После двоеточия — обычный связный текст, без подзаголовков и списков.

        ФИЛЬТР:
        Отбрасывай мусорные новости: подборки промптов, лайфхаки, вакансии, курсы, скидки.
        Не повторяй тему под разными формулировками.
        Не вставляй URL в текст. Не используй markdown и разделитель " | ".
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
                try:
                    content = await self._chat_completion(
                        client=client,
                        headers=headers,
                        model=model,
                        messages=[
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
                        temperature=0.3,
                    )
                    if content:
                        if _needs_russian_rewrite(content):
                            content = await self._rewrite_to_russian(
                                client=client,
                                headers=headers,
                                model=model,
                                text=content,
                            )
                        return content
                except Exception as exc:
                    last_error = exc
                    continue
        if last_error is not None:
            raise last_error
        raise RuntimeError("No LLM response received.")

    async def _rewrite_to_russian(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        model: str,
        text: str,
    ) -> str:
        rewritten = await self._chat_completion(
            client=client,
            headers=headers,
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Перепиши готовый AI-дайджест строго на русском языке. "
                        "Сохрани структуру абзацев и эмодзи. "
                        "Каждый абзац должен описывать ровно одну новость. "
                        "На английском оставляй только точечные названия продуктов, моделей, компаний и короткие технические термины."
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0.1,
        )
        return rewritten or text

    async def _chat_completion(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        response = await client.post(
            f"{self._base_url}/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
        return (
            body.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )


def _needs_russian_rewrite(text: str) -> bool:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return False
    cyrillic = sum(1 for char in letters if re.match(r"[А-Яа-яЁё]", char))
    if cyrillic / len(letters) < 0.45:
        return True
    return bool(
        re.search(
            r"\b(released|launch(?:ed|es)?|introducing|updated|comparison|available|ships?)\b",
            text.lower(),
        )
    )
