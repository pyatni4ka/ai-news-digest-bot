from __future__ import annotations

import unittest

from digest_bot.bot.keyboards import digest_inline_keyboard, digest_static_keyboard, main_menu_keyboard


class BotKeyboardTestCase(unittest.TestCase):
    def test_main_menu_contains_digest_now_and_topics(self) -> None:
        keyboard = main_menu_keyboard()
        labels = [button.text for row in keyboard.keyboard for button in row]
        self.assertIn("Дайджест сейчас", labels)
        self.assertIn("За сегодня", labels)
        self.assertIn("Модели", labels)
        self.assertIn("Watchlist", labels)
        self.assertIn("Бесплатно", labels)
        self.assertIn("Dev tools", labels)
        self.assertIn("Vibe coding", labels)

    def test_inline_keyboard_contains_topic_buttons(self) -> None:
        keyboard = digest_inline_keyboard(42, {"sections": {}, "summary_payload": {}})
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertIn("Дайджест сейчас", labels)
        self.assertEqual(labels, ["Дайджест сейчас"])

    def test_static_keyboard_has_only_manual_digest_button(self) -> None:
        keyboard = digest_static_keyboard(
            {
                "sections": {
                    "models": {"links": ["https://example.com/model"]},
                    "watchlist": {"links": ["https://example.com/watch"]},
                    "dev_tools": {"links": ["https://example.com/dev"]},
                    "freebies": {"links": ["https://example.com/free"]},
                    "resources": {"links": ["https://example.com/resource"]},
                }
            },
            "https://github.com/example/actions/workflows/x.yml",
        )
        self.assertIsNotNone(keyboard)
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertEqual(labels, ["Дайджест сейчас"])

    def test_static_keyboard_supports_manual_digest_url(self) -> None:
        keyboard = digest_static_keyboard({"sections": {}}, "https://github.com/example/actions/workflows/x.yml")
        self.assertIsNotNone(keyboard)
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertIn("Дайджест сейчас", labels)

if __name__ == "__main__":
    unittest.main()
