# uru-lands

Data aggregator for Uruguay's real estate and land auction market.
Scrapes MercadoLibre (public API) and IMPO (Diario Oficial judicial
auctions), enriches auctions with market price context, publishes to
Telegram.

## Features

- **MercadoLibre scraper** — fetches land listings via the public API
  (`api.mercadolibre.com/sites/MLU/search`). No HTML parsing, no
  Playwright, no browser blocks. Returns structured data including GPS
  coordinates, all photos, seller info, and full attributes.

- **IMPO auction scraper** — parses the official government site for
  judicial auctions (`impo.com.uy/remates`). Extracts property type,
  location, area, padrón, currency, reserve price, auctioneer contact,
  and links to full edictos in Diario Oficial.

- **Market enrichment** — for each auction, computes median and mean
  price per m² for comparable listings in the same department from
  MercadoLibre, producing an estimated market value. This is the core
  value proposition: "This auction has no reserve, the plot is 6,800 m²
  in Pando, comparable listings go for $45/m² — estimated market value
  ~$306,000."

- **Telegram publishing** — MarkdownV2 posts with rich formatting,
  emoji, hashtags, and disclaimers. Supports English and Spanish.

- **Deduplication** — by URL, ML item ID, content hash, and edicto
  number. Persistent across runs via JSON cache.

## Quick start

```bash
# Clone the repo
git clone <your-repo-url>
cd uru-lands

# Create virtual env and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your Telegram bot token and chat ID

# Test-run without sending to Telegram
python main.py --dry-run --max 10

# Full cycle
python main.py
```

## Usage

```bash
# All sources, full cycle
python main.py

# Only MercadoLibre marketplace listings
python main.py --source ml --max 30

# Only IMPO auctions, land plots only, English posts
python main.py --source impo --land-only --lang en

# Dry run — parse and print, no side effects
python main.py --source impo --dry-run

# Export to JSON instead of Telegram
python main.py --no-send --export results.json
```

## Architecture

```
config.py              Env vars and logging
models.py              Listing pydantic model
scraper.py             MercadoLibre API scraper
impo_parser.py         IMPO edicto text parser (regex-based)
impo_scraper.py        IMPO HTTP fetcher
enrichment.py          Auction + market data combiner
auction_formatter.py   Telegram MarkdownV2 formatter
telegram_bot.py        MercadoLibre → Telegram sender
duplicate_checker.py   Multi-strategy deduplication
main.py                CLI orchestrator
```

## Testing

```bash
python tests/test_impo_parser.py        # 39 unit tests
python tests/test_auction_formatter.py  # Smoke tests
```

Tests are plain Python scripts — no pytest required. Exit code 0 means
all tests passed. CI runs on every push via GitHub Actions.

## Dependencies

Intentionally minimal:
- `aiohttp` — async HTTP client
- `pydantic` — data validation
- `python-dotenv` — env file loader

That's it. No Playwright, no Selenium, no requests, no BeautifulSoup.

## Data sources

| Source | Method | Coverage | Notes |
|--------|--------|----------|-------|
| MercadoLibre | Public API | ~800 land listings | Stable, no blocks |
| IMPO (Diario Oficial) | HTML parsing | ~50 auctions/week | Government site, ISO-8859-1 |
| InfoCasas | Not yet | ~400 listings | Mobile API discovery TBD |
| Gallito | Not yet | ~1500 listings | Cloudflare, needs paid proxy |
| BuscandoCasa | Not yet | ~500 listings | Simple HTML, easy |
| ANV (state agency) | Not yet | ~30 auctions/month | Government auctions |
| ANRTCI | Not yet | Varies | Auctioneer association |

## Legal

Data from public government sources (IMPO Diario Oficial) and official
APIs (MercadoLibre). All content is aggregated, reformatted, and
annotated with market analysis — not copied verbatim. Posts include
disclaimers that analysis is not investment advice.

## License

Private project. All rights reserved.
