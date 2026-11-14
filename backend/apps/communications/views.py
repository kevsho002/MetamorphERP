"""API del periódico virtual (Fase 25).

GET    /announcements/?category=&q=&scope=published|draft|archived|all&pending=1   portada (todos los usuarios)
POST   /announcements/                         crea (borrador o {publish: true})            announcements.manage
GET    /announcements/pending/                 comunicados con acuse pendiente del usuario (banner)
GET    /announcements/compliance/              resumen de cumplimiento de los comunicados con acuse  announcements.compliance
GET    /announcements/{id}/                    detalle (+ mi acuse)
PATCH  /announcements/{id}/  ·  DELETE (solo borradores)                             announcements.manage
POST   /announcements/{id}/publish/ · /archive/                                       announcements.manage
POST   /announcements/{id}/ack/                acuse de recibo (huella SHA-256 del contenido confirmado)
GET    /announcements/{id}/compliance/?export=csv   reporte por usuario + historial de fotos   announcements.compliance
POST   /announcements/{id}/compliance/         toma una foto manual del cumplimiento
"""

import csv

from django.db import DatabaseError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasActionPermission, PasswordChangeNotRequired
from apps.accounts.roles import Perm, Role
from apps.communications import services
from apps.communications.models import Announcement, AnnouncementAck, Category, ComplianceSnapshot, Status

NO_STORE = {"Cache-Control": "no-store"}
SQL_MESSAGES = {
    "50120": "El sistema rechazó el cambio: los acuses de recibo son inmutables.",
    "50121": "El sistema rechazó el acuse: el comunicado no está publicado o no requiere acuse.",
    "50122": "El sistema rechazó el cambio: el contenido de un comunicado con acuse publicado está congelado.",
    "50123": "El sistema rechazó el borrado: solo se eliminan borradores.",
}
STATUS_LABELS = {"ACKNOWLEDGED": "Confirmado", "LATE": "Confirmado fuera de plazo", "PENDING": "Pendiente", "OVERDUE": "Vencido"}


class _View(APIView):
    permission_classes = [IsAuthenticated, PasswordChangeNotRequired, HasActionPermission]
    method_permissions: dict = {}

    @property
    def action(self):
        return self.request.method.lower()

    @property
    def action_permissions(self):
        return self.method_permissions

    def handle_exception(self, exc):
        if isinstance(exc, services.CommsError):
            return Response({"detail": exc.message, "code": exc.code, "errors": exc.errors}, status=exc.status)
        if isinstance(exc, DatabaseError):
            code = next((c for c in SQL_MESSAGES if c in str(exc)), None)
            if code:
                return Response({"detail": SQL_MESSAGES[code], "code": f"sql_{code}"}, status=status.HTTP_409_CONFLICT)
        return super().handle_exception(exc)


def _data(request) -> dict:
    return request.data if isinstance(request.data, dict) else {}


def _get(user, pk) -> Announcement:
    a = get_object_or_404(Announcement.objects.select_related("created_by", "published_by"), pk=pk)
    if services.can_manage(user) or services.can_report(user):
        return a
    if a.status != Status.PUBLISHED or not services.in_audience(a, user):
        from django.http import Http404

        raise Http404
    return a


class AnnouncementsView(_View):
    method_permissions = {"get": Perm.SELF_SERVICE, "post": Perm.ANNOUNCEMENTS_MANAGE}

    def get(self, request):
        p = request.query_params
        category = (p.get("category") or "").upper()
        items = services.feed(request.user, category=category if category in Category.values else "",
                              search=(p.get("q") or "").strip()[:100], scope=p.get("scope") or "published",
                              pending_only=p.get("pending") in ("1", "true"))
        acks = {k.announcement_id: k for k in AnnouncementAck.objects.filter(user=request.user, announcement__in=items)}
        pending = services.pending_for(request.user)
        return Response({
            "results": [services.brief(a, user=request.user, acks=acks) for a in items],
            "categories": [{"value": v, "label": label, "critical": v in services.CRITICAL_CATEGORIES} for v, label in Category.choices],
            "roles": [{"value": v, "label": label} for v, label in Role.choices],
            "can_manage": services.can_manage(request.user), "can_report": services.can_report(request.user),
            "pending_count": len(pending), "default_ack_days": services.DEFAULT_ACK_DAYS,
        }, headers=NO_STORE)

    def post(self, request):
        a = services.create(_data(request), user=request.user, request=request)
        verb = "publicado" if a.status == Status.PUBLISHED else "guardado como borrador"
        return Response({"feedback": f"Comunicado «{a.title}» {verb}.", "announcement": services.detail(a, request.user)},
                        status=status.HTTP_201_CREATED, headers=NO_STORE)


