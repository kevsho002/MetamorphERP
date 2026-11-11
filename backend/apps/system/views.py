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
                "allowed_image_types": ["image/png", "image/jpeg"],
                "server_time": timezone.now(),
            },
            headers={"Cache-Control": "no-store"},
        )
