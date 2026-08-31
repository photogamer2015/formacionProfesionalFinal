"""
Vistas del módulo Comprobante de Venta.

Incluye:
- Menú del módulo (con dos sub-secciones)
- Registrar comprobante (formulario completo, todos los campos obligatorios)
- Lista de comprobantes
- Editar / Eliminar
- Totales de venta (ranking de vendedoras)
"""

from collections import defaultdict
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from .forms import ComprobanteForm
from .models import (
    ARCHIVOS_AVATAR_PERFIL, ARCHIVOS_PORTADA_PERFIL,
    AVATARES_PERFIL, AVATAR_PERFIL_PREDETERMINADO,
    HOBBIES_MURAL, INTERESES_MURAL, MUSICA_MURAL, PELICULAS_MURAL,
    PORTADAS_PERFIL, PORTADA_PERFIL_PREDETERMINADA,
    Comprobante, Curso, Matricula, PerfilUsuario, RecuperacionPendiente,
)
from .permisos import (
    es_admin, es_asesor, matricula_requerida,
)
from .busqueda import filtrar_queryset_busqueda
from .views_social import contexto_social_perfil


User = get_user_model()
MURAL_MAX_SELECCIONES = 6


def _normalizar_rango_fechas(request):
    desde = (request.GET.get('desde') or '').strip()
    hasta = (request.GET.get('hasta') or '').strip()
    desde_fecha = parse_date(desde) if desde else None
    hasta_fecha = parse_date(hasta) if hasta else None

    if desde and desde_fecha is None:
        desde = ''
    if hasta and hasta_fecha is None:
        hasta = ''
    if desde_fecha and hasta_fecha and desde_fecha > hasta_fecha:
        desde_fecha, hasta_fecha = hasta_fecha, desde_fecha
        desde, hasta = desde_fecha.isoformat(), hasta_fecha.isoformat()

    return desde, hasta, desde_fecha, hasta_fecha


def _aplicar_rango_fechas(qs, desde_fecha, hasta_fecha):
    if desde_fecha:
        qs = qs.filter(fecha_inscripcion__gte=desde_fecha)
    if hasta_fecha:
        qs = qs.filter(fecha_inscripcion__lte=hasta_fecha)
    return qs


def _rango_querystring(desde, hasta):
    params = {}
    if desde:
        params['desde'] = desde
    if hasta:
        params['hasta'] = hasta
    return urlencode(params)


def _opciones_mural(opciones, seleccionadas):
    seleccionadas = set(seleccionadas if isinstance(seleccionadas, list) else [])
    return [
        {
            'clave': clave,
            'etiqueta': etiqueta,
            'seleccionada': clave in seleccionadas,
        }
        for clave, etiqueta in opciones
    ]


def _seleccion_mural_valida(request, nombre, opciones):
    valores = list(dict.fromkeys(request.POST.getlist(nombre)))
    claves_validas = {clave for clave, _etiqueta in opciones}
    if len(valores) > MURAL_MAX_SELECCIONES:
        return None
    if any(valor not in claves_validas for valor in valores):
        return None
    return valores


# ═════════════════════════════════════════════════════════════════
# Menú principal del módulo Comprobante
# ═════════════════════════════════════════════════════════════════

@matricula_requerida
def comprobante_menu(request):
    """Menú con las dos sub-secciones: Totales de venta y Registrar comprobante."""
    total_comprobantes = Comprobante.objects.count()
    total_ventas = Comprobante.objects.aggregate(
        s=Sum('pago_abono')
    )['s'] or Decimal('0.00')
    total_pendiente = Comprobante.objects.aggregate(
        s=Sum('diferencia')
    )['s'] or Decimal('0.00')
    total_facturado = total_ventas + total_pendiente

    return render(request, 'comprobantes/menu.html', {
        'total_comprobantes': total_comprobantes,
        'total_ventas': total_ventas,
        'total_pendiente': total_pendiente,
        'total_facturado': total_facturado,
    })


# ═════════════════════════════════════════════════════════════════
# Registrar comprobante
# ═════════════════════════════════════════════════════════════════

