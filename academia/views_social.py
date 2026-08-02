"""Funciones sociales de los perfiles de usuarios."""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .models import AmistadUsuario, MeGustaPerfil, avatar_archivo_usuario
from .permisos import es_admin, es_asesor


User = get_user_model()


def _nombre_usuario(user):
    return user.get_full_name().strip() or user.get_username()


def _rol_usuario(user):
    if es_admin(user):
        return 'Administrador'
    if es_asesor(user):
        return 'Asesor'
    return 'Usuario'


def _ids_amistad(user_a, user_b):
    return tuple(sorted((user_a.pk, user_b.pk)))


def relacion_entre(user_a, user_b):
    if not user_a.pk or not user_b.pk or user_a.pk == user_b.pk:
        return None
    usuario_a_id, usuario_b_id = _ids_amistad(user_a, user_b)
    return (
        AmistadUsuario.objects
        .filter(usuario_a_id=usuario_a_id, usuario_b_id=usuario_b_id)
        .select_related(
            'usuario_a', 'usuario_a__perfil_visual',
            'usuario_b', 'usuario_b__perfil_visual',
            'solicitada_por', 'solicitada_por__perfil_visual',
        )
        .first()
    )


def amigos_de(user):
    relaciones = (
        AmistadUsuario.objects
        .filter(
            Q(usuario_a=user) | Q(usuario_b=user),
            estado='aceptada',
        )
        .select_related(
            'usuario_a', 'usuario_a__perfil_visual',
            'usuario_b', 'usuario_b__perfil_visual',
        )
    )
    amigos = []
    for relacion in relaciones:
        amigo = relacion.otro_usuario(user)
        if not amigo or not amigo.is_active:
            continue
        amigos.append({
            'user': amigo,
            'nombre': _nombre_usuario(amigo),
            'rol': _rol_usuario(amigo),
            'avatar_archivo': avatar_archivo_usuario(amigo),
        })
    return sorted(amigos, key=lambda item: item['nombre'].casefold())


def contexto_social_perfil(usuario_actual, perfil_usuario):
    amigos = amigos_de(perfil_usuario)
    relacion = relacion_entre(usuario_actual, perfil_usuario)

    if usuario_actual.pk == perfil_usuario.pk:
        estado_amistad = 'propio'
    elif relacion is None:
        estado_amistad = 'sin_relacion'
    elif relacion.estado == 'aceptada':
        estado_amistad = 'amigos'
    elif relacion.solicitada_por_id == usuario_actual.pk:
        estado_amistad = 'solicitud_enviada'
    else:
        estado_amistad = 'solicitud_recibida'

    return {
        'amigos_perfil': amigos,
        'total_amigos': len(amigos),
        'total_me_gusta': MeGustaPerfil.objects.filter(
            perfil=perfil_usuario,
        ).count(),
        'dio_me_gusta': (
            usuario_actual.pk != perfil_usuario.pk
            and MeGustaPerfil.objects.filter(
                usuario=usuario_actual,
                perfil=perfil_usuario,
            ).exists()
        ),
        'relacion_amistad': relacion,
        'estado_amistad': estado_amistad,
    }


@login_required
@require_GET
def buscar_amigos(request):
    """Busca usuarios activos sin distinguir mayúsculas de minúsculas."""
    consulta = (request.GET.get('q') or '').strip()[:80]
    usuarios = User.objects.filter(is_active=True).exclude(pk=request.user.pk)

    for termino in consulta.split():
        usuarios = usuarios.filter(
            Q(username__icontains=termino)
            | Q(first_name__icontains=termino)
            | Q(last_name__icontains=termino)
        )

    usuarios = list(
        usuarios
        .select_related('perfil_visual')
        .order_by('first_name', 'last_name', 'username')[:20]
    )
    ids_usuarios = [usuario.pk for usuario in usuarios]
    relaciones = (
        AmistadUsuario.objects
        .filter(
            Q(usuario_a=request.user, usuario_b_id__in=ids_usuarios)
            | Q(usuario_b=request.user, usuario_a_id__in=ids_usuarios)
        )
        .select_related('solicitada_por')
    )
    relaciones_por_usuario = {
        relacion.otro_usuario(request.user).pk: relacion
        for relacion in relaciones
    }

    resultados = []
    for usuario in usuarios:
        relacion = relaciones_por_usuario.get(usuario.pk)
        if relacion is None:
            estado = 'sin_relacion'
        elif relacion.estado == 'aceptada':
            estado = 'amigos'
        elif relacion.solicitada_por_id == request.user.pk:
            estado = 'solicitud_enviada'
        else:
            estado = 'solicitud_recibida'

        resultados.append({
            'id': usuario.pk,
            'nombre': _nombre_usuario(usuario),
            'username': usuario.get_username(),
            'rol': _rol_usuario(usuario),
            'avatar': static(avatar_archivo_usuario(usuario)),
            'perfil_url': reverse(
                'academia:comprobante_asesor_detalle',
                args=[usuario.pk],
            ),
            'solicitar_url': reverse(
                'academia:amistad_solicitar',
                args=[usuario.pk],
            ),
            'accion_url': (
                reverse('academia:amistad_accion', args=[relacion.pk])
                if relacion else ''
            ),
            'estado': estado,
        })

    return JsonResponse({'resultados': resultados, 'consulta': consulta})


