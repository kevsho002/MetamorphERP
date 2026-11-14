"""Fase 27 — Búsqueda de colaboradores para los campos con autocompletado (typeahead).

GET /api/v1/hcm/employee-lookup/?q=&scope=&terminated=1&limit=

Reemplaza los campos donde se digitaba el ID corporativo a mano (grilla WFM, adherencia, reporte ACD, grupos ACD,
justificaciones, jerarquía operativa). Devuelve solo lo necesario para elegir (ID, nombre, estado, centro de costos y
país) y busca por nombre, apellidos, ID corporativo o documento, sin distinguir acentos; varias palabras se combinan (AND).

Alcance: toda la organización para quien ya ve esos listados (RRHH, WFM, ACD, roster, General IDs o AP). `scope=acd`
limita a los agentes con membresía ACD activa (los que aparecen en la grilla y en los reportes de estados).
"""

from __future__ import annotations

from django.db.models import CharField, F, Func, Q
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import PasswordChangeNotRequired, user_permissions
from apps.accounts.roles import Perm
from apps.hcm.models import Employee

LOOKUP_PERMS = frozenset({Perm.HCM_VIEW, Perm.WFM_VIEW, Perm.ACD_VIEW, Perm.ROSTER_VIEW, Perm.GENERAL_IDS_VIEW,
                          Perm.ACTIONS_VIEW})
DEFAULT_LIMIT, MAX_LIMIT = 12, 30
ACCENT_INSENSITIVE = "Latin1_General_CI_AI"  # «mejia» encuentra «Mejía»
NAME_FIELDS = ("first_name", "middle_name", "last_name", "second_last_name")


class AccentInsensitive(Func):
    """`campo COLLATE Latin1_General_CI_AI` (Collate de Django entrecomilla el nombre y SQL Server lo rechaza)."""

    template = f"%(expressions)s COLLATE {ACCENT_INSENSITIVE}"
    output_field = CharField()


def search(q: str = "", *, scope: str = "", include_terminated: bool = False, limit: int = DEFAULT_LIMIT) -> dict:
    qs = Employee.objects.select_related("country", "cost_center")
    if scope == "acd":
        from apps.acd.models import AgentMembership

        qs = qs.filter(pk__in=AgentMembership.objects.filter(is_active=True).values("employee_id"))
    if not include_terminated:
        qs = qs.exclude(employment_status=Employee.Status.TERMINATED)
    q = (q or "").strip()
    if q:
        qs = qs.annotate(**{f"ai_{f}": AccentInsensitive(F(f)) for f in NAME_FIELDS})
        cond = Q()
        for term in q.split()[:4]:
            names = Q()
            for f in NAME_FIELDS:
                names |= Q(**{f"ai_{f}__icontains": term})
            cond &= names | Q(employee_code__icontains=term) | Q(national_id_number__icontains=term)
        qs = qs.filter(cond)
    total = qs.count()
    rows = qs.order_by("first_name", "last_name", "employee_code")[:min(max(limit, 1), MAX_LIMIT)]
    return {
        "total": total,
        "results": [{"employee_code": e.employee_code, "full_name": e.full_name, "country": e.country.country_code,
                     "status": e.employment_status, "status_label": e.get_employment_status_display(),
                     "cost_center": e.cost_center.code if e.cost_center_id else None} for e in rows],
    }


class EmployeeLookupView(APIView):
    permission_classes = [IsAuthenticated, PasswordChangeNotRequired]

    def get(self, request):
        if not LOOKUP_PERMS & user_permissions(request.user):
            raise PermissionDenied("No tiene acceso a la búsqueda de colaboradores.")
        p = request.query_params
        limit = int(p["limit"]) if str(p.get("limit") or "").isdigit() else DEFAULT_LIMIT
        scope = "acd" if p.get("scope") == "acd" else ""
        return Response(search(p.get("q", ""), scope=scope, include_terminated=p.get("terminated") == "1", limit=limit),
                        headers={"Cache-Control": "no-store"})
