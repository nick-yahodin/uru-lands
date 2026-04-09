"""
Парсер аукционных объявлений IMPO (Diario Oficial Uruguay).

Извлекает структурированные данные из текста edictos:
  - Дата и время аукциона
  - Место проведения
  - Тип имущества (inmueble / mueble / rural / urban)
  - Площадь (м² или гектары)
  - Локация (город, департамент)
  - Условия (валюта, sin base / con base)
  - Rematador (имя, матрикула)
  - Номер edicto
  - Padrón (кадастровый номер, если указан)

Фильтрует только земельные участки и недвижимость (бытовые лоты — машины,
вещи, инвентарь — отбрасываются).
"""

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, List


# ── Модель данных ─────────────────────────────────────────

@dataclass
class Auction:
    """Объявление об аукционе."""
    # Основное
    auction_date: Optional[str] = None      # "2026-04-10"
    auction_time: Optional[str] = None      # "13:30"
    location: Optional[str] = None          # "Uruguay 826"
    department: Optional[str] = None        # "CANELONES"

    # Предмет аукциона
    property_type: Optional[str] = None     # "terreno" / "inmueble" / "campo" / "apartamento"
    description: Optional[str] = None       # Полное описание
    area_m2: Optional[float] = None         # Площадь в м²
    area_raw: Optional[str] = None          # Сырая строка площади

    # Локация участка
    city: Optional[str] = None              # Город/локалидад
    region: Optional[str] = None            # Departamento (где находится имущество)
    zone: Optional[str] = None              # "urbana" / "rural" / "suburbana"

    # Идентификаторы
    padron: Optional[str] = None            # Кадастровый номер
    edicto_number: Optional[str] = None     # Номер публикации "4736/026"
    edicto_url: Optional[str] = None        # URL полного edicto

    # Условия торгов
    currency: Optional[str] = None          # "USD" / "UYU"
    has_base: bool = False                  # False = "sin base"
    base_price: Optional[float] = None      # Если есть стартовая цена

    # Продавец
    rematador_name: Optional[str] = None    # "HERNANDEZ Lorenzo"
    rematador_matricula: Optional[str] = None  # "5605"

    # Метаданные
    published_date: Optional[str] = None    # Дата публикации в Diario Oficial
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # Флаги для фильтрации
    is_real_estate: bool = False            # True для земли/недвижимости
    is_land: bool = False                   # True только для земельных участков
    is_rural: bool = False                  # True для сельхоз земли


# ── Константы ─────────────────────────────────────────────

DEPARTMENTS = {
    "ARTIGAS", "CANELONES", "CERRO LARGO", "COLONIA", "DURAZNO",
    "FLORES", "FLORIDA", "LAVALLEJA", "MALDONADO", "MONTEVIDEO",
    "PAYSANDÚ", "PAYSANDU", "RÍO NEGRO", "RIO NEGRO", "RIVERA",
    "ROCHA", "SALTO", "SAN JOSÉ", "SAN JOSE", "SORIANO",
    "TACUAREMBÓ", "TACUAREMBO", "TREINTA Y TRES",
}

# Ключевые слова для классификации типа имущества
LAND_KEYWORDS = [
    "terreno", "solar", "solares", "fracción de terreno", "fracción de campo",
    "padrón rural", "chacra", "campo", "predio",
]

REAL_ESTATE_KEYWORDS = LAND_KEYWORDS + [
    "inmueble", "casa", "vivienda", "apartamento", "propiedad horizontal",
    "local comercial", "galpón", "edificio",
]

RURAL_KEYWORDS = [
    "rural", "campo", "chacra", "hectárea", "há", "hás", "padrón rural",
    "paraje", "sección catastral",
]

# Регулярные выражения
RE_FECHA = re.compile(
    r"Fecha:\s*\*?\*?(\d{1,2}/\d{1,2}/\d{4})\*?\*?\s*-\s*Hora:\s*\*?\*?([\d:]+)\*?\*?"
)
RE_LUGAR = re.compile(r"Lugar:\s*\*?\*?([^\n\r]+?)(?:\*\*|\n|$)")
RE_BIEN = re.compile(r"Bien a rematar\s*-\s*([^\n\r]+)", re.IGNORECASE)
RE_CONDICIONES = re.compile(r"Condiciones\s*-\s*([^\n\r]+)", re.IGNORECASE)
RE_REMATADOR = re.compile(
    r"Rematador\s*-\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]+?),\s*mat\.?\s*N[°º]?\s*(\d+)",
    re.IGNORECASE,
)
RE_PUBLICADO = re.compile(
    r"Publicado en el Diario Oficial el d[ií]a\s*(\d{1,2}/\d{1,2}/\d{4}).*?aviso\s*(\d+/\d+)",
    re.IGNORECASE | re.DOTALL,
)
RE_PADRON = re.compile(
    r"padr[oó]n(?:es)?\s*(?:rural(?:es)?\s*)?(?:N[°º]?|No\.?)?\s*([\d\.]+)",
    re.IGNORECASE,
)
RE_SUPERFICIE = re.compile(
    r"superficie\s+(?:total\s+)?(?:individual\s+)?(?:aproximada\s+)?"
    r"([\d\.,]+)\s*(hectáreas?|hás\.?|há\.?|ha\.?|m²|mts?\.?|metros|m)\b",
    re.IGNORECASE,
)
RE_AREA_HA = re.compile(
    r"([\d\.,]+)\s*(?:hás?\.?|hectáreas?)",
    re.IGNORECASE,
)
RE_AREA_M2 = re.compile(
    r"([\d\.,]+)\s*(?:m²|mts?\.?|metros)",
    re.IGNORECASE,
)


