"""Comunicados en /admin/ (consulta y auditoría; la publicación se hace en el periódico virtual del ERP)."""

from django.contrib import admin

from apps.communications.models import Announcement, AnnouncementAck, ComplianceSnapshot


class _ReadOnly(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Announcement)
class AnnouncementAdmin(_ReadOnly):
    list_display = ("title", "category", "status", "requires_ack", "pinned", "published_at", "ack_due_date")
    list_filter = ("status", "category", "requires_ack")
    search_fields = ("title", "summary")


@admin.register(AnnouncementAck)
class AnnouncementAckAdmin(_ReadOnly):
    list_display = ("announcement", "username", "acknowledged_at", "ip_address", "content_hash")
    list_filter = ("announcement",)
    search_fields = ("username",)


@admin.register(ComplianceSnapshot)
class ComplianceSnapshotAdmin(_ReadOnly):
    list_display = ("announcement", "taken_at", "trigger", "audience", "acknowledged", "pending", "overdue", "compliance_pct")
    list_filter = ("trigger", "announcement")
