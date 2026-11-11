from django.urls import path, re_path

from apps.roster import views

CODE = r"(?P<code>[A-Za-z0-9]+-\d{4}-\d{6}-\d)"

urlpatterns = [
    path("roster/attributes/", views.AttributeListView.as_view(), name="roster-attributes"),
    path("roster/dimensions/", views.DimensionListView.as_view(), name="roster-dimensions"),
    path("roster/report/", views.RosterReportView.as_view(), name="roster-report"),
    re_path(rf"^roster/employees/{CODE}/$", views.EmployeeRosterView.as_view(), name="roster-employee"),
    re_path(rf"^roster/employees/{CODE}/history/$", views.EmployeeRosterHistoryView.as_view(), name="roster-employee-history"),
    re_path(rf"^roster/employees/{CODE}/changes/$", views.EmployeeRosterChangeView.as_view(), name="roster-employee-changes"),
    re_path(
        rf"^roster/employees/{CODE}/changes/validate/$",
        views.EmployeeRosterValidateView.as_view(),
        name="roster-employee-changes-validate",
    ),
]
