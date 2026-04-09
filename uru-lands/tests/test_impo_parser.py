"""
Тесты парсера IMPO на реальных данных из Diario Oficial.

Запуск:  python3 test_impo_parser.py
"""

import json
import os
import sys
from dataclasses import asdict

# Add parent dir to path so tests can import from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from impo_parser import (
    parse_impo_text, parse_edicto_block,
    filter_land_only, filter_real_estate,
    _parse_area, _classify_property, _extract_location,
    _extract_conditions,
)


# ── Тестовые данные (реальные edictos из IMPO) ────────────

SAMPLE_TEXT = open(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "impo_sample.txt"),
    encoding="utf-8",
).read()


# ── Helpers ───────────────────────────────────────────────

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
results = {"pass": 0, "fail": 0}


def check(name, condition, expected=None, got=None):
    if condition:
        print(f"  {PASS} {name}")
        results["pass"] += 1
    else:
        print(f"  {FAIL} {name}")
        if expected is not None:
            print(f"      expected: {expected!r}")
            print(f"      got:      {got!r}")
        results["fail"] += 1


# ── Тесты классификации ──────────────────────────────────

def test_classification():
    print("\n[1] Классификация имущества")

    # Земля — sólar de terreno
    desc = "Bien inmueble: Solar de terreno con construcciones, ubicado en Pando, zona suburbana, superficie aproximada 6.809 m²."
    is_re, is_land, is_rural, ptype = _classify_property(desc)
    check("solar de terreno → is_land=True", is_land, True, is_land)
    check("solar de terreno → is_real_estate=True", is_re, True, is_re)
    check("solar de terreno → property_type='terreno'", ptype == "terreno", "terreno", ptype)

    # Сельхоз campo
    desc = "Bien inmueble: Fracción de campo con construcciones, paraje José Ignacio, zona rural, superficie aproximada 9 hás."
    is_re, is_land, is_rural, ptype = _classify_property(desc)
    check("fracción de campo → is_land=True", is_land, True, is_land)
    check("fracción de campo → is_rural=True", is_rural, True, is_rural)
    check("fracción de campo → property_type='campo'", ptype == "campo", "campo", ptype)

    # Квартира
    desc = "Bien inmueble: Unidad de propiedad horizontal N° 901 ubicado en Montevideo, superficie 47 m."
    is_re, is_land, is_rural, ptype = _classify_property(desc)
    check("propiedad horizontal → is_real_estate=True", is_re, True, is_re)
    check("propiedad horizontal → is_land=False", not is_land, False, is_land)
    check("propiedad horizontal → property_type='apartamento'", ptype == "apartamento", "apartamento", ptype)

    # Машина — НЕ недвижимость
    desc = "Bien mueble: Automóvil marca FIAT, modelo PALIO, año 2000."
    is_re, is_land, is_rural, ptype = _classify_property(desc)
    check("automóvil → is_real_estate=False", not is_re, False, is_re)
    check("automóvil → is_land=False", not is_land, False, is_land)

    # Рurал padrón
    desc = "Bien inmueble: Padrón rural No 11.415, ubicado en Rivera, paraje La Calera, superficie aproximada 112 há."
    is_re, is_land, is_rural, ptype = _classify_property(desc)
    check("padrón rural → is_land=True", is_land, True, is_land)
    check("padrón rural → is_rural=True", is_rural, True, is_rural)
    check("padrón rural → property_type='campo'", ptype == "campo", "campo", ptype)


# ── Тесты площади ────────────────────────────────────────

def test_area_parsing():
    print("\n[2] Парсинг площади")

    cases = [
        ("superficie aproximada 6.809 m²", 6809.0, "m²"),
        ("superficie aproximada 9 hás", 90000.0, "ha"),
        ("superficie aproximada 112 há", 1120000.0, "ha"),
        ("superficie aproximada 286 m", 286.0, "m²"),
        ("superficie individual aproximada 75 m", 75.0, "m²"),
        ("superficie total 1.500 m²", 1500.0, "m²"),
    ]

    for text, expected_m2, _ in cases:
        got_m2, raw = _parse_area(text)
        match = got_m2 == expected_m2
        check(f"{text[:40]:40s} → {expected_m2} m²", match, expected_m2, got_m2)


# ── Тесты условий ────────────────────────────────────────

def test_conditions():
    print("\n[3] Парсинг условий")

    cases = [
        ("Sin base, en dólares estadounidenses", "USD", False),
        ("Sin base, en pesos uruguayos", "UYU", False),
        ("Sin base", None, False),
        ("Base de U$S 50.000, en dólares estadounidenses", "USD", True),
    ]

    for text, expected_curr, expected_base in cases:
        curr, has_base = _extract_conditions(text)
        check(
            f"'{text[:40]}' → {expected_curr}, base={expected_base}",
            curr == expected_curr and has_base == expected_base,
            (expected_curr, expected_base), (curr, has_base),
        )


