from django.urls import path, re_path

from apps.adherence import views

P = "adherence"
CODE = r"(?P<code>[A-Za-z][A-Za-z0-9_\-]{0,29})"

urlpatterns = [
    path(f"{P}/catalogs/", views.CatalogsView.as_view(), name="adh-catalogs"),
    path(f"{P}/activities/", views.ActivitiesView.as_view(), name="adh-activities"),
    re_path(rf"^{P}/activities/{CODE}/$", views.ActivityDetailView.as_view(), name="adh-activity"),
    path(f"{P}/planner/", views.PlannerView.as_view(), name="adh-planner"),
    path(f"{P}/segments/", views.SegmentsView.as_view(), name="adh-segments"),
    path(f"{P}/segments/bulk/", views.SegmentsBulkView.as_view(), name="adh-segments-bulk"),
    path(f"{P}/segments/<int:pk>/", views.SegmentDetailView.as_view(), name="adh-segment"),
    path(f"{P}/exceptions/", views.ExceptionsView.as_view(), name="adh-exceptions"),
    path(f"{P}/exceptions/<int:pk>/", views.ExceptionDetailView.as_view(), name="adh-exception"),
    path(f"{P}/report/", views.ReportView.as_view(), name="adh-report"),
    path(f"{P}/detail/", views.DetailView.as_view(), name="adh-detail"),
    path(f"{P}/compute/", views.ComputeView.as_view(), name="adh-compute"),
    path(f"{P}/grid/", views.GridView.as_view(), name="adh-grid"),
    path(f"{P}/grid/filters/", views.GridFiltersView.as_view(), name="adh-grid-filters"),
    path(f"{P}/grid/agent/", views.AgentHistoryView.as_view(), name="adh-grid-agent"),
    path(f"{P}/grid/audit/", views.AuditTrailView.as_view(), name="adh-grid-audit"),
    path(f"{P}/grid/settings/", views.GridSettingView.as_view(), name="adh-grid-settings"),
    # Fase 19
    path(f"{P}/segments/<int:pk>/replace/", views.SegmentReplaceView.as_view(), name="adh-segment-replace"),
    path(f"{P}/attendance/reconcile/", views.ReconcileView.as_view(), name="adh-attendance-reconcile"),
    path(f"{P}/day/", views.DayView.as_view(), name="adh-day"),
    path(f"{P}/requests/", views.RequestsView.as_view(), name="adh-requests"),
    path(f"{P}/requests/<int:pk>/decide/", views.RequestDecideView.as_view(), name="adh-request-decide"),
    path(f"{P}/requests/<int:pk>/cancel/", views.RequestCancelView.as_view(), name="adh-request-cancel"),
    path(f"{P}/my-plan/", views.MyPlanView.as_view(), name="adh-my-plan"),
]
