"""Price index and inflation from monthly observations.

Index method: fixed-base, fixed-weight basket (Laspeyres-type), per city.

    index_t = 100 · Σ w_i · (p_i,t / p_i,base) / Σ w_i        over products priced in month t

w_i is the product's basket weight. When a product is missing in a month its weight is left out
of both sums for that month (so a gap doesn't read as a price drop); `coverage` reports the
share of basket weight that was actually priced. Months below MIN_COVERAGE are left out: with
only rent priced, say, the "index" would just be rent. The national index is the population-weighted
mean of city indices.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .models import City, Observation, Product

MIN_COVERAGE = 0.6


def observations_frame(city: str | None = None, product: str | None = None) -> pd.DataFrame:
    qs = Observation.objects.all()
    if city:
        qs = qs.filter(city__slug=city)
    if product:
        qs = qs.filter(product__slug=product)
    rows = qs.values_list("product__slug", "city__slug", "month", "price")
    df = pd.DataFrame(list(rows), columns=["product", "city", "month", "price"])
    df["month"] = pd.to_datetime(df["month"])
    df["price"] = df["price"].astype(float)
    return df


def _weights() -> pd.Series:
    return pd.Series(dict(Product.objects.values_list("slug", "basket_weight")), dtype=float)


def _relatives(prices: pd.DataFrame, base: pd.Timestamp | None) -> tuple[pd.DataFrame, pd.Timestamp]:
    """prices: month × product. Returns price relatives to the base month and the base used."""
    full = prices.dropna(axis=0, how="any")
    if base is None:
        if full.empty:
            raise ValueError("no month has a price for every product; pass a base month explicitly")
        base = full.index.min()
    base_prices = prices.loc[base]
    priced = base_prices.dropna().index
    return prices[priced] / base_prices[priced], base


def city_index(df: pd.DataFrame, weights: pd.Series | None = None, base: date | None = None) -> pd.DataFrame:
    """Index, month-on-month and year-on-year change for each city in `df`."""
    weights = _weights() if weights is None else weights
    out = []
    for city, part in df.groupby("city"):
        prices = part.pivot_table(index="month", columns="product", values="price")
        months = pd.date_range(prices.index.min(), prices.index.max(), freq="MS")
        prices = prices.reindex(months)
        rel, base_used = _relatives(prices, pd.Timestamp(base) if base else None)
        w = weights.reindex(rel.columns).fillna(0).to_numpy()
        values = rel.to_numpy()
        present = ~np.isnan(values)
        num = np.nansum(values * w, axis=1)
        den = (present * w).sum(axis=1)
        index = np.where(den > 0, 100 * num / np.where(den > 0, den, 1), np.nan)
        frame = pd.DataFrame({
            "city": city,
            "month": months,
            "index": index,
            "coverage": den / w.sum(),
        })
        frame.loc[frame["coverage"] < MIN_COVERAGE, "index"] = np.nan
        frame = frame[frame["index"].notna() | (frame["month"] < frame.loc[frame["index"].notna(), "month"].max())]
        frame["mom"] = frame["index"].pct_change(1, fill_method=None) * 100
        frame["yoy"] = frame["index"].pct_change(12, fill_method=None) * 100
        frame["base"] = base_used
        out.append(frame)
    if not out:
        return pd.DataFrame(columns=["city", "month", "index", "coverage", "mom", "yoy", "base"])
    return pd.concat(out, ignore_index=True).round({"index": 2, "coverage": 3, "mom": 2, "yoy": 2})


def national_index(by_city: pd.DataFrame) -> pd.DataFrame:
    """Population-weighted mean of city indices."""
    pop = pd.Series(dict(City.objects.values_list("slug", "population")), dtype=float)
    df = by_city.assign(pop=by_city["city"].map(pop).fillna(0))
    df = df[df["index"].notna() & (df["pop"] > 0)]
    nat = (
        df.assign(wi=df["index"] * df["pop"])
        .groupby("month")[["wi", "pop"]].sum()
        .pipe(lambda g: (g["wi"] / g["pop"]).rename("index"))
        .reset_index()
    )
    nat["mom"] = nat["index"].pct_change(1, fill_method=None) * 100
    nat["yoy"] = nat["index"].pct_change(12, fill_method=None) * 100
    return nat.round({"index": 2, "mom": 2, "yoy": 2})


def drivers(df: pd.DataFrame, month: date, weights: pd.Series | None = None) -> pd.DataFrame:
    """Contribution of each product to one city's year-on-year inflation, in percentage points.

    contribution_i = 100 · w_i · (rel_i,t − rel_i,t−12) / Σw / (index_t−12 / 100)
    The contributions add up to the city's YoY change (when every product is priced in both months).
    """
    weights = _weights() if weights is None else weights
    prices = df.pivot_table(index="month", columns="product", values="price")
    t, t12 = pd.Timestamp(month), pd.Timestamp(month) - pd.DateOffset(months=12)
    if t not in prices.index or t12 not in prices.index:
        raise ValueError("need prices for the month and the same month a year earlier")
    rel, _ = _relatives(prices, None)
    both = rel.loc[[t, t12]].dropna(axis=1)
    w = weights.reindex(both.columns).fillna(0)
    index_prev = 100 * (both.loc[t12] * w).sum() / w.sum()
    contrib = 100 * w * (both.loc[t] - both.loc[t12]) / w.sum() / (index_prev / 100)
    out = pd.DataFrame({
        "product": both.columns,
        "price": prices.loc[t, both.columns].to_numpy(),
        "price_year_ago": prices.loc[t12, both.columns].to_numpy(),
        "change_pct": ((prices.loc[t, both.columns] / prices.loc[t12, both.columns] - 1) * 100).to_numpy(),
        "contribution_pp": contrib.to_numpy(),
    })
    return out.sort_values("contribution_pp", ascending=False, key=np.abs).round(2).reset_index(drop=True)
