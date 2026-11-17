from django.contrib import admin

from .models import City, Forecast, IngestionRun, ModelRun, Observation, Product


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "region", "population"]
    search_fields = ["name", "slug"]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "category", "unit", "basket_weight"]
    list_filter = ["category"]
    list_editable = ["basket_weight"]


@admin.register(Observation)
class ObservationAdmin(admin.ModelAdmin):
    list_display = ["month", "product", "city", "price", "samples", "spread"]
    list_filter = ["product__category", "product", "city"]
    date_hierarchy = "month"
    list_select_related = ["product", "city"]
    readonly_fields = ["run"]


@admin.register(IngestionRun)
class IngestionRunAdmin(admin.ModelAdmin):
    list_display = ["started_at", "source", "file_name", "rows_read", "rows_kept", "rows_rejected",
                    "observations_written"]
    list_filter = ["source"]
    readonly_fields = [f.name for f in IngestionRun._meta.fields]

    def has_add_permission(self, request):
        return False  # runs are created by `manage.py ingest`, never by hand


class ForecastInline(admin.TabularInline):
    model = Forecast
    extra = 0
    can_delete = False
    readonly_fields = ["product", "city", "month", "price", "lower", "upper"]
    max_num = 0


@admin.register(ModelRun)
class ModelRunAdmin(admin.ModelAdmin):
    list_display = ["trained_at", "algorithm", "horizon", "train_until", "series", "mape", "naive_mape"]
    readonly_fields = [f.name for f in ModelRun._meta.fields]
    inlines = [ForecastInline]

    def has_add_permission(self, request):
        return False
