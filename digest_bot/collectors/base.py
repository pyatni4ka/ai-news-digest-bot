from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from digest_bot.models import NewsItem, Source


class Collector(ABC):
    @abstractmethod
    async def fetch(self, source: Source, since: datetime) -> list[NewsItem]:
        raise NotImplementedError

