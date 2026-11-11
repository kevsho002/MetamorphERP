from django.urls import path, re_path

from apps.general_ids import views

EMPLOYEE = r"(?P<code>[A-Za-z0-9]+-\d{4}-\d{6}-\d)"

urlpatterns = [
    path("general-ids/catalogs/", views.CatalogsView.as_view(), name="gid-catalogs"),
    path("general-ids/lookup/", views.LookupView.as_view(), name="gid-lookup"),
    path("general-ids/report/", views.ReportView.as_view(), name="gid-report"),
    re_path(rf"^general-ids/employees/{EMPLOYEE}/$", views.EmployeeGeneralIdsView.as_view(), name="gid-employee"),
    re_path(rf"^general-ids/employees/{EMPLOYEE}/validate/$", views.EmployeeGeneralIdValidateView.as_view(), name="gid-employee-validate"),
    re_path(rf"^general-ids/employees/{EMPLOYEE}/(?P<pk>\d+)/$", views.EmployeeGeneralIdDetailView.as_view(), name="gid-employee-detail"),
    re_path(
        rf"^general-ids/employees/{EMPLOYEE}/(?P<pk>\d+)/close/$",
        views.EmployeeGeneralIdDetailView.as_view(close=True),
        name="gid-employee-close",
    ),
]
