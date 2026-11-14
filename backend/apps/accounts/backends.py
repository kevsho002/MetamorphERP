"""Fase 25 — Backend de autenticación que respeta el bloqueo de cuentas.

Igual que ModelBackend (usuario inactivo = no autentica) y, además, una cuenta BLOQUEADA (intentos fallidos o
bloqueo administrativo) tampoco supera la autenticación, aunque la contraseña sea correcta. Aplica por igual al
login del SPA, al de /admin/ y a cada request con sesión (get_user).
"""

from django.contrib.auth.backends import ModelBackend


class LockAwareModelBackend(ModelBackend):
    def user_can_authenticate(self, user):
        return super().user_can_authenticate(user) and getattr(user, "locked_at", None) is None
