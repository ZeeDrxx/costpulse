from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from prices import forecast
from prices.analytics import observations_frame
from prices.models import City, Forecast, ModelRun, Product


class Command(BaseCommand):
    help = "Backtest and train the price forecasting model, then store forecasts for the next months."

    def add_arguments(self, parser):
        parser.add_argument("--horizon", type=int, default=3)
        parser.add_argument("--holdout", type=int, default=6, help="months hidden for the backtest")

    def handle(self, *args, **opts):
        obs = observations_frame()
        try:
            result = forecast.run(obs, horizon=opts["horizon"], holdout=opts["holdout"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        bt = result.backtest
        weights = bt["n"] / bt["n"].sum()
        with transaction.atomic():
            run = ModelRun.objects.create(
                algorithm=forecast.ALGORITHM,
                horizon=opts["horizon"],
                train_until=result.train_until.date(),
                series=result.series,
                mape=float((bt["mape"] * weights).sum()),
                naive_mape=float((bt["naive_mape"] * weights).sum()),
                details={"holdout_months": opts["holdout"], "by_horizon": bt.to_dict(orient="records")},
            )
            products = {p.slug: p for p in Product.objects.all()}
            cities = {c.slug: c for c in City.objects.all()}
            Forecast.objects.bulk_create([
                Forecast(run=run, product=products[r.product], city=cities[r.city], month=r.month.date(),
                         price=r.price, lower=r.lower, upper=r.upper)
                for r in result.forecasts.itertuples(index=False)
            ])

        for r in bt.itertuples(index=False):
            self.stdout.write(f"h={r.horizon}  MAPE {r.mape:5.2f}%   naive {r.naive_mape:5.2f}%   (n={r.n})")
        self.stdout.write(self.style.SUCCESS(f"{run}: {len(result.forecasts)} forecasts stored"))
