"""Cuentas de usuario: NO se administran en /admin/ (Fase 5).

Las cuentas se crean vinculadas a un empleado desde la aplicación (alta de empleado o
ficha del expediente) y se gestionan con la API de usuarios, donde se aplican la matriz
RBAC, la prevención de escalamiento de privilegios, las contraseñas temporales y la
auditoría. El admin queda reservado a parámetros de sesión, cliente web y auditoría
(apps/system/admin.py). Las cuentas técnicas de superusuario se crean con
`python manage.py createsuperuser`.
"""

from django.contrib import admin
from django.contrib.auth.models import Group

# Los permisos se derivan del rol (apps/accounts/roles.py): los grupos de Django no se usan.
if admin.site.is_registered(Group):
    admin.site.unregister(Group)
