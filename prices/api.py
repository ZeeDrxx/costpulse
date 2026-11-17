"""REST API (Django REST Framework). Read-only: data only changes through the ingest pipeline."""

from __future__ import annotations

import re
from datetime import date

import pandas as pd
from rest_framework import generics, serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView

from . import analytics
from .models import City, Forecast, IngestionRun, ModelRun, Observation, Product


def _month(value: str | None, name: str) -> date | None:
    if not value:
        return None
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
        raise ValidationError({name: "expected YYYY-MM"})
    return date(int(value[:4]), int(value[5:]), 1)


def _city(slug: str | None) -> str | None:
    if slug and slug != "national" and not City.objects.filter(slug=slug).exists():
        raise NotFound(f"unknown city '{slug}'")
    return slug


# --------------------------------------------------------------------------- reference data


class CitySerializer(serializers.ModelSerializer):
    class Meta:
        model = City
        fields = ["slug", "name", "region", "population", "latitude", "longitude"]


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ["slug", "name", "category", "unit", "basket_weight"]


class CityList(generics.ListAPIView):
    queryset = City.objects.all()
    serializer_class = CitySerializer
    pagination_class = None


class ProductList(generics.ListAPIView):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    pagination_class = None


# --------------------------------------------------------------------------- prices


class ObservationSerializer(serializers.ModelSerializer):
    product = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    city = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    month = serializers.DateField(format="%Y-%m")

    class Meta:
        model = Observation
        fields = ["product", "city", "month", "price", "samples", "spread"]


class ObservationList(generics.ListAPIView):
    """Monthly median prices. Filters: ?city=, ?product=, ?from=YYYY-MM, ?to=YYYY-MM"""

    serializer_class = ObservationSerializer

    def get_queryset(self):
        p = self.request.query_params
        qs = Observation.objects.select_related("product", "city")
        if p.get("city"):
            qs = qs.filter(city__slug=p["city"])
        if p.get("product"):
            qs = qs.filter(product__slug=p["product"])
        if start := _month(p.get("from"), "from"):
            qs = qs.filter(month__gte=start)
        if end := _month(p.get("to"), "to"):
            qs = qs.filter(month__lte=end)
        return qs.order_by("product__slug", "city__slug", "month")


# --------------------------------------------------------------------------- index & inflation


def _records(df: pd.DataFrame) -> list[dict]:
    df = df.copy()
    for col in ("month", "base"):
        if col in df:
            df[col] = pd.to_datetime(df[col]).dt.strftime("%Y-%m")
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


class IndexView(APIView):
    """Price index (base = 100), month-on-month and year-on-year change.

    ?city=<slug> or ?city=national (default), ?from=YYYY-MM, ?to=YYYY-MM
    """

    def get(self, request):
        city = _city(request.query_params.get("city", "national"))
        start = _month(request.query_params.get("from"), "from")
        end = _month(request.query_params.get("to"), "to")
        obs = analytics.observations_frame(None if city == "national" else city)
        if obs.empty:
            return Response({"city": city, "series": []})
        by_city = analytics.city_index(obs)
        series = analytics.national_index(by_city) if city == "national" else by_city.drop(columns="city")
        if start:
            series = series[series["month"] >= pd.Timestamp(start)]
        if end:
            series = series[series["month"] <= pd.Timestamp(end)]
        return Response({"city": city, "series": _records(series)})


class LatestInflationView(APIView):
    """Latest month for every city and the national figure: index, MoM %, YoY %."""

    def get(self, request):
        obs = analytics.observations_frame()
        if obs.empty:
            return Response([])
        by_city = analytics.city_index(obs)
        latest = by_city.sort_values("month").groupby("city").tail(1)
        nat = analytics.national_index(by_city).tail(1).assign(city="national")
        cols = ["city", "month", "index", "mom", "yoy"]
        return Response(_records(pd.concat([nat[cols], latest[cols]], ignore_index=True)))


class DriversView(APIView):
    """Which products drove a city's year-on-year inflation. ?city=<slug>&month=YYYY-MM"""

    def get(self, request):
        city = _city(request.query_params.get("city"))
        if not city or city == "national":
            raise ValidationError({"city": "a city slug is required"})
        obs = analytics.observations_frame(city)
        month = _month(request.query_params.get("month"), "month") or obs["month"].max().date()
        try:
            table = analytics.drivers(obs, month)
        except ValueError as exc:
            raise ValidationError({"month": str(exc)}) from exc
        return Response({"city": city, "month": month.strftime("%Y-%m"), "drivers": _records(table)})


# --------------------------------------------------------------------------- forecasts & runs


class ForecastSerializer(serializers.ModelSerializer):
    product = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    city = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    month = serializers.DateField(format="%Y-%m")

    class Meta:
        model = Forecast
        fields = ["product", "city", "month", "price", "lower", "upper"]


class ForecastList(generics.ListAPIView):
    """Forecasts from the latest model run, with 80% intervals. Filters: ?city=, ?product="""

    serializer_class = ForecastSerializer

    def get_queryset(self):
        run = ModelRun.objects.first()
        if run is None:
            return Forecast.objects.none()
        qs = run.forecasts.select_related("product", "city")
        p = self.request.query_params
        if p.get("city"):
            qs = qs.filter(city__slug=p["city"])
        if p.get("product"):
            qs = qs.filter(product__slug=p["product"])
        return qs.order_by("product__slug", "city__slug", "month")


class ModelRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = ModelRun
        fields = ["id", "trained_at", "algorithm", "horizon", "train_until", "series", "mape", "naive_mape", "details"]


class ModelRunList(generics.ListAPIView):
    queryset = ModelRun.objects.all()
    serializer_class = ModelRunSerializer


class IngestionRunSerializer(serializers.ModelSerializer):
    rows_rejected = serializers.IntegerField(read_only=True)

    class Meta:
        model = IngestionRun
        fields = ["id", "source", "file_name", "started_at", "rows_read", "rows_kept", "rows_rejected",
                  "rejected", "observations_written"]


class IngestionRunList(generics.ListAPIView):
    queryset = IngestionRun.objects.all()
    serializer_class = IngestionRunSerializer


class Root(APIView):
    def get(self, request):
        names = ["cities", "products", "observations", "index", "inflation-latest", "drivers",
                 "forecasts", "model-runs", "ingestion-runs"]
        return Response({n: reverse(f"api-{n}", request=request) for n in names})
