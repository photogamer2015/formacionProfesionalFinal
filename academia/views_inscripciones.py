"""Pagos de inscripciones: lo que se cobra de inscripción al matricular
(«Reserva / Abono», hasta $10), separado por día como el Registro Estudiantil.

- El día es la fecha de matrícula, igual que en el Registro Estudiantil.
- Cuenta el pago hecho al matricular (el pago inicial: los abonos más antiguos
  con la fecha de la matrícula, misma regla que «Editar pago inicial») de tipo
  «Abono»: un módulo pagado ese mismo día no es inscripción.
- Incluye las matrículas que pasaron al archivo por un cierre de curso, para
  que los días anteriores no se pierdan.
- Es de consulta para todos los roles.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Prefetch
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from .forms_registro_estudiantil import nombre_usuario
from .models import Abono, AbonoArchivado, Matricula, nombre_banco, nombre_metodo_pago
from .permisos import matricula_requerida
from .views_comprobantes import _etiqueta_metodo_pago
from .views_registro_estudiantil import _archivadas, _etiqueta_hoja, _fecha, _modalidad

TIPO_INSCRIPCION = 'reserva_abono'
CERO = Decimal('0.00')


def _abonos_inscripcion(abonos, fecha_matricula):
    """Abonos de la inscripción, de una lista ordenada por creación."""
    bloque = []
    for abono in abonos:
        if abono.fecha != fecha_matricula:
            break
        if abono.tipo_pago == 'abono':
            bloque.append(abono)
    return bloque


def _partes_abono(abono):
    """(método, banco, monto) de un abono; el mixto se separa en dos."""
    monto_2 = abono.monto_2 or CERO
    if monto_2 > 0:
        # En un pago mixto `monto` es el total y `monto_2` la segunda parte.
        return [
            (abono.metodo, abono.banco, abono.monto - monto_2),
            (abono.metodo_2, abono.banco_2, monto_2),
        ]
    return [(abono.metodo, abono.banco, abono.monto)]


def _totales_por_dia():
    """{día: {'cantidad', 'total'}} de todas las inscripciones."""
    dias = defaultdict(lambda: {'cantidad': 0, 'total': CERO})

    vivas = dict(
        Matricula.objects.filter(tipo_matricula=TIPO_INSCRIPCION)
        .values_list('pk', 'fecha_matricula')
    )
    abonos = defaultdict(list)
    for abono in (
        Abono.objects.filter(matricula__tipo_matricula=TIPO_INSCRIPCION)
        .only('matricula_id', 'fecha', 'monto', 'tipo_pago')
        .order_by('matricula_id', 'creado', 'id')
    ):
        abonos[abono.matricula_id].append(abono)

    archivadas = dict(
        _archivadas().filter(tipo_matricula=TIPO_INSCRIPCION)
        .values_list('pk', 'fecha_matricula')
    )
    abonos_archivados = defaultdict(list)
    for abono in (
        AbonoArchivado.objects.filter(matricula_archivada_id__in=_archivadas().filter(
            tipo_matricula=TIPO_INSCRIPCION,
        ).values('pk'))
        .only('matricula_archivada_id', 'fecha', 'monto', 'tipo_pago')
        .order_by('matricula_archivada_id', 'creado_original', 'id')
    ):
        abonos_archivados[abono.matricula_archivada_id].append(abono)

    for fechas, por_matricula in ((vivas, abonos), (archivadas, abonos_archivados)):
        for pk, fecha in fechas.items():
            bloque = _abonos_inscripcion(por_matricula.get(pk, []), fecha)
            if bloque:
                dias[fecha]['cantidad'] += 1
                dias[fecha]['total'] += sum((a.monto for a in bloque), CERO)
    return dias


def _inscripciones_del_dia(dia):
    """Filas de las inscripciones de un día, en el orden en que se registraron."""
    orden = []
    vivas = (
        Matricula.objects.filter(tipo_matricula=TIPO_INSCRIPCION, fecha_matricula=dia)
        .select_related('estudiante', 'curso', 'jornada', 'jornada__sede', 'registrado_por')
        .prefetch_related(Prefetch(
            'abonos', queryset=Abono.objects.order_by('creado', 'id'), to_attr='abonos_orden',
        ))
    )
    for m in vivas:
        bloque = _abonos_inscripcion(m.abonos_orden, m.fecha_matricula)
        if not bloque:
            continue
        jornada = m.jornada
        partes = [
            (nombre_metodo_pago(metodo) or 'Sin método', _etiqueta_metodo_pago(metodo, banco), monto)
            for abono in bloque for metodo, banco, monto in _partes_abono(abono)
        ]
        orden.append(((m.creado, m.pk), {
            'archivada': False,
            'hora': timezone.localtime(m.creado),
            'estudiante': m.estudiante.nombres,
            'cedula': m.estudiante.cedula,
            'curso': m.curso.nombre,
            'modalidad': m.modalidad,
            'modalidad_texto': _modalidad(m.modalidad, jornada.sede_nombre if jornada else ''),
            'jornada': jornada.descripcion_legible if jornada else '',
            'inicio': jornada.fecha_inicio if jornada else None,
            'monto': sum((a.monto for a in bloque), CERO),
            'partes': partes,
            'recibos': [a.numero_recibo for a in bloque if a.numero_recibo],
            'registra': nombre_usuario(m.registrado_por),
            'retiro': m.estado == 'retiro_voluntario',
            'url_pagos': reverse('academia:matricula_abonos', args=[m.pk]),
        }))

    archivadas = (
        _archivadas().filter(tipo_matricula=TIPO_INSCRIPCION, fecha_matricula=dia)
        .prefetch_related(Prefetch(
            'abonos_archivados',
            queryset=AbonoArchivado.objects.order_by('creado_original', 'id'),
            to_attr='abonos_orden',
        ))
    )
    for a in archivadas:
        bloque = _abonos_inscripcion(a.abonos_orden, a.fecha_matricula)
        if not bloque:
            continue
        partes = []
        for abono in bloque:
            metodo = abono.metodo_label or nombre_metodo_pago(abono.metodo) or 'Sin método'
            banco = abono.banco_label or nombre_banco(abono.banco)
            partes.append((metodo, f'{metodo} · {banco}' if banco else metodo, abono.monto))
        creado = a.creado_original or a.archivado_en
        orden.append(((creado, a.pk), {
            'archivada': True,
            'hora': timezone.localtime(creado) if creado else None,
            'estudiante': a.nombres,
            'cedula': a.cedula,
            'curso': a.curso_nombre,
            'modalidad': a.modalidad,
            'modalidad_texto': _modalidad(a.modalidad, a.sede),
            'jornada': a.jornada_descripcion,
            'inicio': a.jornada_fecha_inicio,
            'monto': sum((ab.monto for ab in bloque), CERO),
            'partes': partes,
            'recibos': [ab.numero_recibo for ab in bloque if ab.numero_recibo],
            'registra': a.registrado_por_nombre,
            'retiro': a.estado == 'retiro_voluntario',
            'url_pagos': '',
        }))

    orden.sort(key=lambda item: item[0])
    filas = [fila for _, fila in orden]
    for numero, fila in enumerate(filas, 1):
        fila['numero'] = numero
    return filas


def _pestanas(totales, hoy, seleccionado):
    """Un día por pestaña, del más reciente al más antiguo, con su total."""
    dias = dict(totales)
    for dia in (hoy, seleccionado):
        dias.setdefault(dia, {'cantidad': 0, 'total': CERO})
    pestanas = [
        {
            'fecha': dia,
            'iso': dia.isoformat(),
            'etiqueta': _etiqueta_hoja(dia, hoy),
            'cantidad': datos['cantidad'],
            'total': datos['total'],
            'activa': dia == seleccionado,
            'hoy': dia == hoy,
        }
        for dia, datos in sorted(dias.items(), reverse=True)
    ]
    meses = []
    for pestana in pestanas:
        mes = pestana['fecha'].replace(day=1)
        if not meses or meses[-1]['mes'] != mes:
            meses.append({'mes': mes, 'pestanas': []})
        meses[-1]['pestanas'].append(pestana)
    return pestanas, meses


@matricula_requerida
def matricula_inscripciones(request):
    """Pagos de inscripciones de un día (?dia=AAAA-MM-DD; hoy si falta)."""
    hoy = timezone.localdate()
    dia = _fecha(request.GET.get('dia')) or hoy
    filas = _inscripciones_del_dia(dia)

    total = sum((f['monto'] for f in filas), CERO)
    metodos = {}
    for fila in filas:
        for metodo, _etiqueta, monto in fila['partes']:
            metodos[metodo] = metodos.get(metodo, CERO) + monto
    pestanas, meses = _pestanas(_totales_por_dia(), hoy, dia)

    return render(request, 'matricula/inscripciones.html', {
        'modalidad': 'inscripciones',
        'dia': dia,
        'hoy': hoy,
        'es_hoy': dia == hoy,
        'dia_anterior': dia - timedelta(days=1),
        'dia_siguiente': dia + timedelta(days=1),
        'filas': filas,
        'total': total,
        'cantidad': len(filas),
        'metodos': sorted(metodos.items(), key=lambda item: (-item[1], item[0])),
        'pestanas': pestanas,
        'meses_pestanas': meses,
    })
