from __future__ import annotations

import unittest

from digest_bot.bot.keyboards import digest_inline_keyboard, digest_static_keyboard, main_menu_keyboard


class BotKeyboardTestCase(unittest.TestCase):
    def test_main_menu_has_four_buttons_in_two_rows(self) -> None:
        keyboard = main_menu_keyboard()
        labels = [button.text for row in keyboard.keyboard for button in row]
        self.assertEqual(len(keyboard.keyboard), 2)
        self.assertEqual(len(labels), 4)
        self.assertIn("Свежий дайджест", labels)
        self.assertIn("За сегодня", labels)
        self.assertIn("Источники", labels)
        self.assertIn("Настройки", labels)

    def test_main_menu_has_no_category_buttons(self) -> None:
        keyboard = main_menu_keyboard()
        labels = [button.text for row in keyboard.keyboard for button in row]
        for old_label in ("Модели", "Coding", "Watchlist", "Dev tools", "Vibe coding", "Бесплатно", "Сравнения", "За месяц", "Главное"):
            self.assertNotIn(old_label, labels)

    def test_inline_keyboard_has_reaction_and_refresh_buttons(self) -> None:
        keyboard = digest_inline_keyboard(42, {"sections": {}, "summary_payload": {}})
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertIn("👍", labels)
        self.assertIn("👎", labels)
        self.assertIn("🧒 Проще", labels)
        self.assertIn("🔄 Обновить", labels)
        self.assertEqual(len(labels), 4)

    def test_static_keyboard_has_only_manual_digest_button(self) -> None:
        keyboard = digest_static_keyboard(
            {
                "sections": {
                    "models": {"links": ["https://example.com/model"]},
                }
            },
            "https://github.com/example/actions/workflows/x.yml",
        )
        self.assertIsNotNone(keyboard)
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertEqual(labels, ["Получить дайджест здесь и сейчас"])

    def test_static_keyboard_supports_manual_digest_url(self) -> None:
        keyboard = digest_static_keyboard({"sections": {}}, "https://github.com/example/actions/workflows/x.yml")
        self.assertIsNotNone(keyboard)
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertIn("Получить дайджест здесь и сейчас", labels)

if __name__ == "__main__":
    unittest.main()
