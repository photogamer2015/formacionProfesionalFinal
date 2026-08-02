"""
Context processor que expone los roles del usuario en TODOS los templates.

Uso en plantillas:
    {% if es_admin %}...{% endif %}
    {% if es_asesor %}...{% endif %}
    {% if puede_editar_cursos %}...{% endif %}
"""
from .permisos import (
    es_admin as _es_admin,
    es_asesor as _es_asesor,
    puede_agregar_categorias as _puede_agregar_categorias,
    puede_agregar_cursos as _puede_agregar_cursos,
    puede_cambiar_cursos as _puede_cambiar_cursos,
    puede_editar_cursos as _puede_editar_cursos,
    puede_eliminar_categorias as _puede_eliminar_categorias,
    puede_eliminar_cursos as _puede_eliminar_cursos,
    puede_gestionar_matriculas as _puede_gestionar_matriculas,
    puede_gestionar_jornadas as _puede_gestionar_jornadas,
)


def roles(request):
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {
            'es_admin': False,
            'es_asesor': False,
            'puede_editar_cursos': False,
            'puede_agregar_cursos': False,
            'puede_cambiar_cursos': False,
            'puede_eliminar_cursos': False,
            'puede_agregar_categorias': False,
            'puede_eliminar_categorias': False,
            'puede_gestionar_matriculas': False,
            'puede_gestionar_jornadas': False,
            'rol_actual': '',
        }

    es_a = _es_admin(user)
    es_s = _es_asesor(user)
    if es_a:
        rol_actual = 'Administrador'
    elif es_s:
        rol_actual = 'Asesor'
    else:
        rol_actual = 'Usuario'

    return {
        'es_admin': es_a,
        'es_asesor': es_s,
        'puede_editar_cursos': _puede_editar_cursos(user),
        'puede_agregar_cursos': _puede_agregar_cursos(user),
        'puede_cambiar_cursos': _puede_cambiar_cursos(user),
        'puede_eliminar_cursos': _puede_eliminar_cursos(user),
        'puede_agregar_categorias': _puede_agregar_categorias(user),
        'puede_eliminar_categorias': _puede_eliminar_categorias(user),
        'puede_gestionar_matriculas': _puede_gestionar_matriculas(user),
        'puede_gestionar_jornadas': _puede_gestionar_jornadas(user),
        'rol_actual': rol_actual,
    }


def feature_flags(request):
    """Expone flags de funcionalidad a todos los templates."""
    from .views import MATRICULA_ONLINE_HABILITADA
    return {
        'matricula_online_habilitada': MATRICULA_ONLINE_HABILITADA,
    }


def recordatorios(request):
    """
    Expone a TODOS los templates los recordatorios no leídos dirigidos al
    usuario actual, para alimentar la campana de notificación del encabezado.

    Variables:
        recordatorios_no_leidos      → queryset de recordatorios pendientes
        recordatorios_no_leidos_n    → cantidad (para el badge de la campana)
    """
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {
            'recordatorios_no_leidos': [],
            'recordatorios_no_leidos_n': 0,
            'solicitudes_amistad_pendientes': [],
            'solicitudes_amistad_pendientes_n': 0,
            'notificaciones_no_leidas_n': 0,
        }
    try:
        from django.db.models import Q
        from .models import AmistadUsuario, Recordatorio

        pendientes = list(Recordatorio.no_leidos_de(user)[:20])
        solicitudes = list(
            AmistadUsuario.objects
            .filter(
                Q(usuario_a=user) | Q(usuario_b=user),
                estado='pendiente',
            )
            .exclude(solicitada_por=user)
            .select_related(
                'solicitada_por', 'solicitada_por__perfil_visual',
                'usuario_a', 'usuario_b',
            )[:20]
        )
    except Exception:
        # Si el modelo aún no está migrado, no rompemos el render.
        pendientes = []
        solicitudes = []
    return {
        'recordatorios_no_leidos': pendientes,
        'recordatorios_no_leidos_n': len(pendientes),
        'solicitudes_amistad_pendientes': solicitudes,
        'solicitudes_amistad_pendientes_n': len(solicitudes),
        'notificaciones_no_leidas_n': len(pendientes) + len(solicitudes),
    }


def perfil_usuario(request):
    """Avatar del usuario autenticado para el encabezado global."""
    from .models import (
        ARCHIVOS_AVATAR_PERFIL,
        AVATAR_PERFIL_PREDETERMINADO,
        PerfilUsuario,
    )

    archivo_predeterminado = ARCHIVOS_AVATAR_PERFIL[
        AVATAR_PERFIL_PREDETERMINADO
    ]
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {
            'perfil_avatar': AVATAR_PERFIL_PREDETERMINADO,
            'perfil_avatar_archivo': archivo_predeterminado,
        }

    try:
        avatar = (
            PerfilUsuario.objects
            .filter(user_id=user.pk)
            .values_list('avatar', flat=True)
            .first()
        ) or AVATAR_PERFIL_PREDETERMINADO
    except Exception:
        # La cabecera sigue funcionando aunque la migración aún no se aplique.
        avatar = AVATAR_PERFIL_PREDETERMINADO

    return {
        'perfil_avatar': avatar,
        'perfil_avatar_archivo': ARCHIVOS_AVATAR_PERFIL.get(
            avatar,
            archivo_predeterminado,
        ),
    }
    
