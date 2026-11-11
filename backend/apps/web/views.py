"""Despliegue unificado: Django entrega el index.html del build de React."""

from django.conf import settings
from django.db.transaction import non_atomic_requests
from django.http import FileResponse, HttpRequest, JsonResponse
from django.views.decorators.http import require_safe


@non_atomic_requests
@require_safe
def spa_index(request: HttpRequest):
    index = settings.FRONTEND_DIST_DIR / "index.html"
    if not index.is_file():
        return JsonResponse(
            {"detail": "Frontend no compilado. Ejecute `npm run build` en frontend/ o use `npm run dev`."},
            status=404,
        )
    response = FileResponse(index.open("rb"), content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-cache"  # los assets llevan hash; el index no se cachea
    return response


@non_atomic_requests
def api_not_found(request: HttpRequest):
    return JsonResponse({"detail": "No encontrado."}, status=404)


def csrf_failure(request: HttpRequest, reason: str = ""):
    """CSRF_FAILURE_VIEW: respuesta JSON (el SPA no puede mostrar la página HTML de Django)."""
    return JsonResponse(
        {"detail": "Verificación CSRF fallida. Recargue la página e intente de nuevo.", "code": "csrf_failed"},
        status=403,
    )
