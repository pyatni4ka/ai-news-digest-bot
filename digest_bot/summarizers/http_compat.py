from __future__ import annotations

import json
import re
from textwrap import dedent
from typing import Any

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


_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")
_STORY_INDEX_RE = re.compile(r"^\[(\d+)]\s*")
_ALT_INDEX_RE = re.compile(r"^\(?(\d+)\)?(?:[.):\-]\s*)?")
_CODE_FENCE_RE = re.compile(r"^```(?:json|text)?\s*|\s*```$", re.IGNORECASE)
_URL_RE = re.compile(r"https?://\S+")
_LEADING_LIST_RE = re.compile(r"^[\-\*\u2022]+\s*")


def build_system_prompt(slot: str, paragraph_count: int, complexity_level: int = 1) -> str:
    time_scope = "за последний месяц" if slot == "monthly" else "за текущее окно"
    audience = _audience_block(complexity_level)
    return dedent(
        f"""
        Ты редактор личного русскоязычного AI-дайджеста.
        Подготовь Telegram-дайджест по {paragraph_count} историям {time_scope}.

        {audience}

        ДАННЫЕ И ПОРЯДОК:
        В payload есть массив `story_order`. Используй ТОЛЬКО его и строго в этом порядке.
        Не добавляй новости вне `story_order`, не меняй порядок, не объединяй разные истории в один абзац.

        ЯЗЫК:
        Весь текст — СТРОГО на русском языке.
        На английском оставляй ТОЛЬКО: названия компаний (OpenAI, Anthropic), названия продуктов и моделей (Claude, GPT, Cursor), устоявшиеся термины которые не переводят (API, GPU, open-source, benchmark, fine-tuning, reasoning).
        Все остальные слова — на русском. Никаких английских фраз, предложений или заголовков.

        СТИЛЬ РУССКОГО ЯЗЫКА:
        Пиши в стиле качественного русскоязычного техноблога — живо, конкретно, без воды.
        Используй активные глаголы: «запустил», «выложил», «обновил», «добавил», «открыл».
        Запрещены канцеляризмы: «осуществляет», «производит», «является», «в рамках», «данный», «текущий».
        Не употребляй вводные штампы: «стоит отметить», «важно подчеркнуть», «следует упомянуть».

        РЕДАКТУРНЫЙ СТАНДАРТ:
        Пиши как опытный редактор, а не как агрегатор.
        Не копируй сырой source title — сформулируй собственный заголовок по сути новости.
        Не выдумывай детали, которых нет в источнике.
        Не используй кликбейт, маркетинговую воду и общие слова без смысла.
        Не вставляй URL, markdown, буллиты и разделитель " | ".

        ЗАГОЛОВОК — ПРАВИЛА:
        Заголовок: короткий, конкретный, информативный. Формула: кто + что сделал + почему важно.
        НЕ ИСПОЛЬЗУЙ Title Case. Нормальный sentence case, кроме имён собственных.
        Если это релиз новой модели — можно CAPS только для названия модели, не для всего заголовка.
        Если это действительно бесплатный продукт — можно «АБСОЛЮТНО БЕСПЛАТНО», только если подтверждено в данных.
        Не ставь точку в конце заголовка.

        АНТИПАТТЕРНЫ ЗАГОЛОВКОВ (запрещено):
        — «Компания X выпустила новый продукт Y» → скучно, нет сути
        — «Новая модель от OpenAI» → слишком общо
        — «Важное обновление для разработчиков» → вода без факта
        Вместо этого — сразу суть:
        — «GPT-4.1 вдвое дешевле GPT-4o и лучше справляется с кодом»
        — «Cursor добавил фоновых агентов: теперь несколько задач параллельно»
        — «DeepSeek выложил V3-0324 с улучшенным reasoning — бесплатно»

        ФОРМАТ ВЫВОДА:
        Верни ровно {paragraph_count} абзацев, если в `story_order` есть {paragraph_count} историй.
        Каждый абзац — ровно одна история.
        Формат каждого абзаца строго такой:
        [<номер>] <эмодзи> <заголовок>
        <2-3 предложения: что произошло, почему важно, какой практический вывод>
        Заголовок и текст — только перевод строки, не двоеточие.
        Между абзацами — одна пустая строка.
        Не обрезай предложения и не ставь многоточие вместо завершённой мысли.

        ФИЛЬТР:
        Отбрасывай мусорные новости: подборки промптов, лайфхаки, вакансии, курсы, скидки.
        Не повторяй тему под разными формулировками.
        """
    ).strip()


