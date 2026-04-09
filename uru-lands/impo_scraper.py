"""
IMPO (Diario Oficial) auction scraper.

Fetches the public page of judicial auctions and parses edictos
using impo_parser. Used as a complement to MercadoLibre scraper —
auctions contain unique low-price land deals not available on
commercial marketplaces.

The site is an official government resource (impo.com.uy) with
simple server-side HTML, no anti-bot protection, no rate limiting.
Fetching once a day is more than enough.
"""

import logging
from typing import List, Optional

import aiohttp

from impo_parser import Auction, parse_impo_text, filter_land_only, filter_real_estate

logger = logging.getLogger(__name__)

IMPO_REMATES_URL = "http://www.impo.com.uy/remates"

# IMPO uses ISO-8859-1 encoding, not UTF-8
IMPO_ENCODING = "iso-8859-1"


class IMPOScraper:
    """Scraper for Uruguay's Diario Oficial auction listings."""

    def __init__(self, session: Optional[aiohttp.ClientSession] = None):
        self._session = session
        self._own_session = session is None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "es-UY,es;q=0.9,en;q=0.8",
                },
            )
            self._own_session = True
        return self._session

    async def close(self):
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()

    async def fetch_page(self, url: str = IMPO_REMATES_URL) -> Optional[str]:
        """
        Downloads the IMPO remates page and returns decoded text.

        IMPO uses ISO-8859-1 encoding. We decode manually to avoid
        mojibake on Spanish characters (á, é, í, ó, ú, ñ).
        """
        session = await self._get_session()
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.error(f"IMPO returned status {resp.status}")
                    return None

                raw_bytes = await resp.read()
                text = raw_bytes.decode(IMPO_ENCODING, errors="replace")
                logger.info(f"Fetched {len(text)} bytes from IMPO")
                return text

        except aiohttp.ClientError as e:
            logger.error(f"IMPO fetch failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected IMPO error: {e}", exc_info=True)
            return None

    async def scrape(
        self,
        land_only: bool = False,
        real_estate_only: bool = True,
    ) -> List[Auction]:
        """
        Full scrape cycle: fetch → parse → filter.

        Args:
            land_only: Keep only land plots (terrenos, campos, chacras)
            real_estate_only: Keep all real estate (default)

        Returns:
            List of parsed auctions
        """
        text = await self.fetch_page()
        if not text:
            logger.warning("IMPO page fetch returned no content")
            return []

        auctions = parse_impo_text(text)
        logger.info(f"Parsed {len(auctions)} auction entries")

        if land_only:
            auctions = filter_land_only(auctions)
            logger.info(f"Filtered to {len(auctions)} land auctions")
        elif real_estate_only:
            auctions = filter_real_estate(auctions)
            logger.info(f"Filtered to {len(auctions)} real estate auctions")

        return auctions
