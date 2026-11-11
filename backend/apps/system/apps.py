from django.apps import AppConfig


class SystemConfig(AppConfig):
    name = "apps.system"
    label = "system"
    verbose_name = "Plataforma: sesiones, cliente web y auditoría"

    def ready(self):
        from apps.system import signals  # noqa: F401  (registra receptores de login/logout)