class PendingView(_View):
    method_permissions = {"get": Perm.SELF_SERVICE}

    def get(self, request):
        items = services.pending_for(request.user)
        today = timezone.localdate()
        return Response({"count": len(items), "overdue": sum(1 for a in items if a.ack_due_date and today > a.ack_due_date),
                         "results": [{"id": a.pk, "title": a.title, "category_label": services.CATEGORY_LABELS[a.category],
                                      "ack_due_date": a.ack_due_date} for a in items[:10]]}, headers=NO_STORE)


class ComplianceSummaryView(_View):
    method_permissions = {"get": Perm.ANNOUNCEMENTS_COMPLIANCE}

    def get(self, request):
        return Response({"results": services.summary()}, headers=NO_STORE)


class AnnouncementDetailView(_View):
    method_permissions = {"get": Perm.SELF_SERVICE, "patch": Perm.ANNOUNCEMENTS_MANAGE, "delete": Perm.ANNOUNCEMENTS_MANAGE}

    def get(self, request, pk):
        return Response(services.detail(_get(request.user, pk), request.user), headers=NO_STORE)

    def patch(self, request, pk):
        a = services.update(_get(request.user, pk), _data(request), user=request.user, request=request)
        return Response({"feedback": "Comunicado actualizado.", "announcement": services.detail(a, request.user)}, headers=NO_STORE)

    def delete(self, request, pk):
        services.delete_draft(_get(request.user, pk), user=request.user, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PublishView(_View):
    method_permissions = {"post": Perm.ANNOUNCEMENTS_MANAGE}

    def post(self, request, pk):
        a = services.publish(_get(request.user, pk), user=request.user, request=request)
        return Response({"feedback": f"Comunicado «{a.title}» publicado.", "announcement": services.detail(a, request.user)},
                        headers=NO_STORE)


class ArchiveView(_View):
    method_permissions = {"post": Perm.ANNOUNCEMENTS_MANAGE}

    def post(self, request, pk):
        a = services.archive(_get(request.user, pk), user=request.user, request=request)
        return Response({"feedback": f"Comunicado «{a.title}» archivado.", "announcement": services.detail(a, request.user)},
                        headers=NO_STORE)


class AckView(_View):
    method_permissions = {"post": Perm.SELF_SERVICE}

    def post(self, request, pk):
        a = _get(request.user, pk)
        if not _data(request).get("confirm"):
            raise services.CommsError("Confirme que leyó y comprende el comunicado.", "confirm_required")
        ack = services.acknowledge(a, user=request.user, request=request)
        return Response({"feedback": f"Acuse de recibo registrado el {timezone.localtime(ack.acknowledged_at):%d/%m/%Y %H:%M}.",
                         "announcement": services.detail(a, request.user)}, headers=NO_STORE)


class ComplianceView(_View):
    method_permissions = {"get": Perm.ANNOUNCEMENTS_COMPLIANCE, "post": Perm.ANNOUNCEMENTS_COMPLIANCE}

    def get(self, request, pk):
        a = _get(request.user, pk)
        if not a.requires_ack:
            raise services.CommsError("Este comunicado no requiere acuse de recibo.", "no_ack", 409)
        c = services.compliance(a)
        if request.query_params.get("export") == "csv":
            response = HttpResponse(content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = f'attachment; filename="compliance_comunicado_{a.pk}.csv"'
            response["Cache-Control"] = "no-store"
            response.write("﻿")
            w = csv.writer(response)
            w.writerow(["Comunicado", a.title, "Plazo", a.ack_due_date or "", "Cumplimiento %", c["compliance_pct"]])
            w.writerow(["Usuario", "Nombre", "Rol", "ID corporativo", "Centro de costos", "Estado", "Confirmado", "IP"])
            for r in c["rows"]:
                w.writerow([r["username"], r["name"], r["role"], r["employee_code"] or "", r["cost_center"] or "",
                            STATUS_LABELS[r["status"]],
                            timezone.localtime(r["acknowledged_at"]).strftime("%d/%m/%Y %H:%M") if r["acknowledged_at"] else "",
                            r["ip"] or ""])
            return response
        snaps = [{"taken_at": s.taken_at, "trigger": s.trigger, "trigger_label": s.get_trigger_display(), "audience": s.audience,
                  "acknowledged": s.acknowledged, "pending": s.pending, "overdue": s.overdue, "compliance_pct": s.compliance_pct}
                 for s in a.snapshots.all()[:60]]
        return Response({"announcement": services.brief(a), "status_labels": STATUS_LABELS, **c, "snapshots": snaps}, headers=NO_STORE)

    def post(self, request, pk):
        a = _get(request.user, pk)
        if not a.requires_ack or a.status == Status.DRAFT:
            raise services.CommsError("Solo los comunicados publicados con acuse tienen reporte.", "no_ack", 409)
        s = services.take_snapshot(a, ComplianceSnapshot.Trigger.MANUAL)
        return Response({"feedback": f"Foto del cumplimiento guardada: {s.compliance_pct} %."}, status=status.HTTP_201_CREATED,
                        headers=NO_STORE)
