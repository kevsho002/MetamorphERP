from django.urls import path, re_path

from apps.acd import views

EMPLOYEE = r"(?P<{name}>[A-Za-z0-9]+-\d{{4}}-\d{{6}}-\d)"
GROUP = r"(?P<code>[A-Za-z][A-Za-z0-9_\-]{0,29})"
P = "acd"

urlpatterns = [
    path(f"{P}/catalogs/", views.CatalogsView.as_view(), name="acd-catalogs"),
    path(f"{P}/me/", views.MeView.as_view(), name="acd-me"),
    path(f"{P}/me/login/", views.MeLoginView.as_view(), name="acd-me-login"),
    path(f"{P}/me/status/", views.MeStatusView.as_view(), name="acd-me-status"),
    path(f"{P}/me/logout/", views.MeLogoutView.as_view(), name="acd-me-logout"),
    path(f"{P}/agents/", views.AgentsView.as_view(), name="acd-agents"),
    re_path(rf"^{P}/agents/{EMPLOYEE.format(name='code')}/logout/$", views.AgentLogoutView.as_view(), name="acd-agent-logout"),
    path(f"{P}/report/", views.ReportView.as_view(), name="acd-report"),
    path(f"{P}/groups/", views.GroupsView.as_view(), name="acd-groups"),
    re_path(rf"^{P}/groups/{GROUP}/$", views.GroupDetailView.as_view(), name="acd-group"),
    re_path(rf"^{P}/groups/{GROUP}/members/$", views.GroupMembersView.as_view(), name="acd-group-members"),
    re_path(rf"^{P}/groups/{GROUP}/members/{EMPLOYEE.format(name='employee_code')}/$", views.GroupMemberDetailView.as_view(),
            name="acd-group-member"),
]
