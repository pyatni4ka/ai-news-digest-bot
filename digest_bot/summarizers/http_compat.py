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
        Весь общий текст, все заголовки и все пояснения должны быть строго на русском языке.
        На английском можно оставлять только точечные названия продуктов, моделей, компаний, API, IDE и устоявшиеся термины вроде benchmark, coding agent, long context.
        Не копируй английские заголовки источников как есть. Всегда переписывай смысл новости на русском.
        Первые {max(paragraph_count - 2, 1)} абзацев должны описывать ровно по одной важной новости и начинаться в формате:
        <эмодзи> <короткий заголовок>:
        После двоеточия дай 1-2 плотных предложения на русском: что произошло и почему это важно.
        Предпоследний абзац, если хватает материала по IDE, агентам и приложениям для разработки, сделай блоком в формате:
        🧑‍💻 Dev tools:
        и затем 2-4 коротких, но содержательных апдейта через разделитель " | ".
        Последний абзац, если хватает материала, сделай блоком в формате:
        🗞 Короткой строкой:
        и затем 2-4 коротких второстепенных новости в одной строке.
        Делай акцент на релизах и апдейтах AI-моделей, сравнении моделей, coding, vibe coding, IDE, AI-агентах, новых приложениях для разработки и апдейтах таких приложений.
        Особенно внимательно отслеживай OpenAI, ChatGPT, Anthropic, Claude, Google, Gemini, xAI, Grok, Cursor, Windsurf, Claude Code, Copilot, Codex, Replit, Aider и OpenHands.
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
        Не включай подборки промптов, про-советы, лайфхаки, вакансии, курсы, скидки и маркетинговый шум, если там нет реального релиза, апдейта, сравнения или запуска продукта.
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
                        "Сохрани структуру абзацев, эмодзи и блоки `🧑‍💻 Dev tools:` и `🗞 Короткой строкой:`. "
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
