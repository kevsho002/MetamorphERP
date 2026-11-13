"""Rutas raíz: API REST versionada, admin de Django y SPA de React (catch-all al final)."""

from django.contrib import admin
from django.db.transaction import non_atomic_requests
from django.urls import include, path, re_path

from apps.health.views import DatabaseHealthView, LivenessView
from apps.web.views import api_not_found, spa_index

api_v1 = [
    path("health", non_atomic_requests(LivenessView.as_view()), name="health"),
    path("health/db", non_atomic_requests(DatabaseHealthView.as_view()), name="health-db"),
    path("", include("apps.accounts.urls")),
    path("", include("apps.employees.urls")),
    path("", include("apps.system.urls")),
    path("", include("apps.roster.urls")),
    path("", include("apps.operations.urls")),
    path("", include("apps.general_ids.urls")),
    path("", include("apps.scheduling.urls")),
    path("", include("apps.personnel_actions.urls")),
    path("", include("apps.acd.urls")),
    path("", include("apps.adherence.urls")),
    path("", include("apps.payroll.urls")),
    path("", include("apps.holidays.urls")),  # Fase 21: calendario de feriados
]

admin.site.site_header = "Metamorph ERP — Administración"
admin.site.site_title = "Metamorph ERP"
admin.site.index_title = "Panel de administración"

urlpatterns = [
    path("api/v1/", include(api_v1)),
    re_path(r"^api/", api_not_found),  # /api/* desconocido -> 404 JSON (nunca el SPA)
    path("admin/", admin.site.urls),
    re_path(r"^(?!static/).*$", spa_index),  # rutas de React Router
]
