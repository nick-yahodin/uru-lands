"""Smoke test for auction formatter — ensures output has no crashes."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from impo_parser import Auction
from enrichment import EnrichedAuction
from auction_formatter import format_auction_post


def test_english_format():
    auction = Auction(
        auction_date="2026-04-10",
        auction_time="13:30",
        location="Uruguay 826",
        department="Canelones",
        city="Pando",
        property_type="terreno",
        area_m2=6809.0,
        area_raw="6.809 m²",
        is_real_estate=True,
        is_land=True,
        has_base=False,
        currency="USD",
        rematador_name="HERNANDEZ Lorenzo",
        rematador_matricula="5605",
        edicto_number="5585/026",
        edicto_url="http://www.impo.com.uy/bases/avisos-remate/5585-026",
        zone="suburbana",
    )
    enriched = EnrichedAuction(
        auction=auction,
        comparable_count=15,
        market_price_per_m2_median=45.0,
        market_price_per_m2_mean=48.5,
        estimated_market_value=306405.0,
        comparable_sample=[],
    )

    post = format_auction_post(enriched, language="en")
    assert "Terreno auction" in post
    assert "Pando" in post
    assert "6 809 m²" in post or "6,809 m²" in post or "6.809" in post
    assert "No minimum" in post
    assert "USD" in post
    assert "HERNANDEZ Lorenzo" in post
    assert "market value" in post.lower()
    assert "#UruguayAuction" in post
    print("✓ English format OK")
    return True


def test_spanish_format():
    auction = Auction(
        auction_date="2026-04-08",
        auction_time="15:30",
        city="José Ignacio",
        department="Maldonado",
        property_type="campo",
        area_m2=90000.0,
        area_raw="9 hás",
        is_real_estate=True,
        is_land=True,
        is_rural=True,
        has_base=False,
        currency="USD",
        rematador_name="TEXEIRA Dionisio",
        rematador_matricula="6079",
        edicto_number="6073/026",
    )
    enriched = EnrichedAuction(auction=auction, comparable_sample=[])
    post = format_auction_post(enriched, language="es")
    assert "Remate" in post
    assert "José Ignacio" in post
    assert "9 ha" in post
    assert "Sin base" in post
    print("✓ Spanish format OK")
    return True


def test_no_enrichment():
    """Auction without market data should still format correctly."""
    auction = Auction(
        auction_date="2026-04-08",
        property_type="terreno",
        area_m2=500.0,
        city="Montevideo",
        department="Montevideo",
        has_base=False,
        currency="UYU",
        is_real_estate=True,
        is_land=True,
    )
    enriched = EnrichedAuction(auction=auction, comparable_sample=[])
    post = format_auction_post(enriched, language="en")
    assert "Terreno" in post
    assert "market" not in post.lower() or "Market context" not in post
    print("✓ No-enrichment format OK")
    return True


if __name__ == "__main__":
    tests = [test_english_format, test_spanish_format, test_no_enrichment]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"✗ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {t.__name__}: unexpected {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(0 if failed == 0 else 1)
