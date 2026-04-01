from __future__ import annotations

import asyncio
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
    extract_story_indexes,
    fallback_digest_paragraphs,
    gather_images,
    match_story_items_to_paragraphs,
    select_sections,
    strip_story_index,
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

    def test_classify_does_not_match_substrings_inside_unrelated_words(self) -> None:
        now = datetime.now(UTC)
        items = [
            NewsItem(
                source_key="tg:test",
                external_id="video-1",
                title="Sora’s shutdown could be a reality check moment for AI video",
                summary="This is about AI video and market strategy.",
                body="A market story about AI video and product positioning.",
                published_at=now,
                collected_at=now,
                tags=["news", "ai"],
            ),
            NewsItem(
                source_key="tg:test",
                external_id="raiders-1",
                title="Streamer drama in ARC Raiders",
                summary="A gaming story that should stay outside the digest.",
                body="Pure gaming drama around a match and a streamer conflict.",
                published_at=now,
                collected_at=now,
                tags=["telegram", "tech"],
            ),
        ]
        classify_items(items)
        for item in items:
            self.assertNotIn("coding", item.categories)
            self.assertNotIn("dev_tools", item.categories)
            self.assertNotIn("watchlist", item.categories)

    def test_classify_reset_rebuilds_categories_from_scratch(self) -> None:
        now = datetime.now(UTC)
        item = NewsItem(
            source_key="tg:test",
            external_id="reset-1",
            title="Streamer drama in ARC Raiders",
            summary="Gaming story only.",
            body="Pure gaming story with no engineering angle.",
            published_at=now,
            collected_at=now,
            tags=["telegram", "tech"],
            categories=["coding", "dev_tools", "watchlist"],
        )
        classify_items([item], reset=True)
        self.assertEqual(item.categories, ["general"])

    def test_classify_ignores_late_body_footer_mentions_for_ai_relevance(self) -> None:
        now = datetime.now(UTC)
        item = NewsItem(
            source_key="web:test",
            external_id="footer-1",
            title="Pretext",
            summary=(
                "A new browser library measures wrapped text height without touching the DOM. "
                "The article is about rendering performance, not AI."
            ),
            body=(
                ("This browser tooling article is about layout performance and rendering. " * 20)
                + "Later in the footer the author mentions Claude in passing while discussing a demo artifact."
            ),
            published_at=now,
            collected_at=now,
            tags=["javascript", "react", "typescript"],
        )
        classify_items([item], reset=True)
        self.assertEqual(item.categories, ["general"])

    def test_classify_does_not_treat_google_drive_as_ai_watchlist_news(self) -> None:
        now = datetime.now(UTC)
        item = NewsItem(
            source_key="tg:test",
            external_id="drive-1",
            title="Telegram Drive превращает мессенджер в Google Drive",
            summary="Инструмент для хранения файлов в Telegram без AI-функций.",
            body="Обычный файловый клиент для Telegram с поддержкой Windows и macOS.",
            published_at=now,
            collected_at=now,
            tags=["telegram", "engineering"],
        )
        classify_items([item], reset=True)
        self.assertEqual(item.categories, ["general"])

    def test_classify_filters_offtopic_ai_documentary_story(self) -> None:
        now = datetime.now(UTC)
        item = NewsItem(
            source_key="tg:test",
            external_id="movie-1",
            title="В прокат вышел документальный фильм о будущем ИИ",
            summary=(
                "Документалка собирает интервью с Сэмом Альтманом, Anthropic и DeepMind, "
                "но не содержит продуктового или исследовательского релиза."
            ),
            body="Фильм обсуждает будущее индустрии и мнения экспертов об ИИ.",
            published_at=now,
            collected_at=now,
            tags=["telegram", "ai", "machine_learning"],
        )
        classify_items([item], reset=True)
        sections = select_sections([item], slot="manual")
        self.assertEqual(sections["headline"], [])

    def test_monthly_sections_and_fallback(self) -> None:
        now = datetime.now(UTC)
        items = []
        for idx in range(10):
            items.append(
                NewsItem(
                    source_key="rss:test",
                    external_id=str(idx),
                    title=f"New coding model {idx} released",
                    summary="Major AI release for coding agents and repo editing.",
                    body="Major AI release for coding agents and repo editing with longer context.",
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
        self.assertIn("\n", paragraphs[0])
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
        # Model name is in the title (uppercased for model release)
        self.assertIn("CLAUDE SONNET 4.6", cards[0])
        # English body is NOT leaked — Russian template is used instead
        self.assertNotIn("released", cards[0].lower())

    def test_non_release_story_does_not_hallucinate_model_subject_from_summary(self) -> None:
        now = datetime.now(UTC)
        items = [
            NewsItem(
                source_key="rss:analysis",
                external_id="analysis-1",
                title="Pretext — Under the Hood",
                summary="A deep dive into how Pretext uses Claude for prompt analysis.",
                body="The article explains how Pretext works with Claude. No product launch is announced.",
                url="https://example.com/pretext",
                published_at=now,
                collected_at=now,
                categories=["models", "watchlist"],
                importance=10.0,
            )
        ]
        sections = select_sections(items, slot="manual")
        cards = build_story_cards("manual", sections, 6)
        self.assertTrue(cards)
        self.assertIn("Pretext", cards[0])
        self.assertNotIn("CLAUDE ВЫПУСТИЛА НОВУЮ МОДЕЛЬ", cards[0])

    def test_python_vulnerability_lookup_uses_product_title_not_claude_code(self) -> None:
        now = datetime.now(UTC)
        items = [
            NewsItem(
                source_key="rss:simon-willison",
                external_id="pyvl-1",
                title="Python Vulnerability Lookup",
                summary=(
                    "Tool: Python Vulnerability Lookup. I had Claude Code build this HTML tool for "
                    "pasting in a pyproject.toml or requirements.txt file and checking OSV.dev."
                ),
                body=(
                    "The tool checks pyproject.toml and requirements.txt against OSV.dev and "
                    "returns Python dependency vulnerabilities."
                ),
                url="https://example.com/pyvl",
                published_at=now,
                collected_at=now,
                categories=["coding", "dev_tools", "resources", "watchlist"],
                importance=10.0,
            )
        ]
        sections = select_sections(items, slot="manual")
        cards = build_story_cards("manual", sections, 6)
        self.assertTrue(cards)
        self.assertIn("Python Vulnerability Lookup", cards[0])
        self.assertNotIn("Claude Code открыла исходный код", cards[0])

    def test_long_cyrillic_title_is_cleaned_for_digest_card(self) -> None:
        now = datetime.now(UTC)
        items = [
            NewsItem(
                source_key="tg:vibe",
                external_id="sec-claude-1",
                title=(
                    "Николас Карлини, один из самых уважаемых специалистов по безопасности, на днях "
                    "показал на живой демке, как CLAUDE находит zero-day уязвимости"
                ),
                summary="История про Claude и поиск zero-day уязвимостей в популярных проектах.",
                body="Claude нашёл blind SQL injection и другие серьёзные баги на живой демке.",
                url="https://example.com/sec-claude",
                published_at=now,
                collected_at=now,
                categories=["models", "resources", "watchlist"],
                importance=10.0,
            )
        ]
        sections = select_sections(items, slot="manual")
        cards = build_story_cards("manual", sections, 6)
        self.assertTrue(cards)
        self.assertIn("Николас Карлини показал, как CLAUDE", cards[0])

    def test_cyrillic_fragment_prefers_stats_over_low_signal_tail(self) -> None:
        now = datetime.now(UTC)
        items = [
            NewsItem(
                source_key="telegram:@vibecoding_tg",
                external_id="rewrite-1",
                title='Гений переписал CLI "claude" с использованием Codex и GPT-5.4-high.',
                summary=(
                    'Гений переписал CLI "claude" с использованием Codex и GPT-5.4-high.\n\n'
                    "По его словам, это стоило $1100 в токенах, при этом скорость работы на 73% выше, "
                    "а потребление памяти в режиме активного взаимодействия на 80% ниже.\n\n"
                    "Очень легко реверсировать claude из npm-дистрибутива, затем его переписка происходит 1:1. "
                    "Он неотличим от версии от Anthropic по заголовкам и аналитике, которую он отправляет обратно.\n\n"
                    "исходный код 😳"
                ),
                body=(
                    'Гений переписал CLI "claude" с использованием Codex и GPT-5.4-high.\n\n'
                    "По его словам, это стоило $1100 в токенах, при этом скорость работы на 73% выше, "
                    "а потребление памяти в режиме активного взаимодействия на 80% ниже.\n\n"
                    "Очень легко реверсировать claude из npm-дистрибутива, затем его переписка происходит 1:1. "
                    "Он неотличим от версии от Anthropic по заголовкам и аналитике, которую он отправляет обратно.\n\n"
                    "исходный код 😳"
                ),
                url="https://t.me/vibecoding_tg/2872",
                published_at=now,
                collected_at=now,
                categories=["coding", "dev_tools", "models", "resources", "watchlist"],
                importance=10.0,
            )
        ]
        sections = select_sections(items, slot="manual")
        cards = build_story_cards("manual", sections, 6)
        self.assertTrue(cards)
        self.assertIn("73%", cards[0])
        self.assertNotIn("исходный код 😳", cards[0])

    def test_russian_title_with_model_mention_is_not_uppercased_without_release(self) -> None:
        now = datetime.now(UTC)
        items = [
            NewsItem(
                source_key="tg:security",
                external_id="sec-1",
                title="Николас Карлини показал, как Claude находит zero-day уязвимости",
                summary="Демонстрация на Ghost CMS без релиза новой модели.",
                body="Это история про безопасность и найденные уязвимости, а не про релиз новой модели.",
                url="https://example.com/security",
                published_at=now,
                collected_at=now,
                categories=["models", "watchlist", "resources"],
                importance=10.0,
            )
        ]
        sections = select_sections(items, slot="manual")
        cards = build_story_cards("manual", sections, 6)
        self.assertTrue(cards)
        self.assertIn("Николас Карлини", cards[0])
        self.assertNotIn("НИКОЛАС КАРЛИНИ", cards[0])

    def test_english_app_story_gets_russian_title_and_non_release_emoji(self) -> None:
        from digest_bot.pipeline.digest_builder import _localized_title, _localized_fragment, _emoji_for_item
        now = datetime.now(UTC)
        item = NewsItem(
            source_key="rss:app",
            external_id="app-1",
            title="Bluesky’s new app is an AI for customizing your feed",
            summary=(
                "The latest app from the team behind Bluesky is Attie, an AI assistant that lets you build your own algorithm. "
                "Attie allows users to create custom feeds using natural language."
            ),
            body=(
                "The latest app from the team behind Bluesky is Attie, an AI assistant that lets you build your own algorithm. "
                "Attie allows users to create custom feeds using natural language."
            ),
            url="https://example.com/bluesky",
            published_at=now,
            collected_at=now,
            categories=["models", "watchlist"],
            importance=10.0,
        )
        self.assertEqual(_localized_title(item), "Bluesky запустила AI-приложение для настройки ленты")
        self.assertIn("Attie", _localized_fragment(item, 220))
        self.assertEqual(_emoji_for_item(item), "🤖")

    def test_python_vulnerability_lookup_gets_specific_fragment_not_release_template(self) -> None:
        from digest_bot.pipeline.digest_builder import _localized_fragment
        now = datetime.now(UTC)
        item = NewsItem(
            source_key="rss:tool",
            external_id="tool-1",
            title="Python Vulnerability Lookup",
            summary=(
                "Tool: Python Vulnerability Lookup. A HTML tool for pasting in a pyproject.toml or requirements.txt "
                "file and seeing a list of all reported vulnerabilities from the OSV.dev API."
            ),
            body=(
                "Tool: Python Vulnerability Lookup. A HTML tool for pasting in a pyproject.toml or requirements.txt "
                "file and seeing a list of all reported vulnerabilities from the OSV.dev API."
            ),
            url="https://example.com/tool",
            published_at=now,
            collected_at=now,
            categories=["coding", "dev_tools", "models", "resources", "vibe_coding", "watchlist"],
            importance=10.0,
        )
        fragment = _localized_fragment(item, 220)
        self.assertIn("OSV.dev", fragment)
        self.assertIn("уязвим", fragment.lower())
        self.assertNotIn("Релиз сфокусирован", fragment)

    def test_analytic_open_source_story_is_not_described_as_model_release(self) -> None:
        from digest_bot.pipeline.digest_builder import _localized_title, _localized_fragment
        now = datetime.now(UTC)
        item = NewsItem(
            source_key="rss:analysis",
            external_id="analysis-2",
            title="96% of codebases rely on open source, and AI slop is putting them at risk",
            summary=(
                "Verbose changes. Nonsensical descriptions. Pull requests contributors can’t explain. "
                "AI is DDoS-ing open source software and maintainers say it increases maintainer workload."
            ),
            body=(
                "Verbose changes. Nonsensical descriptions. Pull requests contributors can’t explain. "
                "AI is DDoS-ing open source software and maintainers say it increases maintainer workload."
            ),
            url="https://example.com/oss-risk",
            published_at=now,
            collected_at=now,
            categories=["models", "resources"],
            importance=9.0,
        )
        self.assertIn("AI-slop", _localized_title(item))
        self.assertNotIn("Релиз сфокусирован", _localized_fragment(item, 220))

    def test_fallback_uses_template_when_body_is_empty(self) -> None:
        now = datetime.now(UTC)
        items = [
            NewsItem(
                source_key="rss:model",
                external_id="tmpl-1",
                title="Anthropic ships Claude Sonnet 4.6",
                summary="",
                body="",
                url="https://example.com/tmpl-1",
                published_at=now,
                collected_at=now,
                categories=["models", "release", "coding", "watchlist"],
                importance=12.0,
            ),
        ]
        sections = select_sections(items, slot="manual")
        cards = build_story_cards("manual", sections, 6)
        self.assertTrue(cards)
        # With no body/summary, falls back to template
        self.assertTrue(
            "Релиз сфокусирован" in cards[0]
            or "заметный апдейт" in cards[0],
            f"Expected template fallback, got: {cards[0]!r}",
        )

    def test_extract_key_sentence_picks_informative_sentence(self) -> None:
        from digest_bot.pipeline.digest_builder import _extract_key_sentence
        now = datetime.now(UTC)
        item = NewsItem(
            source_key="rss:test",
            external_id="ks-1",
            title="OpenAI launches GPT-5",
            summary="New model release.",
            body=(
                "OpenAI launched GPT-5 today. "
                "The model achieves 92% on HumanEval and supports 200k token context. "
                "It is available via API."
            ),
            url="https://example.com/ks-1",
            published_at=now,
            collected_at=now,
            categories=["models", "release"],
            importance=10.0,
        )
        sentence = _extract_key_sentence(item)
        self.assertIsNotNone(sentence)
        # Should prefer the sentence with numbers/stats
        self.assertIn("92%", sentence)

    def test_extract_key_sentence_returns_none_for_short_body(self) -> None:
        from digest_bot.pipeline.digest_builder import _extract_key_sentence
        now = datetime.now(UTC)
        item = NewsItem(
            source_key="rss:test",
            external_id="ks-2",
            title="Short news",
            summary="Brief.",
            body="Too short.",
            url="https://example.com/ks-2",
            published_at=now,
            collected_at=now,
        )
        sentence = _extract_key_sentence(item)
        self.assertIsNone(sentence)

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


    def test_truncate_at_word_boundary_does_not_cut_mid_word(self) -> None:
        from digest_bot.pipeline.digest_builder import truncate_at_word_boundary
        result = truncate_at_word_boundary("Anthropic выпустила Claude Sonnet 4.6", 25)
        self.assertIn("…", result)
        # Must not end with a partial word
        before_suffix = result.removesuffix("…")
        self.assertTrue(
            before_suffix.endswith(" ") or before_suffix == "" or not before_suffix[-1].isalpha()
            or before_suffix.split()[-1] in "Anthropic выпустила Claude Sonnet 4.6".split(),
            f"Truncated text ends mid-word: {result!r}",
        )

    def test_truncate_at_word_boundary_short_text_unchanged(self) -> None:
        from digest_bot.pipeline.digest_builder import truncate_at_word_boundary
        text = "Short text"
        self.assertEqual(truncate_at_word_boundary(text, 100), text)

    def test_truncate_at_word_boundary_respects_limit(self) -> None:
        from digest_bot.pipeline.digest_builder import truncate_at_word_boundary
        result = truncate_at_word_boundary("A " * 100, 20)
        self.assertLessEqual(len(result), 20)

    def test_match_story_items_returns_none_for_unmatched_paragraph(self) -> None:
        now = datetime.now(UTC)
        items = [
            NewsItem(
                db_id=1,
                source_key="rss:a",
                external_id="a",
                title="Anthropic ships Claude",
                summary="Claude update",
                body="",
                url="https://example.com/a",
                published_at=now,
                collected_at=now,
                categories=["models"],
                importance=10.0,
            ),
        ]
        paragraphs = [
            "🚀 CLAUDE: Anthropic выпустила Claude.",
            "🔧 Совершенно другая тема про квантовые вычисления и физику.",
        ]
        matched = match_story_items_to_paragraphs(paragraphs, items)
        self.assertEqual(matched[0].db_id, 1)
        self.assertIsNone(matched[1])

    def test_keyword_matching_uses_word_boundaries(self) -> None:
        now = datetime.now(UTC)
        item = NewsItem(
            source_key="telegram:@pekagame",
            external_id="raiders-1",
            title="Стримерша накатала на чела заяву в полицию после матча в ARC Raiders",
            summary="История про конфликт игроков и разборки после матча.",
            body="История целиком про игровой матч, конфликт игроков и разборки после стрима.",
            url="https://example.com/raiders-1",
            published_at=now,
            collected_at=now,
            tags=["telegram", "gaming"],
        )
        classify_items([item], reset=True)
        self.assertNotIn("coding", item.categories)
        self.assertNotIn("dev_tools", item.categories)
        self.assertNotIn("watchlist", item.categories)

    def test_non_ai_component_model_article_is_filtered(self) -> None:
        now = datetime.now(UTC)
        item = NewsItem(
            source_key="rss:webassembly",
            external_id="wasm-1",
            title="WebAssembly component model matures at the edge",
            summary="The article explains how the component model improves portability for edge apps.",
            body="This is about WebAssembly components, portability, runtimes and APIs for edge systems.",
            url="https://example.com/wasm-1",
            published_at=now,
            collected_at=now,
            tags=["news", "webassembly"],
        )
        classify_items([item], reset=True)
        sections = select_sections([item], slot="manual")
        self.assertEqual(sections["headline"], [])

    def test_match_story_items_requires_meaningful_similarity(self) -> None:
        now = datetime.now(UTC)
        item = NewsItem(
            db_id=11,
            source_key="rss:model",
            external_id="model-11",
            title="OpenAI launches GPT-5",
            summary="New flagship model for coding and reasoning.",
            body="",
            url="https://example.com/gpt-5",
            published_at=now,
            collected_at=now,
            categories=["models", "release", "watchlist"],
            importance=12.0,
        )
        paragraphs = ["🚀 Вышел новый релиз AI-модели\nКороткий пересказ без названия компании и модели."]
        matched = match_story_items_to_paragraphs(paragraphs, [item])
        self.assertEqual(matched, [None])

    def test_story_index_helpers_parse_and_strip_prefix(self) -> None:
        paragraphs = [
            "[1] 🚀 OpenAI выпустила GPT-5\nПодробности.",
            "[2] 🧰 Cursor обновила IDE\nПодробности.",
        ]
        self.assertEqual(extract_story_indexes(paragraphs), [1, 2])
        self.assertEqual(strip_story_index(paragraphs[0]), "🚀 OpenAI выпустила GPT-5\nПодробности.")

    def test_analytic_non_release_titles_are_not_rewritten_into_fake_releases(self) -> None:
        now = datetime.now(UTC)
        item = NewsItem(
            source_key="rss:analysis",
            external_id="analysis-1",
            title="Python Vulnerability Lookup",
            summary="A tool article about checking Python packages for vulnerabilities.",
            body="The post describes a utility and why it is useful for security workflows.",
            url="https://example.com/python-vulnerability-lookup",
            published_at=now,
            collected_at=now,
            categories=["coding", "resources", "watchlist"],
            importance=9.0,
        )
        from digest_bot.pipeline.digest_builder import _localized_title
        title = _localized_title(item)
        self.assertIn("Python Vulnerability Lookup", title)
        self.assertNotIn("Claude Code", title)
        self.assertNotIn("новую модель", title)

    def test_localized_title_uses_model_name_in_generic_fallback(self) -> None:
        now = datetime.now(UTC)
        item = NewsItem(
            source_key="rss:test",
            external_id="model-gen",
            title="Introducing GPT-5.2 preview",
            summary="A new model for coding and reasoning.",
            body="",
            url="https://example.com/gpt5",
            published_at=now,
            collected_at=now,
            categories=["models", "release"],
            importance=10.0,
        )
        from digest_bot.pipeline.digest_builder import _localized_title
        title = _localized_title(item)
        # Should not be the generic "Вышел новый релиз AI-модели" — should contain GPT
        self.assertNotEqual(title, "Вышел новый релиз AI-модели")

    def test_version_only_release_title_uses_source_name(self) -> None:
        from digest_bot.pipeline.digest_builder import _localized_title, _story_media_title
        now = datetime.now(UTC)
        item = NewsItem(
            source_key="rss:ollama-releases",
            external_id="ollama-v019",
            title="v0.19.0",
            summary=(
                "What's Changed launch: hide cline integration; launch/vscode: prefer known VS Code paths; "
                "warning when server context length is below 64k for local models."
            ),
            body="Release notes for v0.19.0.",
            url="https://github.com/ollama/ollama/releases/tag/v0.19.0-rc2",
            published_at=now,
            collected_at=now,
            categories=["coding", "dev_tools", "release"],
            importance=9.0,
        )
        self.assertEqual(_localized_title(item), "Ollama выпустила релиз v0.19.0")
        self.assertEqual(_story_media_title(item), "Ollama v0.19.0")

    def test_extract_subject_from_body_when_title_has_no_subject(self) -> None:
        now = datetime.now(UTC)
        item = NewsItem(
            source_key="rss:test",
            external_id="body-sub",
            title="New coding agent released",
            summary="A new agent for code.",
            body="OpenAI released a new coding agent for repository editing.",
            url="https://example.com/body-sub",
            published_at=now,
            collected_at=now,
            categories=["coding", "dev_tools"],
            importance=8.0,
        )
        from digest_bot.pipeline.digest_builder import _extract_subject
        subject = _extract_subject(item)
        self.assertEqual(subject, "OpenAI")


class SentenceCaseTestCase(unittest.TestCase):
    def test_sentence_case_normalizes_title_case(self) -> None:
        from digest_bot.service import DigestService
        # Access _smart_sentence_case via instance (it's a method)
        # We can test the logic directly
        service_cls = DigestService
        # Create a minimal mock-like test
        result = service_cls._smart_sentence_case(None, "ANTHROPIC ВЫПУСТИЛА НОВУЮ МОДЕЛЬ ДЛЯ CODING")
        self.assertTrue(result[0].isupper())
        # Second word should be lowercase (not a proper noun in this context)
        words = result.split()
        self.assertEqual(words[0], "Anthropic")
        self.assertEqual(words[1], "выпустила")

    def test_sentence_case_preserves_proper_names(self) -> None:
        from digest_bot.service import DigestService
        result = DigestService._smart_sentence_case(None, "OPENAI ОБНОВИЛА CHATGPT И ДОБАВИЛА API")
        self.assertIn("OpenAI", result)
        self.assertIn("ChatGPT", result)
        self.assertIn("API", result)

    def test_sentence_case_preserves_acronyms(self) -> None:
        from digest_bot.service import DigestService
        result = DigestService._smart_sentence_case(None, "НОВЫЙ SDK ДЛЯ AI МОДЕЛЕЙ")
        self.assertIn("SDK", result)
        self.assertIn("AI", result)


class DigestHtmlFormattingTestCase(unittest.TestCase):
    def test_safe_join_chunks_respects_limit(self) -> None:
        from digest_bot.service import _safe_join_chunks
        chunks = ["Title"] + [f"Paragraph {i}" * 50 for i in range(20)]
        result = _safe_join_chunks(chunks, limit=200)
        self.assertLessEqual(len(result), 200)
        self.assertTrue(result.startswith("Title"))

    def test_format_digest_html_has_links_and_counter(self) -> None:
        from digest_bot.service import DigestService
        service = DigestService.__new__(DigestService)
        text = "🚀 Claude Sonnet 4.6\nНовая модель.\n\n🧰 Cursor\nНовый агент."
        payload = {"summary_payload": {"story_links": ["https://example.com/1", "https://example.com/2"]}}
        result = service._format_digest_html("Утренний digest", text, "morning", payload)
        self.assertNotIn("───", result)  # no separator between stories
        self.assertIn("Читать →", result)
        self.assertIn("2 новости в выпуске", result)

    def test_story_image_caption_fits_telegram_limit(self) -> None:
        from digest_bot.service import DigestService
        service = DigestService.__new__(DigestService)
        title = "Очень длинный заголовок " * 80
        url = "https://example.com/" + ("path/" * 120)
        caption = service._story_image_caption(title, url)
        visible = (
            caption.replace("<b>", "")
            .replace("</b>", "")
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
        )
        self.assertLessEqual(len(visible), 1024)
        self.assertIn("К новости:", visible)


class HttpCompatSummarizerTestCase(unittest.TestCase):
    def test_normalize_digest_output_adds_missing_indexes(self) -> None:
        from digest_bot.summarizers.http_compat import normalize_digest_output

        text = (
            "🚀 OpenAI выпустила новую модель\n"
            "Модель стала быстрее и точнее. Это важно для рабочих сценариев.\n\n"
            "🧰 Cursor добавил background agent\n"
            "Теперь инструмент сам разбирает задачи по репозиторию. Это ускоряет ревью."
        )
        result = normalize_digest_output(text, 2)
        self.assertIn("[1] 🚀 OpenAI выпустила новую модель", result)
        self.assertIn("[2] 🧰 Cursor добавил background agent", result)

    def test_normalize_digest_output_rejects_wrong_story_count(self) -> None:
        from digest_bot.summarizers.http_compat import normalize_digest_output

        with self.assertRaises(ValueError):
            normalize_digest_output("🗞 Одна история\nТекст.", 2)

    def test_format_structured_digest_uses_story_order(self) -> None:
        from digest_bot.summarizers.http_compat import format_structured_digest

        now = datetime.now(UTC)
        story_order = [
            NewsItem(
                source_key="rss:test",
                external_id="1",
                title="OpenAI released a new model",
                summary="A model release story.",
                body="OpenAI introduced a new model for coding.",
                url="https://example.com/1",
                published_at=now,
                collected_at=now,
                categories=["models", "release"],
                importance=10.0,
            ),
            NewsItem(
                source_key="rss:test",
                external_id="2",
                title="Cursor ships a background coding agent",
                summary="A dev tool story.",
                body="Cursor added a background coding agent for repos.",
                url="https://example.com/2",
                published_at=now,
                collected_at=now,
                categories=["coding", "dev_tools"],
                importance=9.0,
            ),
        ]
        content = (
            '{"stories": ['
            '{"index": 1, "headline": "OpenAI выпустила новую модель", "body": "OpenAI представила новую модель для coding-задач. Это усиливает конкуренцию в AI-разработке."},'
            '{"index": 2, "headline": "Cursor добавил background agent", "body": "Cursor вынес часть задач по репозиторию в фоновый агент. Это ускоряет разбор изменений и правок."}'
            "]}"
        )
        result = format_structured_digest(content, story_order)
        self.assertIn("[1] 🚀 OpenAI выпустила новую модель", result)
        self.assertIn("[2] 🧰 Cursor добавил background agent", result)


class FallbackSummarizerTestCase(unittest.TestCase):
    def test_fallback_summarizer_prefixes_story_indexes(self) -> None:
        from digest_bot.summarizers.fallback import FallbackSummarizer

        now = datetime.now(UTC)
        items = [
            NewsItem(
                source_key="rss:test",
                external_id="1",
                title="Anthropic ships Claude Sonnet 4.6",
                summary="Major model update for coding and agents.",
                body="Anthropic released Claude Sonnet 4.6 with better coding and agent planning.",
                url="https://example.com/1",
                published_at=now,
                collected_at=now,
                categories=["models", "release", "coding", "watchlist"],
                importance=12.0,
            ),
            NewsItem(
                source_key="rss:test",
                external_id="2",
                title="Cursor ships a background coding agent",
                summary="New AI tool for repository work and terminal tasks.",
                body="Cursor released a background coding agent for repository work and terminal tasks.",
                url="https://example.com/2",
                published_at=now,
                collected_at=now,
                categories=["coding", "dev_tools", "watchlist"],
                importance=10.0,
            ),
        ]
        sections = select_sections(items, slot="manual")
        text = asyncio.run(FallbackSummarizer().summarize("manual", sections, 2))
        self.assertIn("[1]", text)
        self.assertIn("[2]", text)


if __name__ == "__main__":
    unittest.main()
