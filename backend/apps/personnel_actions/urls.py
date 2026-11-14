from django.urls import path, re_path

from apps.personnel_actions import views

P = "personnel-actions"
FOLIO = r"(?P<folio>[A-Za-z]{2,6}-\d{4}-\d{6})"
EMPLOYEE = r"(?P<code>[A-Za-z0-9]+-\d{4}-\d{6}-\d)"

urlpatterns = [
    path(f"{P}/", views.ActionsView.as_view(), name="pa-list"),
    path(f"{P}/types/", views.TypesView.as_view(), name="pa-types"),
    path(f"{P}/validate/", views.ValidateView.as_view(), name="pa-validate"),
    path(f"{P}/missing-initial/", views.MissingInitialView.as_view(), name="pa-missing-initial"),
    path(f"{P}/schedule-preview/", views.SchedulePreviewView.as_view(), name="pa-schedule-preview"),
    path(f"{P}/employees/picker/", views.EmployeePickerView.as_view(), name="pa-employee-picker"),
    re_path(rf"^{P}/employees/{EMPLOYEE}/$", views.EmployeeActionsView.as_view(), name="pa-employee"),
    re_path(rf"^{P}/employees/{EMPLOYEE}/lifecycle/$", views.LifecycleView.as_view(), name="pa-employee-lifecycle"),
    path(f"{P}/role-matrix/", views.RoleMatrixView.as_view(), name="pa-role-matrix"),
    re_path(rf"^{P}/role-matrix/(?P<code>[A-Za-z0-9_]+)/$", views.RoleMatrixView.as_view(), name="pa-role-matrix-type"),
    path(f"{P}/attachments/<int:pk>/content/", views.AttachmentContentView.as_view(), name="pa-attachment-content"),
    path(f"{P}/attachments/<int:pk>/remove/", views.AttachmentRemoveView.as_view(), name="pa-attachment-remove"),
    re_path(rf"^{P}/{FOLIO}/$", views.ActionDetailView.as_view(), name="pa-detail"),
    re_path(rf"^{P}/{FOLIO}/attachments/$", views.ActionAttachmentsView.as_view(), name="pa-attachments"),
    re_path(rf"^{P}/{FOLIO}/submit/$", views.TransitionView.as_view(transition="submit"), name="pa-submit"),
    re_path(rf"^{P}/{FOLIO}/sign/$", views.TransitionView.as_view(transition="sign"), name="pa-sign"),
    re_path(rf"^{P}/{FOLIO}/cancel/$", views.TransitionView.as_view(transition="cancel"), name="pa-cancel"),
]
