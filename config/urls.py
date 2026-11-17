from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "CostPulse admin"
admin.site.site_title = "CostPulse"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("prices.urls")),
]
