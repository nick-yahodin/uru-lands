"""Конфигурация проекта. Все секреты — только через .env."""

import os
import logging
from dotenv import load_dotenv

load_dotenv()

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Proxy (опционально)
PROXY_SERVER = os.getenv("PROXY_SERVER", "")
PROXY_USER = os.getenv("PROXY_USER", "")
PROXY_PASSWORD = os.getenv("PROXY_PASSWORD", "")

# Scraping
MAX_PAGES = int(os.getenv("MAX_PAGES", "3"))
MAX_LISTINGS = int(os.getenv("MAX_LISTINGS", "50"))
REQUEST_DELAY_MIN = float(os.getenv("REQUEST_DELAY_MIN", "1.0"))
REQUEST_DELAY_MAX = float(os.getenv("REQUEST_DELAY_MAX", "3.0"))
HEADLESS = os.getenv("HEADLESS", "true").lower() in ("true", "1", "yes")

# Paths
DATA_DIR = os.getenv("DATA_DIR", "data")
CACHE_FILE = os.path.join(DATA_DIR, "seen_listings.json")
LOG_FILE = os.path.join(DATA_DIR, "parser.log")

# MercadoLibre API
ML_API_BASE = "https://api.mercadolibre.com"
ML_SEARCH_URL = f"{ML_API_BASE}/sites/MLU/search"
ML_ITEM_URL = f"{ML_API_BASE}/items"
ML_CATEGORY_TERRENOS = "MLU1466"  # Terrenos en Uruguay


def setup_logging(level: str = "INFO"):
    os.makedirs(DATA_DIR, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
        ],
    )