# ── Функции парсинга ──────────────────────────────────────

def _parse_date(date_str: str) -> Optional[str]:
    """Конвертирует DD/MM/YYYY в YYYY-MM-DD."""
    try:
        parts = date_str.strip().split("/")
        if len(parts) == 3:
            d, m, y = parts
            return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    except (ValueError, AttributeError):
        pass
    return None


def _parse_area(description: str) -> tuple[Optional[float], Optional[str]]:
    """
    Извлекает площадь в м² из описания.
    Возвращает (area_m2, raw_string).

    Примеры:
      "superficie aproximada 6.809 m²" → (6809.0, "6.809 m²")
      "superficie aproximada 9 hás" → (90000.0, "9 hás")
      "superficie aproximada 112 há" → (1120000.0, "112 há")
    """
    # Сначала пробуем найти "superficie ... X unit" — более надёжный паттерн
    match = RE_SUPERFICIE.search(description)
    if match:
        value_str, unit = match.groups()
        raw = f"{value_str} {unit}"
    else:
        # Fallback: ищем любое число с единицей
        ha_match = RE_AREA_HA.search(description)
        if ha_match:
            value_str = ha_match.group(1)
            unit = "ha"
            raw = f"{value_str} ha"
        else:
            m2_match = RE_AREA_M2.search(description)
            if m2_match:
                value_str = m2_match.group(1)
                unit = "m²"
                raw = f"{value_str} m²"
            else:
                return None, None

    # Парсим число. В уругвайской записи "6.809" = 6809 (тысячи),
    # "6,809" тоже может быть 6809, но может быть и десятичная дробь.
    # Эвристика: если после точки/запятой ровно 3 цифры → тысячный разделитель
    try:
        normalized = value_str.replace(" ", "")
        if "," in normalized and "." in normalized:
            # "1.234,56" — испанский формат
            normalized = normalized.replace(".", "").replace(",", ".")
        elif "." in normalized:
            parts = normalized.split(".")
            if len(parts) == 2 and len(parts[1]) == 3:
                # "6.809" = 6809 (тысячный разделитель)
                normalized = normalized.replace(".", "")
            # иначе оставляем как есть (десятичная точка)
        elif "," in normalized:
            parts = normalized.split(",")
            if len(parts) == 2 and len(parts[1]) == 3:
                # "6,809" = 6809
                normalized = normalized.replace(",", "")
            else:
                normalized = normalized.replace(",", ".")

        value = float(normalized)
    except ValueError:
        return None, raw

    # Конвертируем в м²
    unit_lower = unit.lower()
    # Проверяем на гектары: ha, hás, há, hectárea
    is_hectares = (
        unit_lower.startswith("ha")
        or unit_lower.startswith("há")
        or "hect" in unit_lower
    )
    if is_hectares:
        value *= 10000

    return value, raw


def _classify_property(description: str) -> tuple[bool, bool, bool, Optional[str]]:
    """
    Классифицирует тип имущества.
    Возвращает (is_real_estate, is_land, is_rural, property_type).
    """
    lower = description.lower()

    # Проверяем, что это вообще inmueble (не мебель, не машины)
    is_real_estate = "bien inmueble" in lower or any(
        kw in lower for kw in REAL_ESTATE_KEYWORDS
    )
    if not is_real_estate:
        # Исключаем явно не-недвижимость
        if any(kw in lower for kw in ["bien mueble", "bienes muebles", "vehículo", "automóvil"]):
            return False, False, False, None

    # Определяем, земля ли это
    is_land = any(kw in lower for kw in LAND_KEYWORDS)

    # Определяем, сельская ли
    is_rural = any(kw in lower for kw in RURAL_KEYWORDS)

    # Определяем конкретный тип
    property_type = None
    if "fracción de campo" in lower or "padrón rural" in lower:
        property_type = "campo"
    elif "chacra" in lower:
        property_type = "chacra"
    elif "fracción de terreno" in lower or "solar de terreno" in lower:
        property_type = "terreno"
    elif "solar" in lower:
        property_type = "terreno"
    elif "propiedad horizontal" in lower:
        property_type = "apartamento"
    elif "casa" in lower or "vivienda" in lower:
        property_type = "casa"
    elif "galpón" in lower:
        property_type = "galpón"
    elif "local" in lower:
        property_type = "local"
    elif is_land:
        property_type = "terreno"
    elif is_real_estate:
        property_type = "inmueble"

    return is_real_estate, is_land, is_rural, property_type


