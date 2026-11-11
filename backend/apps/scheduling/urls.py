from django.urls import path, re_path

from apps.scheduling import views

EMPLOYEE = r"(?P<code>[A-Za-z0-9]+-\d{4}-\d{6}-\d)"
P = "scheduling"

urlpatterns = [
    path(f"{P}/catalogs/", views.CatalogsView.as_view(), name="sch-catalogs"),
    path(f"{P}/night-rules/", views.NightRulesView.as_view(), name="sch-night-rules"),
    path(f"{P}/lunch-rules/", views.LunchRulesView.as_view(), name="sch-lunch-rules"),
    path(f"{P}/schedule-preview/", views.SchedulePreviewView.as_view(), name="sch-schedule-preview"),
    re_path(rf"^{P}/employees/{EMPLOYEE}/assignments/$", views.EmployeeAssignmentsView.as_view(), name="sch-assignments"),
    re_path(rf"^{P}/employees/{EMPLOYEE}/timeline/$", views.EmployeeTimelineView.as_view(), name="sch-timeline"),
    re_path(rf"^{P}/employees/{EMPLOYEE}/days/(?P<day>\d{{4}}-\d{{2}}-\d{{2}})/$", views.EmployeeDayView.as_view(), name="sch-employee-day"),
    path(f"{P}/time-records/", views.TimeRecordsView.as_view(), name="sch-time-records"),
    path(f"{P}/time-records/upload/", views.TimeRecordUploadView.as_view(), name="sch-time-upload"),
    path(f"{P}/time-records/<int:pk>/", views.TimeRecordDetailView.as_view(), name="sch-time-record-detail"),
    path(f"{P}/report/", views.HoursReportView.as_view(), name="sch-report"),
    path(f"{P}/pay-cycles/", views.PayCyclesView.as_view(), name="sch-pay-cycles"),
    re_path(rf"^{P}/pay-cycles/(?P<code>[A-Za-z][A-Za-z0-9_\-]{{0,29}})/generate/$", views.PayCycleGenerateView.as_view(), name="sch-pay-cycle-generate"),
    path(f"{P}/pay-periods/<int:pk>/close/", views.PayPeriodStatusView.as_view(), name="sch-pay-period-close"),
    path(f"{P}/pay-periods/<int:pk>/reopen/", views.PayPeriodStatusView.as_view(target="OPEN"), name="sch-pay-period-reopen"),
]
