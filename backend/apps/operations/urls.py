from django.urls import path

from apps.operations import views

urlpatterns = [path("operations/catalogs/", views.OperationsCatalogView.as_view(), name="operations-catalogs")]
