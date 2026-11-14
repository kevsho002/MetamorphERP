"""Configuración pública del cliente web (la consulta el SPA al iniciar y cada pocos minutos)."""

from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.system import policy


class ClientConfigView(APIView):
    """GET /system/client-config/ — sin datos sensibles: solo lo que el navegador necesita para comportarse."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        s = policy.current()
        return Response(
            {
                "maintenance_mode": s.maintenance_mode,
                "maintenance_message": s.maintenance_message if s.maintenance_mode else "",
                "announcement": s.announcement,
                "announcement_level": s.announcement_level,
                "idle_timeout_seconds": s.idle_timeout_minutes * 60,
                "idle_warning_seconds": min(s.idle_warning_seconds, s.idle_timeout_minutes * 60 // 2),
                "max_session_hours": s.max_session_hours,
                "max_document_mb": s.max_document_mb,
                "brand_palette": s.brand_palette,  # Fase 22: apariencia corporativa
                "brand_accent": s.brand_accent,
                "allowed_image_types": ["image/png", "image/jpeg"],
                "server_time": timezone.now(),
            },
            headers={"Cache-Control": "no-store"},
        )


# ================================================================ Fase 22
from django.db import transaction  # noqa: E402
from rest_framework.permissions import IsAuthenticated  # noqa: E402

from apps.accounts.permissions import HasActionPermission, PasswordChangeNotRequired, user_permissions  # noqa: E402
from apps.accounts.roles import Perm  # noqa: E402
from apps.system import datamodel, notifications, theme  # noqa: E402
from apps.system.audit import Category, record  # noqa: E402
from apps.system.models import BRAND_PALETTES, PlatformSettings  # noqa: E402

NO_STORE = {"Cache-Control": "no-store"}


class _View(APIView):
    permission_classes = [IsAuthenticated, PasswordChangeNotRequired, HasActionPermission]
    method_permissions: dict = {}

    @property
    def action(self):
        return self.request.method.lower()

    @property
    def action_permissions(self):
        return self.method_permissions


class NotificationsView(_View):
    """GET /system/notifications/ — centro de notificaciones operativas del usuario (en vivo).
    POST {keys: [...]} o {all: true} — las marca como leídas."""

    method_permissions = {"get": Perm.SELF_SERVICE, "post": Perm.SELF_SERVICE}

    def get(self, request):
        return Response(notifications.for_user(request.user), headers=NO_STORE)

    def post(self, request):
        n = notifications.mark_read(request.user, request.data.get("keys") or [], all_keys=bool(request.data.get("all")))
        return Response({"marked": n, **notifications.for_user(request.user)}, headers=NO_STORE)


class AppearanceView(_View):
    """GET /system/appearance/ — paleta corporativa vigente y opciones · PATCH (Administrador) — la cambia para todos."""

    method_permissions = {"get": Perm.SELF_SERVICE, "patch": Perm.SYSTEM_STATUS}

    def get(self, request):
        s = policy.current()
        return Response({"brand_palette": s.brand_palette, "brand_accent": s.brand_accent,
                         "palettes": [{"value": v, "label": label} for v, label in BRAND_PALETTES],
                         "can_manage": Perm.SYSTEM_STATUS in user_permissions(request.user),
                         "personal": personal_dict(request.user), "effective": theme.effective(request.user)},
                        headers=NO_STORE)

    @transaction.atomic
    def patch(self, request):
        import re

        s = PlatformSettings.objects.select_for_update().filter(pk=1).first() or PlatformSettings(pk=1)
        palette = str(request.data.get("brand_palette", s.brand_palette)).upper()
        accent = str(request.data.get("brand_accent", s.brand_accent) or "").strip()
        errors = {}
        if palette not in dict(BRAND_PALETTES):
            errors["brand_palette"] = "Paleta desconocida."
        if accent and not re.fullmatch(r"#[0-9a-fA-F]{6}", accent):
            errors["brand_accent"] = "Color hexadecimal (#RRGGBB)."
        if palette == "CUSTOM" and not accent:
            errors["brand_accent"] = "La paleta personalizada necesita el color de acento."
        if errors:
            return Response({"detail": next(iter(errors.values())), "errors": errors}, status=400)
        before = (s.brand_palette, s.brand_accent)
        s.brand_palette, s.brand_accent = palette, accent if palette == "CUSTOM" else ""
        s.updated_by = request.user.username[:150]
        s.save()
        label = dict(BRAND_PALETTES)[palette]
        record("appearance_updated", Category.SYSTEM, f"Paleta corporativa cambiada a «{label}»"
               + (f" ({s.brand_accent})" if s.brand_accent else "") + ".", request=request, actor=request.user,
               details={"before": before, "after": [s.brand_palette, s.brand_accent]})
        return Response({"feedback": f"Paleta corporativa «{label}» aplicada para todos los usuarios.",
                         "brand_palette": s.brand_palette, "brand_accent": s.brand_accent}, headers=NO_STORE)


def personal_dict(user) -> dict:
    p = theme.personal(user)
    return {"theme": p.theme if p else "system", "density": p.density if p else "comfortable",
            "time_mode": p.time_mode if p else "hms", "palette": p.palette if p else "", "accent": p.accent if p else "",
            "saved": p is not None}


class MyAppearanceView(_View):
    """Fase 23 — Preferencias visuales PERSONALES (perfil): PUT las guarda; DELETE vuelve a la configuración global."""

    method_permissions = {"get": Perm.SELF_SERVICE, "put": Perm.SELF_SERVICE, "delete": Perm.SELF_SERVICE}

    def get(self, request):
        return Response({"personal": personal_dict(request.user), "effective": theme.effective(request.user)}, headers=NO_STORE)

    def put(self, request):
        import re

        from apps.system.models import UserPreference

        d = request.data
        pref = UserPreference.objects.filter(user=request.user).first() or UserPreference(user=request.user)
        errors = {}
        for f, choices in (("theme", UserPreference.Theme.values), ("density", UserPreference.Density.values),
                           ("time_mode", UserPreference.TimeMode.values)):
            if f in d:
                if d[f] not in choices:
                    errors[f] = f"Valor inválido ({', '.join(choices)})."
                else:
                    setattr(pref, f, d[f])
        if "palette" in d:
            palette = str(d.get("palette") or "").upper()
            if palette and palette not in dict(BRAND_PALETTES):
                errors["palette"] = "Paleta desconocida."
            pref.palette = palette
        if "accent" in d:
            pref.accent = str(d.get("accent") or "").strip()
        if pref.accent and not re.fullmatch(r"#[0-9a-fA-F]{6}", pref.accent):
            errors["accent"] = "Color hexadecimal (#RRGGBB)."
        if pref.palette == "CUSTOM" and not pref.accent:
            errors["accent"] = "La paleta personalizada necesita el color de acento."
        if pref.palette != "CUSTOM":
            pref.accent = ""
        if errors:
            return Response({"detail": next(iter(errors.values())), "errors": errors}, status=400)
        pref.save()
        return Response({"feedback": "Preferencias guardadas en su perfil.", "personal": personal_dict(request.user),
                         "effective": theme.effective(request.user)}, headers=NO_STORE)

    def delete(self, request):
        from apps.system.models import UserPreference

        UserPreference.objects.filter(user=request.user).update(palette="", accent="")
        return Response({"feedback": "Volvió a la paleta corporativa predeterminada.", "personal": personal_dict(request.user),
                         "effective": theme.effective(request.user)}, headers=NO_STORE)


class DataStatsView(_View):
    """GET /system/data/stats/ — filas y espacio por tabla (adm.usp_SystemTableStats)."""

    method_permissions = {"get": Perm.SYSTEM_STATUS}

    def get(self, request):
        return Response(datamodel.table_stats(), headers=NO_STORE)


class ErdView(_View):
    """GET /system/data/erd/ — tablas, columnas y relaciones (FK) para el ERD interactivo."""

    method_permissions = {"get": Perm.SYSTEM_STATUS}

    def get(self, request):
        return Response(datamodel.erd(), headers=NO_STORE)


# ================================================================ Fase 25
class SystemOverviewView(_View):
    """GET /system/overview/ — sesiones activas en tiempo real y recuento de usuarios (Administrador)."""

    method_permissions = {"get": Perm.SYSTEM_STATUS}

    def get(self, request):
        from apps.system import overview

        return Response(overview.snapshot(request), headers=NO_STORE)


class SessionCloseView(_View):
    """POST /system/sessions/<id>/close/ — cierra una sesión activa (no la propia)."""

    method_permissions = {"post": Perm.SYSTEM_STATUS}

    def post(self, request, pk):
        from apps.system import overview, sessions
        from apps.system.models import UserSession

        s = UserSession.objects.filter(pk=pk, ended_at__isnull=True).select_related("user").first()
        if s is None:
            return Response({"detail": "La sesión ya no está activa."}, status=404)
        if s.session_key == request.session.session_key:
            return Response({"detail": "No puede cerrar su propia sesión desde aquí: use «Cerrar sesión»."}, status=409)
        sessions.end_sessions(UserSession.objects.filter(pk=s.pk), sessions.Reason.ADMIN)
        record("sessions_closed", Category.AUTH, f"Sesión de «{s.user.username}» cerrada desde Estado del sistema.",
               request=request, target_type="user_session", target_id=str(s.pk), details={"usuarios": [s.user.username], "cantidad": 1})
        return Response({"feedback": f"Sesión de {s.user.username} cerrada.", **overview.snapshot(request)}, headers=NO_STORE)


class SqlObjectsView(_View):
    """GET /system/data/objects/ — catálogo de vistas, procedimientos almacenados, funciones y triggers (Fase 25)."""

    method_permissions = {"get": Perm.SYSTEM_STATUS}

    def get(self, request):
        return Response(datamodel.sql_objects(), headers=NO_STORE)
