from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render

from .models import City, IngestionRun, ModelRun, Observation


def home(request):
    return render(request, "prices/home.html", {
        "cities": City.objects.all(),
        "observations": Observation.objects.count(),
        "last_ingest": IngestionRun.objects.first(),
        "model": ModelRun.objects.first(),
    })


def health(request):
    with connection.cursor() as cur:
        cur.execute("SELECT 1")
    return JsonResponse({"status": "ok"})