@matricula_requerida
@transaction.atomic
def comprobante_registrar(request):
    asesores = User.objects.all().order_by('first_name', 'username')
    error_vendedora = None

    if request.method == 'POST':
        form = ComprobanteForm(request.POST)
        vendedora_id = request.POST.get('vendedora_id')
        
        asesor = User.objects.filter(id=vendedora_id).first()
        if not asesor:
            error_vendedora = 'Debes seleccionar un asesor válido.'
        if form.is_valid() and not error_vendedora:
            comp = form.save(commit=False)
            comp.vendedora = asesor
            full = f'{asesor.first_name} {asesor.last_name}'.strip()
            comp.vendedora_nombre = full or asesor.username
            comp.save()
            messages.success(
                request,
                f'Comprobante registrado a nombre de {comp.nombre_persona}. '
                f'Vendedora: {comp.vendedora_nombre}.'
            )
            return redirect('academia:comprobante_lista')
    else:
        form = ComprobanteForm()

    return render(request, 'comprobantes/form.html', {
        'form': form,
        'modo': 'registrar',
        'titulo': 'Registrar Comprobante',
        'asesores': asesores,
        'error_vendedora': error_vendedora,
    })


# ═════════════════════════════════════════════════════════════════
# Editar comprobante
# ═════════════════════════════════════════════════════════════════

@matricula_requerida
@transaction.atomic
def comprobante_editar(request, pk):
    comp = get_object_or_404(Comprobante, pk=pk)
    asesores = User.objects.all().order_by('first_name', 'username')
    error_vendedora = None

    # Solo el admin o quien lo registró puede editarlo
    if not es_admin(request.user) and comp.vendedora_id != request.user.id:
        messages.error(
            request,
            'Solo puedes editar comprobantes que tú registraste. '
            'Pide ayuda a un administrador.'
        )
        return redirect('academia:comprobante_lista')

    if request.method == 'POST':
        form = ComprobanteForm(request.POST, instance=comp)
        vendedora_id = request.POST.get('vendedora_id')
        
        asesor = User.objects.filter(id=vendedora_id).first()
        if not asesor:
            error_vendedora = 'Debes seleccionar un asesor válido.'
        if form.is_valid() and not error_vendedora:
            comp_updated = form.save(commit=False)
            comp_updated.vendedora = asesor
            full = f'{asesor.first_name} {asesor.last_name}'.strip()
            comp_updated.vendedora_nombre = full or asesor.username
            comp_updated.save()
            messages.success(request, 'Comprobante actualizado correctamente.')
            return redirect('academia:comprobante_lista')
    else:
        form = ComprobanteForm(instance=comp)

    return render(request, 'comprobantes/form.html', {
        'form': form,
        'comprobante': comp,
        'modo': 'editar',
        'titulo': f'Editar Comprobante #{comp.pk}',
        'asesores': asesores,
        'error_vendedora': error_vendedora,
    })


# ═════════════════════════════════════════════════════════════════
# Eliminar comprobante
# ═════════════════════════════════════════════════════════════════

@matricula_requerida
@require_POST
def comprobante_eliminar(request, pk):
    comp = get_object_or_404(Comprobante, pk=pk)

    # Solo admin puede eliminar
    if not es_admin(request.user):
        messages.error(
            request,
            'Solo un administrador puede eliminar comprobantes.'
        )
        return redirect('academia:comprobante_lista')

    nombre = comp.nombre_persona
    comp.delete()
    messages.success(request, f'Comprobante de "{nombre}" eliminado.')
    return redirect('academia:comprobante_lista')


# ═════════════════════════════════════════════════════════════════
# Lista de comprobantes (con filtros)
# ═════════════════════════════════════════════════════════════════

