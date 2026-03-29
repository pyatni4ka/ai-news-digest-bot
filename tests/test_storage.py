from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from digest_bot.models import Source
from digest_bot.storage import Repository


class RepositoryTestCase(unittest.TestCase):
    def test_seed_sources_updates_enabled_flag_on_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Repository(Path(tmp_dir) / "digest.db")
            source = Source(
                key="telegram:@example",
                name="@example",
                kind="telegram",
                location="@example",
                enabled=True,
            )
            repo.seed_sources([source])
            self.assertTrue(repo.list_sources(enabled_only=False)[0].enabled)

            repo.seed_sources(
                [
                    Source(
                        key="telegram:@example",
                        name="@example",
                        kind="telegram",
                        location="@example",
                        enabled=False,
                    )
                ]
            )

            sources = repo.list_sources(enabled_only=False)
            self.assertEqual(len(sources), 1)
            self.assertFalse(sources[0].enabled)


if __name__ == "__main__":
    unittest.main()
