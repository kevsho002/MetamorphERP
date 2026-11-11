from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.accounts import views

router = SimpleRouter()
router.register("users", views.UserViewSet, basename="user")

urlpatterns = [
    path("auth/csrf/", views.CsrfView.as_view(), name="auth-csrf"),
    path("auth/login/", views.LoginView.as_view(), name="auth-login"),
    path("auth/logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("auth/me/", views.MeView.as_view(), name="auth-me"),
    path("auth/password/change/", views.PasswordChangeView.as_view(), name="auth-password-change"),
    path("roles/", views.RoleListView.as_view(), name="role-list"),
    *router.urls,
]
