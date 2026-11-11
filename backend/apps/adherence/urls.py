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
]
