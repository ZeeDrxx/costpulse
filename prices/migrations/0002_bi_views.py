"""Star-schema views for Power BI (and any SQL client).

Power BI connects to these views, not to the Django tables, so the report survives
schema changes in the app as long as the views keep their columns.
Plain SQL that runs on both PostgreSQL and SQLite.
"""

from django.db import migrations

VIEWS = {
    "bi_dim_city": """
        SELECT id AS city_id, slug, name, region, population, latitude, longitude
        FROM prices_city""",
    "bi_dim_product": """
        SELECT id AS product_id, slug, name, category, unit, basket_weight
        FROM prices_product""",
    "bi_fact_price": """
        SELECT o.id AS price_id, o.product_id, o.city_id, o.month,
               o.price, o.samples, o.spread
        FROM prices_observation o""",
    "bi_fact_forecast": """
        SELECT f.id AS forecast_id, f.product_id, f.city_id, f.month,
               f.price, f.lower, f.upper, f.run_id
        FROM prices_forecast f
        WHERE f.run_id = (SELECT id FROM prices_modelrun ORDER BY trained_at DESC LIMIT 1)""",
    "bi_ingestion_run": """
        SELECT id AS run_id, source, file_name, started_at, rows_read, rows_kept,
               rows_read - rows_kept AS rows_rejected, observations_written
        FROM prices_ingestionrun""",
    "bi_model_run": """
        SELECT id AS model_run_id, trained_at, algorithm, horizon, train_until, series, mape, naive_mape
        FROM prices_modelrun""",
}


class Migration(migrations.Migration):
    dependencies = [("prices", "0001_initial")]

    operations = [
        migrations.RunSQL(sql=f"CREATE VIEW {name} AS {body}", reverse_sql=f"DROP VIEW IF EXISTS {name}")
        for name, body in VIEWS.items()
    ]
