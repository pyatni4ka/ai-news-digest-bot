from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from digest_bot.bot.keyboards import digest_inline_keyboard, links_keyboard, main_menu_keyboard
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
    async def digest_now_handler(message: Message) -> None:
        if not service.is_admin_chat(message.chat.id):
            return
        await message.answer("Собираю свежий выпуск.")
        digest_id = await service.refresh_and_build_current_digest()
        await service.send_digest(digest_id)

    @router.message(Command("digest_month"))
    @router.message(F.text == "За месяц")
    async def digest_month_handler(message: Message) -> None:
        if not service.is_admin_chat(message.chat.id):
            return
        await message.answer("Собираю месячный выпуск.")
        await service.sync_sources(lookback_hours=24 * 31)
        digest_id = await service.build_digest("monthly")
        await service.send_digest(digest_id)

    @router.message(F.text == "Главное")
    async def headline_handler(message: Message) -> None:
        if not service.is_admin_chat(message.chat.id):
            return
        await _send_latest_digest(message, service)

    @router.message(F.text == "Модели")
    async def models_handler(message: Message) -> None:
        if not service.is_admin_chat(message.chat.id):
            return
        await _send_section(message, service, "models")

    @router.message(F.text == "Coding")
    async def coding_handler(message: Message) -> None:
        if not service.is_admin_chat(message.chat.id):
            return
        await _send_section(message, service, "coding")

    @router.message(F.text == "Vibe coding")
    async def vibe_handler(message: Message) -> None:
        if not service.is_admin_chat(message.chat.id):
            return
        await _send_section(message, service, "vibe_coding")

    @router.message(F.text == "Сравнения")
    async def comparisons_handler(message: Message) -> None:
        if not service.is_admin_chat(message.chat.id):
            return
        await _send_section(message, service, "comparisons")

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
                await callback.message.answer(service.render_digest_section(digest_id, section_key))
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
            case "refresh":
                await callback.answer("Обновляю")
                digest_id = await service.refresh_and_build_current_digest()
                await service.send_digest(digest_id)
            case _:
                await callback.answer()

    return router


async def _send_latest_digest(message: Message, service: DigestService) -> None:
    digest_id = service.latest_digest_id()
    if digest_id is None:
        digest_id = await service.refresh_and_build_current_digest()
    text, payload = service.render_digest_message(digest_id)
    await message.answer(text, parse_mode="HTML", reply_markup=digest_inline_keyboard(digest_id, payload))


async def _send_section(message: Message, service: DigestService, key: str) -> None:
    digest_id = service.latest_digest_id()
    if digest_id is None:
        digest_id = await service.refresh_and_build_current_digest()
    await message.answer(service.render_digest_section(digest_id, key))
