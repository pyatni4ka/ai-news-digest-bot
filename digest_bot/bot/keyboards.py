from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="Сейчас"),
                KeyboardButton(text="Главное"),
                KeyboardButton(text="Модели"),
            ],
            [
                KeyboardButton(text="Coding"),
                KeyboardButton(text="Dev tools"),
                KeyboardButton(text="Vibe coding"),
            ],
            [
                KeyboardButton(text="Сравнения"),
                KeyboardButton(text="За месяц"),
                KeyboardButton(text="Источники"),
            ],
            [
                KeyboardButton(text="Настройки"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие",
    )


def digest_inline_keyboard(digest_id: int, payload: dict) -> InlineKeyboardMarkup:
    model_links = payload.get("summary_payload", {}).get("model_links", [])
    resource_links = payload.get("summary_payload", {}).get("resource_links", [])
    rows = [
        [
            InlineKeyboardButton(text="Подробнее", callback_data=f"dg:more:{digest_id}"),
            InlineKeyboardButton(text="Только coding", callback_data=f"dg:sec:{digest_id}:coding"),
        ],
        [
            InlineKeyboardButton(
                text="Только dev tools",
                callback_data=f"dg:sec:{digest_id}:dev_tools",
            ),
            InlineKeyboardButton(
                text="Только vibe coding",
                callback_data=f"dg:sec:{digest_id}:vibe_coding",
            ),
        ],
        [
            InlineKeyboardButton(text="Ресурсы", callback_data=f"dg:links:{digest_id}:resources"),
        ],
        [
            InlineKeyboardButton(text="Сохранить", callback_data=f"dg:save:{digest_id}"),
            InlineKeyboardButton(text="Меньше такого", callback_data=f"dg:noise:{digest_id}"),
        ],
        [InlineKeyboardButton(text="Обновить сейчас", callback_data="dg:refresh:now")],
    ]
    if model_links:
        rows.insert(
            2,
            [InlineKeyboardButton(text="Открыть модель", url=model_links[0])],
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def digest_static_keyboard(payload: dict) -> InlineKeyboardMarkup | None:
    model_links = payload.get("summary_payload", {}).get("model_links", [])
    resource_links = payload.get("summary_payload", {}).get("resource_links", [])
    rows: list[list[InlineKeyboardButton]] = []
    if model_links:
        rows.append([InlineKeyboardButton(text="Открыть модель", url=model_links[0])])
    if resource_links:
        rows.append([InlineKeyboardButton(text="Открыть ресурс", url=resource_links[0])])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def links_keyboard(urls: list[str], prefix: str) -> InlineKeyboardMarkup | None:
    if not urls:
        return None
    rows = [
        [InlineKeyboardButton(text=f"{prefix} {index + 1}", url=url)]
        for index, url in enumerate(urls[:5])
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
