"""Reference data: the cities and products CostPulse tracks, and every alias seen in raw sources.

Raw files spell things many ways ("Casa", "Fès", "Fez", "Gasoil", "huile d'olive"…). Cleaning maps
them all to one slug. Unknown names are rejected and counted, never guessed.
"""

from __future__ import annotations

import unicodedata

# slug: (name, region, approx. population, lat, lon, aliases)
CITIES: dict[str, tuple[str, str, int, float, float, list[str]]] = {
    "casablanca": ("Casablanca", "Casablanca-Settat", 3_220_000, 33.573, -7.589, ["casa", "dar el beida", "dar al bayda"]),
    "rabat": ("Rabat", "Rabat-Salé-Kénitra", 520_000, 34.020, -6.841, []),
    "marrakech": ("Marrakech", "Marrakech-Safi", 1_000_000, 31.629, -7.981, ["marrakesh", "marrakech medina"]),
    "fes": ("Fes", "Fès-Meknès", 1_260_000, 34.033, -5.000, ["fez", "fès"]),
    "tangier": ("Tangier", "Tanger-Tétouan-Al Hoceïma", 1_270_000, 35.759, -5.834, ["tanger", "tangiers"]),
    "agadir": ("Agadir", "Souss-Massa", 480_000, 30.427, -9.598, []),
    "meknes": ("Meknes", "Fès-Meknès", 600_000, 33.895, -5.554, ["meknès", "miknas"]),
    "oujda": ("Oujda", "Oriental", 550_000, 34.681, -1.908, ["oujda angad"]),
}

# slug: (name, category, canonical unit, basket weight, aliases)
PRODUCTS: dict[str, tuple[str, str, str, float, list[str]]] = {
    "diesel": ("Diesel", "fuel", "L", 6, ["gasoil", "gazoil", "diesel 50ppm"]),
    "gasoline": ("Gasoline", "fuel", "L", 3, ["essence", "essence sans plomb", "super sans plomb", "petrol"]),
    "flour": ("Soft wheat flour", "food", "kg", 3, ["farine", "farine de blé tendre", "wheat flour"]),
    "sugar": ("Sugar", "food", "kg", 2, ["sucre", "sucre granulé"]),
    "vegetable-oil": ("Vegetable oil", "food", "L", 3, ["huile de table", "huile végétale", "table oil"]),
    "olive-oil": ("Olive oil", "food", "L", 2, ["huile d'olive", "huile dolive"]),
    "milk": ("Milk", "food", "L", 3, ["lait", "lait pasteurisé"]),
    "chicken": ("Chicken", "food", "kg", 3, ["poulet", "poulet vif", "chicken (live)"]),
    "beef": ("Beef", "food", "kg", 3, ["viande bovine", "boeuf", "bœuf"]),
    "tomatoes": ("Tomatoes", "fresh", "kg", 3, ["tomate", "tomates"]),
    "onions": ("Onions", "fresh", "kg", 2, ["oignon", "oignons"]),
    "potatoes": ("Potatoes", "fresh", "kg", 2, ["pomme de terre", "pommes de terre"]),
    "rent-2br": ("Rent, 2-room flat", "housing", "month", 25, ["rent 2 rooms", "loyer 2 pièces"]),
}

# Quantity units found in raw files → (canonical unit, factor to multiply the quantity by)
UNITS: dict[str, tuple[str, float]] = {
    "kg": ("kg", 1.0), "kilo": ("kg", 1.0), "g": ("kg", 0.001), "gr": ("kg", 0.001),
    "l": ("L", 1.0), "litre": ("L", 1.0), "liter": ("L", 1.0), "cl": ("L", 0.01), "ml": ("L", 0.001),
    "unit": ("unit", 1.0), "pièce": ("unit", 1.0), "piece": ("unit", 1.0),
    "month": ("month", 1.0), "mois": ("month", 1.0),
}


def normalize(text: object) -> str:
    """Lower-case, trim, collapse spaces, drop accents: 'Fès ' → 'fes'."""
    s = " ".join(str(text).strip().lower().replace("’", "'").split())
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _lookup(table: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for slug, row in table.items():
        for name in [slug, row[0], *row[-1]]:
            out[normalize(name)] = slug
            out[normalize(name).replace("-", " ")] = slug
    return out


CITY_LOOKUP = _lookup(CITIES)
PRODUCT_LOOKUP = _lookup(PRODUCTS)


def seed() -> None:
    """Create or update the City and Product rows. Safe to run any number of times."""
    from .models import City, Product

    for slug, (name, region, pop, lat, lon, _aliases) in CITIES.items():
        City.objects.update_or_create(
            slug=slug, defaults=dict(name=name, region=region, population=pop, latitude=lat, longitude=lon)
        )
    for slug, (name, category, unit, weight, _aliases) in PRODUCTS.items():
        Product.objects.update_or_create(
            slug=slug, defaults=dict(name=name, category=category, unit=unit, basket_weight=weight)
        )
