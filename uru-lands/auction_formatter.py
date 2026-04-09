"""
Telegram message formatter for IMPO auctions.

Creates rich posts with:
  - Property type, location, area
  - Market value estimate (if enriched)
  - Auction date/time/location
  - Rematador contact
  - Link to full edicto
  - Tags for discovery
"""

import re
from typing import List

from enrichment import EnrichedAuction
from impo_parser import Auction


def _escape(text: str) -> str:
    """Escape MarkdownV2 special characters."""
    if not text:
        return ""
    # Backslash must be escaped first to avoid double-escaping
    text = text.replace("\\", "\\\\")
    for c in r"_*[]()~`>#+-=|{}.!":
        text = text.replace(c, f"\\{c}")
    return text


def _fmt_area(area_m2: float) -> str:
    """Pretty-print area in m² or hectares."""
    if area_m2 >= 10000:
        ha = area_m2 / 10000
        if ha == int(ha):
            return f"{int(ha)} ha"
        return f"{ha:.1f} ha"
    return f"{area_m2:,.0f} m²".replace(",", " ")


def _fmt_date(date_iso: str) -> str:
    """Convert YYYY-MM-DD to DD/MM/YYYY for Spanish audience."""
    try:
        y, m, d = date_iso.split("-")
        return f"{d}/{m}/{y}"
    except (ValueError, AttributeError):
        return date_iso or "TBD"


def _generate_tags(auction: Auction) -> List[str]:
    """Generate hashtags based on auction properties."""
    tags = ["#UruguayAuction", "#Remate"]

    if auction.department:
        dept_clean = re.sub(r"[^A-Za-záéíóúñÁÉÍÓÚÑ]", "", auction.department)
        if dept_clean:
            tags.append(f"#{dept_clean}")

    if auction.property_type:
        ptype_clean = auction.property_type.replace(" ", "").title()
        tags.append(f"#{ptype_clean}")

    if auction.is_rural:
        tags.append("#Rural")
    else:
        tags.append("#Urbano")

    if auction.is_land:
        if auction.area_m2 and auction.area_m2 >= 100000:  # 10+ ha
            if "#Campo" not in tags:
                tags.append("#Campo")
        elif auction.area_m2 and auction.area_m2 >= 10000:  # 1-10 ha
            if "#Chacra" not in tags:
                tags.append("#Chacra")
        else:
            if "#Terreno" not in tags:
                tags.append("#Terreno")

    if not auction.has_base:
        tags.append("#SinBase")

    if auction.currency == "USD":
        tags.append("#USD")

    return tags[:8]  # Max 8 tags


def format_auction_post(enriched: EnrichedAuction, language: str = "en") -> str:
    """
    Format an enriched auction as a Telegram post in MarkdownV2.

    Args:
        enriched: Enriched auction with market data
        language: 'en' or 'es' for post content

    Returns:
        MarkdownV2-formatted message (max ~1000 chars for Telegram)
    """
    a = enriched.auction
    if language == "es":
        return _format_spanish(enriched)
    return _format_english(enriched)


