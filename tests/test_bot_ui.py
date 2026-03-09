from __future__ import annotations

import unittest

from digest_bot.bot.keyboards import digest_inline_keyboard, digest_static_keyboard, main_menu_keyboard


class BotKeyboardTestCase(unittest.TestCase):
    def test_main_menu_contains_digest_now_and_topics(self) -> None:
        keyboard = main_menu_keyboard()
        labels = [button.text for row in keyboard.keyboard for button in row]
        self.assertIn("Дайджест сейчас", labels)
        self.assertIn("Модели", labels)
        self.assertIn("Dev tools", labels)
        self.assertIn("Vibe coding", labels)

    def test_inline_keyboard_contains_topic_buttons(self) -> None:
        keyboard = digest_inline_keyboard(42, {"sections": {}, "summary_payload": {}})
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertIn("Дайджест сейчас", labels)
        self.assertIn("Модели", labels)
        self.assertIn("Dev tools", labels)
        self.assertIn("Ресурсы", labels)

    def test_static_keyboard_uses_section_links(self) -> None:
        keyboard = digest_static_keyboard(
            {
                "sections": {
                    "models": {"links": ["https://example.com/model"]},
                    "dev_tools": {"links": ["https://example.com/dev"]},
                    "resources": {"links": ["https://example.com/resource"]},
                }
            }
        )
        self.assertIsNotNone(keyboard)
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertIn("Модели", labels)
        self.assertIn("Dev tools", labels)
        self.assertIn("Ресурсы", labels)


if __name__ == "__main__":
    unittest.main()
