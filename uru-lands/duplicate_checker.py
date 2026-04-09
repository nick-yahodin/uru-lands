"""Проверка и фильтрация дубликатов объявлений."""

import json
import hashlib
import logging
import os
from datetime import datetime, timedelta
from typing import List, Set

from models import Listing
from config import CACHE_FILE

logger = logging.getLogger(__name__)


class DuplicateChecker:
    """
    Фильтрует дубликаты по:
    1. URL (точное совпадение)
    2. ML Item ID
    3. Хеш контента (title + price + location)
    """

    def __init__(self, cache_file: str = CACHE_FILE, max_age_days: int = 30):
        self.cache_file = cache_file
        self.max_age_days = max_age_days
        self._seen_urls: Set[str] = set()
        self._seen_ids: Set[str] = set()
        self._seen_hashes: Set[str] = set()
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                cutoff = datetime.now() - timedelta(days=self.max_age_days)
                for entry in data:
                    ts = entry.get("ts", "")
                    try:
                        if ts and datetime.fromisoformat(ts) < cutoff:
                            continue
                    except (ValueError, TypeError):
                        pass

                    if entry.get("url"):
                        self._seen_urls.add(entry["url"])
                    if entry.get("ml_id"):
                        self._seen_ids.add(entry["ml_id"])
                    if entry.get("hash"):
                        self._seen_hashes.add(entry["hash"])

                logger.info(f"Loaded {len(self._seen_urls)} seen URLs from cache")
        except Exception as e:
            logger.error(f"Failed to load cache: {e}")

    def _save(self, listings: List[Listing]):
        """Добавляет новые листинги в кеш и сохраняет."""
        try:
            existing = []
            if os.path.exists(self.cache_file):
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)

            for lst in listings:
                existing.append({
                    "url": str(lst.url),
                    "ml_id": lst.ml_item_id or "",
                    "hash": self._content_hash(lst),
                    "ts": datetime.now().isoformat(),
                })

            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False)

        except Exception as e:
            logger.error(f"Failed to save cache: {e}")

    @staticmethod
    def _content_hash(listing: Listing) -> str:
        content = f"{listing.title}|{listing.price}|{listing.location}".lower()
        return hashlib.md5(content.encode()).hexdigest()

    def is_duplicate(self, listing: Listing) -> bool:
        url_str = str(listing.url)
        if url_str in self._seen_urls:
            return True
        if listing.ml_item_id and listing.ml_item_id in self._seen_ids:
            return True
        if self._content_hash(listing) in self._seen_hashes:
            return True
        return False

    def filter_new(self, listings: List[Listing]) -> List[Listing]:
        """Возвращает только новые (не виденные ранее) объявления."""
        new = []
        for lst in listings:
            if not self.is_duplicate(lst):
                self._seen_urls.add(str(lst.url))
                if lst.ml_item_id:
                    self._seen_ids.add(lst.ml_item_id)
                self._seen_hashes.add(self._content_hash(lst))
                new.append(lst)

        dupes = len(listings) - len(new)
        if dupes:
            logger.info(f"Filtered {dupes} duplicates, {len(new)} new listings")

        self._save(new)
        return new