@matricula_requerida
def comprobante_lista(request):
    q = (request.GET.get('q') or '').strip()
    curso_id = (request.GET.get('curso') or '').strip()
    modalidad = (request.GET.get('modalidad') or '').strip()
    factura = (request.GET.get('factura') or '').strip()
    vendedora_id = (request.GET.get('vendedora') or '').strip()

    qs = (
        Comprobante.objects
        .select_related('curso', 'vendedora')
        .all()
    )

    if q:
        qs = filtrar_queryset_busqueda(qs, q, [
            'nombre_persona',
            'celular',
            'fact_cedula',
            'fact_nombres',
            'fact_correo',
            'curso__nombre',
        ])
    if curso_id.isdigit():
        qs = qs.filter(curso_id=int(curso_id))
    if modalidad in ('virtual', 'presencial'):
        qs = qs.filter(modalidad=modalidad)
    if factura in ('si', 'no'):
        qs = qs.filter(factura_realizada=factura)
    if vendedora_id.isdigit():
        qs = qs.filter(vendedora_id=int(vendedora_id))

    # Resumen rápido
    total_count = qs.count()
    suma_pago = qs.aggregate(s=Sum('pago_abono'))['s'] or Decimal('0.00')
    suma_diferencia = qs.aggregate(s=Sum('diferencia'))['s'] or Decimal('0.00')

    # Para los filtros
    cursos = Curso.objects.filter(activo=True).order_by('nombre')
    vendedoras = (
        User.objects
        .filter(comprobantes_registrados__isnull=False)
        .distinct()
        .order_by('first_name', 'username')
    )

    return render(request, 'comprobantes/lista.html', {
        'comprobantes': qs,
        'cursos': cursos,
        'vendedoras': vendedoras,
        'total_count': total_count,
        'suma_pago': suma_pago,
        'suma_diferencia': suma_diferencia,
        'filtros': {
            'q': q,
            'curso': curso_id,
            'modalidad': modalidad,
            'factura': factura,
            'vendedora': vendedora_id,
        },
    })


# ═════════════════════════════════════════════════════════════════
# Totales de venta — Ranking de asesoras
# ═════════════════════════════════════════════════════════════════

@matricula_requerida
def comprobante_totales(request):
    """
    Ranking de vendedoras por número de ventas.

    El administrador también ve los montos; las asesoras reciben únicamente
    cantidades para no exponer información financiera del equipo.
    Permite filtrar por rango de fechas (opcional).
    """
    desde, hasta, desde_fecha, hasta_fecha = _normalizar_rango_fechas(request)
    mostrar_montos = es_admin(request.user)

    qs = _aplicar_rango_fechas(Comprobante.objects.all(), desde_fecha, hasta_fecha)
    rango_querystring = _rango_querystring(desde, hasta)

    # Agrupar por vendedora
    ranking_base = (
        qs.values('vendedora_id', 'vendedora__first_name',
                  'vendedora__last_name', 'vendedora__username')
        .annotate(
            num_ventas=Count('id'),
            ventas_retiro=Count('id', filter=Q(matricula__estado='retiro_voluntario')),
        )
    )
    if mostrar_montos:
        ranking = ranking_base.annotate(
            total_pago=Sum('pago_abono'),
            total_diferencia=Sum('diferencia'),
        ).order_by('-num_ventas', '-total_pago')
    else:
        ranking = ranking_base.order_by(
            '-num_ventas', 'vendedora__first_name', 'vendedora__username',
        )

    # Procesar para template
    ranking_list = []
    for row in ranking:
        nombre = (
            f"{row['vendedora__first_name']} {row['vendedora__last_name']}".strip()
            or row['vendedora__username']
        )
        item = {
            'vendedora_id': row['vendedora_id'],
            'nombre': nombre,
            'num_ventas': row['num_ventas'],
            'ventas_activas': row['num_ventas'] - row['ventas_retiro'],
            'ventas_retiro': row['ventas_retiro'],
        }
        if mostrar_montos:
            pago = row['total_pago'] or Decimal('0.00')
            diferencia = row['total_diferencia'] or Decimal('0.00')
            item.update({
                'total_pago': pago,
                'total_diferencia': diferencia,
                'total_general': pago + diferencia,
            })
        ranking_list.append(item)

    # Totales globales
    total_ventas = qs.count()
    total_retiros = qs.filter(matricula__estado='retiro_voluntario').count()
    total_activas = total_ventas - total_retiros
    total_cobrado = None
    total_pendiente = None
    total_general = None
    if mostrar_montos:
        total_cobrado = qs.aggregate(s=Sum('pago_abono'))['s'] or Decimal('0.00')
        total_pendiente = qs.aggregate(s=Sum('diferencia'))['s'] or Decimal('0.00')
        total_general = total_cobrado + total_pendiente

    # Ranking por curso
    por_curso_base = qs.values('curso_id', 'curso__nombre').annotate(
        num_ventas=Count('id'),
    )
    if mostrar_montos:
        por_curso = por_curso_base.annotate(
            total_pago=Sum('pago_abono'),
        ).order_by('-num_ventas')[:10]
    else:
        por_curso = por_curso_base.order_by('-num_ventas', 'curso__nombre')[:10]

    return render(request, 'comprobantes/totales.html', {
        'ranking': ranking_list,
        'por_curso': por_curso,
        'total_ventas': total_ventas,
        'total_activas': total_activas,
        'total_retiros': total_retiros,
        'total_cobrado': total_cobrado,
        'total_pendiente': total_pendiente,
        'total_general': total_general,
        'mostrar_montos': mostrar_montos,
        'rango_querystring': rango_querystring,
        'filtros': {
            'desde': desde,
            'hasta': hasta,
        },
    })


