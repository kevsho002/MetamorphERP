"""GET /operations/catalogs/ — clientes con sus marcas y líneas de negocio con sus sub-líneas (solo lectura).

La creación y edición se hace en /admin/ › Catálogos operativos.
"""

from django.db.models import Prefetch
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasActionPermission, PasswordChangeNotRequired
from apps.accounts.roles import Perm
from apps.operations.models import Brand, Client, LineOfBusiness, SubLineOfBusiness


def _entry(obj) -> dict:
    return {
        "code": obj.code, "name": obj.name, "country": obj.country.country_code if obj.country_id else None,
        "description": obj.description or None, "is_active": obj.is_active,
    }


class OperationsCatalogView(APIView):
    permission_classes = [IsAuthenticated, PasswordChangeNotRequired, HasActionPermission]
    action = "catalogs"
    action_permissions = {"catalogs": Perm.ROSTER_VIEW}

    def get(self, request):
        include_inactive = request.query_params.get("include_inactive") in {"1", "true"}
        clients = Client.objects.select_related("country").prefetch_related(
            Prefetch("brands", queryset=Brand.objects.select_related("country").order_by("name"))
        )
        lines = LineOfBusiness.objects.select_related("country").prefetch_related(
            Prefetch("sub_lines", queryset=SubLineOfBusiness.objects.select_related("country").order_by("name"))
        )
        if not include_inactive:
            clients, lines = clients.filter(is_active=True), lines.filter(is_active=True)
        keep = (lambda o: True) if include_inactive else (lambda o: o.is_active)
        return Response(
            {
                "clients": [
                    {**_entry(c), "legal_name": c.legal_name or None, "brands": [_entry(b) for b in c.brands.all() if keep(b)]}
                    for c in clients
                ],
                "lines_of_business": [
                    {**_entry(lob), "sub_lines": [_entry(s) for s in lob.sub_lines.all() if keep(s)]} for lob in lines
                ],
            }
        )
