from django.db.transaction import non_atomic_requests
from django.urls import path

from apps.system import views

urlpatterns = [
    path("system/client-config/", non_atomic_requests(views.ClientConfigView.as_view()), name="system-client-config"),
    # Fase 22
    path("system/notifications/", views.NotificationsView.as_view(), name="system-notifications"),
    path("system/appearance/", views.AppearanceView.as_view(), name="system-appearance"),
    path("system/appearance/me/", views.MyAppearanceView.as_view(), name="system-appearance-me"),  # Fase 23
    path("system/data/stats/", views.DataStatsView.as_view(), name="system-data-stats"),
    path("system/data/erd/", views.ErdView.as_view(), name="system-data-erd"),
    # Fase 25
    path("system/overview/", views.SystemOverviewView.as_view(), name="system-overview"),
    path("system/sessions/<int:pk>/close/", views.SessionCloseView.as_view(), name="system-session-close"),
    path("system/data/objects/", views.SqlObjectsView.as_view(), name="system-data-objects"),
]
