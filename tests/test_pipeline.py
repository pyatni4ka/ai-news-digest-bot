from __future__ import annotations

from datetime import UTC, datetime
import unittest

from digest_bot.models import NewsItem
from digest_bot.pipeline.classify import classify_items
from digest_bot.pipeline.dedup import deduplicate, normalize_url
from digest_bot.pipeline.digest_builder import (
    build_story_media,
    build_story_cards,
    build_story_sequence,
    compute_window_with_hours,
    fallback_digest_paragraphs,
    gather_images,
    match_story_items_to_paragraphs,
    select_sections,
)


class PipelineTestCase(unittest.TestCase):
    def test_normalize_url_strips_tracking(self) -> None:
        url = "https://example.com/post?utm_source=telegram&id=42#fragment"
        self.assertEqual(normalize_url(url), "https://example.com/post?id=42")

    def test_today_window_starts_at_local_midnight(self) -> None:
        now = datetime(2026, 3, 10, 12, 15, tzinfo=UTC)
        start_at, end_at = compute_window_with_hours("today", now, "Europe/Moscow", 9, 19)
        self.assertEqual(start_at.isoformat(), "2026-03-09T21:00:00+00:00")
        self.assertEqual(end_at.isoformat(), "2026-03-10T12:15:00+00:00")

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
        self.assertIn("РЕЛИЗ AI-МОДЕЛИ", paragraphs[0])
        self.assertGreaterEqual(len(paragraphs), 6)

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
        self.assertEqual(len(sections["freebies"]), 1)

    def test_noise_items_are_filtered_from_sections(self) -> None:
        now = datetime.now(UTC)
        items = [
            NewsItem(
                source_key="tg:noise",
                external_id="noise-1",
                title="9 лучших промптов для учебы и работы",
                summary="Подборка лучших промптов на каждый день.",
                body="Подборка лучших промптов и лайфхаков для учебы и работы.",
                url="https://example.com/noise-1",
                published_at=now,
                collected_at=now,
                tags=["telegram"],
            ),
            NewsItem(
                source_key="rss:official",
                external_id="release-1",
                title="Anthropic ships Claude Sonnet 4.6",
                summary="New model release focused on coding and agents.",
                body="Anthropic released Claude Sonnet 4.6 with better coding, long context and agent planning.",
                url="https://example.com/release-1",
                published_at=now,
                collected_at=now,
                tags=["official"],
            ),
        ]
        classify_items(items)
        self.assertIn("noise", items[0].categories)
        sections = select_sections(items, slot="manual")
        headline_titles = [item.title for item in sections["headline"]]
        self.assertIn("Anthropic ships Claude Sonnet 4.6", headline_titles)
        self.assertNotIn("9 лучших промптов для учебы и работы", headline_titles)

    def test_general_non_ai_items_are_filtered_from_sections(self) -> None:
        now = datetime.now(UTC)
        items = [
            NewsItem(
                source_key="tg:noise",
                external_id="noise-2",
                title="Учим любой язык с нуля до С1 БЕСПЛАТНО",
                summary="На YouTube нашли канал с десятками плейлистов для изучения языков.",
                body="Десятки плейлистов для языков и учебы без какого-либо отношения к AI.",
                url="https://example.com/noise-2",
                published_at=now,
                collected_at=now,
                tags=["telegram", "coding", "engineering"],
            ),
            NewsItem(
                source_key="rss:official",
                external_id="release-2",
                title="OpenAI launches new coding agent",
                summary="New coding agent for repo editing and IDE workflows.",
                body="OpenAI launched a new coding agent for repository editing and IDE workflows.",
                url="https://example.com/release-2",
                published_at=now,
                collected_at=now,
                tags=["official"],
            ),
        ]
        classify_items(items)
        sections = select_sections(items, slot="manual")
        headline_titles = [item.title for item in sections["headline"]]
        self.assertIn("OpenAI launches new coding agent", headline_titles)
        self.assertNotIn("Учим любой язык с нуля до С1 БЕСПЛАТНО", headline_titles)

    def test_watchlist_release_scores_higher_than_generic_release(self) -> None:
        now = datetime.now(UTC)
        items = [
            NewsItem(
                source_key="rss:watchlist",
                external_id="watch-1",
                title="OpenAI launches Codex coding agent",
                summary="Official release for repo editing and terminal tasks.",
                body="OpenAI launched Codex coding agent for repository editing and terminal work.",
                url="https://example.com/watch-1",
                published_at=now,
                collected_at=now,
                tags=["official"],
            ),
            NewsItem(
                source_key="rss:generic",
                external_id="generic-1",
                title="Acme launches coding agent",
                summary="Official release for repo editing and terminal tasks.",
                body="Acme launched a coding agent for repository editing and terminal work.",
                url="https://example.com/generic-1",
                published_at=now,
                collected_at=now,
                tags=["official"],
            ),
        ]
        classify_items(items)
        self.assertIn("watchlist", items[0].categories)
        self.assertGreater(items[0].importance, items[1].importance)
        sections = select_sections(items, slot="manual")
        self.assertEqual(sections["watchlist"][0].title, "OpenAI launches Codex coding agent")

    def test_dev_tools_block_is_rendered(self) -> None:
        now = datetime.now(UTC)
        items = [
            NewsItem(
                source_key="rss:model",
                external_id="model-1",
                title="Anthropic ships Claude Sonnet 4.6",
                summary="Major model update for coding and agents.",
                body="Anthropic released Claude Sonnet 4.6 with better coding, long context and agent planning.",
                url="https://example.com/model-1",
                published_at=now,
                collected_at=now,
                categories=["models", "release", "coding"],
                importance=12.0,
            ),
            NewsItem(
                source_key="rss:dev",
                external_id="dev-1",
                title="Cursor launches background coding agent",
                summary="Cursor added a new repo agent for IDE workflows.",
                body="Cursor launched a background coding agent for repository tasks in the IDE.",
                url="https://example.com/dev-1",
                published_at=now,
                collected_at=now,
                categories=["coding", "dev_tools", "watchlist"],
                importance=11.0,
            ),
            NewsItem(
                source_key="rss:dev",
                external_id="dev-2",
                title="Windsurf updates its IDE agents",
                summary="Windsurf shipped faster IDE agents for debugging.",
                body="Windsurf updated its IDE agents with faster debugging and editing loops.",
                url="https://example.com/dev-2",
                published_at=now,
                collected_at=now,
                categories=["coding", "dev_tools", "vibe_coding", "watchlist"],
                importance=10.5,
            ),
            NewsItem(
                source_key="rss:dev",
                external_id="dev-3",
                title="OpenHands ships a new developer app",
                summary="OpenHands added a new desktop app for coding agents.",
                body="OpenHands launched a new developer app for coding agents and repository workflows.",
                url="https://example.com/dev-3",
                published_at=now,
                collected_at=now,
                categories=["coding", "dev_tools", "resources", "watchlist"],
                importance=10.0,
            ),
        ]
        sections = select_sections(items, slot="manual")
        cards = build_story_cards("manual", sections, 6)
        self.assertTrue(any("Cursor запустила background coding agent" in card for card in cards))
        self.assertTrue(any("Windsurf обновила IDE-агентов" in card for card in cards))

    def test_english_items_are_localized_to_russian_in_fallback(self) -> None:
        now = datetime.now(UTC)
        items = [
            NewsItem(
                source_key="rss:model",
                external_id="ru-1",
                title="Anthropic ships Claude Sonnet 4.6",
                summary="Major model update for coding, long context and agents.",
                body="Anthropic released Claude Sonnet 4.6 with better coding, long context and agent planning.",
                url="https://example.com/ru-1",
                published_at=now,
                collected_at=now,
                categories=["models", "release", "coding", "watchlist"],
                importance=12.0,
            ),
        ]
        sections = select_sections(items, slot="manual")
        cards = build_story_cards("manual", sections, 6)
        self.assertTrue(cards)
        self.assertIn("выпустила", cards[0].lower())
        self.assertIn("Релиз сфокусирован", cards[0])

    def test_gather_images_prefers_one_cover_per_item_before_extras(self) -> None:
        now = datetime.now(UTC)
        items = [
            NewsItem(
                source_key="rss:one",
                external_id="1",
                title="One",
                summary="",
                body="",
                url="https://example.com/1",
                published_at=now,
                collected_at=now,
                importance=10.0,
                images=[
                    "https://example.com/assets/logo.svg",
                    "https://example.com/assets/story-one-cover.png",
                    "https://example.com/assets/story-one-inline.png",
                ],
            ),
            NewsItem(
                source_key="rss:two",
                external_id="2",
                title="Two",
                summary="",
                body="",
                url="https://example.com/2",
                published_at=now,
                collected_at=now,
                importance=9.0,
                images=[
                    "https://example.com/assets/placeholder.svg",
                    "https://example.com/assets/story-two-cover.png",
                    "https://example.com/assets/story-two-inline.png",
                ],
            ),
        ]
        images = gather_images(items, 4)
        self.assertEqual(
            images[:2],
            [
                "https://example.com/assets/story-one-cover.png",
                "https://example.com/assets/story-two-cover.png",
            ],
        )

    def test_gather_images_skips_extras_when_enough_primary_images_exist(self) -> None:
        now = datetime.now(UTC)
        items = []
        for index in range(5):
            items.append(
                NewsItem(
                    source_key=f"rss:{index}",
                    external_id=str(index),
                    title=f"Item {index}",
                    summary="",
                    body="",
                    url=f"https://example.com/{index}",
                    published_at=now,
                    collected_at=now,
                    importance=10.0 - index,
                    images=[
                        f"https://example.com/assets/item-{index}-cover.png",
                        f"https://example.com/assets/item-{index}-inline.png",
                    ],
                )
            )
        images = gather_images(items, 4)
        self.assertEqual(
            images,
            [
                "https://example.com/assets/item-0-cover.png",
                "https://example.com/assets/item-1-cover.png",
                "https://example.com/assets/item-2-cover.png",
                "https://example.com/assets/item-3-cover.png",
            ],
        )

    def test_build_story_media_attaches_one_image_per_main_story(self) -> None:
        now = datetime.now(UTC)
        items = [
            NewsItem(
                db_id=101,
                source_key="rss:model",
                external_id="model-1",
                title="Anthropic ships Claude Sonnet 4.6",
                summary="Major model update for coding and agents.",
                body="Anthropic released Claude Sonnet 4.6 with better coding and agent planning.",
                url="https://example.com/model-1",
                published_at=now,
                collected_at=now,
                categories=["models", "release", "coding"],
                importance=12.0,
                images=["https://example.com/model-1-cover.png", "https://example.com/model-1-inline.png"],
            ),
            NewsItem(
                db_id=102,
                source_key="rss:dev",
                external_id="dev-1",
                title="Cursor launches background coding agent",
                summary="Cursor added a new repo agent for IDE workflows.",
                body="Cursor launched a background coding agent for repository tasks in the IDE.",
                url="https://example.com/dev-1",
                published_at=now,
                collected_at=now,
                categories=["coding", "dev_tools", "watchlist"],
                importance=11.0,
                images=["https://example.com/dev-1-cover.png"],
            ),
        ]
        sections = select_sections(items, slot="manual")
        story_media = build_story_media("manual", sections, max_items=4)
        self.assertEqual(
            story_media,
            [
                {
                    "title": "Claude Sonnet 4.6",
                    "image_paths": ["https://example.com/model-1-cover.png"],
                    "item_id": 101,
                    "url": "https://example.com/model-1",
                },
                {
                    "title": "Cursor launches background coding agent",
                    "image_paths": ["https://example.com/dev-1-cover.png"],
                    "item_id": 102,
                    "url": "https://example.com/dev-1",
                },
            ],
        )

    def test_match_story_items_to_paragraphs_uses_title_similarity(self) -> None:
        now = datetime.now(UTC)
        items = [
            NewsItem(
                db_id=1,
                source_key="rss:model",
                external_id="model-1",
                title="Introducing Sonnet 4.6",
                summary="Claude Sonnet 4.6 is the new model for coding and long context.",
                body="",
                url="https://example.com/sonnet",
                published_at=now,
                collected_at=now,
                categories=["models", "release", "coding"],
                importance=10.0,
            ),
            NewsItem(
                db_id=2,
                source_key="rss:dev",
                external_id="dev-1",
                title="DeepSWE: Training a Fully Open-sourced Coding Agent",
                summary="DeepSWE-Preview reached a high score on SWE-Bench.",
                body="",
                url="https://example.com/deepswe",
                published_at=now,
                collected_at=now,
                categories=["coding", "dev_tools"],
                importance=9.0,
            ),
        ]
        paragraphs = [
            "🤖 CLAUDE SONNET 4.6: Anthropic выпустила обновлённую модель для coding.",
            "🧠 DEEPSWE-PREVIEW: Together AI представила coding agent с высоким результатом на SWE-Bench.",
        ]
        matched = match_story_items_to_paragraphs(paragraphs, items)
        self.assertEqual([item.db_id if item else None for item in matched], [1, 2])


if __name__ == "__main__":
    unittest.main()
