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
                KeyboardButton(text="Дайджест сейчас"),
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
    rows = [
        [
            InlineKeyboardButton(text="Подробнее", callback_data=f"dg:more:{digest_id}"),
            InlineKeyboardButton(text="Дайджест сейчас", callback_data="dg:refresh:now"),
        ],
        [
            InlineKeyboardButton(text="Модели", callback_data=f"dg:sec:{digest_id}:models"),
            InlineKeyboardButton(text="Coding", callback_data=f"dg:sec:{digest_id}:coding"),
        ],
        [
            InlineKeyboardButton(
                text="Dev tools",
                callback_data=f"dg:sec:{digest_id}:dev_tools",
            ),
            InlineKeyboardButton(
                text="Vibe coding",
                callback_data=f"dg:sec:{digest_id}:vibe_coding",
            ),
        ],
        [
            InlineKeyboardButton(text="Сравнения", callback_data=f"dg:sec:{digest_id}:comparisons"),
            InlineKeyboardButton(text="Ресурсы", callback_data=f"dg:sec:{digest_id}:resources"),
        ],
        [
            InlineKeyboardButton(text="Сохранить", callback_data=f"dg:save:{digest_id}"),
            InlineKeyboardButton(text="Меньше такого", callback_data=f"dg:noise:{digest_id}"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def digest_static_keyboard(payload: dict) -> InlineKeyboardMarkup | None:
    sections = payload.get("sections", {})
    section_specs = [
        ("Модели", sections.get("models", {}).get("links", [])),
        ("Dev tools", sections.get("dev_tools", {}).get("links", [])),
        ("Coding", sections.get("coding", {}).get("links", [])),
        ("Vibe coding", sections.get("vibe_coding", {}).get("links", [])),
        ("Сравнения", sections.get("comparisons", {}).get("links", [])),
        ("Ресурсы", sections.get("resources", {}).get("links", [])),
    ]
    rows: list[list[InlineKeyboardButton]] = []
    current_row: list[InlineKeyboardButton] = []
    for label, links in section_specs:
        if not links:
            continue
        current_row.append(InlineKeyboardButton(text=label, url=links[0]))
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def links_keyboard(urls: list[str], prefix: str) -> InlineKeyboardMarkup | None:
    if not urls:
        return None
    rows = [
        [InlineKeyboardButton(text=f"{prefix} {index + 1}", url=url)]
        for index, url in enumerate(urls[:5])
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
