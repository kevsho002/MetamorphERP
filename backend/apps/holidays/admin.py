from django.contrib import admin

from apps.holidays.models import Holiday, HolidaySegment


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ("date", "name", "kind", "country", "premium_percent", "is_active")
    list_filter = ("kind", "is_active")
    search_fields = ("name",)


@admin.register(HolidaySegment)
class HolidaySegmentAdmin(admin.ModelAdmin):
    list_display = ("shift_date", "employee", "holiday", "worked_seconds", "premium_percent")
    readonly_fields = [f.name for f in HolidaySegment._meta.fields]

    def has_add_permission(self, request):
        return False
