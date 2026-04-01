from __future__ import annotations

from datetime import UTC, datetime
import unittest

from bs4 import BeautifulSoup

from digest_bot.collectors.rss import _extract_images as _extract_rss_images
from digest_bot.collectors.rss import _parse_feed_datetime
from digest_bot.collectors.webpage import (
    _extract_article_candidates,
    _extract_images as _extract_webpage_images,
    _limit_article_candidates,
    _parse_article,
)
from digest_bot.models import Source


class CollectorParsingTestCase(unittest.TestCase):
    def test_rss_entry_without_datetime_is_skipped(self) -> None:
        self.assertIsNone(_parse_feed_datetime({}))

    def test_webpage_candidate_extracts_listing_date(self) -> None:
        html = """
        <html><body>
          <ul>
            <li>
              <a href="/blog/ideogram-v3">Ideogram 3.0 on Replicate</a>
              <span>May 7, 2025</span>
            </li>
          </ul>
        </body></html>
        """
        candidates = _extract_article_candidates(
            html=html,
            listing_url="https://replicate.com/blog",
            include_patterns=["/blog/"],
            exclude_patterns=[],
            limit=10,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0][0], "https://replicate.com/blog/ideogram-v3")
        self.assertEqual(candidates[0][1], datetime(2025, 5, 7, tzinfo=UTC))

    def test_webpage_candidate_limit_prefers_fresh_then_undated(self) -> None:
        since = datetime(2025, 5, 1, tzinfo=UTC)
        candidates = [
            ("https://example.com/old", datetime(2025, 4, 10, tzinfo=UTC)),
            ("https://example.com/fresh-b", datetime(2025, 5, 7, tzinfo=UTC)),
            ("https://example.com/undated", None),
            ("https://example.com/fresh-a", datetime(2025, 5, 8, tzinfo=UTC)),
        ]
        limited = _limit_article_candidates(candidates, since=since, limit=3)
        self.assertEqual(
            limited,
            [
                ("https://example.com/fresh-a", datetime(2025, 5, 8, tzinfo=UTC)),
                ("https://example.com/fresh-b", datetime(2025, 5, 7, tzinfo=UTC)),
                ("https://example.com/undated", None),
            ],
        )

    def test_webpage_article_without_any_date_is_skipped(self) -> None:
        source = Source(
            key="webpage:test",
            name="Test",
            kind="webpage",
            location="https://example.com/blog",
        )
        html = """
        <html>
          <head><title>Old post</title><meta property="og:title" content="Old post"></head>
          <body><article><p>This page has content but no publication date.</p></article></body>
        </html>
        """
        item = _parse_article(source, "https://example.com/blog/old-post", html, None)
        self.assertIsNone(item)

    def test_webpage_images_prefer_cover_over_placeholders_and_icons(self) -> None:
        html = """
        <html>
          <head>
            <meta property="og:image" content="https://example.com/images/story-cover.png">
          </head>
          <body>
            <header><img src="/assets/logo.svg" class="site-logo"></header>
            <article>
              <img src="/assets/placeholder.svg" class="announcement-bar_logo">
              <img src="/assets/google.svg" class="icon-24">
              <figure><img src="/assets/story-inline.webp" width="1200" height="630" alt="Story cover"></figure>
            </article>
          </body>
        </html>
        """
        soup = BeautifulSoup(html, "html.parser")
        soup_images = _extract_webpage_images(soup, "https://example.com/post")
        self.assertEqual(
            soup_images,
            [
                "https://example.com/images/story-cover.png",
                "https://example.com/assets/story-inline.webp",
            ],
        )

    def test_rss_images_filter_bad_assets(self) -> None:
        summary_html = """
        <div>
          <img src="https://example.com/assets/placeholder.svg" class="announcement-bar_logo">
          <img src="https://example.com/assets/site-logo.png" class="logo">
          <img src="https://example.com/assets/story-preview.png" width="1280" height="720" alt="Story preview">
        </div>
        """
        entry = {
            "media_content": [
                {
                    "url": "https://example.com/assets/story-cover.png",
                    "width": "1600",
                    "height": "900",
                }
            ]
        }
        images = _extract_rss_images(summary_html, entry)
        self.assertEqual(
            images,
            [
                "https://example.com/assets/story-cover.png",
                "https://example.com/assets/story-preview.png",
            ],
        )


if __name__ == "__main__":
    unittest.main()
