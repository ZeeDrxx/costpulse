"""Data model.

Raw rows are messy and many (weekly market surveys, fuel notices, rent listings). After cleaning,
each (product, city, month) keeps one robust price: the median of the valid samples. That monthly
grain is what the index, the forecasts, the API and Power BI all work from.
"""

from django.db import models


class City(models.Model):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=80)
    region = models.CharField(max_length=80, blank=True)
    population = models.PositiveIntegerField(null=True, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "cities"

    def __str__(self) -> str:
        return self.name


class Category(models.TextChoices):
    FUEL = "fuel", "Fuel"
    FOOD = "food", "Food staples"
    FRESH = "fresh", "Fresh produce"
    HOUSING = "housing", "Housing"


class Product(models.Model):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=80)
    category = models.CharField(max_length=16, choices=Category.choices)
    unit = models.CharField(max_length=16, help_text="Canonical unit every price is converted to: kg, L, unit, month")
    basket_weight = models.FloatField(
        default=1.0, help_text="Share of a typical household budget, used by the price index (relative)."
    )

    class Meta:
        ordering = ["category", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.unit})"


class IngestionRun(models.Model):
    """One import of one raw file: what was read, kept and rejected, and why."""

    source = models.CharField(max_length=40)
    file_name = models.CharField(max_length=255)
    started_at = models.DateTimeField(auto_now_add=True)
    rows_read = models.PositiveIntegerField(default=0)
    rows_kept = models.PositiveIntegerField(default=0)
    rejected = models.JSONField(default=dict, help_text="Rejected row counts by reason")
    observations_written = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.source} · {self.file_name}"

    @property
    def rows_rejected(self) -> int:
        return sum(self.rejected.values())


class Observation(models.Model):
    """Median price of a product in a city for one month."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="observations")
    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name="observations")
    month = models.DateField(help_text="First day of the month")
    price = models.DecimalField(max_digits=12, decimal_places=2, help_text="MAD per canonical unit")
    samples = models.PositiveIntegerField(help_text="Valid raw samples behind the median")
    spread = models.DecimalField(
        max_digits=12, decimal_places=2, help_text="Interquartile range of the samples (MAD)"
    )
    run = models.ForeignKey(IngestionRun, null=True, on_delete=models.SET_NULL, related_name="observations")

    class Meta:
        ordering = ["month"]
        constraints = [
            models.UniqueConstraint(fields=["product", "city", "month"], name="one_price_per_product_city_month")
        ]
        indexes = [models.Index(fields=["city", "month"]), models.Index(fields=["product", "month"])]

    def __str__(self) -> str:
        return f"{self.product.slug} · {self.city.slug} · {self.month:%Y-%m}: {self.price}"


class ModelRun(models.Model):
    """One training of the forecasting model, with its backtest against a naive baseline."""

    trained_at = models.DateTimeField(auto_now_add=True)
    algorithm = models.CharField(max_length=80)
    horizon = models.PositiveSmallIntegerField()
    train_until = models.DateField()
    series = models.PositiveIntegerField()
    mape = models.FloatField(help_text="Backtest MAPE of the model, %")
    naive_mape = models.FloatField(help_text="Backtest MAPE of 'next month = this month', %")
    details = models.JSONField(default=dict)

    class Meta:
        ordering = ["-trained_at"]

    def __str__(self) -> str:
        return f"{self.algorithm} @ {self.trained_at:%Y-%m-%d}: {self.mape:.2f}% vs naive {self.naive_mape:.2f}%"


class Forecast(models.Model):
    run = models.ForeignKey(ModelRun, on_delete=models.CASCADE, related_name="forecasts")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    city = models.ForeignKey(City, on_delete=models.CASCADE)
    month = models.DateField()
    price = models.DecimalField(max_digits=12, decimal_places=2)
    lower = models.DecimalField(max_digits=12, decimal_places=2)
    upper = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["month"]
        constraints = [
            models.UniqueConstraint(fields=["run", "product", "city", "month"], name="one_forecast_per_run_point")
        ]
