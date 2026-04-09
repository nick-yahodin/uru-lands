"""Единственная модель данных для объявления."""

from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from pydantic import BaseModel, Field, HttpUrl, field_validator


class Listing(BaseModel):
    """Объявление о земельном участке."""

    # Обязательные
    url: HttpUrl
    source: str = "mercadolibre"

    # Основные
    title: Optional[str] = None
    price: Optional[str] = None
    price_usd: Optional[float] = None
    currency: Optional[str] = None
    location: Optional[str] = None
    department: Optional[str] = None  # Departamento (область)
    area: Optional[str] = None
    area_m2: Optional[float] = None
    price_per_m2: Optional[float] = None
    description: Optional[str] = None

    # Медиа
    image_url: Optional[HttpUrl] = None
    image_urls: List[str] = Field(default_factory=list)

    # Детали участка
    zoning: Optional[str] = None  # Rural / Urbano / Suburbano
    utilities: Optional[str] = None  # Agua, Luz, Gas...
    topography: Optional[str] = None
    access_info: Optional[str] = None
    orientation: Optional[str] = None
    front_meters: Optional[float] = None  # Frente del terreno

    # Продавец
    seller_name: Optional[str] = None
    seller_type: Optional[str] = None  # Inmobiliaria / Particular
    seller_phone: Optional[str] = None

    # Координаты
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Метаданные
    ml_item_id: Optional[str] = None  # MLU-xxxxxxx
    date_published: Optional[datetime] = None
    date_scraped: datetime = Field(default_factory=datetime.now)
    deal_type: str = "Venta"
    is_recent: bool = False
    attributes: Dict[str, Any] = Field(default_factory=dict)

    # Telegram
    hashtags: List[str] = Field(default_factory=list)
    sent_to_telegram: bool = False

    @field_validator("url", mode="before")
    @classmethod
    def clean_url(cls, v):
        if isinstance(v, str):
            return v.split("?")[0].split("#")[0]
        return v

    def compute_derived_fields(self):
        """Вычисляет цену за м², извлекает department и т.д."""
        if self.price_usd and self.area_m2 and self.area_m2 > 0:
            self.price_per_m2 = round(self.price_usd / self.area_m2, 2)

        if self.location and not self.department:
            parts = [p.strip() for p in self.location.split(",")]
            if len(parts) >= 2:
                self.department = parts[-1]

    model_config = {"extra": "ignore"}
