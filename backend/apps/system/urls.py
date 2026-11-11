from django.db.transaction import non_atomic_requests
from django.urls import path

from apps.system import views

urlpatterns = [
    path("system/client-config/", non_atomic_requests(views.ClientConfigView.as_view()), name="system-client-config"),
]