def build_structured_system_prompt(slot: str, complexity_level: int = 1) -> str:
    time_scope = "за последний месяц" if slot == "monthly" else "за текущее окно"
    audience = _audience_block(complexity_level)
    return dedent(
        f"""
        Ты редактор личного русскоязычного AI-дайджеста для Telegram.
        Верни ТОЛЬКО JSON по заданной схеме, без markdown, пояснений и code fences.

        {audience}

        ОСНОВНЫЕ ПРАВИЛА:
        - Используй только массив `story_order`.
        - Каждая запись в `stories` должна соответствовать истории с тем же `index` в `story_order`.
        - Пиши строго по-русски, кроме названий компаний, моделей, продуктов и общепринятых терминов вроде API.
        - Не добавляй URL, markdown, списки, лишние поля и комментарии.
        - Не выдумывай факты вне данных.

        ТРЕБОВАНИЯ К `headline`:
        - Короткий, точный, читабельный Telegram-заголовок.
        - Лучше формула «кто + что сделал + суть».
        - Обычный sentence case, без шумного Title Case.
        - Без точки на конце.

        ТРЕБОВАНИЯ К `body`:
        - 2-3 законченных предложения про одну историю {time_scope}.
        - Первое предложение: что произошло.
        - Второе или третье: почему это важно и что это меняет на практике.
        - Без воды, кликбейта и английских фраз.
        """
    ).strip()


def build_summary_payload(
    slot: str,
    paragraph_count: int,
    sectioned_items: dict[str, list[NewsItem]],
) -> str:
    story_order = sectioned_items.get("story_order", [])
    payload = {
        "slot": slot,
        "paragraph_count": paragraph_count,
        "story_count": len(story_order),
        "story_order": serialize_news_items(story_order),
        "sections": {
            key: serialize_news_items(items)
            for key, items in sectioned_items.items()
            if key != "story_order" and items
        },
    }
    return json.dumps(payload, ensure_ascii=False)


