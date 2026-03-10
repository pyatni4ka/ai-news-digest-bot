from __future__ import annotations

from urllib.parse import urlparse

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
                KeyboardButton(text="За сегодня"),
                KeyboardButton(text="Главное"),
            ],
            [
                KeyboardButton(text="Модели"),
                KeyboardButton(text="Coding"),
                KeyboardButton(text="Watchlist"),
            ],
            [
                KeyboardButton(text="Dev tools"),
                KeyboardButton(text="Vibe coding"),
                KeyboardButton(text="Бесплатно"),
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
    rows = [[InlineKeyboardButton(text="Дайджест сейчас", callback_data="dg:refresh:now")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def digest_static_keyboard(payload: dict, manual_digest_url: str | None = None) -> InlineKeyboardMarkup | None:
    if not manual_digest_url:
        return None
    rows = [[InlineKeyboardButton(text="Дайджест сейчас", url=manual_digest_url)]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def links_keyboard(urls: list[str], prefix: str) -> InlineKeyboardMarkup | None:
    if not urls:
        return None
    rows = [
        [InlineKeyboardButton(text=f"{prefix} {index + 1}", url=url)]
        for index, url in enumerate(urls[:5])
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _pick_topic_link(
    links: list[str] | str | None,
    used_urls: set[str],
    used_domains: set[str],
) -> str | None:
    if isinstance(links, str):
        links = [links]
    if not links:
        return None
    for url in links:
        if url and url not in used_urls and urlparse(url).netloc not in used_domains:
            return url
    for url in links:
        if url and url not in used_urls:
            return url
    return None
