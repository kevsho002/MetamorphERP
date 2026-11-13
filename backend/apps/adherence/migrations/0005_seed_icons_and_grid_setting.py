"""Fase 17: iconos de la barra de segmentos para las actividades de referencia y configuración global de la grilla."""

from django.db import migrations

ICONS = {"PRODUCTION": "headset", "BACK_OFFICE": "inbox", "BREAK": "coffee", "MEAL": "utensils", "TRAINING": "school",
         "COACHING": "chat", "MEETING": "users"}


def seed(apps, schema_editor):
    ActivityType = apps.get_model("adherence", "ActivityType")
    for code, icon in ICONS.items():
        ActivityType.objects.filter(code=code, icon="clock").update(icon=icon)
    GridSetting = apps.get_model("adherence", "GridSetting")
    if not GridSetting.objects.filter(group__isnull=True).exists():
        GridSetting.objects.create(group=None, interval_minutes=15, snap_minutes=5, margin_hours=1)


def unseed(apps, schema_editor):
    apps.get_model("adherence", "GridSetting").objects.filter(group__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("adherence", "0004_activitytype_icon_activityclient_and_more")]

    operations = [migrations.RunPython(seed, unseed)]
