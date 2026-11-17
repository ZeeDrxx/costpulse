from django.urls import path

from . import api, views

urlpatterns = [
    path("", views.home, name="home"),
    path("api/", api.Root.as_view(), name="api-root"),
    path("api/cities/", api.CityList.as_view(), name="api-cities"),
    path("api/products/", api.ProductList.as_view(), name="api-products"),
    path("api/observations/", api.ObservationList.as_view(), name="api-observations"),
    path("api/index/", api.IndexView.as_view(), name="api-index"),
    path("api/inflation/latest/", api.LatestInflationView.as_view(), name="api-inflation-latest"),
    path("api/drivers/", api.DriversView.as_view(), name="api-drivers"),
    path("api/forecasts/", api.ForecastList.as_view(), name="api-forecasts"),
    path("api/model-runs/", api.ModelRunList.as_view(), name="api-model-runs"),
    path("api/ingestion-runs/", api.IngestionRunList.as_view(), name="api-ingestion-runs"),
    path("health/", views.health, name="health"),
]
