"""Forecast the next months of every (product, city) price series with scikit-learn.

Approach
- One pooled model per horizon h (direct strategy, no recursion). The target is the log change
  log(p[t+h] / p[t]), so a 2 MAD tomato and a 5,000 MAD rent share one model.
- Features at the forecast origin t: the last three monthly log changes, the 12-month log
  change, the calendar month being predicted (sin/cos) and the product as a categorical
  feature, which lets the model learn seasonal patterns per product.
- Backtest: the last `holdout` months are hidden. The model is compared with the naive
  forecast p[t+h] = p[t], the baseline any forecast has to beat.
- Intervals: the 10th and 90th percentiles of backtest errors, per horizon.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

FEATURES = ["r1", "r2", "r3", "r12", "month_sin", "month_cos", "product_code"]
ALGORITHM = "HistGradientBoostingRegressor (direct, log-change target)"


@dataclass
class ForecastResult:
    forecasts: pd.DataFrame        # product, city, month, price, lower, upper
    backtest: pd.DataFrame         # per horizon: mape, naive_mape, n
    train_until: pd.Timestamp
    series: int


def panel(observations: pd.DataFrame) -> pd.DataFrame:
    """Regular monthly series per (product, city) with lag features. Gaps of one month are filled."""
    frames = []
    for (product, city), part in observations.groupby(["product", "city"]):
        s = part.set_index("month")["price"].sort_index()
        s = s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="MS")).ffill(limit=1)
        logp = np.log(s)
        frames.append(pd.DataFrame({
            "product": product,
            "city": city,
            "month": s.index,
            "price": s.to_numpy(),
            "logp": logp.to_numpy(),
            "r1": logp.diff(1).to_numpy(),
            "r2": logp.diff(1).shift(1).to_numpy(),
            "r3": logp.diff(1).shift(2).to_numpy(),
            "r12": logp.diff(12).to_numpy(),
        }))
    df = pd.concat(frames, ignore_index=True)
    df["product_code"] = df["product"].astype("category").cat.codes
    return df


def _supervised(df: pd.DataFrame, h: int) -> pd.DataFrame:
    """Rows usable as training examples for horizon h (target known)."""
    g = df.groupby(["product", "city"], sort=False)
    out = df.assign(
        target=g["logp"].shift(-h) - df["logp"],
        target_month=df["month"] + pd.DateOffset(months=h),
        future_price=g["price"].shift(-h),
    )
    return _calendar(out)


def _calendar(df: pd.DataFrame) -> pd.DataFrame:
    m = df["target_month"].dt.month
    return df.assign(month_sin=np.sin(2 * np.pi * m / 12), month_cos=np.cos(2 * np.pi * m / 12))


def _model() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        max_iter=300, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=20,
        l2_regularization=1.0, categorical_features=[FEATURES.index("product_code")], random_state=0,
    )


def mape(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.mean(np.abs(predicted / actual - 1)) * 100)


def run(observations: pd.DataFrame, horizon: int = 3, holdout: int = 6) -> ForecastResult:
    if observations.empty:
        raise ValueError("no observations to forecast from")
    df = panel(observations)
    # The latest month most series have reached. A straggler (one re-posted listing landing in a
    # month nobody else has reported yet) must not decide where every forecast starts.
    n_series = df.groupby(["product", "city"]).ngroups
    per_month = df.groupby("month").size()
    last = per_month[per_month >= 0.5 * n_series].index.max()
    df = df[df["month"] <= last]
    cutoff = last - pd.DateOffset(months=holdout)

    backtest, forecasts = [], []
    for h in range(1, horizon + 1):
        sup = _supervised(df, h).dropna(subset=FEATURES + ["target"])
        train = sup[sup["target_month"] <= cutoff]
        test = sup[sup["target_month"] > cutoff]
        if len(train) < 50 or test.empty:
            raise ValueError(f"not enough history for horizon {h} (train={len(train)}, test={len(test)})")

        model = _model().fit(train[FEATURES], train["target"])
        pred = test["price"].to_numpy() * np.exp(model.predict(test[FEATURES]))
        actual = test["future_price"].to_numpy()
        log_err = np.log(actual / pred)
        q_lo, q_hi = np.quantile(log_err, [0.1, 0.9])
        backtest.append({
            "horizon": h, "n": len(test),
            "mape": mape(actual, pred), "naive_mape": mape(actual, test["price"].to_numpy()),
        })

        # Refit on everything and forecast from the last observed month of each series.
        final = _model().fit(sup[FEATURES], sup["target"])
        origin = _calendar(
            df[df["month"] == last].assign(target_month=last + pd.DateOffset(months=h))
        ).dropna(subset=FEATURES)
        centre = origin["price"].to_numpy() * np.exp(final.predict(origin[FEATURES]))
        forecasts.append(pd.DataFrame({
            "product": origin["product"].to_numpy(),
            "city": origin["city"].to_numpy(),
            "month": origin["target_month"].to_numpy(),
            "price": centre,
            "lower": centre * np.exp(q_lo),
            "upper": centre * np.exp(q_hi),
        }))

    fc = pd.concat(forecasts, ignore_index=True).round({"price": 2, "lower": 2, "upper": 2})
    bt = pd.DataFrame(backtest).round({"mape": 2, "naive_mape": 2})
    return ForecastResult(fc, bt, last, df.groupby(["product", "city"]).ngroups)
