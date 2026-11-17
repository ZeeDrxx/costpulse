# CostPulse

**A price observatory.** CostPulse takes raw, messy price data (pump price notices, weekly market
surveys, rental listings), cleans it, reduces it to one robust price per product, city and month,
builds a city-level inflation index, and forecasts the next three months. It serves everything
through a REST API, an admin, a small public page and a Power BI star schema.

> **Data note.** The repository ships a **synthetic** data generator. Its numbers are invented, though
> shaped after public reporting (the 2022 fuel spike, the 2023 vegetable spike, the 2024 olive-oil spike)
> and as messy as real exports. Every figure below comes from that sample. To track real prices, drop
> real files in the same layouts (see [Raw data](#raw-data)).

```
 raw CSVs ──► clean (Pandas) ──► monthly medians ──► index & inflation (NumPy) ──► REST API (DRF)
 fuel / market / rent   │              │                       │                      Django admin
                        └ rejects, by reason                   └─► forecasts (scikit-learn)  Power BI views
```

| | |
|---|---|
| **Stack** | Python 3.12 · Django 5.2 · Django REST Framework · Pandas · NumPy · scikit-learn · PostgreSQL 17 |
| **Runs on** | Docker Compose (local), one OVHcloud VPS with Caddy for HTTPS ([deploy guide](deploy/ovh.md)) |
| **BI** | Star-schema SQL views + DAX measures for Power BI ([powerbi/](powerbi/README.md)) |

## Quick start

```bash
docker compose up --build
```

On first start the container migrates, generates the sample data, ingests it and trains the forecasts
(about a minute). Then open:

- http://localhost:8000: latest inflation by city, index chart
- http://localhost:8000/api/: browsable REST API
- http://localhost:8000/admin/: after `docker compose exec web python manage.py createsuperuser`

Without Docker (SQLite):

```bash
uv sync
uv run python manage.py migrate
uv run python manage.py bootstrap_demo      # generate → ingest → train
uv run python manage.py runserver
```

## What the pipeline does

### 1. Clean ([`prices/pipeline/clean.py`](prices/pipeline/clean.py))

Each source has its own cleaner that returns tidy rows (`product, city, date, price`) and a count of
rejected rows by reason. Nothing is silently fixed.

| Problem in the raw data | Handling |
|---|---|
| `12,85 DH`, `4 500 DH`, `1.234,50`, `n/a` | `parse_price` → float or rejected as `bad_price` |
| `Casa`, `Fès`, `FEZ`, `Tanger` | alias table + accent folding → `casablanca`, `fes`, `tangier` |
| `Gasoil`, `huile d'olive`, `farine` | product aliases → `diesel`, `olive-oil`, `flour` |
| `500 g`, `50 cl`, `5 L` packs | converted to price per kg / L |
| milk sold "per kg" | `unit_mismatch` |
| items not tracked (saffron…) | `unknown_product` |
| the same rental listing posted three times | kept once (latest post), `duplicate_listing` |
| ×10 typos (`128,50` for `12,85`) | robust z-score per product/city/month → `outlier` |

The outlier test is `|x − median| / max(1.4826·MAD, 5% of median) > 3.5`. The 5% floor matters: four
pump notices that agree to the cent have a MAD near zero, and without the floor an ordinary 1%
difference would be thrown out.

On the sample data:

```
fuel_prices.csv   read  4,480  rejected    26  (bad_price=14, outlier=12)                → 1,120 monthly prices
market_survey.csv read 67,200  rejected   857  (bad_price=347, outlier=238, unit_mismatch=137, unknown_product=135) → 5,600
rent_listings.csv read 29,411  rejected 17,847 (not_2_rooms=15,596, duplicate_listing=2,111, outlier=140) → 563
```

### 2. Index and inflation ([`prices/analytics.py`](prices/analytics.py))

A fixed-base, fixed-weight basket per city (Laspeyres-type):

```
index_t = 100 · Σ w_i · (p_i,t / p_i,base) / Σ w_i
```

- A product missing in a month leaves both sums, so a gap doesn't read as a price drop.
- Months where less than 60% of the basket is priced are left out.
- The national index is the population-weighted mean of the city indices.
- `drivers()` splits a city's year-on-year inflation into each product's contribution in percentage points. The contributions add up to the headline number, which the tests check.

### 3. Forecasts ([`prices/forecast.py`](prices/forecast.py))

One pooled `HistGradientBoostingRegressor` per horizon (direct strategy):

- **Target:** the log price change.
- **Features:** the last three monthly changes, the 12-month change, the calendar month being predicted, and the product as a categorical feature, so it learns that tomatoes are seasonal and rent is not.
- **Backtest:** the last 6 months are held out, and the model is compared with the naive forecast "next month = this month".

| Horizon | Model MAPE | Naive MAPE |
|---|---|---|
| 1 month | 2.92% | 3.73% |
| 2 months | 3.44% | 5.24% |
| 3 months | 4.00% | 6.73% |

The forecasts have 80% intervals, taken from the 10th and 90th percentiles of the backtest errors.
Every training run is stored with its scores (`ModelRun`), so accuracy can be tracked over time.

## API

All endpoints are read-only JSON. Months are `YYYY-MM`.

| Endpoint | Returns |
|---|---|
| `GET /api/cities/`, `/api/products/` | reference data (products include basket weights) |
| `GET /api/observations/?city=&product=&from=&to=` | monthly median prices with sample count and IQR |
| `GET /api/index/?city=<slug>\|national&from=&to=` | index, month-on-month %, year-on-year % |
| `GET /api/inflation/latest/` | latest month for every city plus national |
| `GET /api/drivers/?city=&month=` | each product's contribution to YoY inflation |
| `GET /api/forecasts/?city=&product=` | latest run's forecasts with intervals |
| `GET /api/model-runs/`, `/api/ingestion-runs/` | training scores; import logs with rejection reasons |

```bash
curl "localhost:8000/api/drivers/?city=casablanca&month=2022-06"
# diesel +47% → 5.19 pp, gasoline +47% → 2.59 pp, vegetable oil +28% → 1.51 pp, …
```

## Raw data

`manage.py ingest <files or folders>` detects the layout from the header:

| Layout | Required columns | Example row |
|---|---|---|
| fuel | `date, ville, produit, prix` | `06/01/2021,Casablanca,Gasoil,"9,44 DH"` |
| market | `date, city, item, quantity, price` | `2021-01-01,Casa,farine,500 g,"2,30"` |
| rent | `listing_id, posted_at, city, rooms, price` | `L100000,2021-01-22,casa,2,4 350 DH` |

Cities and products, with every alias, live in [`prices/catalog.py`](prices/catalog.py). Re-importing a
month overwrites it, so a file can be corrected and loaded again.

## Power BI

A migration creates `bi_*` views (a star schema) that Power BI imports through a read-only `powerbi`
login. [`powerbi/README.md`](powerbi/README.md) has the connection steps (SSH tunnel to the VPS), the
relationships, the DAX measures ([`measures.dax`](powerbi/measures.dax)) and a page-by-page layout.

## Deployment

[`deploy/ovh.md`](deploy/ovh.md) covers the full path:

- an OVHcloud VPS with Ubuntu 24.04 and a firewall
- Docker
- `docker compose -f compose.yaml -f compose.prod.yaml up -d` (Caddy handles HTTPS)
- a monthly ingest cron job
- nightly `pg_dump` backups

PostgreSQL is never exposed publicly: Power BI reaches it through an SSH tunnel.

## Development

```bash
uv sync
uv run pytest            # 30 tests: parsers, cleaners, index maths, forecasts, API, SQL views
```

CI runs the tests against SQLite and PostgreSQL, then builds the Docker stack and smoke-tests the live API.

```
config/            Django settings (all environment-driven), URLs
prices/
  catalog.py       cities, products, aliases, units
  pipeline/        clean.py (Pandas/NumPy), ingest.py (DB upsert + run log)
  analytics.py     price index, national index, inflation drivers
  forecast.py      scikit-learn forecasting + backtest
  sample.py        synthetic raw data generator
  api.py           Django REST Framework views
  management/      ingest, train_forecasts, generate_sample, bootstrap_demo
  migrations/      0002 creates the bi_* views
powerbi/           DAX, theme, build guide
deploy/            OVH guide, Caddyfile, read-only Power BI role
```

## License

MIT