@login_required
@require_POST
def amistad_solicitar(request, usuario_id):
    destinatario = get_object_or_404(User, pk=usuario_id, is_active=True)
    if destinatario.pk == request.user.pk:
        messages.error(request, 'No puedes enviarte una solicitud de amistad.')
        return redirect(
            'academia:comprobante_asesor_detalle',
            vendedora_id=request.user.pk,
        )

    usuario_a_id, usuario_b_id = _ids_amistad(request.user, destinatario)
    try:
        with transaction.atomic():
            relacion, creada = AmistadUsuario.objects.get_or_create(
                usuario_a_id=usuario_a_id,
                usuario_b_id=usuario_b_id,
                defaults={
                    'solicitada_por': request.user,
                    'estado': 'pendiente',
                },
            )
    except IntegrityError:
        relacion = AmistadUsuario.objects.get(
            usuario_a_id=usuario_a_id,
            usuario_b_id=usuario_b_id,
        )
        creada = False

    nombre = _nombre_usuario(destinatario)
    if creada:
        messages.success(request, f'Solicitud de amistad enviada a {nombre}.')
    elif relacion.estado == 'aceptada':
        messages.info(request, f'{nombre} ya forma parte de tus amigos.')
    elif relacion.solicitada_por_id == request.user.pk:
        messages.info(request, f'La solicitud para {nombre} ya está pendiente.')
    else:
        messages.info(
            request,
            f'{nombre} ya te envió una solicitud. Puedes aceptarla en la campana.',
        )

    return redirect(
        'academia:comprobante_asesor_detalle',
        vendedora_id=destinatario.pk,
    )


@login_required
@require_POST
def amistad_accion(request, pk):
    relacion = get_object_or_404(
        AmistadUsuario.objects.select_related('usuario_a', 'usuario_b'),
        pk=pk,
    )
    if request.user.pk not in {relacion.usuario_a_id, relacion.usuario_b_id}:
        messages.error(request, 'No tienes permiso para modificar esta amistad.')
        return redirect('academia:bienvenida')

    otro_usuario = relacion.otro_usuario(request.user)
    accion = (request.POST.get('accion') or '').strip()

    if accion == 'aceptar':
        if relacion.estado != 'pendiente' or relacion.solicitada_por_id == request.user.pk:
            messages.error(request, 'Esta solicitud no puede ser aceptada por tu usuario.')
        else:
            relacion.estado = 'aceptada'
            relacion.save(update_fields=['estado', 'actualizada'])
            messages.success(
                request,
                f'Ahora tú y {_nombre_usuario(otro_usuario)} son amigos.',
            )
    elif accion == 'rechazar':
        if relacion.estado != 'pendiente' or relacion.solicitada_por_id == request.user.pk:
            messages.error(request, 'Esta solicitud no puede ser rechazada por tu usuario.')
        else:
            nombre = _nombre_usuario(otro_usuario)
            relacion.delete()
            messages.info(request, f'Rechazaste la solicitud de {nombre}.')
    elif accion == 'cancelar':
        if relacion.estado != 'pendiente' or relacion.solicitada_por_id != request.user.pk:
            messages.error(request, 'Esta solicitud no puede ser cancelada.')
        else:
            relacion.delete()
            messages.info(request, 'La solicitud de amistad fue cancelada.')
    elif accion == 'eliminar':
        if relacion.estado != 'aceptada':
            messages.error(request, 'La amistad seleccionada no está activa.')
        else:
            nombre = _nombre_usuario(otro_usuario)
            relacion.delete()
            messages.info(request, f'{nombre} fue eliminado de tus amigos.')
    else:
        messages.error(request, 'Selecciona una acción de amistad válida.')

    return redirect(
        'academia:comprobante_asesor_detalle',
        vendedora_id=otro_usuario.pk,
    )


@login_required
@require_POST
def perfil_me_gusta(request, usuario_id):
    perfil = get_object_or_404(User, pk=usuario_id, is_active=True)
    if perfil.pk == request.user.pk:
        messages.error(request, 'No puedes indicar que te gusta tu propio perfil.')
    else:
        me_gusta, creado = MeGustaPerfil.objects.get_or_create(
            usuario=request.user,
            perfil=perfil,
        )
        if creado:
            messages.success(request, f'Te gusta el perfil de {_nombre_usuario(perfil)}.')
        else:
            me_gusta.delete()
            messages.info(request, 'Quitaste tu me gusta de este perfil.')

    return redirect(
        'academia:comprobante_asesor_detalle',
        vendedora_id=perfil.pk,
    )
