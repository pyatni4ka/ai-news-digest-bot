from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import json
import sqlite3

from digest_bot.models import Digest, DigestButton, DigestSection, NewsItem, Source


class Repository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_key TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    location TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 1,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    config_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS news_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dedup_key TEXT NOT NULL UNIQUE,
                    source_key TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    body TEXT NOT NULL,
                    url TEXT,
                    published_at TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    categories_json TEXT NOT NULL,
                    importance REAL NOT NULL DEFAULT 0,
                    images_json TEXT NOT NULL,
                    raw_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS digests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slot TEXT NOT NULL,
                    start_at TEXT NOT NULL,
                    end_at TEXT NOT NULL,
                    title TEXT NOT NULL,
                    text TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS favorites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    digest_id INTEGER NOT NULL UNIQUE,
                    saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (digest_id) REFERENCES digests(id)
                );

                CREATE TABLE IF NOT EXISTS preferences (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def seed_sources(self, sources: list[Source]) -> None:
        with self._connect() as conn:
            for source in sources:
                conn.execute(
                    """
                    INSERT INTO sources (source_key, name, kind, location, tags_json, priority, enabled, config_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_key) DO UPDATE SET
                        name = excluded.name,
                        kind = excluded.kind,
                        location = excluded.location,
                        tags_json = excluded.tags_json,
                        priority = excluded.priority,
                        config_json = excluded.config_json,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        source.key,
                        source.name,
                        source.kind,
                        source.location,
                        json.dumps(source.tags, ensure_ascii=False),
                        source.priority,
                        1 if source.enabled else 0,
                        json.dumps(source.config, ensure_ascii=False),
                    ),
                )

    def list_sources(self, enabled_only: bool = True) -> list[Source]:
        query = "SELECT * FROM sources"
        params: tuple[object, ...] = ()
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY priority DESC, name ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._map_source(row) for row in rows]

    def add_telegram_source(self, handle: str, priority: int = 3) -> Source:
        normalized = handle.strip()
        if not normalized.startswith("@"):
            normalized = f"@{normalized}"
        source = Source(
            key=f"telegram:{normalized.lower()}",
            name=normalized,
            kind="telegram",
            location=normalized,
            tags=["telegram"],
            priority=priority,
            enabled=True,
            config={"entity": normalized},
        )
        self.seed_sources([source])
        return source

    def set_source_enabled(self, source_key: str, enabled: bool) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE sources SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE source_key = ?",
                (1 if enabled else 0, source_key),
            )

    def save_news_items(self, items: list[NewsItem]) -> int:
        if not items:
            return 0
        inserted = 0
        with self._connect() as conn:
            for item in items:
                try:
                    conn.execute(
                        """
                        INSERT INTO news_items (
                            dedup_key, source_key, external_id, title, summary, body, url,
                            published_at, collected_at, tags_json, categories_json,
                            importance, images_json, raw_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item.dedup_key,
                            item.source_key,
                            item.external_id,
                            item.title,
                            item.summary,
                            item.body,
                            item.url,
                            item.published_at.isoformat(),
                            item.collected_at.isoformat(),
                            json.dumps(item.tags, ensure_ascii=False),
                            json.dumps(item.categories, ensure_ascii=False),
                            item.importance,
                            json.dumps(item.images, ensure_ascii=False),
                            json.dumps(item.raw, ensure_ascii=False),
                        ),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    continue
        return inserted

    def get_items_between(
        self,
        start_at: datetime,
        end_at: datetime,
        limit: int = 200,
        categories: list[str] | None = None,
    ) -> list[sqlite3.Row]:
        query = """
            SELECT id, dedup_key, source_key, external_id, title, summary, body, url, published_at,
                   collected_at, tags_json, categories_json, importance, images_json, raw_json
            FROM news_items
            WHERE published_at >= ? AND published_at < ?
        """
        params: list[object] = [start_at.isoformat(), end_at.isoformat()]
        if categories:
            category_like = " OR ".join(["categories_json LIKE ?" for _ in categories])
            query += f" AND ({category_like})"
            params.extend([f'%"{category}"%' for category in categories])
        query += " ORDER BY importance DESC, published_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            return conn.execute(query, tuple(params)).fetchall()

    def get_top_links(
        self,
        start_at: datetime,
        end_at: datetime,
        limit: int = 5,
        categories: list[str] | None = None,
    ) -> list[str]:
        rows = self.get_items_between(start_at, end_at, limit=limit * 3, categories=categories)
        links: list[str] = []
        for row in rows:
            if row["url"] and row["url"] not in links:
                links.append(row["url"])
            if len(links) >= limit:
                break
        return links

    def save_digest(self, digest: Digest) -> int:
        payload = {
            "paragraphs": digest.paragraphs,
            "buttons": [asdict(button) for button in digest.buttons],
            "sections": {
                key: {
                    "title": section.title,
                    "paragraph": section.paragraph,
                    "item_ids": section.item_ids,
                    "links": section.links,
                }
                for key, section in digest.section_map.items()
            },
            "image_paths": digest.image_paths,
            "summary_payload": digest.summary_payload,
        }
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO digests (slot, start_at, end_at, title, text, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    digest.slot,
                    digest.start_at.isoformat(),
                    digest.end_at.isoformat(),
                    digest.title,
                    "\n\n".join(digest.paragraphs),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            return int(cursor.lastrowid)

    def get_latest_digest(self, slot: str | None = None) -> sqlite3.Row | None:
        query = "SELECT * FROM digests"
        params: tuple[object, ...] = ()
        if slot:
            query += " WHERE slot = ?"
            params = (slot,)
        query += " ORDER BY created_at DESC LIMIT 1"
        with self._connect() as conn:
            return conn.execute(query, params).fetchone()

    def get_digest(self, digest_id: int) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM digests WHERE id = ?",
                (digest_id,),
            ).fetchone()

    def save_favorite(self, digest_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO favorites (digest_id) VALUES (?)",
                (digest_id,),
            )

    def increment_suppression(self, category: str) -> int:
        key = f"suppress:{category}"
        current = int(self.get_preference(key) or "0")
        updated = current + 1
        self.set_preference(key, str(updated))
        return updated

    def set_preference(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO preferences (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def get_preference(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM preferences WHERE key = ?",
                (key,),
            ).fetchone()
        return None if row is None else str(row["value"])

    def hydrate_digest(self, row: sqlite3.Row) -> tuple[str, dict]:
        return str(row["text"]), json.loads(str(row["payload_json"]))

    def _map_source(self, row: sqlite3.Row) -> Source:
        return Source(
            key=str(row["source_key"]),
            name=str(row["name"]),
            kind=str(row["kind"]),
            location=str(row["location"]),
            tags=json.loads(str(row["tags_json"])),
            priority=int(row["priority"]),
            enabled=bool(row["enabled"]),
            config=json.loads(str(row["config_json"])),
        )
