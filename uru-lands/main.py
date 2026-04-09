#!/usr/bin/env python3
"""
uru-lands — Uruguay real estate and auction data aggregator.

Usage:
    python main.py                      # Full cycle: all sources → dedupe → Telegram
    python main.py --source ml          # MercadoLibre only
    python main.py --source impo        # IMPO auctions only
    python main.py --no-send            # Scrape but don't send to Telegram
    python main.py --land-only          # Filter to land plots only
    python main.py --dry-run            # Parse and print, no side effects
    python main.py --max 20             # Limit results
    python main.py --lang en            # Post language (en/es)
    python main.py --debug              # Verbose logging

Examples:
    python main.py --source impo --land-only --lang en
    python main.py --source ml --max 30 --no-send --export results.json
"""

import asyncio
import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from config import (
    setup_logging, MAX_LISTINGS, TELEGRAM_BOT_TOKEN, DATA_DIR,
)
from scraper import MercadoLibreScraper
from impo_scraper import IMPOScraper
from enrichment import AuctionEnricher
from duplicate_checker import DuplicateChecker
from auction_formatter import format_auction_post
from telegram_bot import TelegramSender

logger = logging.getLogger("main")


async def run_mercadolibre(args) -> list:
    """Scrape MercadoLibre marketplace listings."""
    logger.info("▶ MercadoLibre scraper")
    scraper = MercadoLibreScraper()
    try:
        listings = await scraper.scrape(
            max_results=args.max,
            enrich=not args.no_enrich,
        )
        logger.info(f"  Found {len(listings)} listings")
        return listings
    finally:
        await scraper.close()


async def run_impo(args) -> list:
    """Scrape IMPO auction listings and enrich with market data."""
    logger.info("▶ IMPO auction scraper")
    scraper = IMPOScraper()
    try:
        auctions = await scraper.scrape(
            land_only=args.land_only,
            real_estate_only=not args.land_only,
        )
        logger.info(f"  Found {len(auctions)} auctions")
    finally:
        await scraper.close()

    if not auctions:
        return []

    # Enrich with market data
    if not args.no_enrich:
        logger.info("▶ Enriching auctions with MercadoLibre market data")
        enricher = AuctionEnricher()
        try:
            enriched = await enricher.enrich_batch(auctions)
            with_data = sum(1 for e in enriched if e.estimated_market_value)
            logger.info(f"  Enriched {with_data}/{len(enriched)} with market data")
            return enriched
        finally:
            await enricher.close()

    from enrichment import EnrichedAuction
    return [EnrichedAuction(auction=a, comparable_sample=[]) for a in auctions]


async def send_auctions_to_telegram(enriched_list, language: str) -> int:
    """Send formatted auction posts to Telegram."""
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set — skipping send")
        return 0

    import aiohttp
    from config import TELEGRAM_CHAT_ID

    api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    sent = 0

    async with aiohttp.ClientSession() as session:
        for enriched in enriched_list:
            try:
                text = format_auction_post(enriched, language=language)
                payload = {
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": text,
                    "parse_mode": "MarkdownV2",
                    "disable_web_page_preview": False,
                }
                async with session.post(f"{api}/sendMessage", json=payload) as resp:
                    if resp.status == 200:
                        sent += 1
                        logger.info(f"  Sent: {enriched.auction.edicto_number}")
                    else:
                        body = await resp.text()
                        logger.error(f"  Send failed ({resp.status}): {body[:200]}")

                await asyncio.sleep(1.5)  # Telegram rate limit
            except Exception as e:
                logger.error(f"  Send exception: {e}")

    return sent


