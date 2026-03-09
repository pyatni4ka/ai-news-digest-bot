from __future__ import annotations

from datetime import UTC, datetime
import unittest

from digest_bot.collectors.rss import _parse_feed_datetime
from digest_bot.collectors.webpage import _extract_article_candidates, _parse_article
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


if __name__ == "__main__":
    unittest.main()
