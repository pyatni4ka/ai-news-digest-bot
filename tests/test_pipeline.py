from __future__ import annotations

from datetime import UTC, datetime
import unittest

from digest_bot.models import NewsItem
from digest_bot.pipeline.classify import classify_items
from digest_bot.pipeline.dedup import deduplicate, normalize_url
from digest_bot.pipeline.digest_builder import build_story_cards, fallback_digest_paragraphs, select_sections


class PipelineTestCase(unittest.TestCase):
    def test_normalize_url_strips_tracking(self) -> None:
        url = "https://example.com/post?utm_source=telegram&id=42#fragment"
        self.assertEqual(normalize_url(url), "https://example.com/post?id=42")

    def test_classify_and_deduplicate(self) -> None:
        now = datetime.now(UTC)
        items = [
            NewsItem(
                source_key="rss:test",
                external_id="1",
                title="Cursor adds new coding agent",
                summary="A new coding agent ships with repo editing and terminal support.",
                body="Cursor released a coding agent with repo-wide editing.",
                url="https://example.com/a",
                published_at=now,
                collected_at=now,
                tags=["official"],
            ),
            NewsItem(
                source_key="rss:test2",
                external_id="2",
                title="Cursor adds new coding agent",
                summary="Same story",
                body="Same story",
                url="https://example.com/a?utm_source=x",
                published_at=now,
                collected_at=now,
                tags=["news"],
            ),
        ]
        classify_items(items)
        self.assertIn("coding", items[0].categories)
        deduped = deduplicate(items)
        self.assertEqual(len(deduped), 1)

    def test_monthly_sections_and_fallback(self) -> None:
        now = datetime.now(UTC)
        items = []
        for idx in range(10):
            items.append(
                NewsItem(
                    source_key="rss:test",
                    external_id=str(idx),
                    title=f"New coding model {idx}",
                    summary="Major update for coding agents and repo editing.",
                    body="Major update for coding agents and repo editing with longer context.",
                    url=f"https://example.com/{idx}",
                    published_at=now,
                    collected_at=now,
                    categories=["coding", "models"],
                    importance=float(10 - idx),
                )
            )
        sections = select_sections(items, slot="monthly")
        self.assertEqual(len(sections["headline"]), 10)
        self.assertEqual(len(sections["coding"]), 8)
        paragraphs = fallback_digest_paragraphs("monthly", sections)
        self.assertTrue(paragraphs[0].startswith("🚀"))
        self.assertIn(":", paragraphs[0])
        self.assertIn("NEW CODING MODEL", paragraphs[0])
        self.assertTrue(any(paragraph.startswith("🗞 Короткой строкой:") for paragraph in paragraphs))

    def test_free_items_are_marked(self) -> None:
        now = datetime.now(UTC)
        items = [
            NewsItem(
                source_key="rss:test",
                external_id="free-1",
                title="Cursor opens free plan",
                summary="Free plan is now available for all users.",
                body="Cursor launched a free plan with no cost access for personal use.",
                url="https://example.com/free-1",
                published_at=now,
                collected_at=now,
                categories=["coding", "resources"],
                importance=9.0,
            ),
            NewsItem(
                source_key="rss:test",
                external_id="free-2",
                title="Anthropic ships Claude Sonnet 4.6",
                summary="New model release for all users.",
                body="Anthropic released Claude Sonnet 4.6 for all users.",
                url="https://example.com/free-2",
                published_at=now,
                collected_at=now,
                categories=["models", "release", "coding"],
                importance=10.0,
            ),
        ]
        sections = select_sections(items, slot="manual")
        cards = build_story_cards("manual", sections, 6)
        self.assertTrue(any("АБСОЛЮТНО БЕСПЛАТНО" in card for card in cards))
        self.assertTrue(any("CLAUDE SONNET 4.6" in card for card in cards))


if __name__ == "__main__":
    unittest.main()