@matricula_requerida
def comprobante_asesor_ventas(request, vendedora_id):
    """
    Lista las ventas de una vendedora concreta.

    El administrador ve montos; la asesora conserva una vista solo de
    cantidades y datos operativos de la venta.
    """
    asesor = get_object_or_404(User, pk=vendedora_id)
    desde, hasta, desde_fecha, hasta_fecha = _normalizar_rango_fechas(request)
    mostrar_montos = es_admin(request.user)

    ventas = (
        Comprobante.objects
        .filter(vendedora_id=vendedora_id)
        .select_related('curso', 'matricula')
        .order_by('-fecha_inscripcion', '-id')
    )
    ventas = _aplicar_rango_fechas(ventas, desde_fecha, hasta_fecha)

    total_ventas = ventas.count()
    total_retiros = ventas.filter(matricula__estado='retiro_voluntario').count()
    total_activas = total_ventas - total_retiros
    total_cobrado = None
    total_pendiente = None
    total_general = None
    if mostrar_montos:
        total_cobrado = ventas.aggregate(s=Sum('pago_abono'))['s'] or Decimal('0.00')
        total_pendiente = ventas.aggregate(s=Sum('diferencia'))['s'] or Decimal('0.00')
        total_general = total_cobrado + total_pendiente

    rango_querystring = _rango_querystring(desde, hasta)

    return render(request, 'comprobantes/asesor_ventas.html', {
        'asesor': asesor,
        'ventas': ventas,
        'total_ventas': total_ventas,
        'total_activas': total_activas,
        'total_retiros': total_retiros,
        'total_cobrado': total_cobrado,
        'total_pendiente': total_pendiente,
        'total_general': total_general,
        'mostrar_montos': mostrar_montos,
        'rango_querystring': rango_querystring,
        'filtros': {
            'desde': desde,
            'hasta': hasta,
        },
    })


# ═════════════════════════════════════════════════════════════════
# Detalle del Asesor (Perfil)
# ═════════════════════════════════════════════════════════════════

