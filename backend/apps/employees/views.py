"""API de Gestión de Empleados: alta (con cuenta vinculada opcional), edición, carga masiva,
plantillas, expediente digital dinámico, documentos e imágenes."""

import csv
import io
from urllib.parse import quote

from django.db import IntegrityError
from django.db.models import Prefetch, Q
from django.http import FileResponse, HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import services as account_services
from apps.accounts.permissions import HasActionPermission, PasswordChangeNotRequired
from apps.accounts.roles import Perm
from apps.employees import digital_files
from apps.employees.batch import process_single, row_feedback, run_batch
from apps.employees.models import AttributeDefinition, EmployeeAttributeValue, EmployeeTemplate, ImportBatch
from apps.employees.parsers import MAX_FILE_BYTES, FileFormatError, parse_records, parse_upload
from apps.employees.schema import resolve_template
from apps.common.models import CostCenter, Country
from apps.employees.serializers import (
    AttributeDefinitionSerializer,
    EmployeeListSerializer,
    EmployeeSerializer,
    EmployeeTemplateDetailSerializer,
    EmployeeTemplateSerializer,
    ImportBatchRowSerializer,
    ImportBatchSerializer,
    ImportRequestSerializer,
)
from apps.employees.updates import StaleEmployeeError, process_update, update_feedback
from apps.employees.validation import ValidationContext
from apps.hcm.models import DigitalFileDocument, DocumentType, Employee
from apps.system.audit import Category, record
from apps.system.models import AuditEvent

PERMISSIONS = [IsAuthenticated, PasswordChangeNotRequired, HasActionPermission]
NO_STORE = {"Cache-Control": "no-store"}
ORDERING = {
    "employee_code": ("employee_code",),
    "name": ("last_name", "first_name", "employee_code"),
    "hire_date": ("hire_date", "employee_code"),
    "country": ("country__country_code", "employee_code"),
    "cost_center": ("cost_center__code", "employee_code"),
}


class EmployeePagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 200


class EmployeeViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Empleados. POST = alta individual (ID corporativo + expediente + EAV); PATCH = edición."""

    serializer_class = EmployeeSerializer
    permission_classes = PERMISSIONS
    pagination_class = EmployeePagination
    http_method_names = ["get", "post", "patch", "head", "options"]
    lookup_field = "employee_code"
    lookup_value_regex = r"[A-Za-z0-9]+-\d{4}-\d{6}-\d"
    action_permissions = {
        "list": Perm.HCM_VIEW,
        "retrieve": Perm.HCM_VIEW,
        "create": Perm.HCM_MANAGE,
        "validate": Perm.HCM_MANAGE,
        "partial_update": Perm.HCM_MANAGE,
        "validate_update": Perm.HCM_MANAGE,
        "digital_file": Perm.HCM_VIEW,
        "documents": Perm.HCM_VIEW,
        "upload_document": Perm.HCM_MANAGE,
        "photo": Perm.HCM_VIEW,
        "upload_photo": Perm.HCM_MANAGE,
        "create_user_account": Perm.USERS_CREATE,
        "history": Perm.HCM_MANAGE,
    }

    def get_serializer_class(self):
        return EmployeeListSerializer if self.action == "list" else EmployeeSerializer

    def get_queryset(self):
        qs = Employee.objects.select_related("country", "cost_center", "user_account").prefetch_related(
            Prefetch("attribute_values", queryset=EmployeeAttributeValue.objects.select_related("attribute"))
        )
        params = self.request.query_params
        if country := params.get("country"):
            qs = qs.filter(country__country_code__iexact=country)
        if status_ := params.get("status", "").strip().upper():
            if status_ == "INACTIVE":  # suspendidos + retirados
                qs = qs.exclude(employment_status=Employee.Status.ACTIVE)
            else:
                qs = qs.filter(employment_status__in=[s.strip() for s in status_.split(",") if s.strip()])
        if cost_center := params.get("cost_center"):
            qs = qs.filter(cost_center__code__iexact=cost_center)
        if search := params.get("search", "").strip():
            qs = qs.filter(
                Q(employee_code__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(national_id_number__icontains=search)
                | Q(work_email__icontains=search)
            )
        ordering = params.get("ordering", "employee_code")
        descending = ordering.startswith("-")
        fields = ORDERING.get(ordering.lstrip("-"), ORDERING["employee_code"])
        return qs.order_by(*(f"-{f}" if descending else f for f in fields))

    @staticmethod
    def _account_request(data: dict) -> dict | None:
        """`user_account: {"create": true, "role": "EMPLOYEE", "username": ""}` (opcional en el alta)."""
        raw = data.pop("user_account", None)
        if not isinstance(raw, dict):
            return None
        wants = raw.get("create")
        if wants in (True, 1) or str(wants).strip().lower() in {"true", "1", "si", "sí", "yes"}:
            return raw
        return None

    def _single(self, request, dry_run: bool):
        if not isinstance(request.data, dict):
            raise ValidationError({"detail": "Envíe un objeto JSON con los datos del empleado."})
        payload = dict(request.data)
        account_request = self._account_request(payload)
        plan_holder = {}

        def account_checks(row):
            if account_request is None:
                return
            plan = account_services.plan_linked_account(
                request.user,
                role=account_request.get("role"),
                username=account_request.get("username"),
                first_name=row.core.get("first_name") or payload.get("first_name"),
                last_name=row.core.get("last_name") or payload.get("last_name"),
                email=row.core.get("work_email"),
            )
            for field_name, message, code in plan.errors:
                row.error(code, message, field_name)
            for field_name, message, code in plan.warnings:
                row.warn(code, message, field_name)
            plan_holder["plan"] = plan

        outcome = process_single(payload, user=request.user, dry_run=dry_run, extra_checks=account_checks)
        row = outcome.row
        body = {
            "valid": row.ok,
            "feedback": row_feedback(outcome, row_label=None),
            "errors": [m.as_dict() for m in row.errors],
            "warnings": [m.as_dict() for m in row.warnings],
            "template": row.spec.as_dict() if row.spec else None,
        }
        if "plan" in plan_holder:
            body["user_account_preview"] = plan_holder["plan"].preview()
        return outcome, body, plan_holder.get("plan")

    def create(self, request, *args, **kwargs):
        outcome, body, plan = self._single(request, dry_run=False)
        if not outcome.row.ok:
            body["detail"] = body["feedback"]
            return Response(body, status=status.HTTP_400_BAD_REQUEST)
        employee = self.get_queryset().get(pk=outcome.employee.pk)
        record(
            "employee_created", Category.EMPLOYEES, f"Alta del empleado {employee.employee_code} — {employee.full_name}.",
            request=request, target=employee,
            details={"country": employee.country.country_code, "template_id": outcome.row.template.pk, "via": "formulario"},
        )
        headers = None
        if plan is not None:
            try:
                account, temporary = account_services.create_linked_account(request.user, employee, plan, request=request)
            except IntegrityError:  # carrera: alguien tomó el mismo usuario entre la validación y el alta
                raise ValidationError(
                    {"detail": f"El usuario «{plan.username}» acaba de ser tomado por otra cuenta. No se creó el empleado; "
                               "vuelva a intentar con otro nombre de usuario."}
                ) from None
            body["user_account"] = {**_account_summary(account), "temporary_password": temporary}
            body["feedback"] += (
                f" Se creó la cuenta Metamorph «{account.username}» ({account.get_role_display()}) vinculada al ID "
                f"corporativo {employee.employee_code}. Entregue la contraseña temporal por un canal seguro: el sistema "
                "pedirá cambiarla en el primer ingreso."
            )
            headers = NO_STORE
            employee = self.get_queryset().get(pk=employee.pk)
        body["employee"] = self.get_serializer(employee).data
        return Response(body, status=status.HTTP_201_CREATED, headers=headers)

    @action(detail=False, methods=["post"])
    def validate(self, request):
        """Valida el formulario contra la plantilla del país sin guardar (incluye reglas de BD)."""
        _, body, _plan = self._single(request, dry_run=True)
        if not body["valid"]:  # en una validación previa no hubo intento de alta
            body["feedback"] = body["feedback"].replace("No se creó el empleado por ", "Los datos tienen ", 1)
        return Response(body)

    # ------------------------------------------------------------------ edición
    def _update(self, request, dry_run: bool):
        if not isinstance(request.data, dict):
            raise ValidationError({"detail": "Envíe un objeto JSON con los campos a modificar."})
        employee = self.get_object()
        if not dry_run:
            # Bloqueo de fila durante la transacción (además del control optimista por ROWVERSION).
            employee = Employee.objects.select_for_update().get(pk=employee.pk)
        payload = dict(request.data)
        row_version = payload.pop("row_version", None)
        try:
            outcome = process_update(
                employee, payload, user=request.user, dry_run=dry_run, row_version=row_version, request=request
            )
        except StaleEmployeeError:
            return Response(
                {
                    "detail": f"Otra persona modificó al empleado {employee.employee_code} mientras usted lo editaba. "
                    "Recargue el formulario para ver los datos actuales y vuelva a aplicar sus cambios.",
                    "code": "stale",
                },
                status=status.HTTP_409_CONFLICT,
            )
        row = outcome.row
        body = {
            "valid": row.ok,
            "saved": outcome.saved,
            "changes": outcome.changes,
            "feedback": update_feedback(outcome, dry_run),
            "errors": [m.as_dict() for m in row.errors],
            "warnings": [m.as_dict() for m in row.warnings],
            "template": row.spec.as_dict() if row.spec else None,
        }
        if not row.ok:
            body["detail"] = body["feedback"]
            return Response(body, status=status.HTTP_400_BAD_REQUEST)
        if not dry_run:
            if outcome.saved:
                record(
                    "employee_updated", Category.EMPLOYEES,
                    f"Edición del empleado {employee.employee_code}: {', '.join(outcome.changes)}.",
                    request=request, target=employee, details={"changes": outcome.changes},
                )
            body["employee"] = self.get_serializer(self.get_queryset().get(pk=employee.pk)).data
        return Response(body)

    def update(self, request, *args, **kwargs):
        if not kwargs.get("partial"):
            return Response({"detail": "Use PATCH con los campos a modificar."}, status=status.HTTP_405_METHOD_NOT_ALLOWED)
        return self._update(request, dry_run=False)

    @action(detail=True, methods=["post"], url_path="validate")
    def validate_update(self, request, employee_code=None):
        """Valida una edición sin guardar (mismo cuerpo que PATCH)."""
        return self._update(request, dry_run=True)

    # ------------------------------------------------------------ expediente digital
    @action(detail=True, methods=["get"], url_path="digital-file")
    def digital_file(self, request, employee_code=None):
        """Expediente dinámico. ?as_of=AAAA-MM-DD evalúa la plantilla vigente a esa fecha (por defecto, la de ingreso)."""
        employee = self.get_object()
        raw = request.query_params.get("as_of", "").strip()
        as_of = None
        if raw:
            as_of = timezone.localdate() if raw.lower() in {"today", "hoy"} else parse_date(raw)
            if as_of is None:
                raise ValidationError({"as_of": "Use el formato AAAA-MM-DD."})
        data = digital_files.build_dossier(
            employee, EmployeeSerializer(employee, context=self.get_serializer_context()).data, user=request.user, as_of=as_of
        )
        return Response(data, headers=NO_STORE)

    def _document_error(self, exc: "digital_files.DocumentError"):
        return Response(
            {"detail": exc.message, "code": exc.code, "errors": [{"field": exc.field, "code": exc.code, "message": exc.message}]},
            status=status.HTTP_400_BAD_REQUEST,
        )

    @action(detail=True, methods=["get"], parser_classes=[MultiPartParser, FormParser])
    def documents(self, request, employee_code=None):
        """Historial de versiones (?type=CÓDIGO para un tipo)."""
        employee = self.get_object()
        docs = (
            DigitalFileDocument.objects.filter(digital_file__employee=employee)
            .select_related("document_type")
            .exclude(document_type__code=DocumentType.PROFILE_PHOTO)
            .order_by("document_type__name", "-version_number")
        )
        if code := request.query_params.get("type"):
            docs = docs.filter(document_type__code=code.upper())
        results = [
            {
                "type": doc.document_type.code,
                "type_name": doc.document_type.name,
                **digital_files.document_payload(doc, viewable=digital_files.can_view_document(request.user, doc.document_type)),
            }
            for doc in docs
        ]
        return Response({"results": results}, headers=NO_STORE)

    @documents.mapping.post
    def upload_document(self, request, employee_code=None):
        """multipart: file (PNG/JPG/JPEG), document_type (código), issue_date, expiry_date."""
        employee = self.get_object()
        code = str(request.data.get("document_type", "")).strip().upper()
        doc_type = DocumentType.objects.filter(code=code).first() if code else None
        if doc_type is None or doc_type.code == DocumentType.PROFILE_PHOTO:
            return self._document_error(
                digital_files.DocumentError("Seleccione un tipo de documento válido.", "invalid_type", "document_type")
            )
        if not digital_files.can_view_document(request.user, doc_type):
            return Response({"detail": "Su rol no puede gestionar este tipo de documento."}, status=status.HTTP_403_FORBIDDEN)
        upload = request.FILES.get("file")
        if upload is None:
            return self._document_error(digital_files.DocumentError("Adjunte la imagen (PNG, JPG o JPEG).", "required", "file"))
        try:
            doc = digital_files.upload_document(
                employee, doc_type, upload,
                issue_date=request.data.get("issue_date"), expiry_date=request.data.get("expiry_date"),
                actor=request.user.username,
            )
        except digital_files.DocumentError as exc:
            return self._document_error(exc)
        record(
            "document_uploaded", Category.DOCUMENTS,
            f"{doc_type.name} (versión {doc.version_number}) agregado al expediente de {employee.employee_code}.",
            request=request, target=employee,
            details={"document_id": doc.document_id, "type": doc_type.code, "version": doc.version_number,
                     "sha256": doc.sha256_hash, "size_bytes": doc.size_bytes},
        )
        replaced = " Reemplaza a la versión anterior, que queda en el historial." if doc.version_number > 1 else ""
        return Response(
            {
                "document": {"type": doc_type.code, "type_name": doc_type.name, **digital_files.document_payload(doc, viewable=True)},
                "feedback": f"Se guardó «{doc_type.name}» (versión {doc.version_number}) en el expediente de "
                            f"{employee.employee_code}.{replaced}",
            },
            status=status.HTTP_201_CREATED,
            headers=NO_STORE,
        )

    @action(detail=True, methods=["get"], parser_classes=[MultiPartParser, FormParser])
    def photo(self, request, employee_code=None):
        employee = self.get_object()
        current = digital_files.current_photo(employee)
        if current is None:
            return Response({"detail": "El empleado no tiene fotografía."}, status=status.HTTP_404_NOT_FOUND)
        return _image_response(current, cache="private, max-age=86400")

    @photo.mapping.post
    def upload_photo(self, request, employee_code=None):
        employee = self.get_object()
        upload = request.FILES.get("file")
        if upload is None:
            return self._document_error(digital_files.DocumentError("Adjunte la fotografía (PNG, JPG o JPEG).", "required", "file"))
        doc_type = DocumentType.objects.filter(code=DocumentType.PROFILE_PHOTO).first()
        if doc_type is None:
            return Response({"detail": "Falta el tipo PROFILE_PHOTO: ejecute database/scripts/095."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        try:
            doc = digital_files.upload_document(employee, doc_type, upload, actor=request.user.username)
        except digital_files.DocumentError as exc:
            return self._document_error(exc)
        record(
            "photo_uploaded", Category.DOCUMENTS, f"Fotografía de perfil actualizada (versión {doc.version_number}) de {employee.employee_code}.",
            request=request, target=employee, details={"document_id": doc.document_id, "version": doc.version_number},
        )
        return Response(
            {"photo": digital_files.photo_payload(employee), "feedback": "Fotografía de perfil actualizada."},
            status=status.HTTP_201_CREATED,
        )

    # ------------------------------------------------------------ cuenta de usuario vinculada
    @action(detail=True, methods=["post"], url_path="user-account")
    def create_user_account(self, request, employee_code=None):
        """Crea la cuenta Metamorph de un empleado existente: {role, username?}."""
        employee = self.get_object()
        data = request.data if isinstance(request.data, dict) else {}
        plan = account_services.plan_linked_account(
            request.user, role=data.get("role"), username=data.get("username"),
            first_name=employee.first_name, last_name=employee.last_name, email=employee.work_email, employee=employee,
        )
        if not plan.ok:
            errors = [{"field": f, "message": m, "code": c} for f, m, c in plan.errors]
            return Response({"detail": " ".join(e["message"] for e in errors), "errors": errors}, status=status.HTTP_400_BAD_REQUEST)
        try:
            account, temporary = account_services.create_linked_account(request.user, employee, plan, request=request)
        except IntegrityError:
            raise ValidationError({"detail": f"El usuario «{plan.username}» ya existe. Elija otro."}) from None
        return Response(
            {
                "user_account": {**_account_summary(account), "temporary_password": temporary},
                "warnings": [{"field": f, "message": m, "code": c} for f, m, c in plan.warnings],
                "feedback": f"Se creó la cuenta «{account.username}» ({account.get_role_display()}) vinculada a "
                            f"{employee.employee_code}. Deberá cambiar la contraseña temporal en su primer ingreso.",
            },
            status=status.HTTP_201_CREATED,
            headers=NO_STORE,
        )

    # ------------------------------------------------------------ historial (audit trail del empleado)
    @action(detail=True, methods=["get"])
    def history(self, request, employee_code=None):
        employee = self.get_object()
        account_id = getattr(getattr(employee, "user_account", None), "pk", None) if hasattr(employee, "user_account") else None
        condition = Q(target_type="employee", target_id=employee.employee_code)
        if account_id:
            condition |= Q(target_type="user", target_id=str(account_id))
        events = AuditEvent.objects.filter(condition).order_by("-occurred_at", "-id")[:200]
        return Response(
            {
                "results": [
                    {
                        "id": e.id,
                        "occurred_at": e.occurred_at,
                        "category": e.category,
                        "category_label": e.get_category_display(),
                        "action": e.action,
                        "summary": e.summary,
                        "actor": e.actor_username or None,
                        "success": e.success,
                    }
                    for e in events
                ]
            },
            headers=NO_STORE,
        )


class CatalogView(APIView):
    """Catálogos para filtros y formularios: países, centros de costos y opciones de los campos base."""

    permission_classes = PERMISSIONS
    action = "catalogs"  # HasActionPermission resuelve el permiso por nombre de acción
    action_permissions = {"catalogs": Perm.HCM_VIEW}

    def get(self, request):
        cost_centers = CostCenter.objects.select_related("country").order_by("country__country_code", "code")
        return Response(
            {
                "countries": [
                    {
                        "code": c.country_code,
                        "name": c.country_name,
                        "currency": c.currency_code,
                        "id_prefix": c.id_prefix,
                        "is_active": c.is_active,
                    }
                    for c in Country.objects.all()
                ],
                "cost_centers": [
                    {"code": cc.code, "name": cc.name, "country": cc.country.country_code, "is_active": cc.is_active}
                    for cc in cost_centers
                ],
                "employment_statuses": [{"value": v, "label": label} for v, label in Employee.Status.choices],
                "genders": [{"value": v, "label": label} for v, label in Employee.Gender.choices],
                "pay_frequencies": [{"value": v, "label": label} for v, label in Employee.PayFrequency.choices],
            },
            headers={"Cache-Control": "private, max-age=60"},
        )


class AttributeDefinitionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AttributeDefinition.objects.all()
    serializer_class = AttributeDefinitionSerializer
    permission_classes = PERMISSIONS
    pagination_class = None
    lookup_field = "code"
    action_permissions = {"list": Perm.HCM_VIEW, "retrieve": Perm.HCM_VIEW}


class EmployeeTemplateViewSet(viewsets.ReadOnlyModelViewSet):
    """Plantillas por país (se administran en /admin/). `applicable` arma el formulario dinámico."""

    permission_classes = PERMISSIONS
    action_permissions = {
        "list": Perm.HCM_VIEW,
        "retrieve": Perm.HCM_VIEW,
        "applicable": Perm.HCM_VIEW,
        "csv_template": Perm.HCM_MANAGE,
    }

    def get_queryset(self):
        qs = EmployeeTemplate.objects.select_related("country")
        if country := self.request.query_params.get("country"):
            qs = qs.filter(country__country_code__iexact=country)
        if self.request.query_params.get("active") in {"1", "true"}:
            qs = qs.filter(is_active=True)
        return qs

    def get_serializer_class(self):
        return EmployeeTemplateDetailSerializer if self.action == "retrieve" else EmployeeTemplateSerializer

    @action(detail=False, methods=["get"])
    def applicable(self, request):
        """GET ?country=SV&date=2026-03-01 -> plantilla vigente y su especificación de campos."""
        ctx = ValidationContext()
        country = ctx.country(request.query_params.get("country", ""))
        if country is None:
            raise ValidationError({"country": f"País desconocido. Valores válidos: {ctx.valid_country_codes}."})
        raw_date = request.query_params.get("date")
        on_date = parse_date(raw_date) if raw_date else timezone.localdate()
        if on_date is None:
            raise ValidationError({"date": "Use el formato AAAA-MM-DD."})
        template = ctx.template_for(country, on_date)
        if template is None:
            return Response(
                {"detail": f"No existe una plantilla activa de {country.country_name} vigente al {on_date:%d/%m/%Y}."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(EmployeeTemplateDetailSerializer(template).data)

    @action(detail=True, methods=["get"], url_path="csv")
    def csv_template(self, request, pk=None):
        """Archivo CSV de ejemplo (encabezados de la plantilla) para preparar una carga masiva."""
        template = self.get_object()
        spec = resolve_template(template)
        headers = ["country"] + list(spec.fields)
        example = {"country": spec.country_code}
        for key, field in spec.fields.items():
            example[key] = field.example or field.default or (field.choices[0] if field.choices else "")
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=headers)
        writer.writeheader()
        writer.writerow(example)
        name = f"plantilla_empleados_{spec.country_code}_{template.effective_date:%Y%m%d}.csv"
        response = HttpResponse("﻿" + buffer.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        return response


class ImportBatchViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    """Cargas masivas: POST multipart (`file`: .csv/.xlsx/.json) o JSON (`rows`: [...])."""

    serializer_class = ImportBatchSerializer
    permission_classes = PERMISSIONS
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    action_permissions = {"list": Perm.HCM_MANAGE, "retrieve": Perm.HCM_MANAGE, "create": Perm.HCM_MANAGE}

    def get_queryset(self):
        return ImportBatch.objects.select_related("created_by")

    def _report(self, batch: ImportBatch) -> dict:
        data = ImportBatchSerializer(batch).data
        rows = batch.rows.select_related("country")
        if row_status := self.request.query_params.get("row_status"):
            rows = rows.filter(status=row_status.upper())
        data["rows"] = ImportBatchRowSerializer(rows, many=True).data
        return data

    def retrieve(self, request, *args, **kwargs):
        return Response(self._report(self.get_object()), headers=NO_STORE)

    def create(self, request, *args, **kwargs):
        options = ImportRequestSerializer(data={k: request.data.get(k) for k in ("atomicity", "dry_run", "file_name") if request.data.get(k) not in (None, "")})
        options.is_valid(raise_exception=True)
        opts = options.validated_data
        upload = request.FILES.get("file")
        try:
            if upload is not None:
                if upload.size > MAX_FILE_BYTES:
                    raise FileFormatError(
                        f"El archivo pesa {upload.size / 1_048_576:.1f} MB; el máximo es {MAX_FILE_BYTES // 1_048_576} MB."
                    )
                parsed = parse_upload(upload.read(), upload.name, upload.content_type)
            elif "rows" in request.data:
                parsed = parse_records(request.data["rows"], opts.get("file_name", "api.json"))
            else:
                raise FileFormatError("Adjunte un archivo en el campo «file» (CSV, Excel o JSON) o envíe las filas en «rows».")
        except FileFormatError as exc:
            return Response({"detail": exc.message, "code": "invalid_file"}, status=status.HTTP_400_BAD_REQUEST)

        batch = run_batch(parsed, user=request.user, atomicity=opts["atomicity"], dry_run=opts["dry_run"])
        record(
            "import_validated" if batch.dry_run else "import_applied", Category.IMPORTS,
            f"Lote #{batch.pk} «{batch.file_name}»: {batch.total_rows} filas, {batch.created_rows} altas, "
            f"{batch.error_rows} con errores{' (solo validación)' if batch.dry_run else ''}.",
            request=request, target=batch,
            details={"batch_id": batch.pk, "sha256": batch.file_sha256, "atomicity": batch.atomicity,
                     "created": batch.created_rows, "errors": batch.error_rows},
        )
        code = status.HTTP_200_OK if batch.dry_run else status.HTTP_201_CREATED
        return Response(self._report(batch), status=code, headers=NO_STORE)



def _account_summary(account) -> dict:
    return {
        "id": account.pk,
        "username": account.username,
        "email": account.email or None,
        "role": account.role,
        "role_label": account.get_role_display(),
        "is_active": account.is_active,
        "must_change_password": account.must_change_password,
        "last_login": account.last_login,
    }


def _image_response(document: DigitalFileDocument, *, cache: str, download: bool = False) -> FileResponse:
    """Entrega la imagen desde el almacenamiento privado con cabeceras defensivas."""
    response = FileResponse(digital_files.open_document(document), content_type=document.mime_type)
    disposition = "attachment" if download else "inline"
    response["Content-Disposition"] = f"{disposition}; filename*=UTF-8''{quote(document.original_name)}"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response["Cache-Control"] = cache
    return response


class DocumentContentView(APIView):
    """GET /hcm/documents/{id}/content/ — imagen de un documento (?download=1 para descargar)."""

    permission_classes = PERMISSIONS
    action = "document_content"
    action_permissions = {"document_content": Perm.HCM_VIEW}

    def get(self, request, pk: int):
        document = (
            DigitalFileDocument.objects.select_related("document_type", "digital_file__employee").filter(pk=pk).first()
        )
        if document is None:
            return Response({"detail": "No encontrado."}, status=status.HTTP_404_NOT_FOUND)
        doc_type = document.document_type
        if not digital_files.can_view_document(request.user, doc_type):
            return Response(
                {"detail": "Documento restringido: requiere permiso de planilla.", "code": "restricted"},
                status=status.HTTP_403_FORBIDDEN,
            )
        download = request.query_params.get("download") in {"1", "true"}
        if doc_type.is_sensitive or download:
            employee = document.digital_file.employee
            record(
                "document_downloaded" if download else "document_viewed", Category.DOCUMENTS,
                f"{'Descarga' if download else 'Consulta'} de «{doc_type.name}» (versión {document.version_number}) "
                f"del expediente de {employee.employee_code}.",
                request=request, target=employee, details={"document_id": document.document_id, "type": doc_type.code},
            )
        cache = "private, no-store" if doc_type.is_sensitive else "private, max-age=3600"
        try:
            return _image_response(document, cache=cache, download=download)
        except FileNotFoundError:
            return Response(
                {"detail": "El archivo no está en el almacenamiento (posible restauración incompleta). Avise a soporte."},
                status=status.HTTP_410_GONE,
            )


class DigitalFileListView(APIView):
    """GET /hcm/digital-files/ — empleados con el avance de su expediente (foto y documentos obligatorios)."""

    permission_classes = PERMISSIONS
    action = "digital_files"
    action_permissions = {"digital_files": Perm.HCM_VIEW}

    def get(self, request):
        qs = Employee.objects.select_related("country", "cost_center").order_by("employee_code")
        params = request.query_params
        if country := params.get("country"):
            qs = qs.filter(country__country_code__iexact=country)
        status_ = params.get("status", "ACTIVE").strip().upper()
        if status_ == "INACTIVE":
            qs = qs.exclude(employment_status=Employee.Status.ACTIVE)
        elif status_ and status_ != "ALL":
            qs = qs.filter(employment_status=status_)
        if search := params.get("search", "").strip():
            qs = qs.filter(Q(employee_code__icontains=search) | Q(first_name__icontains=search) | Q(last_name__icontains=search))
        paginator = EmployeePagination()
        page = paginator.paginate_queryset(qs, request, view=self)

        ctx = ValidationContext()
        today = timezone.localdate()
        docs = DigitalFileDocument.objects.filter(digital_file__employee__in=page, is_current=True).values(
            "digital_file__employee_id", "document_type_id", "document_type__code", "document_id", "expiry_date"
        )
        by_employee: dict[int, dict[int, dict]] = {}
        for d in docs:
            by_employee.setdefault(d["digital_file__employee_id"], {})[d["document_type_id"]] = d
        requirement_cache: dict = {}
        results = []
        for emp in page:
            template = ctx.template_for(emp.country, emp.hire_date)
            key = (emp.country_id, template.pk if template else None)
            if key not in requirement_cache:
                spec = resolve_template(template) if template else None
                requirement_cache[key] = [r for r in digital_files.requirements(emp.country_id, spec) if r.required]
            current = by_employee.get(emp.employee_id, {})
            missing, expired = [], []
            for req in requirement_cache[key]:
                doc = current.get(req.type.document_type_id)
                if doc is None:
                    missing.append(req.label)
                elif doc["expiry_date"] and doc["expiry_date"] < today:
                    expired.append(req.label)
            total = len(requirement_cache[key])
            ok = total - len(missing) - len(expired)
            photo = next((d for d in current.values() if d["document_type__code"] == DocumentType.PROFILE_PHOTO), None)
            results.append(
                {
                    "employee_code": emp.employee_code,
                    "full_name": emp.full_name,
                    "country": emp.country.country_code,
                    "country_name": emp.country.country_name,
                    "cost_center": emp.cost_center.code if emp.cost_center else None,
                    "employment_status": emp.employment_status,
                    "employment_status_label": emp.get_employment_status_display(),
                    "hire_date": emp.hire_date,
                    "photo_url": f"/api/v1/hcm/employees/{emp.employee_code}/photo/?v={photo['document_id']}" if photo else None,
                    "documents": {
                        "required_total": total,
                        "required_ok": ok,
                        "percent": round(100 * ok / total) if total else 100,
                        "missing": missing,
                        "expired": expired,
                    },
                }
            )
        return paginator.get_paginated_response(results)
