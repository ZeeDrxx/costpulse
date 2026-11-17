import numpy as np
import pandas as pd
import pytest

from prices.catalog import CITY_LOOKUP, PRODUCT_LOOKUP, normalize
from prices.pipeline.clean import (
    clean_fuel, clean_market, clean_rent, detect_source, map_names, parse_price, parse_quantity, robust_z,
    to_monthly,
)


@pytest.mark.parametrize("raw, expected", [
    ("12,85 DH", 12.85), ("4 500 DH", 4500), ("4 500", 4500), ("1.234,50", 1234.5),
    ("9.40", 9.40), ("15 MAD", 15), ("n/a", np.nan), ("", np.nan),
])
def test_parse_price(raw, expected):
    got = parse_price(pd.Series([raw]))[0]
    assert (np.isnan(got) and np.isnan(expected)) or got == pytest.approx(expected)


def test_parse_quantity_converts_to_canonical_units():
    qty, unit = parse_quantity(pd.Series(["500 g", "2 kg", "50 cl", "1 L", "3 boxes", "kg"]))
    assert qty[:4].tolist() == pytest.approx([0.5, 2, 0.5, 1])
    assert unit[:4].tolist() == ["kg", "kg", "L", "L"]
    assert np.isnan(qty[4]) and np.isnan(qty[5])


def test_names_map_through_aliases_and_accents():
    assert normalize("  FÈS ") == "fes"
    cities = map_names(pd.Series(["Casa", "Fez", "Tanger", " MEKNÈS ", "Paris"]), CITY_LOOKUP)
    assert cities[:4].tolist() == ["casablanca", "fes", "tangier", "meknes"] and pd.isna(cities[4])
    products = map_names(pd.Series(["Gasoil", "huile d'olive", "Huile d’olive", "olive-oil"]), PRODUCT_LOOKUP)
    assert products.tolist() == ["diesel", "olive-oil", "olive-oil", "olive-oil"]


def test_detect_source():
    assert detect_source(["date", "ville", "produit", "prix"]) == "fuel"
    assert detect_source(["date", "city", "item", "quantity", "price", "vendor"]) == "market"
    with pytest.raises(ValueError):
        detect_source(["a", "b"])


def test_clean_fuel_counts_every_rejection():
    raw = pd.DataFrame({
        "date": ["01/03/2024", "02/03/2024", "2024-03-03", "04/03/2024", "05/03/2024"],
        "ville": ["Casa", "Atlantis", "Rabat", "Rabat", "Rabat"],
        "produit": ["Gasoil", "Gasoil", "Gasoil", "Sucre", "Essence"],
        "prix": ["12,85 DH", "12,00 DH", "12,10 DH", "6,00 DH", "-1"],
    })
    tidy, rejected = clean_fuel(raw)
    assert tidy[["product", "city"]].values.tolist() == [["diesel", "casablanca"]]
    assert tidy["price"].iloc[0] == pytest.approx(12.85)
    assert rejected == {"unknown_city": 1, "bad_date": 1, "not_a_fuel": 1, "non_positive_price": 1}


def test_clean_market_prices_per_canonical_unit():
    raw = pd.DataFrame({
        "date": ["2024-03-01"] * 4,
        "city": ["Casablanca"] * 4,
        "item": ["farine", "lait", "lait", "Saffron"],
        "quantity": ["500 g", "50 cl", "1 kg", "1 g"],
        "price": ["2,40", "4.00", "8", "50"],
    })
    tidy, rejected = clean_market(raw)
    assert tidy.set_index("product")["price"].to_dict() == pytest.approx({"flour": 4.8, "milk": 8.0})
    assert rejected == {"unit_mismatch": 1, "unknown_product": 1}


def test_clean_rent_keeps_latest_post_of_two_room_flats():
    raw = pd.DataFrame({
        "listing_id": ["A", "A", "B", "C"],
        "posted_at": ["2024-03-02", "2024-03-20", "2024-03-05", "2024-03-06"],
        "city": ["Rabat"] * 4,
        "rooms": ["2", "2", "3", "2"],
        "price": ["4 000 DH", "3 900 DH", "6 000", "4 200"],
    })
    tidy, rejected = clean_rent(raw)
    assert sorted(tidy["price"].tolist()) == [3900, 4200]
    assert rejected == {"duplicate_listing": 1, "not_2_rooms": 1}


def test_robust_z_floor_protects_small_tight_groups():
    tight = np.array([12.80, 12.85, 12.85, 12.90, 13.30])  # +3.5%: ordinary, not an outlier
    assert (robust_z(tight) < 3.5).all()
    typo = np.array([12.80, 12.85, 12.90, 128.5])
    assert robust_z(typo)[-1] > 3.5


def test_to_monthly_median_count_and_outliers():
    tidy = pd.DataFrame({
        "product": ["diesel"] * 5,
        "city": ["rabat"] * 5,
        "date": pd.to_datetime(["2024-03-01", "2024-03-08", "2024-03-15", "2024-03-22", "2024-04-01"]),
        "price": [12.0, 12.2, 120.0, 12.1, 12.5],
    })
    monthly, rejected = to_monthly(tidy)
    march = monthly[monthly["month"] == "2024-03-01"].iloc[0]
    assert march["price"] == pytest.approx(12.1) and march["samples"] == 3
    assert rejected == {"outlier": 1}
    assert len(monthly) == 2
