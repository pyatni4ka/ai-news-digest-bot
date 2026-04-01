# AI News Digest Bot

Личный Telegram-бот, который:

- читает заданные Telegram-каналы и чаты через Telethon;
- собирает AI-новости из RSS и официальных блогов;
- дедуплицирует и раскладывает их по темам;
- делает краткий русскоязычный дайджест;
- усиливает блоки по coding и vibe coding;
- присылает выпуск утром и вечером с кнопками и изображениями;
- оформляет дайджест как короткие карточки новостей с эмодзи и заголовками;
- пишет названия новых моделей капсом.

По умолчанию проект полностью бесплатный: никакой LLM API для запуска не нужен. Summary в базовом режиме собирается локальной логикой. Дополнительно можно включить бесплатный LLM-режим через OpenRouter Free.

## Что уже реализовано

- SQLite-хранилище новостей, дайджестов и простых предпочтений.
- Telegram-источники из твоего стартового списка.
- Открытые источники: official blogs, RSS, GitHub release feeds, coding/vibe coding tooling.
- Сбор через `telegram`, `rss`, `webpage`.
- Inline-кнопки:
  - `Подробнее`
  - `Только coding`
  - `Только vibe coding`
  - `Ресурсы`
  - `Открыть модель`
  - `Сохранить`
  - `Меньше такого`
  - `Обновить сейчас`
- Планировщик утреннего и вечернего запуска.

## Быстрый старт

1. Создай `.env` на основе `.env.example`.
2. Установи зависимости:

```bash
.venv/bin/python -m pip install -e .
```

3. Авторизуй Telegram-сессию для чтения каналов:

```bash
.venv/bin/ai-news-digest auth-telegram
```

Для VPS удобнее сразу экспортировать `StringSession` и потом положить ее в `.env` как `TG_SESSION_STRING`:

```bash
.venv/bin/ai-news-digest export-telegram-session
```

4. Один раз подтяни новости:

```bash
.venv/bin/ai-news-digest sync
```

5. Собери тестовый выпуск:

```bash
.venv/bin/ai-news-digest digest --slot manual --send
```

6. Запусти бота:

```bash
.venv/bin/ai-news-digest bot
```

## Бесплатный LLM через OpenRouter

Если хочешь более качественное summary без платного OpenAI:

```bash
LLM_BACKEND=openrouter
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=openai/gpt-oss-120b:free
LLM_FALLBACK_MODELS=arcee-ai/trinity-large-preview:free,stepfun/step-3.5-flash:free,openrouter/free
```

Это включает бесплатные модели OpenRouter с более сильным первым выбором и резервной цепочкой.
После настройки сразу проверь доступ:

```bash
.venv/bin/ai-news-digest check-llm
```

Если команда возвращает `401 Unauthorized`, проблема не в prompt'ах и не в pipeline, а в ключе или аккаунте OpenRouter.
Если `401` держится долго, не пытайся лечить это правкой prompt'ов: сначала ротируй ключ или меняй backend.

## Основные команды бота

- `Сейчас`
- `Главное`
- `Модели`
- `Coding`
- `Vibe coding`
- `Сравнения`
- `Источники`
- `Настройки`
- `/add_source @channel`

## Архитектура

- `digest_bot/service.py` — оркестратор.
- `digest_bot/collectors/` — сбор источников.
- `digest_bot/pipeline/` — классификация, дедуп, сборка секций.
- `digest_bot/summarizers/` — OpenAI summary и fallback-режим.
- `digest_bot/bot/` — кнопки и обработчики Telegram.

## Деплой

Есть 2 режима деплоя:

- `Interactive bot` — VPS и постоянный polling
- `Free cloud sender` — GitHub Actions в public repo, без always-on polling

### GitHub Actions в public repo

Это лучший полностью бесплатный вариант, если тебе подходят плановые выпуски утром/вечером и ручной monthly из вкладки Actions.

1. Создай public repository и загрузи туда проект.
2. Локально получи Telethon session string:

```bash
cd /Users/antonpyatnica/ai-news-digest-bot
.venv/bin/ai-news-digest export-telegram-session
```

3. В репозитории добавь `Settings -> Secrets and variables -> Actions -> Secrets`:

- `BOT_TOKEN`
- `ADMIN_CHAT_ID`
- `TG_API_ID`
- `TG_API_HASH`
- `TG_PHONE`
- `TG_SESSION_STRING`
- `OPENROUTER_API_KEY`

4. В `Variables` добавь:

- `TIMEZONE=Europe/Moscow`
- `MORNING_HOUR=9`
- `EVENING_HOUR=19`
- `OPENROUTER_MODEL=openai/gpt-oss-120b:free`
- `LLM_FALLBACK_MODELS=arcee-ai/trinity-large-preview:free,stepfun/step-3.5-flash:free,openrouter/free`

5. После пуша workflow появится в:

- `.github/workflows/ai-digest.yml`

Что делает workflow:

- утром запускает `morning`
- вечером запускает `evening`
- вручную через `workflow_dispatch` позволяет запустить `manual` или `monthly`

Важно:

- в GitHub Actions бот работает как `scheduled sender`, а не как always-on polling bot;
- callback-кнопки в этом режиме отключены;
- остаются только безопасные статические URL-кнопки;
- история SQLite между запусками не хранится, каждый запуск опирается на свежий sync.

### VPS / interactive bot

Для полного Telegram-бота с polling и callback-кнопками нужен VPS:

- рекомендуемый baseline: `2 vCPU / 2 GB RAM / 20-30 GB SSD`
- этого достаточно для постоянного polling, sync и локального fallback summary
- если позже захочешь больше источников или дополнительные фоновые задачи, бери `4 GB RAM`

- `python3 -m venv .venv`
- `.venv/bin/python -m pip install -e .`
- `.env`
- `.venv/bin/ai-news-digest export-telegram-session`
- `.venv/bin/ai-news-digest bot`

Если хочешь поднимать как сервис:

1. Скопируй проект на сервер в `/opt/ai-news-digest-bot`
2. Заполни `.env`
3. Запусти:

```bash
cd /opt/ai-news-digest-bot
APP_DIR=/opt/ai-news-digest-bot SERVICE_USER=$USER ./scripts/install_systemd_service.sh
```

После этого systemd поднимет и закрепит сервис.

## Ограничения текущего MVP

- Generic `webpage` collector не знает специфики каждого блога, поэтому часть сайтов может потребовать докрутки selector-логики.
- Часть внешних источников может менять URL или правила антибот-защиты, поэтому список источников нужно иногда подчищать.
- `Меньше такого` сейчас работает как грубое усиление фильтра шума, а не как тонкая персонализация по темам.
- Для приватных Telegram-чатов твой аккаунт должен состоять в этих чатах.
- Для cloud/VPS лучше использовать `TG_SESSION_STRING`, а не sqlite `.session` файл.
- В GitHub Actions-режиме callback-кнопки недоступны, потому что нет постоянного polling-процесса.
- Бесплатный локальный режим summary менее качественный, чем LLM-режим, но не требует ни API-ключей, ни дополнительных затрат.
- У OpenRouter free есть rate limits, поэтому для частого ручного `Обновить сейчас` можно уткнуться в лимит.
