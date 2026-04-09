"""
Скрапер MercadoLibre — API-first подход.

Стратегия:
1. Поиск через публичный API (быстро, надёжно, без блокировок)
2. Детали через API /items/{id} (все поля, включая координаты)
3. Playwright fallback ТОЛЬКО для описания (если нет в API)
"""

import re
import asyncio
import logging
import random
from datetime import datetime
from typing import List, Optional, Dict, Any

import aiohttp

from config import (
    ML_API_BASE, ML_SEARCH_URL, ML_ITEM_URL, ML_CATEGORY_TERRENOS,
    REQUEST_DELAY_MIN, REQUEST_DELAY_MAX, MAX_LISTINGS,
)
from models import Listing

logger = logging.getLogger(__name__)


class MercadoLibreScraper:
    """Скрапер MercadoLibre через публичный API."""

    def __init__(self, session: Optional[aiohttp.ClientSession] = None):
        self._session = session
        self._own_session = session is None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={"Accept": "application/json"},
            )
            self._own_session = True
        return self._session

    async def close(self):
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()

    # ── Поиск ─────────────────────────────────────────────

    async def search_listings(
        self,
        max_results: int = MAX_LISTINGS,
        sort: str = "date_desc",
        price_min: Optional[int] = None,
        price_max: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Ищет объявления о земельных участках через API MercadoLibre.

        Returns:
            Список сырых результатов из API
        """
        session = await self._get_session()
        all_results = []
        offset = 0
        limit = min(50, max_results)  # API лимит — 50 за запрос

        while offset < max_results:
            params = {
                "category": ML_CATEGORY_TERRENOS,
                "sort_id": sort,
                "offset": offset,
                "limit": limit,
            }

            if price_min:
                params["price"] = f"{price_min}-*"
            if price_max:
                params["price"] = f"*-{price_max}"
            if price_min and price_max:
                params["price"] = f"{price_min}-{price_max}"

            try:
                async with session.get(ML_SEARCH_URL, params=params) as resp:
                    if resp.status != 200:
                        logger.error(f"API search error: {resp.status}")
                        break

                    data = await resp.json()
                    results = data.get("results", [])

                    if not results:
                        logger.info(f"No more results at offset {offset}")
                        break

                    all_results.extend(results)
                    total = data.get("paging", {}).get("total", 0)
                    logger.info(
                        f"Fetched {len(results)} results "
                        f"(offset={offset}, total={total})"
                    )

                    offset += limit
                    if offset >= total:
                        break

                    await self._delay()

            except Exception as e:
                logger.error(f"Search request failed: {e}")
                break

        logger.info(f"Total search results: {len(all_results)}")
        return all_results[:max_results]

    # ── Детали одного объявления ───────────────────────────

    async def get_item_details(self, item_id: str) -> Optional[Dict[str, Any]]:
        """Получает полные детали объявления через API."""
        session = await self._get_session()
        url = f"{ML_ITEM_URL}/{item_id}"

        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"Item {item_id}: API returned {resp.status}")
                    return None
                return await resp.json()
        except Exception as e:
            logger.error(f"Item {item_id} fetch failed: {e}")
            return None

    async def get_item_description(self, item_id: str) -> Optional[str]:
        """Получает описание объявления (отдельный endpoint)."""
        session = await self._get_session()
        url = f"{ML_ITEM_URL}/{item_id}/description"

        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data.get("plain_text") or data.get("text", "")
        except Exception as e:
            logger.debug(f"Description fetch failed for {item_id}: {e}")
            return None

    # ── Конвертация API → Listing ─────────────────────────

    def _parse_search_result(self, item: Dict[str, Any]) -> Optional[Listing]:
        """Конвертирует результат поиска API в Listing."""
        try:
            item_id = item.get("id", "")
            price = item.get("price")
            currency = item.get("currency_id", "")

            # Формируем строку цены
            price_str = None
            if price is not None:
                price_str = f"{currency} {price:,.0f}".replace(",", ".")

            # Извлекаем локацию
            address = item.get("address", {})
            location_parts = []
            if address.get("city_name"):
                location_parts.append(address["city_name"])
            if address.get("state_name"):
                location_parts.append(address["state_name"])
            location = ", ".join(location_parts) if location_parts else None

            # Извлекаем площадь из атрибутов
            area, area_m2 = self._extract_area_from_attributes(
                item.get("attributes", [])
            )

            # Извлекаем изображения
            thumbnail = item.get("thumbnail", "")
            image_url = thumbnail.replace("-I.jpg", "-O.jpg") if thumbnail else None

            listing = Listing(
                url=item.get("permalink", ""),
                ml_item_id=item_id,
                title=item.get("title"),
                price=price_str,
                price_usd=float(price) if price and currency == "USD" else None,
                currency=currency,
                location=location,
                department=address.get("state_name"),
                area=area,
                area_m2=area_m2,
                image_url=image_url,
                date_scraped=datetime.now(),
            )

            listing.compute_derived_fields()
            return listing

        except Exception as e:
            logger.error(f"Failed to parse search result: {e}")
            return None

    async def _enrich_with_details(self, listing: Listing) -> Listing:
        """Обогащает Listing данными из API /items/{id} и /description."""
        if not listing.ml_item_id:
            return listing

        # Параллельно получаем детали и описание
        details, description = await asyncio.gather(
            self.get_item_details(listing.ml_item_id),
            self.get_item_description(listing.ml_item_id),
            return_exceptions=True,
        )

        if isinstance(details, dict):
            self._apply_details(listing, details)

        if isinstance(description, str) and description.strip():
            listing.description = description.strip()
            self._extract_from_description(listing, description)

        listing.compute_derived_fields()
        return listing

    def _apply_details(self, listing: Listing, data: Dict[str, Any]):
        """Применяет данные из /items/{id} к листингу."""

        # Координаты
        geo = data.get("geolocation") or {}
        if geo.get("latitude") and geo.get("longitude"):
            listing.latitude = geo["latitude"]
            listing.longitude = geo["longitude"]

        # Все изображения (высокое качество)
        pictures = data.get("pictures", [])
        listing.image_urls = [
            pic.get("secure_url", pic.get("url", ""))
            for pic in pictures
            if pic.get("secure_url") or pic.get("url")
        ]
        if listing.image_urls and not listing.image_url:
            listing.image_url = listing.image_urls[0]

        # Продавец
        seller = data.get("seller", {})
        if seller:
            nickname = seller.get("nickname")
            if nickname:
                listing.seller_name = nickname
            eshop = seller.get("eshop", {})
            if eshop and eshop.get("nick_name"):
                listing.seller_name = eshop["nick_name"]
                listing.seller_type = "Inmobiliaria"
            elif seller.get("seller_reputation", {}).get("power_seller_status"):
                listing.seller_type = "Vendedor destacado"
            else:
                listing.seller_type = "Particular"

        # Дата публикации
        date_str = data.get("date_created")
        if date_str:
            try:
                listing.date_published = datetime.fromisoformat(
                    date_str.replace("Z", "+00:00")
                )
                hours_ago = (
                    datetime.now() - listing.date_published.replace(tzinfo=None)
                ).total_seconds() / 3600
                listing.is_recent = hours_ago <= 24
            except (ValueError, TypeError):
                pass

        # Атрибуты из таблицы характеристик
        attrs = data.get("attributes", [])
        self._extract_structured_attributes(listing, attrs)

        # Локация (более детальная из item)
        loc = data.get("seller_address", {})
        parts = []
        for key in ("city", "state"):
            sub = loc.get(key, {})
            name = sub.get("name") if isinstance(sub, dict) else None
            if name:
                parts.append(name)
        if parts:
            listing.location = ", ".join(parts)
            if len(parts) >= 2:
                listing.department = parts[-1]

    def _extract_structured_attributes(
        self, listing: Listing, attrs: List[Dict[str, Any]]
    ):
        """Извлекает структурированные атрибуты из API."""
        attr_map = {a.get("id"): a for a in attrs}

        # Площадь
        for key in ("TOTAL_AREA", "COVERED_AREA", "LOT_SIZE"):
            attr = attr_map.get(key)
            if attr and attr.get("value_name"):
                listing.area = attr["value_name"]
                area_val = self._parse_area_value(attr["value_name"])
                if area_val:
                    listing.area_m2 = area_val
                break

        # Утилиты/коммуникации
        utilities = []
        utility_keys = {
            "HAS_WATER": "Agua",
            "HAS_ELECTRICITY": "Electricidad",
            "HAS_GAS": "Gas",
            "HAS_SEWAGE": "Saneamiento",
            "HAS_TELEPHONE": "Teléfono",
            "HAS_INTERNET": "Internet",
        }
        for api_key, label in utility_keys.items():
            attr = attr_map.get(api_key)
            if attr and attr.get("value_name", "").lower() in ("sí", "si", "yes"):
                utilities.append(label)

        if utilities:
            listing.utilities = ", ".join(utilities)

        # Зонирование
        for key in ("PROPERTY_ZONIFICATION", "PROPERTY_TYPE"):
            attr = attr_map.get(key)
            if attr and attr.get("value_name"):
                listing.zoning = attr["value_name"]
                break

        # Ориентация
        attr = attr_map.get("FACING")
        if attr and attr.get("value_name"):
            listing.orientation = attr["value_name"]

        # Фронт
        attr = attr_map.get("FRONT_LENGTH")
        if attr and attr.get("value_name"):
            val = self._parse_number(attr["value_name"])
            if val:
                listing.front_meters = val

        # Все остальные атрибуты — в словарь
        skip = set(utility_keys) | {
            "TOTAL_AREA", "COVERED_AREA", "LOT_SIZE",
            "PROPERTY_ZONIFICATION", "PROPERTY_TYPE", "FACING",
            "FRONT_LENGTH", "ITEM_CONDITION",
        }
        for attr in attrs:
            aid = attr.get("id", "")
            name = attr.get("name", "")
            value = attr.get("value_name")
            if aid not in skip and name and value:
                listing.attributes[name] = value

    def _extract_from_description(self, listing: Listing, text: str):
        """Извлекает доп. данные из текстового описания."""
        lower = text.lower()

        # Утилиты (если не получены из атрибутов)
        if not listing.utilities:
            found = []
            checks = [
                (r"agua\b", "Agua"),
                (r"luz|electricidad", "Electricidad"),
                (r"\bgas\b", "Gas"),
                (r"saneamiento|cloaca|alcantarillado", "Saneamiento"),
                (r"internet|fibra", "Internet"),
            ]
            for pattern, label in checks:
                match = re.search(pattern, lower)
                if match:
                    # Проверяем, что рядом нет отрицания
                    start = max(0, match.start() - 15)
                    context = lower[start : match.start()]
                    if not re.search(r"\bsin\b|\bno\b", context):
                        found.append(label)
            if found:
                listing.utilities = ", ".join(found)

        # Зонирование
        if not listing.zoning:
            for pattern, label in [
                (r"\brural\b", "Rural"),
                (r"\burbano\b", "Urbano"),
                (r"\bsuburbano\b", "Suburbano"),
                (r"\bresidencial\b", "Residencial"),
                (r"\bindustrial\b", "Industrial"),
            ]:
                if re.search(pattern, lower):
                    listing.zoning = label
                    break

        # Площадь (fallback)
        if not listing.area_m2:
            m = re.search(
                r"(\d+[\.,]?\d*)\s*(?:ha|hectáreas|hectareas)", lower
            )
            if m:
                val = float(m.group(1).replace(",", "."))
                listing.area = f"{val} ha"
                listing.area_m2 = val * 10000
            else:
                m = re.search(r"(\d+[\.,]?\d*)\s*m[²2]", lower)
                if m:
                    val = float(m.group(1).replace(",", "."))
                    listing.area = f"{int(val)} m²"
                    listing.area_m2 = val

    # ── Запуск ────────────────────────────────────────────

    async def scrape(
        self,
        max_results: int = MAX_LISTINGS,
        enrich: bool = True,
        **search_kwargs,
    ) -> List[Listing]:
        """
        Полный цикл: поиск → парсинг → обогащение деталями.

        Args:
            max_results: Максимум объявлений
            enrich: Получать ли доп. детали через API
            **search_kwargs: Параметры для search_listings

        Returns:
            Список объявлений Listing
        """
        logger.info(f"Starting scrape (max_results={max_results}, enrich={enrich})")

        # 1. Поиск
        raw_results = await self.search_listings(
            max_results=max_results, **search_kwargs
        )

        # 2. Парсинг в Listing
        listings = []
        for item in raw_results:
            listing = self._parse_search_result(item)
            if listing:
                listings.append(listing)

        logger.info(f"Parsed {len(listings)} listings from search results")

        # 3. Обогащение деталями
        if enrich and listings:
            logger.info("Enriching listings with details...")
            enriched = []
            for i, listing in enumerate(listings):
                try:
                    enriched_listing = await self._enrich_with_details(listing)
                    enriched.append(enriched_listing)
                    if (i + 1) % 10 == 0:
                        logger.info(f"Enriched {i + 1}/{len(listings)}")
                    await self._delay(short=True)
                except Exception as e:
                    logger.error(f"Enrich failed for {listing.ml_item_id}: {e}")
                    enriched.append(listing)
            listings = enriched

        logger.info(f"Scrape complete: {len(listings)} listings")
        return listings

    # ── Утилиты ───────────────────────────────────────────

    @staticmethod
    def _extract_area_from_attributes(
        attrs: List[Dict],
    ) -> tuple[Optional[str], Optional[float]]:
        """Извлекает площадь из атрибутов поиска."""
        for attr in attrs:
            aid = attr.get("id", "")
            if aid in ("TOTAL_AREA", "COVERED_AREA", "LOT_SIZE"):
                val_name = attr.get("value_name", "")
                if val_name:
                    num = MercadoLibreScraper._parse_area_value(val_name)
                    return val_name, num
        return None, None

    @staticmethod
    def _parse_area_value(text: str) -> Optional[float]:
        """Парсит значение площади в м²."""
        if not text:
            return None
        lower = text.lower().strip()

        m = re.search(r"([\d.,]+)\s*(?:ha|hectáreas)", lower)
        if m:
            return float(m.group(1).replace(",", ".")) * 10000

        m = re.search(r"([\d.,]+)\s*m", lower)
        if m:
            return float(m.group(1).replace(",", "."))

        m = re.search(r"([\d.,]+)", lower)
        if m:
            return float(m.group(1).replace(",", "."))

        return None

    @staticmethod
    def _parse_number(text: str) -> Optional[float]:
        m = re.search(r"([\d.,]+)", text)
        if m:
            return float(m.group(1).replace(",", "."))
        return None

    async def _delay(self, short: bool = False):
        if short:
            await asyncio.sleep(random.uniform(0.3, 0.8))
        else:
            await asyncio.sleep(
                random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
            )
