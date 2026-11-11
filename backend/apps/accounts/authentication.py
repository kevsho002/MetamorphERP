from rest_framework import authentication


class SessionAuthentication(authentication.SessionAuthentication):
    """Sesión de Django + CSRF obligatorio en métodos no seguros.

    A diferencia de la clase base, declara un esquema en WWW-Authenticate para
    que DRF responda 401 (no autenticado) en lugar de 403 (sin permiso): el SPA
    distingue así "inicie sesión" de "su rol no lo permite".
    """

    def authenticate_header(self, request):
        return 'Session realm="api"'
