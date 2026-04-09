# uru-lands — Project Context for Claude Code

## What this project is

uru-lands is a data aggregator for Uruguay's real estate and land auction
market. It scrapes MercadoLibre (via public API) and IMPO (Diario Oficial,
for judicial auctions), enriches auctions with market price context, and
publishes findings to Telegram channels.

The business goal: provide a curated feed of undervalued land opportunities
in Uruguay — especially judicial auctions (remates), which are the main
differentiator. Target audience: international investors (English-speaking)
and local buyers (Spanish).

## User context (important)

The owner of this project (Nick) is in Canada, speaks Russian and English,
and does NOT speak Spanish. He is not a developer by trade — he directs
work in natural language and expects Claude Code to handle ALL operational
tasks autonomously: writing code, running tests, committing to git,
debugging failures, deploying.

**Communication style:**
- Respond in Russian unless Nick writes in English
- Code, commits, comments, docs → always English
- Explain technical decisions briefly but clearly
- Never ask Nick to run terminal commands himself — do it yourself
- When something fails, fix it yourself, don't kick it back to the user

## Repository structure

This project lives INSIDE a monorepo at:
`nick-yahodin/nick-yahodin` → `Development/uru-lands/`

When committing, the working directory may be the monorepo root or the
project subfolder — check `git rev-parse --show-toplevel` to confirm.
All commits should be scoped to this subfolder only (don't touch
`Development/figma-swap-library/`, `Development/portfolio-website/`, etc.).

Use scoped commit messages:
- `feat(uru-lands): add InfoCasas parser`
- `fix(uru-lands): handle missing padrón in edictos`
- `test(uru-lands): add formatter smoke tests`
- `chore(uru-lands): update dependencies`

## Architecture

```
config.py              Env vars and logging setup (dotenv-based)
models.py              Listing pydantic model (MercadoLibre data)
scraper.py             MercadoLibre public API scraper
impo_parser.py         IMPO edicto text parser (no HTTP)
impo_scraper.py        IMPO HTTP fetcher (uses impo_parser)
enrichment.py          Combines IMPO auctions with ML market data
auction_formatter.py   Telegram MarkdownV2 formatter (EN/ES)
telegram_bot.py        Telegram sender for MercadoLibre listings
duplicate_checker.py   URL/ID/hash dedup
main.py                CLI entry point — orchestrates everything

tests/
  test_impo_parser.py       39 unit tests, all passing
  test_auction_formatter.py Smoke tests for MarkdownV2 output
  impo_sample.txt           Real IMPO edicto data for fixtures

.github/workflows/
  tests.yml            CI on push, Python 3.10/3.11/3.12
```

## Design principles

1. **API-first.** Prefer public APIs over HTML scraping. MercadoLibre has
   `api.mercadolibre.com/sites/MLU/search` and `/items/{id}` — use those,
   not Playwright. Only fall back to HTML parsing when no API exists
   (IMPO is HTML because it's a government site with no API).

2. **Minimal dependencies.** Only `aiohttp`, `pydantic`, `python-dotenv`.
   Do NOT add Playwright, Selenium, requests, Beautiful Soup unless
   strictly necessary. IMPO parser uses regex because the HTML is
   trivial and we don't want bs4 as a dependency for one file.

3. **Single responsibility per file.** If a file grows past 400 lines,
   that's a smell — split it. The old version had a 3,280-line
   `mercadolibre.py` with three duplicate `_extract_listing_details`
   methods. Don't let that happen again.

4. **Test the parser, smoke-test the rest.** The IMPO parser has
   comprehensive unit tests (39/39) because regex logic is fragile.
   Formatters have smoke tests (no exceptions). HTTP scrapers are
   integration-tested manually against live sites.

5. **Fail loudly in dev, gracefully in prod.** Use `logger.error` with
   full stack traces for unexpected issues. Never silently `except
   Exception: pass`. If a field is missing from an edicto, log a
   warning and set to None — don't crash the whole batch.

## Common tasks

### Adding a new data source
1. Create `<source>_scraper.py` with a class matching the interface
   of `IMPOScraper` or `MercadoLibreScraper` (async `scrape()` method
   returning a list of `Listing` or `Auction`).
2. Wire it into `main.py` with a `--source <name>` flag.
3. Write at least 5 unit tests against real sample data.
4. Update `README.md` with the new source.

### Running tests
```bash
python tests/test_impo_parser.py
python tests/test_auction_formatter.py
```
(No pytest required — tests are plain Python scripts. Exit code 0 = pass.)

### Committing changes
Nick's trigger phrase is "закоммить" or "commit to git" or "push this".
When you hear it:
1. Run `git status` to see what changed
2. Run the tests if any code changed
3. Stage only files in `Development/uru-lands/`
4. Write a clear conventional commit message in English
5. Push to the remote

Do NOT commit `.env`, `data/`, `*.log`, or any files matching `.gitignore`.

### Running the scraper
```bash
python main.py --source impo --land-only --dry-run    # Test without sending
python main.py --source ml --max 20 --no-send         # ML only
python main.py                                         # Full cycle
```

## Known gotchas

- **IMPO encoding is ISO-8859-1**, not UTF-8. Decode manually in
  `impo_scraper.py` — don't trust `resp.text()`.
- **Uruguayan number format**: "6.809 m²" means 6,809 (thousands separator
  is a dot), not 6.809 decimal. The parser handles this, but be careful
  if you add more number parsing.
- **Spanish 'á' is not 'a'** in Python string comparisons. `"ha" in "hás"`
  is `False` because `á` is a separate Unicode codepoint. When matching
  units like hectares, use `startswith("há")` explicitly.
- **MercadoLibre API** returns ~50 items per page. For Uruguay there are
  typically ~400-800 land listings at any time. Don't request more than
  200 at once in production — respect their implicit rate limits.
- **Telegram MarkdownV2** requires escaping `_*[]()~\`>#+-=|{}.!\`. The
  `_escape()` helper in `auction_formatter.py` handles this. If you add
  new fields, make sure they go through it.

## Deployment (future)

Not yet deployed. Target: single small VPS (Hetzner CAX11 ~€4/mo or
DigitalOcean $6/mo), cron job running `main.py` once a day. No
containerization needed — plain systemd timer or cron + venv.

## Business context (for decision-making)

Nick is validating this as a small business. Monetization stages:
1. Free Telegram channel → build audience (months 1-3)
2. Paid subscription $20/mo for enriched feed (months 3-6)
3. White-glove service: help foreign investors buy at auction (months 6+)

When making product decisions, bias toward:
- **Data quality** over quantity (one well-enriched auction > ten raw ones)
- **English content** over Spanish (main audience = international)
- **Aggressive filtering** (skip auctions for cars/furniture, keep only
  real estate — land plots especially)
- **Honest disclaimers** ("Not investment advice. Consult escribano.")
  — this is legally important and builds trust

When in doubt about a product decision, ask Nick — don't guess at
business logic. Technical decisions you can make yourself.