def _format_english(enriched: EnrichedAuction) -> str:
    """English version — for international investors."""
    a = enriched.auction
    lines = []

    # Header
    icon = "🌾" if a.is_rural else "🏞️"
    ptype = (a.property_type or "property").title()
    lines.append(f"{icon} *{_escape(ptype)} auction*")
    lines.append("")

    # Location
    loc_parts = []
    if a.city:
        loc_parts.append(a.city)
    if a.department and a.department not in loc_parts:
        loc_parts.append(a.department)
    if loc_parts:
        lines.append(f"📍 *Location:* {_escape(', '.join(loc_parts))}")

    # Area
    if a.area_m2:
        lines.append(f"📐 *Area:* {_escape(_fmt_area(a.area_m2))}")

    # Padrón
    if a.padron:
        lines.append(f"🔢 *Padrón:* `{_escape(a.padron)}`")

    # Zone
    if a.zone:
        zone_en = {"rural": "Rural", "urbana": "Urban", "suburbana": "Suburban"}.get(
            a.zone, a.zone.title()
        )
        lines.append(f"🏗 *Zone:* {_escape(zone_en)}")

    # Auction terms
    lines.append("")
    base_str = "No minimum" if not a.has_base else "With reserve"
    currency = a.currency or "TBD"
    lines.append(f"💰 *Terms:* {_escape(base_str)}, {_escape(currency)}")

    # Date/time/place
    if a.auction_date:
        lines.append(
            f"📅 *Date:* {_escape(_fmt_date(a.auction_date))} "
            f"at {_escape(a.auction_time or 'TBD')}"
        )
    if a.location:
        lines.append(f"🏛 *Venue:* {_escape(a.location)}")

    # Rematador
    if a.rematador_name:
        mat = f" \\(mat\\. {a.rematador_matricula}\\)" if a.rematador_matricula else ""
        lines.append(f"👤 *Auctioneer:* {_escape(a.rematador_name)}{mat}")

    # Market context (the value-add!)
    if enriched.estimated_market_value and enriched.comparable_count:
        lines.append("")
        lines.append("📊 *Market context*")
        lines.append(
            f"   Comparable listings: {enriched.comparable_count} "
            f"in {_escape(a.department or 'region')}"
        )
        lines.append(
            f"   Median price/m²: ${enriched.market_price_per_m2_median:,.0f}".replace(",", "\\,")
        )
        lines.append(
            f"   Est\\. market value: ~${enriched.estimated_market_value:,.0f}".replace(",", "\\,")
        )

    # Link to full edicto
    if a.edicto_url:
        lines.append("")
        lines.append(f"🔗 [Full edicto]({a.edicto_url})")

    # Disclaimer
    lines.append("")
    lines.append(
        "_Data from Diario Oficial\\. Not investment advice\\. "
        "Consult escribano before bidding\\._"
    )

    # Tags — escape # for MarkdownV2 (renders as clickable hashtags)
    tags = _generate_tags(a)
    if tags:
        lines.append("")
        lines.append(" ".join(_escape(t) for t in tags))

    return "\n".join(lines)


def _format_spanish(enriched: EnrichedAuction) -> str:
    """Spanish version — for local audience."""
    a = enriched.auction
    lines = []

    icon = "🌾" if a.is_rural else "🏞️"
    ptype = (a.property_type or "inmueble").title()
    lines.append(f"{icon} *Remate de {_escape(ptype)}*")
    lines.append("")

    loc_parts = []
    if a.city:
        loc_parts.append(a.city)
    if a.department and a.department not in loc_parts:
        loc_parts.append(a.department)
    if loc_parts:
        lines.append(f"📍 *Ubicación:* {_escape(', '.join(loc_parts))}")

    if a.area_m2:
        lines.append(f"📐 *Superficie:* {_escape(_fmt_area(a.area_m2))}")

    if a.padron:
        lines.append(f"🔢 *Padrón:* `{_escape(a.padron)}`")

    if a.zone:
        lines.append(f"🏗 *Zona:* {_escape(a.zone.title())}")

    lines.append("")
    base_str = "Sin base" if not a.has_base else "Con base"
    currency = a.currency or "a confirmar"
    lines.append(f"💰 *Condiciones:* {_escape(base_str)}, {_escape(currency)}")

    if a.auction_date:
        lines.append(
            f"📅 *Fecha:* {_escape(_fmt_date(a.auction_date))} "
            f"a las {_escape(a.auction_time or 'TBD')}"
        )
    if a.location:
        lines.append(f"🏛 *Lugar:* {_escape(a.location)}")

    if a.rematador_name:
        mat = f" \\(mat\\. {a.rematador_matricula}\\)" if a.rematador_matricula else ""
        lines.append(f"👤 *Rematador:* {_escape(a.rematador_name)}{mat}")

    if enriched.estimated_market_value and enriched.comparable_count:
        lines.append("")
        lines.append("📊 *Referencia de mercado*")
        lines.append(f"   Comparables: {enriched.comparable_count}")
        lines.append(
            f"   Precio mediano/m²: ${enriched.market_price_per_m2_median:,.0f}".replace(",", "\\,")
        )
        lines.append(
            f"   Valor estimado: ~${enriched.estimated_market_value:,.0f}".replace(",", "\\,")
        )

    if a.edicto_url:
        lines.append("")
        lines.append(f"🔗 [Ver edicto completo]({a.edicto_url})")

    lines.append("")
    lines.append(
        "_Datos del Diario Oficial\\. No es asesoramiento de inversión\\. "
        "Consulte con escribano antes de ofertar\\._"
    )

    tags = _generate_tags(a)
    if tags:
        lines.append("")
        lines.append(" ".join(_escape(t) for t in tags))

    return "\n".join(lines)
