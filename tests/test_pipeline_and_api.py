"""End-to-end: synthetic raw files → ingest → index → forecasts → API."""

import pandas as pd
import pytest
from django.core.management import call_command

from prices import analytics, forecast
from prices.models import Forecast, IngestionRun, ModelRun, Observation
from prices.pipeline.ingest import ingest_file
from prices.sample import generate

pytestmark = pytest.mark.django_db


@pytest.fixture(scope="module")
def raw_files(tmp_path_factory):
    return generate(tmp_path_factory.mktemp("raw"), start="2021-01", end="2024-06", cities=["casablanca", "fes"])


@pytest.fixture
def loaded(raw_files):
    for path in raw_files.values():
        ingest_file(path)


def test_ingest_records_runs_and_monthly_prices(loaded):
    assert IngestionRun.objects.count() == 3
    # 2 cities × 42 months × 13 products, one price each; rent re-posts may spill into July
    assert Observation.objects.filter(month__lte="2024-06-01").count() == 2 * 42 * 13
    assert Observation.objects.filter(month__gt="2024-06-01").exclude(product__slug="rent-2br").count() == 0
    for run in IngestionRun.objects.all():
        assert run.rows_kept + run.rows_rejected == run.rows_read
    market = IngestionRun.objects.get(source="market")
    assert {"unknown_product", "unit_mismatch", "bad_price"} <= set(market.rejected)


def test_ingest_twice_updates_instead_of_duplicating(raw_files, loaded):
    before = Observation.objects.count()
    ingest_file(raw_files["fuel"])
    assert Observation.objects.count() == before


def test_index_starts_at_100_and_tracks_inflation(loaded):
    idx = analytics.city_index(analytics.observations_frame())
    first = idx.sort_values("month").groupby("city").head(1)
    assert (first["index"] == 100).all()
    # every month with an index is fully priced; the partial rent-only month is dropped at the end
    assert idx.dropna(subset=["index"])["coverage"].min() == pytest.approx(1.0)
    assert idx["month"].max() == pd.Timestamp("2024-06-01")
    # the synthetic 2022 fuel spike lifts year-on-year inflation well above zero in mid-2022
    mid_2022 = idx[idx["month"] == "2022-06-01"]
    assert (mid_2022["yoy"] > 3).all()


def test_drivers_add_up_to_yoy(loaded):
    obs = analytics.observations_frame("fes")
    idx = analytics.city_index(obs).set_index("month")
    table = analytics.drivers(obs, pd.Timestamp("2023-03-01").date())
    assert table["contribution_pp"].sum() == pytest.approx(idx.loc["2023-03-01", "yoy"], abs=0.05)


def test_national_index_is_population_weighted(loaded):
    by_city = analytics.city_index(analytics.observations_frame())
    nat = analytics.national_index(by_city).set_index("month")
    month = by_city["month"].max()
    pair = by_city[by_city["month"] == month].set_index("city")["index"]
    lo, hi = sorted(pair)
    assert lo <= nat.loc[month, "index"] <= hi
    # Casablanca (3.2M) outweighs Fes (1.26M)
    assert abs(nat.loc[month, "index"] - pair["casablanca"]) < abs(nat.loc[month, "index"] - pair["fes"])


def test_forecast_backtest_and_horizons(loaded):
    result = forecast.run(analytics.observations_frame(), horizon=2, holdout=4)
    assert set(result.backtest["horizon"]) == {1, 2}
    assert len(result.forecasts) == 2 * 13 * 2
    f = result.forecasts
    assert (f["lower"] <= f["price"]).all() and (f["price"] <= f["upper"]).all()
    assert f["month"].min() == pd.Timestamp("2024-07-01")


def test_train_command_stores_run(loaded):
    call_command("train_forecasts", horizon=1, holdout=4, verbosity=0)
    run = ModelRun.objects.get()
    assert run.series == 26 and Forecast.objects.filter(run=run).count() == 26
    assert run.naive_mape > 0


# --------------------------------------------------------------------------- API


def test_api_root_and_reference(client, loaded):
    assert set(client.get("/api/").json()) >= {"cities", "index", "forecasts"}
    cities = client.get("/api/cities/").json()
    assert {c["slug"] for c in cities} >= {"casablanca", "fes"}


def test_api_observations_filters(client, loaded):
    body = client.get("/api/observations/?city=fes&product=diesel&from=2022-01&to=2022-12").json()
    assert body["count"] == 12
    assert body["results"][0] == {**body["results"][0], "product": "diesel", "city": "fes", "month": "2022-01"}


def test_api_index_national_and_city(client, loaded):
    nat = client.get("/api/index/").json()
    assert nat["city"] == "national" and nat["series"][0]["index"] == 100
    fes = client.get("/api/index/?city=fes&from=2024-01").json()
    assert fes["series"][0]["month"] == "2024-01" and len(fes["series"]) == 6


def test_api_latest_and_drivers(client, loaded):
    latest = client.get("/api/inflation/latest/").json()
    assert latest[0]["city"] == "national" and len(latest) == 3
    drivers = client.get("/api/drivers/?city=casablanca&month=2023-03").json()
    assert drivers["month"] == "2023-03" and len(drivers["drivers"]) == 13


def test_api_errors(client, loaded):
    assert client.get("/api/index/?city=atlantis").status_code == 404
    assert client.get("/api/observations/?from=March").status_code == 400
    assert client.get("/api/drivers/?city=fes&month=2021-03").status_code == 400  # no year-ago data


def test_api_forecasts_and_home(client, loaded):
    assert client.get("/api/forecasts/").json()["count"] == 0
    call_command("train_forecasts", horizon=1, holdout=4, verbosity=0)
    assert client.get("/api/forecasts/?city=fes").json()["count"] == 13
    page = client.get("/")
    assert page.status_code == 200 and b"CostPulse" in page.content
    assert client.get("/health/").json() == {"status": "ok"}


def test_bi_views_exist(loaded):
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM bi_fact_price")
        assert cur.fetchone()[0] == Observation.objects.count()
        cur.execute("SELECT COUNT(*) FROM bi_dim_product")
        assert cur.fetchone()[0] == 13