class OpenAICompatibleSummarizer(Summarizer):
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        fallback_models: list[str] | None = None,
        referer: str | None = None,
        title: str | None = None,
        structured_outputs: bool = False,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._fallback_models = fallback_models or []
        self._referer = referer
        self._title = title
        self._structured_outputs = structured_outputs

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
        story_order = sectioned_items.get("story_order", [])
        story_count = len(story_order)
        payload = build_summary_payload(slot, paragraph_count, sectioned_items)
        async with httpx.AsyncClient(timeout=60.0) as client:
            for model in models:
                try:
                    content = ""
                    if self._structured_outputs and story_count:
                        try:
                            content = await self._chat_completion_structured(
                                client=client,
                                headers=headers,
                                model=model,
                                user_payload=payload,
                                slot=slot,
                                complexity_level=complexity_level,
                                story_order=story_order,
                            )
                        except Exception:
                            content = ""
                    if not content:
                        content = await self._chat_completion(
                            client=client,
                            headers=headers,
                            model=model,
                            messages=[
                                {
                                    "role": "system",
                                    "content": build_system_prompt(
                                        slot,
                                        story_count or paragraph_count,
                                        complexity_level,
                                    ),
                                },
                                {
                                    "role": "user",
                                    "content": payload,
                                },
                            ],
                            temperature=0.2,
                            max_tokens=2048,
                        )
                        content = await self._ensure_valid_digest_shape(
                            client=client,
                            headers=headers,
                            model=model,
                            text=content,
                            story_count=story_count or paragraph_count,
                        )
                    if content:
                        if _needs_russian_rewrite(content):
                            content = await self._rewrite_to_russian(
                                client=client,
                                headers=headers,
                                model=model,
                                text=content,
                                story_count=story_count or paragraph_count,
                            )
                            content = await self._ensure_valid_digest_shape(
                                client=client,
                                headers=headers,
                                model=model,
                                text=content,
                                story_count=story_count or paragraph_count,
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

    async def healthcheck(self) -> dict[str, Any]:
        headers = self._build_headers()
        errors: dict[str, str] = {}
        async with httpx.AsyncClient(timeout=20.0) as client:
            for model in [self._model, *self._fallback_models]:
                try:
                    result = await self._chat_completion(
                        client=client,
                        headers=headers,
                        model=model,
                        messages=[
                            {
                                "role": "system",
                                "content": "Ответь одним коротким предложением на русском: соединение работает.",
                            },
                            {"role": "user", "content": "Проверка доступа к модели."},
                        ],
                        temperature=0.0,
                    )
                    return {
                        "ok": True,
                        "model": model,
                        "preview": result[:120],
                    }
                except Exception as exc:
                    errors[model] = f"{type(exc).__name__}: {exc}"
        return {
            "ok": False,
            "model": self._model,
            "errors": errors,
        }

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
        story_count: int,
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
                        "Сохрани структуру абзацев, нумерацию [1]...[N] и эмодзи. "
                        "Каждый абзац должен описывать ровно одну новость. "
                        "На английском оставляй только названия продуктов, моделей и компаний. "
                        f"Верни ровно {story_count} абзацев."
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0.1,
        )
        return rewritten or text

    async def _ensure_valid_digest_shape(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        model: str,
        text: str,
        story_count: int,
    ) -> str:
        try:
            return normalize_digest_output(text, story_count)
        except ValueError:
            repaired = await self._repair_digest_structure(
                client=client,
                headers=headers,
                model=model,
                text=text,
                story_count=story_count,
            )
            return normalize_digest_output(repaired, story_count)

    async def _repair_digest_structure(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        model: str,
        text: str,
        story_count: int,
    ) -> str:
        repaired = await self._chat_completion(
            client=client,
            headers=headers,
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Преобразуй готовый текст в строгий Telegram-формат дайджеста. "
                        "Верни ровно "
                        f"{story_count} абзацев. Каждый абзац в формате:\n"
                        "[<номер>] <эмодзи> <заголовок>\n"
                        "<2-3 предложения>\n\n"
                        "Сохрани исходный смысл. Не добавляй URL, markdown и комментарии. "
                        "Нумерация должна быть подряд: [1], [2], [3]..."
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0.0,
        )
        return repaired or text

    async def _chat_completion_structured(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        model: str,
        user_payload: str,
        slot: str,
        complexity_level: int,
        story_order: list[NewsItem],
    ) -> str:
        story_count = len(story_order)
        if story_count == 0:
            return ""
        content = await self._chat_completion(
            client=client,
            headers=headers,
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": build_structured_system_prompt(slot, complexity_level),
                },
                {"role": "user", "content": user_payload},
            ],
            temperature=0.1,
            extra_payload={
                "response_format": _structured_digest_schema(story_count),
                "plugins": [{"id": "response-healing"}],
                "verbosity": "low",
            },
        )
        return format_structured_digest(content, story_order)

    async def _chat_completion(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        extra_payload: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if extra_payload:
            payload.update(extra_payload)
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


def format_structured_digest(content: str, story_order: list[NewsItem]) -> str:
    parsed = json.loads(_strip_code_fences(content))
    stories = parsed.get("stories")
    if not isinstance(stories, list) or len(stories) != len(story_order):
        raise ValueError("Structured digest does not match story order length.")
    paragraphs: list[str] = []
    for expected_index, (story, item) in enumerate(zip(stories, story_order, strict=False), start=1):
        if not isinstance(story, dict):
            raise ValueError("Story payload must be an object.")
        if int(story.get("index", -1)) != expected_index:
            raise ValueError("Structured digest returned wrong story order.")
        headline = _normalize_headline_text(str(story.get("headline", "")))
        body = _normalize_body_text(str(story.get("body", "")))
        if not headline or not body:
            raise ValueError("Structured digest returned an empty headline or body.")
        paragraphs.append(f"[{expected_index}] {_default_story_emoji(item)} {headline}\n{body}")
    return "\n\n".join(paragraphs)


def normalize_digest_output(text: str, story_count: int) -> str:
    if story_count <= 0:
        raise ValueError("Story count must be positive.")
    cleaned = _strip_code_fences(text).strip()
    paragraphs = [paragraph.strip() for paragraph in _PARAGRAPH_SPLIT_RE.split(cleaned) if paragraph.strip()]
    if len(paragraphs) != story_count:
        raise ValueError("LLM response returned unexpected paragraph count.")

    normalized: list[str] = []
    for expected_index, paragraph in enumerate(paragraphs, start=1):
        normalized.append(_normalize_paragraph(paragraph, expected_index))
    return "\n\n".join(normalized)


def _normalize_paragraph(paragraph: str, expected_index: int) -> str:
    paragraph = _LEADING_LIST_RE.sub("", paragraph.strip())
    index_match = _STORY_INDEX_RE.match(paragraph)
    if index_match is None:
        alt_match = _ALT_INDEX_RE.match(paragraph)
        if alt_match:
            if int(alt_match.group(1)) != expected_index:
                raise ValueError("LLM response reordered stories.")
            paragraph = paragraph[alt_match.end():].strip()
        else:
            paragraph = f"[{expected_index}] {paragraph}"
    else:
        if int(index_match.group(1)) != expected_index:
            raise ValueError("LLM response reordered stories.")

    paragraph = _STORY_INDEX_RE.sub("", paragraph, count=1).strip()
    lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
    if not lines:
        raise ValueError("LLM response paragraph is empty.")

    headline = _normalize_headline_text(lines[0])
    body_source = "\n".join(lines[1:])
    if not body_source and ":" in lines[0]:
        maybe_headline, maybe_body = lines[0].split(":", 1)
        headline = _normalize_headline_text(maybe_headline)
        body_source = maybe_body.strip()
    body = _normalize_body_text(body_source)
    if not headline or not body:
        raise ValueError("LLM response paragraph is missing headline or body.")
    return f"[{expected_index}] {headline}\n{body}"


def _normalize_headline_text(text: str) -> str:
    cleaned = " ".join(_strip_code_fences(text).split())
    cleaned = cleaned.strip().strip("*_#>` ").strip("«»\"' ")
    cleaned = _LEADING_LIST_RE.sub("", cleaned)
    if ":" in cleaned and cleaned.count(":") == 1 and len(cleaned) > 80:
        cleaned = cleaned.split(":", 1)[0].strip()
    return cleaned.rstrip(" .;:")


def _normalize_body_text(text: str) -> str:
    cleaned = _strip_code_fences(text)
    cleaned = _URL_RE.sub("", cleaned)
    lines = [_LEADING_LIST_RE.sub("", line.strip()) for line in cleaned.splitlines() if line.strip()]
    merged = " ".join(lines).strip().strip("*_#>` ")
    merged = re.sub(r"\s+", " ", merged)
    merged = merged.rstrip(" -|,:;")
    if not merged:
        return ""
    if merged[-1] not in ".!?":
        merged += "."
    return merged


def _strip_code_fences(text: str) -> str:
    return _CODE_FENCE_RE.sub("", text).strip()


def _default_story_emoji(item: NewsItem) -> str:
    categories = set(item.categories)
    if {"models", "release"} & categories or _looks_like_model_news(item):
        return "🚀"
    if "comparisons" in categories:
        return "⚖️"
    if {"coding", "dev_tools", "vibe_coding", "watchlist"} & categories:
        return "🧰"
    if "resources" in categories:
        return "📚"
    if "freebies" in categories:
        return "🆓"
    return "🗞"


def _looks_like_model_news(item: NewsItem) -> bool:
    haystack = f"{item.title} {item.summary}".lower()
    return bool(
        re.search(
            r"\b(model|release|weights|checkpoint|preview|beta|version|выпустила|представила|обновила|новая модель)\b",
            haystack,
        )
    )


def _structured_digest_schema(story_count: int) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "digest_stories",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "stories": {
                        "type": "array",
                        "minItems": story_count,
                        "maxItems": story_count,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "index": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": story_count,
                                    "description": "Позиция истории в story_order.",
                                },
                                "headline": {
                                    "type": "string",
                                    "minLength": 6,
                                    "maxLength": 120,
                                    "description": "Русский Telegram-заголовок без точки на конце.",
                                },
                                "body": {
                                    "type": "string",
                                    "minLength": 40,
                                    "maxLength": 480,
                                    "description": "2-3 предложения по этой новости на русском языке.",
                                },
                            },
                            "required": ["index", "headline", "body"],
                        },
                    },
                },
                "required": ["stories"],
            },
        },
    }
