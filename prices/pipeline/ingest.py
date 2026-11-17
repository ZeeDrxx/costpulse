"""Load a raw CSV into the database: detect its layout, clean it, reduce it to months, upsert."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from django.db import transaction

from .. import catalog
from ..models import City, IngestionRun, Observation, Product
from .clean import SOURCES, detect_source, to_monthly


@dataclass
class IngestResult:
    run: IngestionRun
    source: str

    def summary(self) -> str:
        r = self.run
        reasons = ", ".join(f"{k}={v}" for k, v in sorted(r.rejected.items())) or "none"
        return (f"{r.file_name} [{self.source}]: read {r.rows_read}, kept {r.rows_kept}, "
                f"rejected {r.rows_rejected} ({reasons}) -> {r.observations_written} monthly prices")


def read_raw(path: Path) -> pd.DataFrame:
    # Everything as text: parsing is the cleaner's job, and pandas must not guess number formats.
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


@transaction.atomic
def ingest_file(path: str | Path) -> IngestResult:
    path = Path(path)
    catalog.seed()
    raw = read_raw(path)
    source = detect_source(list(raw.columns))
    tidy, rejected = SOURCES[source][1](raw)
    monthly, outliers = to_monthly(tidy)
    rejected = Counter(rejected) + outliers

    run = IngestionRun.objects.create(
        source=source,
        file_name=path.name,
        rows_read=len(raw),
        rows_kept=len(raw) - sum(rejected.values()),
        rejected=dict(rejected),
    )

    products = {p.slug: p for p in Product.objects.all()}
    cities = {c.slug: c for c in City.objects.all()}
    rows = [
        Observation(
            product=products[r.product],
            city=cities[r.city],
            month=r.month.date(),
            price=round(float(r.price), 2),
            samples=int(r.samples),
            spread=round(float(r.spread), 2),
            run=run,
        )
        for r in monthly.itertuples(index=False)
    ]
    Observation.objects.bulk_create(
        rows,
        batch_size=2000,
        update_conflicts=True,
        unique_fields=["product", "city", "month"],
        update_fields=["price", "samples", "spread", "run"],
    )
    run.observations_written = len(rows)
    run.save(update_fields=["observations_written"])
    return IngestResult(run=run, source=source)
