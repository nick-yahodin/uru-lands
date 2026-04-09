"""Отправка объявлений в Telegram-канал."""

import asyncio
import logging
import re
from typing import List, Optional
from io import BytesIO

import aiohttp

from models import Listing
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


class TelegramSender:
    """Отправляет объявления о земельных участках в Telegram."""

    def __init__(
        self,
        token: str = TELEGRAM_BOT_TOKEN,
        chat_id: str = TELEGRAM_CHAT_ID,
    ):
        if not token or not chat_id:
            raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID required")
        self.api = f"https://api.telegram.org/bot{token}"
        self.chat_id = chat_id

    def format_message(self, listing: Listing) -> str:
        """Форматирует объявление для Telegram (Markdown V2)."""
        lines = []

        # Заголовок
        title = self._escape(listing.title or "Terreno en venta")
        lines.append(f"🏞️ *{title}*")
        lines.append("")

        # Основные поля
        if listing.price:
            lines.append(f"💰 *Precio:* {self._escape(listing.price)}")

        if listing.location:
            lines.append(f"📍 *Ubicación:* {self._escape(listing.location)}")

        if listing.area:
            area_str = self._escape(listing.area)
            if listing.price_per_m2:
                area_str += f" \\(${listing.price_per_m2:.0f}/m²\\)"
            lines.append(f"📐 *Superficie:* {area_str}")

        if listing.zoning:
            lines.append(f"🏗 *Zona:* {self._escape(listing.zoning)}")

        if listing.utilities and listing.utilities != "Не указано":
            lines.append(f"⚡ *Servicios:* {self._escape(listing.utilities)}")

        if listing.front_meters:
            lines.append(f"↔️ *Frente:* {listing.front_meters:.0f} m")

        if listing.orientation:
            lines.append(f"🧭 *Orientación:* {self._escape(listing.orientation)}")

        # Описание (сокращённое)
        if listing.description:
            desc = listing.description[:300]
            if len(listing.description) > 300:
                desc += "..."
            lines.append("")
            lines.append(f"📝 {self._escape(desc)}")

        # Продавец
        if listing.seller_name:
            seller = self._escape(listing.seller_name)
            stype = self._escape(listing.seller_type or "")
            lines.append(f"\n👤 {seller} \\({stype}\\)")

        # Ссылка
        lines.append("")
        lines.append(f"🔗 [Ver en MercadoLibre]({listing.url})")

        # Метки
        if listing.is_recent:
            lines.append("🆕 *Publicación reciente*")

        # Хештеги
        tags = self._generate_hashtags(listing)
        if tags:
            lines.append("")
            lines.append(" ".join(tags))

        return "\n".join(lines)

    async def send_listing(self, listing: Listing) -> bool:
        """Отправляет объявление в Telegram (с фото если есть)."""
        message = self.format_message(listing)

        try:
            async with aiohttp.ClientSession() as session:
                if listing.image_url:
                    # Отправляем с фото
                    data = aiohttp.FormData()
                    data.add_field("chat_id", self.chat_id)
                    data.add_field("photo", str(listing.image_url))
                    data.add_field("caption", message)
                    data.add_field("parse_mode", "MarkdownV2")

                    async with session.post(
                        f"{self.api}/sendPhoto", data=data
                    ) as resp:
                        if resp.status == 200:
                            logger.info(f"Sent with photo: {listing.title}")
                            return True
                        else:
                            error = await resp.text()
                            logger.warning(f"sendPhoto failed ({resp.status}): {error}")
                            # Fallback: отправляем без фото
                            return await self._send_text(session, message)
                else:
                    return await self._send_text(session, message)

        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    async def _send_text(self, session: aiohttp.ClientSession, text: str) -> bool:
        """Отправляет текстовое сообщение."""
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": False,
        }
        async with session.post(f"{self.api}/sendMessage", json=payload) as resp:
            if resp.status == 200:
                return True
            error = await resp.text()
            logger.error(f"sendMessage failed ({resp.status}): {error}")
            return False

    async def send_batch(
        self, listings: List[Listing], delay: float = 1.5
    ) -> int:
        """Отправляет пачку объявлений с задержкой."""
        sent = 0
        for i, listing in enumerate(listings):
            success = await self.send_listing(listing)
            if success:
                sent += 1
                listing.sent_to_telegram = True
            if i < len(listings) - 1:
                await asyncio.sleep(delay)

        logger.info(f"Sent {sent}/{len(listings)} listings to Telegram")
        return sent

    @staticmethod
    def _generate_hashtags(listing: Listing) -> List[str]:
        """Генерирует хештеги на основе данных объявления."""
        tags = ["#Uruguay", "#Terreno"]

        if listing.department:
            dept = re.sub(r"[^a-zA-ZáéíóúñÁÉÍÓÚÑ]", "", listing.department)
            if dept:
                tags.append(f"#{dept}")

        if listing.deal_type == "Venta":
            tags.append("#EnVenta")

        if listing.zoning:
            z = listing.zoning.replace(" ", "")
            tags.append(f"#{z}")

        if listing.area_m2:
            if listing.area_m2 >= 10000:
                ha = listing.area_m2 / 10000
                if ha >= 100:
                    tags.append("#Campo")
                elif ha >= 10:
                    tags.append("#Chacra")
                else:
                    tags.append("#TerrenoGrande")
            else:
                tags.append("#Lote")

        if listing.is_recent:
            tags.append("#Nuevo")

        if listing.utilities and "Agua" in listing.utilities:
            tags.append("#ConServicios")

        return tags[:8]  # Максимум 8 тегов

    @staticmethod
    def _escape(text: str) -> str:
        """Экранирует спецсимволы для Telegram MarkdownV2."""
        chars = r"_*[]()~`>#+-=|{}.!\\"
        for c in chars:
            text = text.replace(c, f"\\{c}")
        return text
