from __future__ import annotations

import re
from textwrap import dedent

import httpx

from digest_bot.models import NewsItem
from digest_bot.pipeline.digest_builder import serialize_news_items
from digest_bot.summarizers.base import Summarizer


def _audience_block(level: int) -> str:
    if level <= 3:
        return (
            "АУДИТОРИЯ (уровень: новичок):\n"
            "Читатель только начинает разбираться в AI. Пиши максимально просто.\n"
            "Каждый технический термин объясняй в скобках простыми словами.\n"
            "Например: «reasoning (умение модели рассуждать по шагам)», «benchmark (тест для сравнения моделей)», «API (способ подключиться к сервису из кода)».\n"
            "Пиши как для умного друга, который не разбирается в технологиях."
        )
    if level <= 6:
        return (
            "АУДИТОРИЯ (уровень: уверенный):\n"
            "Читатель понимает базовые понятия: AI, модель, API, prompt, token, benchmark.\n"
            "Объясняй только редкие или новые термины.\n"
            "Пиши понятно, но без излишних упрощений."
        )
    if level <= 9:
        return (
            "АУДИТОРИЯ (уровень: продвинутый):\n"
            "Читатель хорошо разбирается в AI: знает модели, архитектуры, инструменты.\n"
            "Не объясняй стандартные термины. Можно использовать профессиональную лексику.\n"
            "Пиши плотно и информативно."
        )
    return (
        "АУДИТОРИЯ (уровень: эксперт):\n"
        "Читатель — AI-инженер. Используй профессиональный язык.\n"
        "Можно упоминать архитектуры, метрики, детали реализации без пояснений."
    )


def build_system_prompt(slot: str, paragraph_count: int, complexity_level: int = 1) -> str:
    time_scope = "за последний месяц" if slot == "monthly" else "за текущее окно"
    audience = _audience_block(complexity_level)
    return dedent(
        f"""
        Ты редактор личного русскоязычного AI-дайджеста.
        Выбери {paragraph_count} самых важных новостей {time_scope}.

        {audience}

        ДАННЫЕ И ПОРЯДОК:
        В данных есть раздел `story_order`. Используй именно новости из `story_order` строго в том порядке, в котором они даны. Не добавляй новости вне `story_order` и не меняй порядок.

        ЯЗЫК:
        Весь текст — СТРОГО на русском языке.
        На английском оставляй ТОЛЬКО: названия компаний (OpenAI, Anthropic), названия продуктов и моделей (Claude, GPT, Cursor), устоявшиеся термины которые не переводят (API, GPU, open-source).
        Все остальные слова — на русском. Никаких английских фраз, предложений или заголовков.

        ФОРМАТ АБЗАЦА:
        Каждый абзац — ровно одна новость. Формат:
        <эмодзи> <заголовок на русском>
        <2-3 предложения: что произошло, почему это важно, и что это значит на практике>
        Заголовок и текст разделяются переносом строки, НЕ двоеточием.
        Текст должен быть полным и законченным — НИКОГДА не обрезай предложения, не ставь многоточие.

        ЗАГОЛОВОК — ПРАВИЛА:
        Заголовок должен быть коротким, конкретным и информативным.
        В заголовке сразу дай суть: кто + что сделал.
        НЕ ИСПОЛЬЗУЙ Title Case (Каждое Слово С Большой Буквы). Пиши обычным sentence case: только первое слово с большой буквы, остальные — с маленькой (кроме имён собственных: OpenAI, Claude, Cursor и т.д.).
        Если это релиз новой модели — заголовок ПОЛНОСТЬЮ В ВЕРХНЕМ РЕГИСТРЕ.
        Если продукт бесплатен — добавь в заголовок АБСОЛЮТНО БЕСПЛАТНО (в верхнем регистре).
        Для остальных новостей НЕ используй CAPS.

        СТРУКТУРА:
        Не делай сводных блоков ("Dev tools", "Короткой строкой"). Каждая новость — отдельный абзац.
        Каждый абзац: первая строка — эмодзи и заголовок, вторая строка — пояснение.
        Не используй двоеточие после заголовка. Разделяй заголовок и текст переносом строки.

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
        complexity_level: int = 1,
    ) -> str:
        headers = self._build_headers()
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
                                "content": build_system_prompt(slot, paragraph_count, complexity_level),
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

    async def simplify(self, text: str) -> str:
        headers = self._build_headers()
        async with httpx.AsyncClient(timeout=60.0) as client:
            result = await self._chat_completion(
                client=client,
                headers=headers,
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Перепиши этот AI-дайджест максимально простым языком, "
                            "как будто объясняешь другу, который вообще не разбирается в технологиях. "
                            "Каждый термин объясни в скобках. "
                            "Сохрани структуру: эмодзи, заголовок, пояснение. "
                            "Пиши строго на русском, на английском только названия компаний и продуктов."
                        ),
                    },
                    {"role": "user", "content": text},
                ],
                temperature=0.2,
            )
        return result or text

    async def compare(self, items_a: list[dict], items_b: list[dict], name_a: str, name_b: str) -> str:
        headers = self._build_headers()
        async with httpx.AsyncClient(timeout=60.0) as client:
            result = await self._chat_completion(
                client=client,
                headers=headers,
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты AI-аналитик. Сравни два AI-продукта/модели на основе последних новостей. "
                            "Пиши на русском. Формат: 2-3 абзаца сравнения. "
                            "Укажи ключевые отличия, сильные стороны каждого, последние обновления."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"{name_a}:\n{items_a}\n\n{name_b}:\n{items_b}",
                    },
                ],
                temperature=0.3,
            )
        return result or f"Не удалось сравнить {name_a} и {name_b}."

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self._referer:
            headers["HTTP-Referer"] = self._referer
        if self._title:
            headers["X-Title"] = self._title
        return headers

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
                        "На английском оставляй только названия продуктов, моделей и компаний."
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
