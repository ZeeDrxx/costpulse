# Power BI report

The report reads the **star-schema views** that a Django migration creates
([`prices/migrations/0002_bi_views.py`](../prices/migrations/0002_bi_views.py)), never the app tables.
The app can change its tables freely as long as the views keep their columns.

```
            bi_dim_city ─┐             ┌─ bi_dim_product
                         ▼             ▼
   Months ──────────► bi_fact_price ◄──┘        bi_ingestion_run   (data quality)
      │                                         bi_model_run       (forecast accuracy)
      └───────────► bi_fact_forecast   (latest model run only)
```

| View | Grain | Key columns |
|---|---|---|
| `bi_fact_price` | product × city × month | `price` (MAD, median of samples), `samples`, `spread` (IQR) |
| `bi_fact_forecast` | product × city × future month | `price`, `lower`, `upper` (80% interval) |
| `bi_dim_city` | city | `name`, `region`, `population`, `latitude`, `longitude` |
| `bi_dim_product` | product | `name`, `category`, `unit`, `basket_weight` |
| `bi_ingestion_run` | imported file | `rows_read`, `rows_rejected`, `observations_written` |
| `bi_model_run` | training run | `mape`, `naive_mape` |

## 1. Connect

**Local stack** (`docker compose up`): PostgreSQL listens on `localhost:5432`.

**Server**: the database port is bound to the server's `127.0.0.1` only, so open an SSH tunnel first:

```bash
ssh -N -L 5433:127.0.0.1:5432 deploy@your-server
```

Then connect to `localhost:5433` with the read-only `powerbi` login
(created by [`deploy/powerbi_role.sql`](../deploy/powerbi_role.sql); it can only read the `bi_*` views).

In Power BI Desktop: **Get data → PostgreSQL database**. Server `localhost:5432` (or `localhost:5433`),
database `costpulse`, mode **Import**. Select the six `bi_*` views.

## 2. Model

1. Rename the queries if you like (`bi_fact_price` → `Prices`…). The DAX below uses the view names.
2. **Modeling → New table**, paste `Months` from [`measures.dax`](measures.dax). Sort `Month label` by `Month sort`.
3. Relationships (Model view, all single direction, many-to-one):
   - `bi_fact_price[product_id]` → `bi_dim_product[product_id]`
   - `bi_fact_price[city_id]` → `bi_dim_city[city_id]`
   - `bi_fact_price[month]` → `Months[month]`
   - the same three for `bi_fact_forecast`
4. Paste every measure from [`measures.dax`](measures.dax) (**New measure**, one at a time).
   Format `%` measures as percentages, prices as decimal numbers with 2 places.
5. Set `bi_dim_city[latitude]` / `[longitude]` data categories to Latitude / Longitude.
6. **View → Themes → Browse for themes** → [`theme.json`](theme.json).

## 3. Pages

| Page | Visuals |
|---|---|
| **Overview** | Cards: `National YoY %`, `Latest Month`, `Model MAPE %` vs `Naive MAPE %`. Line: `National Index` by `Months[Month label]`. Map: bubble size `Index YoY %` by city. |
| **Cities** | Slicer `bi_dim_city[name]`. Line: `Price Index` by month. Matrix: product rows × `Price YoY %`, `Avg Price`, conditional colour on YoY. |
| **Products** | Slicer `bi_dim_product[category]`. Small multiples line: `Avg Price` by month, split by product. |
| **Forecast** | Slicers city + product. Line: `Price (actual + forecast)` with an error band from `Forecast Lower` / `Forecast Upper`. Table of `bi_fact_forecast`. |
| **Data quality** | Clustered bar: `Rows Read` vs `Rows Rejected` by `bi_ingestion_run[source]`. Card: `Rejection Rate`. Table of model runs. |

## 4. Check the numbers

`Price Index` uses the same method as the API, so pick a city and a month in Power BI and compare with:

```bash
curl "http://localhost:8000/api/index/?city=casablanca&from=2026-01&to=2026-01"
```

The two should match to the second decimal. If they don't, a relationship is probably missing or bidirectional.
