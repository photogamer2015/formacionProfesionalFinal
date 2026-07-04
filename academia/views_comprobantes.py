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

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import ComprobanteForm
from .models import Comprobante, Curso, Matricula
from .permisos import matricula_requerida, admin_requerido, es_admin


User = get_user_model()


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
        qs = qs.filter(
            Q(nombre_persona__icontains=q)
            | Q(celular__icontains=q)
            | Q(fact_cedula__icontains=q)
            | Q(fact_nombres__icontains=q)
            | Q(fact_correo__icontains=q)
            | Q(curso__nombre__icontains=q)
        )
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

@admin_requerido
def comprobante_totales(request):
    """
    Ranking de vendedoras: cuántas ventas hizo cada una y por cuánto.
    Permite filtrar por rango de fechas (opcional).

    NOTA: Este ranking comparativo del equipo es exclusivo del administrador.
    Los asesores solo pueden ver su propio perfil de ventas.
    """
    desde = (request.GET.get('desde') or '').strip()
    hasta = (request.GET.get('hasta') or '').strip()

    qs = Comprobante.objects.all()
    if desde:
        qs = qs.filter(fecha_inscripcion__gte=desde)
    if hasta:
        qs = qs.filter(fecha_inscripcion__lte=hasta)

    # Agrupar por vendedora
    ranking = (
        qs.values('vendedora_id', 'vendedora__first_name',
                  'vendedora__last_name', 'vendedora__username')
        .annotate(
            num_ventas=Count('id'),
            total_pago=Sum('pago_abono'),
            total_diferencia=Sum('diferencia'),
            ventas_retiro=Count('id', filter=Q(matricula__estado='retiro_voluntario')),
        )
        .order_by('-num_ventas', '-total_pago')
    )

    # Procesar para template
    ranking_list = []
    for row in ranking:
        nombre = (
            f"{row['vendedora__first_name']} {row['vendedora__last_name']}".strip()
            or row['vendedora__username']
        )
        pago = row['total_pago'] or Decimal('0.00')
        dif = row['total_diferencia'] or Decimal('0.00')
        ranking_list.append({
            'vendedora_id': row['vendedora_id'],
            'nombre': nombre,
            'num_ventas': row['num_ventas'],
            'ventas_activas': row['num_ventas'] - row['ventas_retiro'],
            'ventas_retiro': row['ventas_retiro'],
            'total_pago': pago,
            'total_diferencia': dif,
            'total_general': pago + dif,
        })

    # Totales globales
    total_ventas = qs.count()
    total_retiros = qs.filter(matricula__estado='retiro_voluntario').count()
    total_activas = total_ventas - total_retiros
    total_cobrado = qs.aggregate(s=Sum('pago_abono'))['s'] or Decimal('0.00')
    total_pendiente = qs.aggregate(s=Sum('diferencia'))['s'] or Decimal('0.00')
    total_general = total_cobrado + total_pendiente

    # Ranking por curso
    por_curso = (
        qs.values('curso_id', 'curso__nombre')
        .annotate(
            num_ventas=Count('id'),
            total_pago=Sum('pago_abono'),
        )
        .order_by('-num_ventas')[:10]
    )

    return render(request, 'comprobantes/totales.html', {
        'ranking': ranking_list,
        'por_curso': por_curso,
        'total_ventas': total_ventas,
        'total_activas': total_activas,
        'total_retiros': total_retiros,
        'total_cobrado': total_cobrado,
        'total_pendiente': total_pendiente,
        'total_general': total_general,
        'filtros': {
            'desde': desde,
            'hasta': hasta,
        },
    })


# ═════════════════════════════════════════════════════════════════
# Detalle del Asesor (Perfil)
# ═════════════════════════════════════════════════════════════════

@matricula_requerida
def comprobante_asesor_detalle(request, vendedora_id):
    """
    Muestra la lista de estudiantes matriculados por una vendedora en particular.

    El administrador puede ver el perfil de cualquier asesor. Un asesor solo
    puede ver su propio perfil; si intenta abrir el de otra persona, se le
    redirige a su propio detalle.
    """
    if not es_admin(request.user) and int(vendedora_id) != request.user.id:
        messages.error(
            request,
            'Solo puedes ver tu propio perfil de ventas.'
        )
        return redirect('academia:comprobante_asesor_detalle', vendedora_id=request.user.id)

    asesor = get_object_or_404(User, pk=vendedora_id)
    comprobantes = (
        Comprobante.objects.filter(
            Q(matricula__vendedora_id=vendedora_id) |
            Q(matricula__vendedora__isnull=True, vendedora_id=vendedora_id)
        )
        .select_related('curso', 'matricula', 'matricula__estudiante')
        .order_by('-fecha_inscripcion', '-id')
    )

    total_ventas = comprobantes.count()
    total_retiros = comprobantes.filter(matricula__estado='retiro_voluntario').count()
    total_activas = total_ventas - total_retiros

    suma_pago = comprobantes.aggregate(s=Sum('pago_abono'))['s'] or Decimal('0.00')
    suma_diferencia = comprobantes.aggregate(s=Sum('diferencia'))['s'] or Decimal('0.00')

    registros = (
        Matricula.objects.filter(registrado_por_id=vendedora_id)
        .select_related('curso', 'estudiante')
        .order_by('-fecha_matricula', '-id')
    )

    return render(request, 'comprobantes/asesor_detalle.html', {
        'asesor': asesor,
        'comprobantes': comprobantes,
        'registros': registros,
        'total_ventas': total_ventas,
        'total_activas': total_activas,
        'total_retiros': total_retiros,
        'suma_pago': suma_pago,
        'suma_diferencia': suma_diferencia,
    })
