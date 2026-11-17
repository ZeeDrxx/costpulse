"""Cleaning raw price files with Pandas and NumPy.

Every cleaner takes the raw DataFrame of one source and returns:
  - a tidy frame with columns  product, city, date, price   (price in MAD per canonical unit)
  - a Counter of rejected rows by reason

`to_monthly` then removes outliers and reduces the samples to one robust price per
(product, city, month). Nothing is silently fixed: every dropped row is counted.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Callable

import numpy as np
import pandas as pd

from ..catalog import CITY_LOOKUP, PRODUCT_LOOKUP, PRODUCTS, UNITS, normalize

TIDY_COLUMNS = ["product", "city", "date", "price"]
OUTLIER_Z = 3.5  # robust z-score above which a sample is dropped
SPREAD_FLOOR = 0.05  # minimum scale as a share of the median: ±17.5% is never an outlier
_QTY = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*([a-zA-Zèé]+)\s*$")


# --------------------------------------------------------------------------- field parsers


def parse_price(values: pd.Series) -> pd.Series:
    """'12,85 DH' → 12.85, '4 500 DH' → 4500, '1.234,50' → 1234.5, 'n/a' → NaN."""
    s = values.astype("string").str.lower()
    s = s.str.replace(r"(dh|mad|dhs)\b", "", regex=True)
    s = s.str.replace(r"[\s  ]", "", regex=True)
    both = s.str.contains(",", regex=False) & s.str.contains(".", regex=False)
    s = s.where(~both, s.str.replace(".", "", regex=False))  # 1.234,50 → 1234,50
    s = s.str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce").astype(float)


def parse_quantity(values: pd.Series) -> tuple[pd.Series, pd.Series]:
    """'500 g' → (0.5, 'kg'); '1 L' → (1.0, 'L'). Unparseable → (NaN, None)."""
    parts = values.astype("string").str.extract(_QTY)
    qty = pd.to_numeric(parts[0].str.replace(",", ".", regex=False), errors="coerce").astype(float)
    unit_key = parts[1].str.lower()
    canon = unit_key.map(lambda u: UNITS.get(u, (None, np.nan))[0] if isinstance(u, str) else None)
    factor = unit_key.map(lambda u: UNITS.get(u, (None, np.nan))[1] if isinstance(u, str) else np.nan)
    return qty * factor.astype(float), canon


def map_names(values: pd.Series, lookup: dict[str, str]) -> pd.Series:
    return values.map(lambda v: lookup.get(normalize(v)) if pd.notna(v) else None)


# --------------------------------------------------------------------------- helpers


def _reject(df: pd.DataFrame, mask: pd.Series, reason: str, rejected: Counter) -> pd.DataFrame:
    n = int(mask.sum())
    if n:
        rejected[reason] += n
    return df[~mask]


def _finish(df: pd.DataFrame, rejected: Counter) -> tuple[pd.DataFrame, Counter]:
    df = _reject(df, df["price"] <= 0, "non_positive_price", rejected)
    return df[TIDY_COLUMNS].reset_index(drop=True), rejected


def _common(df: pd.DataFrame, rejected: Counter) -> pd.DataFrame:
    df = _reject(df, df["city"].isna(), "unknown_city", rejected)
    df = _reject(df, df["product"].isna(), "unknown_product", rejected)
    df = _reject(df, df["date"].isna(), "bad_date", rejected)
    df = _reject(df, df["price"].isna(), "bad_price", rejected)
    return df


# --------------------------------------------------------------------------- sources


def clean_fuel(raw: pd.DataFrame) -> tuple[pd.DataFrame, Counter]:
    """Pump price notices. Columns: date (dd/mm/yyyy), ville, produit, prix ('12,85 DH')."""
    rejected: Counter = Counter()
    df = pd.DataFrame({
        "city": map_names(raw["ville"], CITY_LOOKUP),
        "product": map_names(raw["produit"], PRODUCT_LOOKUP),
        "date": pd.to_datetime(raw["date"], format="%d/%m/%Y", errors="coerce"),
        "price": parse_price(raw["prix"]),
    })
    df = _common(df, rejected)
    df = _reject(df, ~df["product"].isin(["diesel", "gasoline"]), "not_a_fuel", rejected)
    return _finish(df, rejected)


def clean_market(raw: pd.DataFrame) -> tuple[pd.DataFrame, Counter]:
    """Weekly market survey. Columns: date (ISO), city, item, quantity ('500 g'), price."""
    rejected: Counter = Counter()
    qty, unit = parse_quantity(raw["quantity"])
    df = pd.DataFrame({
        "city": map_names(raw["city"], CITY_LOOKUP),
        "product": map_names(raw["item"], PRODUCT_LOOKUP),
        "date": pd.to_datetime(raw["date"], format="%Y-%m-%d", errors="coerce"),
        "price": parse_price(raw["price"]),
        "qty": qty,
        "unit": unit,
    })
    df = _common(df, rejected)
    df = _reject(df, df["qty"].isna() | (df["qty"] <= 0), "bad_quantity", rejected)
    expected = df["product"].map(lambda p: PRODUCTS[p][2])
    df = _reject(df, df["unit"] != expected, "unit_mismatch", rejected)
    df = df.assign(price=df["price"] / df["qty"])  # price per canonical unit
    return _finish(df, rejected)


def clean_rent(raw: pd.DataFrame) -> tuple[pd.DataFrame, Counter]:
    """Rental listings. Columns: listing_id, posted_at, city, district, rooms, surface_m2, price.

    Only 2-room flats are kept; a listing re-posted several times counts once (latest post).
    """
    rejected: Counter = Counter()
    raw = raw.copy()
    raw["posted_at"] = pd.to_datetime(raw["posted_at"], format="%Y-%m-%d", errors="coerce")
    raw = raw.sort_values("posted_at")
    dup = raw.duplicated(subset=["listing_id"], keep="last")
    raw = _reject(raw, dup, "duplicate_listing", rejected)
    rooms = pd.to_numeric(raw["rooms"], errors="coerce")
    raw = _reject(raw, rooms != 2, "not_2_rooms", rejected)
    df = pd.DataFrame({
        "city": map_names(raw["city"], CITY_LOOKUP),
        "product": "rent-2br",
        "date": raw["posted_at"],
        "price": parse_price(raw["price"]),
    })
    df = _common(df, rejected)
    return _finish(df, rejected)


SOURCES: dict[str, tuple[set[str], Callable[[pd.DataFrame], tuple[pd.DataFrame, Counter]]]] = {
    "fuel": ({"date", "ville", "produit", "prix"}, clean_fuel),
    "market": ({"date", "city", "item", "quantity", "price"}, clean_market),
    "rent": ({"listing_id", "posted_at", "city", "rooms", "price"}, clean_rent),
}


def detect_source(columns: list[str]) -> str:
    cols = set(columns)
    for name, (required, _) in SOURCES.items():
        if required <= cols:
            return name
    raise ValueError(f"unrecognised file layout: columns {sorted(cols)}")


# --------------------------------------------------------------------------- monthly reduction


def robust_z(values: np.ndarray, floor: float = SPREAD_FLOOR) -> np.ndarray:
    """|x - median| / scale, with scale = max(1.4826 · MAD, floor · median).

    The floor matters when a month has a handful of near-identical samples (four pump notices):
    the MAD is then tiny and an ordinary 1% difference would look extreme. With the floor, a
    price within ±(OUTLIER_Z · floor) of the median is never an outlier, while a ×10 typo always is.
    """
    med = np.median(values)
    scale = max(1.4826 * np.median(np.abs(values - med)), floor * abs(med))
    if scale == 0:
        return np.zeros_like(values, dtype=float)
    return np.abs(values - med) / scale


def to_monthly(tidy: pd.DataFrame) -> tuple[pd.DataFrame, Counter]:
    """One row per (product, city, month): median price, sample count and IQR, outliers removed."""
    rejected: Counter = Counter()
    if tidy.empty:
        return pd.DataFrame(columns=["product", "city", "month", "price", "samples", "spread"]), rejected
    df = tidy.assign(month=tidy["date"].dt.to_period("M").dt.to_timestamp())
    keys = ["product", "city", "month"]
    z = df.groupby(keys)["price"].transform(lambda s: robust_z(s.to_numpy(dtype=float)))
    df = _reject(df, z > OUTLIER_Z, "outlier", rejected)
    grouped = df.groupby(keys)["price"]
    monthly = pd.DataFrame({
        "price": grouped.median(),
        "samples": grouped.size(),
        "spread": grouped.quantile(0.75) - grouped.quantile(0.25),
    }).reset_index()
    monthly[["price", "spread"]] = monthly[["price", "spread"]].round(2)
    return monthly, rejected
