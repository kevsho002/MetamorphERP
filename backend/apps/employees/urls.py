from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.employees import views

router = SimpleRouter()
router.register("hcm/employees", views.EmployeeViewSet, basename="employee")
router.register("hcm/employee-templates", views.EmployeeTemplateViewSet, basename="employee-template")
router.register("hcm/attributes", views.AttributeDefinitionViewSet, basename="attribute")
router.register("hcm/employee-imports", views.ImportBatchViewSet, basename="employee-import")

urlpatterns = [
    path("hcm/catalogs/", views.CatalogView.as_view(), name="hcm-catalogs"),
    path("hcm/user-account-candidates/", views.AccountCandidatesView.as_view(), name="hcm-account-candidates"),
    path("hcm/digital-files/", views.DigitalFileListView.as_view(), name="hcm-digital-files"),
    path("hcm/documents/<int:pk>/content/", views.DocumentContentView.as_view(), name="hcm-document-content"),
    *router.urls,
]