def export_results(data, path: str):
    """Export results to JSON."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"Exported → {path}")


async def main():
    parser = argparse.ArgumentParser(
        description="uru-lands — Uruguay real estate and auction scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--source",
        choices=["ml", "impo", "all"],
        default="all",
        help="Data source(s) to scrape",
    )
    parser.add_argument("--max", type=int, default=MAX_LISTINGS, help="Max listings")
    parser.add_argument("--land-only", action="store_true", help="Land plots only")
    parser.add_argument("--no-send", action="store_true", help="Skip Telegram")
    parser.add_argument("--no-enrich", action="store_true", help="Skip enrichment")
    parser.add_argument("--dry-run", action="store_true", help="No side effects")
    parser.add_argument("--export", type=str, help="Export to JSON file")
    parser.add_argument("--lang", choices=["en", "es"], default="en", help="Post language")
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    setup_logging("DEBUG" if args.debug else "INFO")
    logger.info("═" * 50)
    logger.info(f"uru-lands — {datetime.now():%Y-%m-%d %H:%M:%S}")
    logger.info(f"Source: {args.source} | Lang: {args.lang} | Land only: {args.land_only}")
    logger.info("═" * 50)

    all_ml_listings = []
    all_auctions = []

    try:
        if args.source in ("ml", "all"):
            all_ml_listings = await run_mercadolibre(args)

        if args.source in ("impo", "all"):
            all_auctions = await run_impo(args)

    except Exception as e:
        logger.error(f"Scraping failed: {e}", exc_info=args.debug)
        return 1

    # Deduplication
    checker = DuplicateChecker()

    new_ml = []
    if all_ml_listings:
        new_ml = checker.filter_new(all_ml_listings)
        logger.info(f"ML: {len(new_ml)} new (of {len(all_ml_listings)})")

    new_auctions = []
    if all_auctions:
        # Use edicto_number as dedup key
        seen = set()
        try:
            with open(f"{DATA_DIR}/seen_edictos.txt", "r") as f:
                seen = set(line.strip() for line in f if line.strip())
        except FileNotFoundError:
            pass

        for e in all_auctions:
            if e.auction.edicto_number and e.auction.edicto_number not in seen:
                new_auctions.append(e)
                seen.add(e.auction.edicto_number)

        Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
        with open(f"{DATA_DIR}/seen_edictos.txt", "w") as f:
            for ed in sorted(seen):
                f.write(f"{ed}\n")

        logger.info(f"IMPO: {len(new_auctions)} new (of {len(all_auctions)})")

    # Export
    if args.export or args.dry_run:
        path = args.export or f"{DATA_DIR}/dry_run_{datetime.now():%Y%m%d_%H%M%S}.json"
        export_data = {
            "timestamp": datetime.now().isoformat(),
            "mercadolibre": [lst.model_dump(mode="json") for lst in new_ml],
            "auctions": [
                {
                    "auction": vars(e.auction),
                    "market_price_per_m2_median": e.market_price_per_m2_median,
                    "estimated_market_value": e.estimated_market_value,
                    "comparable_count": e.comparable_count,
                }
                for e in new_auctions
            ],
        }
        export_results(export_data, path)

    if args.dry_run:
        logger.info("Dry run — no Telegram posts sent")
        _print_summary(new_ml, new_auctions)
        return 0

    # Send to Telegram
    if not args.no_send:
        if new_ml:
            try:
                sender = TelegramSender()
                sent = await sender.send_batch(new_ml)
                logger.info(f"ML → Telegram: {sent}/{len(new_ml)}")
            except Exception as e:
                logger.error(f"ML send failed: {e}")

        if new_auctions:
            sent = await send_auctions_to_telegram(new_auctions, args.lang)
            logger.info(f"IMPO → Telegram: {sent}/{len(new_auctions)}")

    _print_summary(new_ml, new_auctions)
    return 0


def _print_summary(ml_listings, auctions):
    logger.info("─" * 50)
    logger.info("SUMMARY")
    logger.info(f"  MercadoLibre listings: {len(ml_listings)}")
    logger.info(f"  IMPO auctions: {len(auctions)}")

    if auctions:
        land = sum(1 for e in auctions if e.auction.is_land)
        rural = sum(1 for e in auctions if e.auction.is_rural)
        no_base = sum(1 for e in auctions if not e.auction.has_base)
        with_market = sum(1 for e in auctions if e.estimated_market_value)
        logger.info(f"    land plots: {land}")
        logger.info(f"    rural: {rural}")
        logger.info(f"    no-base auctions: {no_base}")
        logger.info(f"    with market context: {with_market}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