def _extract_location(description: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Извлекает город, департамент и зону из описания.
    Возвращает (city, region, zone).
    """
    lower = description.lower()

    # Зона
    zone = None
    if "zona urbana" in lower:
        zone = "urbana"
    elif "zona rural" in lower:
        zone = "rural"
    elif "zona suburbana" in lower:
        zone = "suburbana"

    # Департамент
    region = None
    for dept in DEPARTMENTS:
        if dept.lower() in lower:
            region = dept.title()
            break

    # Город/локалидад
    city = None
    # Паттерны: "localidad catastral X", "ciudad de X", "paraje X"
    city_patterns = [
        r"localidad catastral\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ\s]+?)(?:,|\.|zona|\s+con|\s+departamento)",
        r"ciudad de\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ\s]+?)(?:,|\.|zona|\s+con|\s+departamento)",
        r"paraje\s+['\"]?([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ\s]+?)['\"]?(?:,|\.|zona|\s+con)",
    ]
    for pattern in city_patterns:
        match = re.search(pattern, description)
        if match:
            city = match.group(1).strip().rstrip(",")
            break

    return city, region, zone


def _extract_conditions(conditions_text: str) -> tuple[Optional[str], bool]:
    """
    Парсит условия торгов.
    Возвращает (currency, has_base).
    """
    if not conditions_text:
        return None, False

    lower = conditions_text.lower()

    # Валюта
    currency = None
    if "dólar" in lower or "dolar" in lower or "u$s" in lower or "usd" in lower:
        currency = "USD"
    elif "peso" in lower or "uyu" in lower:
        currency = "UYU"

    # База
    has_base = "sin base" not in lower

    return currency, has_base


def parse_edicto_block(block: str, current_department: Optional[str] = None) -> Optional[Auction]:
    """
    Парсит один блок edicto из текста IMPO.

    Args:
        block: Текст блока (с "Fecha:", "Lugar:", etc.)
        current_department: Текущий департамент (из заголовка страницы)

    Returns:
        Auction или None, если блок невалиден
    """
    if "Fecha:" not in block or "Bien a rematar" not in block:
        return None

    auction = Auction(department=current_department)

    # Дата и время
    m = RE_FECHA.search(block)
    if m:
        auction.auction_date = _parse_date(m.group(1))
        auction.auction_time = m.group(2).strip()

    # Место
    m = RE_LUGAR.search(block)
    if m:
        auction.location = m.group(1).strip().rstrip(".*")

    # Описание (Bien a rematar)
    m = RE_BIEN.search(block)
    if m:
        bien_text = m.group(1).strip()
        auction.description = bien_text

        # Классификация
        is_re, is_land, is_rural, prop_type = _classify_property(bien_text)
        auction.is_real_estate = is_re
        auction.is_land = is_land
        auction.is_rural = is_rural
        auction.property_type = prop_type

        # Площадь
        auction.area_m2, auction.area_raw = _parse_area(bien_text)

        # Локация участка
        city, region, zone = _extract_location(bien_text)
        auction.city = city
        if region and not current_department:
            auction.department = region
        auction.zone = zone

        # Padrón
        m_padron = RE_PADRON.search(bien_text)
        if m_padron:
            auction.padron = m_padron.group(1).replace(".", "")

    # Условия
    m = RE_CONDICIONES.search(block)
    if m:
        currency, has_base = _extract_conditions(m.group(1))
        auction.currency = currency
        auction.has_base = has_base

    # Rematador
    m = RE_REMATADOR.search(block)
    if m:
        auction.rematador_name = m.group(1).strip()
        auction.rematador_matricula = m.group(2)

    # Публикация
    m = RE_PUBLICADO.search(block)
    if m:
        auction.published_date = _parse_date(m.group(1))
        auction.edicto_number = m.group(2)
        # Формируем URL
        num, year = m.group(2).split("/")
        auction.edicto_url = f"http://www.impo.com.uy/bases/avisos-remate/{num}-{year}"

    return auction


def parse_impo_text(text: str) -> List[Auction]:
    """
    Парсит полный текст со страницы IMPO remates.

    Args:
        text: Сырой текст (HTML или markdown) со страницы

    Returns:
        Список распарсенных аукционов
    """
    auctions = []
    current_department = None

    # Разбиваем по блокам edicto
    # Каждый блок начинается с "Fecha:" и заканчивается "Publicado en el Diario Oficial"
    blocks = re.split(r"(?=Fecha:\s*\*?\*?\d)", text)

    for block in blocks:
        if not block.strip():
            continue

        # Проверяем, не заголовок ли департамента в этом блоке
        for dept in DEPARTMENTS:
            if re.search(rf"\b{dept}\b", block[:200]):
                current_department = dept.title()
                break

        auction = parse_edicto_block(block, current_department)
        if auction:
            auctions.append(auction)

    return auctions


def filter_land_only(auctions: List[Auction]) -> List[Auction]:
    """Оставляет только земельные участки (terrenos, campos, chacras)."""
    return [a for a in auctions if a.is_land]


def filter_real_estate(auctions: List[Auction]) -> List[Auction]:
    """Оставляет всю недвижимость (земля + здания)."""
    return [a for a in auctions if a.is_real_estate]
