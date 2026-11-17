-- Read-only login for Power BI: it can read the bi_* views and nothing else.
-- Run once, on the server:
--   docker compose exec -T db psql -U costpulse -d costpulse -v pw="'a-strong-password'" < deploy/powerbi_role.sql
CREATE ROLE powerbi LOGIN PASSWORD :pw;
GRANT CONNECT ON DATABASE costpulse TO powerbi;
GRANT USAGE ON SCHEMA public TO powerbi;
GRANT SELECT ON bi_dim_city, bi_dim_product, bi_fact_price, bi_fact_forecast, bi_ingestion_run, bi_model_run TO powerbi;
-- Views run with their owner's rights, so no grant on the prices_* tables is needed (or given).
