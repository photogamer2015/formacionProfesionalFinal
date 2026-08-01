"""Middleware del módulo académico."""
from datetime import datetime

from django.utils import timezone

from .auditoria import registrar_actividad


class UltimaActividadMiddleware:
    """Registra la última actividad del usuario autenticado en su sesión.

    Guarda en la sesión un timestamp ISO (`ultima_actividad`) y el id del
    usuario. Sirve para que el Registro Administrativo muestre quién está
    conectado y cuándo fue su última conexión, sin crear modelos nuevos.

    Para no escribir en la base de datos en cada request, solo actualiza la
    marca si pasó más de 60 segundos desde la última.
    """

    INTERVALO_SEGUNDOS = 60

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user_antes = getattr(request, 'user', None)
        if user_antes is not None and user_antes.is_authenticated:
            ahora = timezone.now()
            actualizar = True
            previa = request.session.get('ultima_actividad')
            if previa:
                try:
                    prev_dt = datetime.fromisoformat(previa)
                    actualizar = (ahora - prev_dt).total_seconds() > self.INTERVALO_SEGUNDOS
                except (ValueError, TypeError):
                    actualizar = True
            if actualizar:
                request.session['ultima_actividad'] = ahora.isoformat()
                request.session['ultima_actividad_uid'] = user_antes.id

        response = self.get_response(request)

        # En el inicio de sesión el usuario todavía era anónimo al entrar al
        # middleware, pero ya está autenticado al volver de la vista. En el
        # cierre de sesión ocurre lo contrario; por eso conservamos primero la
        # cuenta autenticada disponible en cualquiera de los dos momentos.
        user_despues = getattr(request, 'user', None)
        usuario_auditable = (
            user_antes if user_antes is not None and user_antes.is_authenticated
            else user_despues
        )
        registrar_actividad(request, response, usuario_auditable)
        return response
