"""Synthetic raw data shaped like the real sources, for demos and tests.

The numbers are SYNTHETIC. Price levels and the big moves (the 2022 fuel spike, the
2023 vegetable spike, the 2024 olive-oil spike) are modelled loosely on public reporting so the
charts look plausible, but no row is a real observation. The point is the shape of the data:
three layouts, French and English names, decimal commas, grams vs kilos, typos ×10,
blank prices, unknown items and re-posted listings, i.e. what the cleaning pipeline has to handle.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pandas as pd

from .catalog import CITIES, PRODUCTS

# Price of each product in Casablanca, January 2021 (MAD per canonical unit).
BASE = {
    "diesel": 9.4, "gasoline": 10.6, "flour": 4.6, "sugar": 6.0, "vegetable-oil": 15.0,
    "olive-oil": 50.0, "milk": 7.0, "chicken": 15.0, "beef": 80.0, "tomatoes": 5.5,
    "onions": 4.0, "potatoes": 4.5, "rent-2br": 5000.0,
}

# Long-run path of each product as (month, multiplier) anchors, interpolated in log space.
PATH = {
    "diesel": [("2021-01", 1.0), ("2022-06", 1.76), ("2023-01", 1.40), ("2024-06", 1.36), ("2026-10", 1.30)],
    "gasoline": [("2021-01", 1.0), ("2022-06", 1.73), ("2023-06", 1.33), ("2026-10", 1.31)],
    "flour": [("2021-01", 1.0), ("2022-09", 1.20), ("2026-10", 1.25)],
    "sugar": [("2021-01", 1.0), ("2023-01", 1.05), ("2026-10", 1.06)],
    "vegetable-oil": [("2021-01", 1.0), ("2022-06", 1.45), ("2024-01", 1.20), ("2026-10", 1.22)],
    "olive-oil": [("2021-01", 1.0), ("2022-12", 1.20), ("2024-03", 2.00), ("2025-06", 1.50), ("2026-10", 1.40)],
    "milk": [("2021-01", 1.0), ("2023-03", 1.15), ("2026-10", 1.20)],
    "chicken": [("2021-01", 1.0), ("2022-04", 1.30), ("2023-06", 1.25), ("2026-10", 1.35)],
    "beef": [("2021-01", 1.0), ("2023-06", 1.30), ("2025-03", 1.45), ("2026-10", 1.40)],
    "tomatoes": [("2021-01", 1.0), ("2023-03", 1.60), ("2024-01", 1.20), ("2026-10", 1.25)],
    "onions": [("2021-01", 1.0), ("2023-03", 1.70), ("2024-01", 1.20), ("2026-10", 1.20)],
    "potatoes": [("2021-01", 1.0), ("2023-03", 1.30), ("2026-10", 1.25)],
    "rent-2br": [("2021-01", 1.0), ("2026-10", 1.18)],
}

SEASON = {"tomatoes": (0.25, 1), "onions": (0.15, 2), "potatoes": (0.10, 3), "chicken": (0.08, 7)}  # (amplitude, peak month)
NOISE = {"fuel": 0.01, "food": 0.015, "fresh": 0.06, "housing": 0.01}
RENT_LEVEL = {"casablanca": 1.0, "rabat": 0.96, "marrakech": 0.76, "tangier": 0.72, "agadir": 0.64,
              "fes": 0.56, "meknes": 0.50, "oujda": 0.46}
LISTINGS_PER_MONTH = {"casablanca": 90, "rabat": 60}
QUANTITIES = {"kg": ["1 kg", "1 kg", "500 g", "2 kg"], "L": ["1 L", "1 L", "50 cl", "5 L"]}
DISTRICTS = ["Centre", "Maarif", "Agdal", "Hay Riad", "Gueliz", "Médina", "Founty", "Malabata", "Saiss"]


def _true_prices(rng: np.random.Generator, months: pd.DatetimeIndex) -> dict[tuple[str, str], np.ndarray]:
    t = (months.year - 2021) * 12 + months.month - 1
    out = {}
    for product, (_name, category, *_rest) in PRODUCTS.items():
        anchors = PATH[product]
        at = [(pd.Timestamp(m).year - 2021) * 12 + pd.Timestamp(m).month - 1 for m, _ in anchors]
        path = np.exp(np.interp(t, at, np.log([v for _, v in anchors])))
        amp, peak = SEASON.get(product, (0.0, 1))
        season = 1 + amp * np.cos(2 * np.pi * (months.month - peak) / 12)
        for city in CITIES:
            level = RENT_LEVEL[city] if product == "rent-2br" else 1 + rng.normal(0, 0.02 if category == "fuel" else 0.05)
            shock = np.zeros(len(months))
            for i in range(len(months)):  # AR(1) noise: prices drift, they don't jump around i.i.d.
                shock[i] = (0.6 * shock[i - 1] if i else 0) + rng.normal(0, NOISE[category])
            out[(product, city)] = BASE[product] * level * path * season * np.exp(shock)
    return out


def _alias(rng: np.random.Generator, slug: str, table: dict, p_alias: float = 0.25) -> str:
    row = table[slug]
    names = [row[0], *row[-1]]
    name = rng.choice(names[1:]) if len(names) > 1 and rng.random() < p_alias else names[0]
    return str(name).upper() if rng.random() < 0.03 else (f" {name} " if rng.random() < 0.03 else str(name))


def _fmt(value: float, comma: bool, suffix: str = "") -> str:
    s = f"{value:.2f}"
    return (s.replace(".", ",") if comma else s) + suffix


def generate(out_dir: str | Path, start: str = "2021-01", end: str = "2026-10", seed: int = 7,
             cities: list[str] | None = None) -> dict[str, Path]:
    """Write fuel_prices.csv, market_survey.csv and rent_listings.csv. Returns their paths."""
    rng = np.random.default_rng(seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    months = pd.date_range(start, end, freq="MS")
    truth = _true_prices(rng, months)
    city_list = cities or list(CITIES)

    def typo(price: float) -> float:
        return price * 10 if rng.random() < 0.004 else price

    # ---- fuel notices: ~weekly per city, dd/mm/yyyy, "12,85 DH"
    fuel_path = out / "fuel_prices.csv"
    with fuel_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "ville", "produit", "prix"])
        for mi, m in enumerate(months):
            for city in city_list:
                for product in ("diesel", "gasoline"):
                    for day in sorted(rng.choice(range(1, 29), size=4, replace=False)):
                        price = typo(truth[(product, city)][mi] * (1 + rng.normal(0, 0.005)))
                        cell = "" if rng.random() < 0.003 else _fmt(price, True, " DH")
                        w.writerow([f"{day:02d}/{m.month:02d}/{m.year}", _alias(rng, city, CITIES),
                                    _alias(rng, product, PRODUCTS, 0.6), cell])

    # ---- market survey: weekly, 3 vendors per product, mixed pack sizes and decimal styles
    market_path = out / "market_survey.csv"
    food = [p for p, row in PRODUCTS.items() if row[1] in ("food", "fresh")]
    with market_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "city", "item", "quantity", "price", "vendor"])
        for mi, m in enumerate(months):
            for week in range(4):
                day = m + pd.Timedelta(days=7 * week + int(rng.integers(0, 3)))
                for city in city_list:
                    for product in food:
                        unit = PRODUCTS[product][2]
                        for vendor in range(1, 4):
                            qty_label = str(rng.choice(QUANTITIES[unit]))
                            qty = float(qty_label.split()[0]) * {"g": 0.001, "cl": 0.01}.get(qty_label.split()[1], 1)
                            price = typo(truth[(product, city)][mi] * qty * (1 + rng.normal(0, 0.04)))
                            item = _alias(rng, product, PRODUCTS, 0.5)
                            r = rng.random()
                            if r < 0.002:
                                item = "Saffron"                      # not tracked → unknown_product
                            elif r < 0.004:
                                qty_label = "1 kg" if unit == "L" else "1 L"  # unit_mismatch
                            cell = "n/a" if rng.random() < 0.005 else _fmt(price, rng.random() < 0.5)
                            w.writerow([day.date().isoformat(), _alias(rng, city, CITIES), item,
                                        qty_label, cell, f"V{vendor}"])

    # ---- rent listings: 1–4 rooms, re-posted listings, "4 500 DH"
    rent_path = out / "rent_listings.csv"
    room_factor = {1: 0.7, 2: 1.0, 3: 1.35, 4: 1.8}
    next_id = 100000
    with rent_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["listing_id", "posted_at", "city", "district", "rooms", "surface_m2", "price"])
        for mi, m in enumerate(months):
            for city in city_list:
                for _ in range(LISTINGS_PER_MONTH.get(city, 40)):
                    rooms = int(rng.choice([1, 2, 2, 2, 3, 3, 4]))
                    price = typo(truth[("rent-2br", city)][mi] * room_factor[rooms] * rng.lognormal(0, 0.12))
                    price = round(price / 50) * 50
                    cell = f"{price:,.0f}".replace(",", " ") + " DH" if rng.random() < 0.6 else str(price)
                    posted = m + pd.Timedelta(days=int(rng.integers(0, 28)))
                    row = [f"L{next_id}", posted.date().isoformat(), _alias(rng, city, CITIES),
                           str(rng.choice(DISTRICTS)), rooms, int(30 + rooms * 22 + rng.normal(0, 8)), cell]
                    w.writerow(row)
                    if rng.random() < 0.08:  # re-posted a few days later, same listing
                        row[1] = (posted + pd.Timedelta(days=int(rng.integers(3, 20)))).date().isoformat()
                        w.writerow(row)
                    next_id += 1

    return {"fuel": fuel_path, "market": market_path, "rent": rent_path}