# ── Тесты локации ────────────────────────────────────────

def test_location():
    print("\n[4] Извлечение локации")

    desc = "Solar de terreno con construcciones, ubicado en la séptima sección judicial de Canelones, ciudad de Pando, zona suburbana"
    city, region, zone = _extract_location(desc)
    check("Pando город", city == "Pando", "Pando", city)
    check("Canelones департамент", region == "Canelones", "Canelones", region)
    check("suburbana зона", zone == "suburbana", "suburbana", zone)

    desc = "Padrón rural No 11.415, ubicado en la Cuarta Sección Catastral del departamento de Rivera, Paraje 'La Calera'"
    city, region, zone = _extract_location(desc)
    check("Rivera департамент", region == "Rivera", "Rivera", region)


# ── Интеграционный тест: полный парсинг ──────────────────

def test_full_parse():
    print("\n[5] Полный парсинг текста IMPO")

    auctions = parse_impo_text(SAMPLE_TEXT)
    check(f"Распарсено блоков: {len(auctions)} (ожидалось ≥ 7)", len(auctions) >= 7)

    # Проверяем, что нашли конкретный terreno в Pando
    pando = [a for a in auctions if a.city and "Pando" in a.city]
    check(f"Найден terreno в Pando ({len(pando)})", len(pando) >= 1)
    if pando:
        p = pando[0]
        check(f"  Pando: area_m2 = {p.area_m2}", p.area_m2 == 6809.0, 6809.0, p.area_m2)
        check(f"  Pando: date = {p.auction_date}", p.auction_date == "2026-04-10", "2026-04-10", p.auction_date)
        check(f"  Pando: rematador", p.rematador_name and "HERNANDEZ" in p.rematador_name)
        check(f"  Pando: is_land = {p.is_land}", p.is_land)
        check(f"  Pando: edicto_number = {p.edicto_number}", p.edicto_number == "5585/026", "5585/026", p.edicto_number)

    # Проверяем фильтрацию
    land_only = filter_land_only(auctions)
    real_estate = filter_real_estate(auctions)
    check(f"Земельные участки: {len(land_only)}", len(land_only) >= 3)
    check(f"Недвижимость всего: {len(real_estate)}", len(real_estate) >= 5)
    check(f"Земли ≤ недвижимости", len(land_only) <= len(real_estate))

    # Убеждаемся, что машины отфильтрованы
    cars = [a for a in auctions if a.description and "Automóvil" in a.description]
    check(f"Машины НЕ в real_estate", all(not a.is_real_estate for a in cars))

    return auctions


# ── Красивый вывод примеров ──────────────────────────────

def print_samples(auctions):
    print("\n[6] Примеры распарсенных земельных участков")
    land_auctions = filter_land_only(auctions)

    for i, a in enumerate(land_auctions[:5], 1):
        print(f"\n  ── Лот #{i} ──")
        print(f"  📅 {a.auction_date} {a.auction_time}")
        print(f"  🏛  {a.property_type} ({'сельский' if a.is_rural else 'городской'})")
        if a.area_m2:
            if a.area_m2 >= 10000:
                print(f"  📐 {a.area_m2/10000:.1f} ha ({a.area_raw})")
            else:
                print(f"  📐 {a.area_m2:.0f} m² ({a.area_raw})")
        if a.city:
            print(f"  📍 {a.city}, {a.department or a.region}")
        elif a.department:
            print(f"  📍 {a.department}")
        if a.currency:
            base_str = "con base" if a.has_base else "SIN BASE"
            print(f"  💰 {base_str}, {a.currency}")
        if a.rematador_name:
            print(f"  👤 {a.rematador_name} (mat. {a.rematador_matricula})")
        if a.padron:
            print(f"  🔢 Padrón: {a.padron}")
        if a.edicto_url:
            print(f"  🔗 {a.edicto_url}")


# ── Main ─────────────────────────────────────────────────

if __name__ == "__main__":
    test_classification()
    test_area_parsing()
    test_conditions()
    test_location()
    auctions = test_full_parse()
    print_samples(auctions)

    print("\n" + "═" * 50)
    total = results["pass"] + results["fail"]
    print(f"Результаты: {results['pass']}/{total} тестов прошли")
    if results["fail"] == 0:
        print("✅ Все тесты успешны!")
        sys.exit(0)
    else:
        print(f"❌ {results['fail']} тестов упали")
        sys.exit(1)
