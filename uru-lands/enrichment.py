"""
Auction enrichment — combines IMPO auctions with MercadoLibre market data.

For each auction, looks up comparable listings on MercadoLibre in the same
department/city and computes average price per m². This lets us estimate
the potential discount of the auction vs. market value — the core value
proposition of the service.
"""

import logging
from dataclasses import dataclass
from statistics import median, mean
from typing import List, Optional

from impo_parser import Auction
from models import Listing
from scraper import MercadoLibreScraper

logger = logging.getLogger(__name__)


@dataclass
class EnrichedAuction:
    """Auction with market price context."""
    auction: Auction

    # Market reference
    comparable_count: int = 0
    market_price_per_m2_median: Optional[float] = None
    market_price_per_m2_mean: Optional[float] = None
    market_price_range: Optional[tuple] = None  # (min, max)

    # Derived insights
    estimated_market_value: Optional[float] = None  # auction.area_m2 * median price/m²
    comparable_sample: List[dict] = None  # Small sample of similar listings

    def summary(self) -> str:
        """Short human-readable summary."""
        a = self.auction
        parts = []

        if a.property_type:
            parts.append(a.property_type.title())
        if a.area_m2:
            if a.area_m2 >= 10000:
                parts.append(f"{a.area_m2/10000:.1f} ha")
            else:
                parts.append(f"{a.area_m2:.0f} m²")
        if a.city or a.department:
            parts.append(a.city or a.department)

        base = " · ".join(parts)

        if self.estimated_market_value:
            base += f" · est. market ~${self.estimated_market_value:,.0f}"

        return base


class AuctionEnricher:
    """Enriches IMPO auctions with MercadoLibre market data."""

    def __init__(self, ml_scraper: Optional[MercadoLibreScraper] = None):
        self._ml_scraper = ml_scraper
        self._own_scraper = ml_scraper is None
        # Cache: department → list of comparable listings (to avoid refetch)
        self._cache: dict[str, List[Listing]] = {}

    async def _get_scraper(self) -> MercadoLibreScraper:
        if self._ml_scraper is None:
            self._ml_scraper = MercadoLibreScraper()
        return self._ml_scraper

    async def close(self):
        if self._own_scraper and self._ml_scraper:
            await self._ml_scraper.close()

    async def _get_comparables(
        self, department: str, limit: int = 30
    ) -> List[Listing]:
        """
        Fetches land listings from MercadoLibre for a given department.
        Cached per-department to avoid re-fetching.
        """
        if department in self._cache:
            return self._cache[department]

        try:
            scraper = await self._get_scraper()
            # Search all terrenos — we filter by department afterwards
            # since ML API doesn't support department filter directly
            listings = await scraper.scrape(max_results=limit, enrich=False)

            # Filter to matching department (case-insensitive substring match)
            dept_lower = department.lower()
            matching = [
                lst for lst in listings
                if lst.department and dept_lower in lst.department.lower()
            ]

            self._cache[department] = matching
            logger.info(
                f"Fetched {len(matching)} comparable listings for {department}"
            )
            return matching

        except Exception as e:
            logger.error(f"Failed to fetch comparables for {department}: {e}")
            self._cache[department] = []
            return []

    async def enrich(self, auction: Auction) -> EnrichedAuction:
        """Enriches a single auction with market context."""
        enriched = EnrichedAuction(auction=auction, comparable_sample=[])

        # Need department and area to compute anything meaningful
        if not auction.department:
            return enriched
        if not auction.area_m2 or auction.area_m2 <= 0:
            return enriched

        comparables = await self._get_comparables(auction.department)
        if not comparables:
            return enriched

        # Keep only comparables with valid price and area
        valid = [
            lst for lst in comparables
            if lst.price_per_m2 and lst.price_per_m2 > 0
        ]

        if not valid:
            return enriched

        prices_per_m2 = [lst.price_per_m2 for lst in valid]

        enriched.comparable_count = len(valid)
        enriched.market_price_per_m2_median = round(median(prices_per_m2), 2)
        enriched.market_price_per_m2_mean = round(mean(prices_per_m2), 2)
        enriched.market_price_range = (
            round(min(prices_per_m2), 2),
            round(max(prices_per_m2), 2),
        )
        enriched.estimated_market_value = round(
            auction.area_m2 * enriched.market_price_per_m2_median, 0
        )

        # Small sample for context (top 3 closest by area)
        sorted_by_area_diff = sorted(
            valid,
            key=lambda lst: abs((lst.area_m2 or 0) - auction.area_m2),
        )[:3]
        enriched.comparable_sample = [
            {
                "title": lst.title,
                "price": lst.price,
                "area_m2": lst.area_m2,
                "location": lst.location,
                "url": str(lst.url),
            }
            for lst in sorted_by_area_diff
        ]

        return enriched

    async def enrich_batch(self, auctions: List[Auction]) -> List[EnrichedAuction]:
        """Enriches a list of auctions."""
        results = []
        for auction in auctions:
            try:
                enriched = await self.enrich(auction)
                results.append(enriched)
            except Exception as e:
                logger.error(f"Enrichment failed for {auction.edicto_number}: {e}")
                results.append(EnrichedAuction(auction=auction, comparable_sample=[]))

        return results