@login_required
def comprobante_asesor_detalle(request, vendedora_id):
    """
    Muestra el perfil social de un usuario registrado.

    La información social es visible para cualquier usuario autenticado. Los
    indicadores, estudiantes y actividad se muestran únicamente en el perfil
    propio para que al consultar otro usuario solo aparezca su tarjeta pública.
    """
    asesor = get_object_or_404(User, pk=vendedora_id)
    es_perfil_propio = asesor.pk == request.user.pk
    puede_ver_actividad_perfil = es_perfil_propio or es_admin(request.user)
    mostrar_detalle_operativo_perfil = (
        es_perfil_propio and puede_ver_actividad_perfil
    )
    editar_mural = (
        es_perfil_propio
        and (request.GET.get('editar_mural') or '').strip() == '1'
    )

    if request.method == 'POST':
        if not es_perfil_propio:
            messages.error(
                request,
                'Solo cada usuario puede personalizar su propio perfil.'
            )
            return redirect(
                'academia:comprobante_asesor_detalle',
                vendedora_id=asesor.pk,
            )

        preferencia = (request.POST.get('preferencia') or '').strip()
        if preferencia == 'mural':
            descripcion_personal = (
                request.POST.get('descripcion_personal') or ''
            ).strip()
            selecciones = {
                'musica_favorita': _seleccion_mural_valida(
                    request, 'musica', MUSICA_MURAL,
                ),
                'hobbies_favoritos': _seleccion_mural_valida(
                    request, 'hobbies', HOBBIES_MURAL,
                ),
                'peliculas_favoritas': _seleccion_mural_valida(
                    request, 'peliculas', PELICULAS_MURAL,
                ),
                'intereses_personales': _seleccion_mural_valida(
                    request, 'intereses', INTERESES_MURAL,
                ),
            }
            if len(descripcion_personal) > 500:
                messages.error(
                    request,
                    'Tu presentación no puede superar los 500 caracteres.',
                )
            elif any(valor is None for valor in selecciones.values()):
                messages.error(
                    request,
                    'Selecciona hasta 6 opciones válidas en cada categoría.',
                )
            else:
                PerfilUsuario.objects.update_or_create(
                    user=asesor,
                    defaults={
                        'descripcion_personal': descripcion_personal,
                        **selecciones,
                    },
                )
                messages.success(
                    request,
                    'Tu mural de Formación EC se actualizó correctamente.',
                )
        elif preferencia == 'portada' or 'portada' in request.POST:
            portada = (request.POST.get('portada') or '').strip()
            portadas_validas = {clave for clave, _etiqueta in PORTADAS_PERFIL}
            if portada not in portadas_validas:
                messages.error(request, 'Selecciona una portada válida.')
            else:
                PerfilUsuario.objects.update_or_create(
                    user=asesor,
                    defaults={'portada': portada},
                )
                messages.success(
                    request,
                    'Tu portada se actualizó correctamente.'
                )
        else:
            avatar = (request.POST.get('avatar') or '').strip()
            avatares_validos = {clave for clave, _etiqueta in AVATARES_PERFIL}
            if avatar not in avatares_validos:
                messages.error(request, 'Selecciona un avatar válido.')
            else:
                PerfilUsuario.objects.update_or_create(
                    user=asesor,
                    defaults={'avatar': avatar},
                )
                messages.success(
                    request,
                    'Tu avatar se actualizó correctamente en todo el sistema.'
                )
        return redirect(
            'academia:comprobante_asesor_detalle',
            vendedora_id=asesor.pk,
        )

    perfil = PerfilUsuario.objects.filter(user=asesor).first()
    avatar_seleccionado = (
        perfil.avatar if perfil else AVATAR_PERFIL_PREDETERMINADO
    )
    portada_seleccionada = (
        perfil.portada if perfil else PORTADA_PERFIL_PREDETERMINADA
    )
    avatares = [
        {
            'clave': clave,
            'etiqueta': etiqueta,
            'archivo': ARCHIVOS_AVATAR_PERFIL[clave],
        }
        for clave, etiqueta in AVATARES_PERFIL
    ]
    portadas = [
        {
            'clave': clave,
            'etiqueta': etiqueta,
            'archivo': ARCHIVOS_PORTADA_PERFIL[clave],
        }
        for clave, etiqueta in PORTADAS_PERFIL
    ]
    descripcion_personal = perfil.descripcion_personal if perfil else ''
    musica_mural = _opciones_mural(
        MUSICA_MURAL,
        perfil.musica_favorita if perfil else [],
    )
    hobbies_mural = _opciones_mural(
        HOBBIES_MURAL,
        perfil.hobbies_favoritos if perfil else [],
    )
    peliculas_mural = _opciones_mural(
        PELICULAS_MURAL,
        perfil.peliculas_favoritas if perfil else [],
    )
    intereses_mural = _opciones_mural(
        INTERESES_MURAL,
        perfil.intereses_personales if perfil else [],
    )
    mural_grupos = [
        ('Música', musica_mural),
        ('Hobbies', hobbies_mural),
        ('Películas y series', peliculas_mural),
        ('Intereses', intereses_mural),
    ]
    mural_grupos_visibles = [
        (
            titulo,
            [opcion for opcion in opciones if opcion['seleccionada']],
        )
        for titulo, opciones in mural_grupos
        if any(opcion['seleccionada'] for opcion in opciones)
    ]
    mural_tiene_gustos = bool(mural_grupos_visibles)
    contexto_social = contexto_social_perfil(request.user, asesor)

    if es_admin(asesor):
        asesor_rol = 'Administrador'
    elif es_asesor(asesor):
        asesor_rol = 'Asesor'
    else:
        asesor_rol = 'Usuario'

    if mostrar_detalle_operativo_perfil:
        comprobantes = (
            Comprobante.objects.filter(
                Q(matricula__vendedora_id=vendedora_id) |
                Q(matricula__vendedora__isnull=True, vendedora_id=vendedora_id)
            )
            .select_related('curso', 'matricula', 'matricula__estudiante')
            .order_by('-fecha_inscripcion', '-id')
        )
        comprobantes_globales = (
            Comprobante.objects
            .select_related('curso', 'matricula', 'matricula__estudiante')
            .order_by('-fecha_inscripcion', '-id')
        )
        comprobantes_retirados_personales = comprobantes.filter(
            matricula__estado='retiro_voluntario',
        )
        comprobantes_retirados = comprobantes_globales.filter(
            matricula__estado='retiro_voluntario',
        )
        comprobantes_pendientes = comprobantes_globales.filter(
            diferencia__gt=Decimal('0.00'),
        ).exclude(
            matricula__estado='retiro_voluntario',
        )
        recuperaciones = RecuperacionPendiente.objects.select_related(
            'matricula', 'matricula__estudiante', 'matricula__curso',
        ).distinct()
        total_ventas = comprobantes.count()
        total_retiros = comprobantes_retirados.count()
        total_activas = total_ventas - comprobantes_retirados_personales.count()
        total_saldos_pendientes = comprobantes_pendientes.count()
        total_recuperaciones = recuperaciones.count()
        registros = (
            Matricula.objects.filter(registrado_por_id=vendedora_id)
            .select_related('curso', 'estudiante')
            .order_by('-fecha_matricula', '-id')
        )
    else:
        comprobantes = Comprobante.objects.none()
        comprobantes_retirados = Comprobante.objects.none()
        comprobantes_pendientes = Comprobante.objects.none()
        recuperaciones = RecuperacionPendiente.objects.none()
        registros = Matricula.objects.none()
        total_ventas = 0
        total_activas = 0
        total_retiros = 0
        total_saldos_pendientes = 0
        total_recuperaciones = 0

    return render(request, 'comprobantes/asesor_detalle.html', {
        'asesor': asesor,
        'comprobantes': comprobantes,
        'registros': registros,
        'total_ventas': total_ventas,
        'total_activas': total_activas,
        'total_retiros': total_retiros,
        'total_saldos_pendientes': total_saldos_pendientes,
        'total_recuperaciones': total_recuperaciones,
        'comprobantes_pendientes': comprobantes_pendientes,
        'comprobantes_retirados': comprobantes_retirados,
        'recuperaciones': recuperaciones,
        'es_perfil_propio': es_perfil_propio,
        'puede_ver_actividad_perfil': puede_ver_actividad_perfil,
        'mostrar_detalle_operativo_perfil': mostrar_detalle_operativo_perfil,
        'editar_mural': editar_mural,
        'asesor_rol': asesor_rol,
        'avatar_seleccionado': avatar_seleccionado,
        'avatar_asesor_archivo': ARCHIVOS_AVATAR_PERFIL.get(
            avatar_seleccionado,
            ARCHIVOS_AVATAR_PERFIL[AVATAR_PERFIL_PREDETERMINADO],
        ),
        'avatares': avatares,
        'portada_seleccionada': portada_seleccionada,
        'portada_asesor_archivo': ARCHIVOS_PORTADA_PERFIL.get(
            portada_seleccionada,
            ARCHIVOS_PORTADA_PERFIL[PORTADA_PERFIL_PREDETERMINADA],
        ),
        'portadas': portadas,
        'descripcion_personal': descripcion_personal,
        'musica_mural': musica_mural,
        'hobbies_mural': hobbies_mural,
        'peliculas_mural': peliculas_mural,
        'intereses_mural': intereses_mural,
        'mural_grupos': mural_grupos,
        'mural_grupos_visibles': mural_grupos_visibles,
        'mural_tiene_gustos': mural_tiene_gustos,
        'mural_max_selecciones': MURAL_MAX_SELECCIONES,
        **contexto_social,
    })
