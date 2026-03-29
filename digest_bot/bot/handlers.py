from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from digest_bot.bot.keyboards import digest_inline_keyboard, links_keyboard, main_menu_keyboard
from digest_bot.glossary import format_glossary_all, format_glossary_term
from digest_bot.service import DigestService


def build_router(service: DigestService) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def start_handler(message: Message) -> None:
        if not service.is_admin_chat(message.chat.id):
            return
        await message.answer(
            "Личный AI digest bot активен. Источники уже подключены, можно вызывать сборку вручную или ждать утренний/вечерний дайджест.",
            reply_markup=main_menu_keyboard(),
        )

    @router.message(Command("digest_now"))
    @router.message(F.text == "Сейчас")
    @router.message(F.text == "Получить дайджест здесь и сейчас")
    @router.message(F.text == "Свежий дайджест")
    async def digest_now_handler(message: Message) -> None:
        if not service.is_admin_chat(message.chat.id):
            return
        progress_msg = await message.answer("Собираю свежий выпуск...")

        async def on_progress(done: int, total: int, current_name: str) -> None:
            try:
                await progress_msg.edit_text(
                    f"Собираю свежий выпуск... ({done}/{total} источников)\nТекущий: {current_name}"
                )
            except Exception:
                pass

        digest_id = await service.refresh_and_build_current_digest(on_progress=on_progress)
        try:
            await progress_msg.delete()
        except Exception:
            pass
        await service.send_digest(digest_id)

    @router.message(Command("digest_today"))
    @router.message(F.text == "За сегодня")
    async def digest_today_handler(message: Message) -> None:
        if not service.is_admin_chat(message.chat.id):
            return
        await message.answer("Собираю дайджест за сегодня.")
        await service.sync_sources(lookback_hours=30)
        digest_id = await service.build_digest("today")
        await service.send_digest(digest_id)

    @router.message(Command("digest_month"))
    async def digest_month_handler(message: Message) -> None:
        if not service.is_admin_chat(message.chat.id):
            return
        await message.answer("Собираю месячный выпуск.")
        await service.sync_sources(lookback_hours=24 * 31)
        digest_id = await service.build_digest("monthly")
        await service.send_digest(digest_id)

    @router.message(Command("sources"))
    @router.message(F.text == "Источники")
    async def sources_handler(message: Message) -> None:
        if not service.is_admin_chat(message.chat.id):
            return
        await message.answer(service.render_sources())

    @router.message(F.text == "Настройки")
    async def settings_handler(message: Message) -> None:
        if not service.is_admin_chat(message.chat.id):
            return
        await message.answer(service.render_settings())

    @router.message(Command("add_source"))
    async def add_source_handler(message: Message) -> None:
        if not service.is_admin_chat(message.chat.id):
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("Используй: /add_source @channel")
            return
        source = service.add_source(parts[1].strip())
        await message.answer(f"Источник добавлен: {source.name}")

    @router.message(Command("help"))
    async def help_handler(message: Message) -> None:
        if not service.is_admin_chat(message.chat.id):
            return
        await message.answer(
            "Команды бота:\n\n"
            "Свежий дайджест — собрать и отправить дайджест\n"
            "За сегодня — дайджест за текущий день\n"
            "Источники — список подключённых источников\n"
            "Настройки — текущие настройки бота\n\n"
            "/digest_week — недельный дайджест\n"
            "/digest_month — месячный дайджест\n"
            "/glossary — словарь AI-терминов\n"
            "/glossary <термин> — объяснение конкретного термина\n"
            "/trends — тренды за последнюю неделю\n"
            "/compare <A> <B> — сравнить две модели\n"
            "/level — текущий уровень сложности\n"
            "/level <1-10> — установить уровень вручную\n"
            "/follow <компания> — подписаться на новости компании\n"
            "/unfollow <компания> — отписаться\n"
            "/following — список подписок\n"
            "/add_source @channel — добавить Telegram-канал\n\n"
            "Кнопки под дайджестом:\n"
            "👍/👎 — оценить выпуск\n"
            "🧒 Проще — переписать проще\n"
            "🔄 Обновить — обновить дайджест"
        )

    @router.message(Command("digest_week"))
    async def digest_week_handler(message: Message) -> None:
        if not service.is_admin_chat(message.chat.id):
            return
        await message.answer("Собираю недельный выпуск.")
        await service.sync_sources(lookback_hours=24 * 8)
        digest_id = await service.build_digest("weekly")
        await service.send_digest(digest_id)

    @router.message(Command("glossary"))
    async def glossary_handler(message: Message) -> None:
        if not service.is_admin_chat(message.chat.id):
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await message.answer(format_glossary_all(), parse_mode="HTML")
        else:
            result = format_glossary_term(parts[1].strip())
            await message.answer(result or "Термин не найден. Попробуй /glossary для полного списка.")

    @router.message(Command("trends"))
    async def trends_handler(message: Message) -> None:
        if not service.is_admin_chat(message.chat.id):
            return
        text = await service.render_trends()
        await message.answer(text)

    @router.message(Command("compare"))
    async def compare_handler(message: Message) -> None:
        if not service.is_admin_chat(message.chat.id):
            return
        parts = (message.text or "").split()
        if len(parts) < 3:
            await message.answer("Используй: /compare Claude GPT")
            return
        await message.answer("Сравниваю...")
        result = await service.compare_models(parts[1], parts[2])
        await message.answer(result)

    @router.message(Command("level"))
    async def level_handler(message: Message) -> None:
        if not service.is_admin_chat(message.chat.id):
            return
        parts = (message.text or "").split()
        if len(parts) >= 2:
            try:
                new_level = int(parts[1])
                service.set_complexity_level(new_level)
                await message.answer(f"Уровень сложности установлен: {service.get_complexity_level()}/10")
            except ValueError:
                await message.answer("Используй: /level <1-10>")
        else:
            level = service.get_complexity_level()
            await message.answer(
                f"Текущий уровень сложности: {level}/10\n"
                "Уровень растёт автоматически каждые ~7 дайджестов.\n"
                "Установить вручную: /level <1-10>"
            )

    @router.message(Command("follow"))
    async def follow_handler(message: Message) -> None:
        if not service.is_admin_chat(message.chat.id):
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("Используй: /follow OpenAI")
            return
        companies = service.follow_company(parts[1].strip())
        await message.answer(f"Подписка добавлена. Подписки: {', '.join(companies)}")

    @router.message(Command("unfollow"))
    async def unfollow_handler(message: Message) -> None:
        if not service.is_admin_chat(message.chat.id):
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("Используй: /unfollow OpenAI")
            return
        companies = service.unfollow_company(parts[1].strip())
        if companies:
            await message.answer(f"Отписка выполнена. Подписки: {', '.join(companies)}")
        else:
            await message.answer("Подписок больше нет.")

    @router.message(Command("following"))
    async def following_handler(message: Message) -> None:
        if not service.is_admin_chat(message.chat.id):
            return
        companies = service.list_followed()
        if companies:
            await message.answer(f"Подписки: {', '.join(companies)}")
        else:
            await message.answer("Подписок пока нет. Добавить: /follow OpenAI")

    @router.callback_query(F.data.startswith("dg:"))
    async def digest_callback(callback: CallbackQuery) -> None:
        if callback.message is None:
            return
        if not service.is_admin_chat(callback.message.chat.id):
            return
        action = (callback.data or "").split(":")
        if len(action) < 2:
            await callback.answer()
            return

        match action[1]:
            case "more":
                digest_id = int(action[2])
                await callback.message.answer(service.render_digest_details(digest_id))
                await callback.answer()
            case "sec":
                digest_id = int(action[2])
                section_key = action[3]
                await service.send_digest_section(callback.message.chat.id, digest_id, section_key)
                await callback.answer()
            case "links":
                digest_id = int(action[2])
                link_kind = action[3]
                label, urls = service.get_digest_links(digest_id, link_kind)
                await callback.message.answer(
                    label,
                    reply_markup=links_keyboard(urls, "Открыть"),
                )
                await callback.answer()
            case "save":
                digest_id = int(action[2])
                service.save_favorite(digest_id)
                await callback.answer("Сохранено")
            case "noise":
                digest_id = int(action[2])
                updated = service.suppress_noise_for_digest(digest_id)
                await callback.answer(f"Фильтр шума усилен ({updated})")
            case "simplify":
                digest_id = int(action[2])
                await callback.answer("Упрощаю...")
                simplified = await service.explain_simpler(digest_id)
                await callback.message.answer(simplified)
            case "rate":
                digest_id = int(action[2])
                direction = action[3] if len(action) > 3 else "up"
                rating = 1 if direction == "up" else -1
                service.rate_digest(digest_id, rating)
                label = "👍 Спасибо!" if rating > 0 else "👎 Учту!"
                await callback.answer(label)
            case "refresh":
                slot = action[2] if len(action) > 2 else "now"
                await callback.answer("Обновляю")
                if slot == "today":
                    await service.sync_sources(lookback_hours=30)
                    digest_id = await service.build_digest("today")
                else:
                    digest_id = await service.refresh_and_build_current_digest()
                await service.send_digest(digest_id)
            case _:
                await callback.answer()

    return router
