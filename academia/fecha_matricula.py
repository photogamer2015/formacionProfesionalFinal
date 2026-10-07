"""Validación de la fecha de matrícula.

Un año mal escrito (2030 en vez de 2026) deja la matrícula y su pago inicial
en otro mes de los reportes. Se aceptan fechas desde FECHA_MINIMA hasta el
último día del mes subsiguiente (en octubre, hasta el 31 de diciembre; en
diciembre, hasta fin de febrero del año siguiente). Al editar solo se revisa
si la fecha cambia, para no bloquear otros cambios en matrículas antiguas que
ya tienen una fecha rara.

La ayuda visual del formulario está en templates/includes/fecha_matricula.html
(calcula el mismo límite).
"""
import calendar
from datetime import date

from django import forms
from django.utils import timezone

FECHA_MINIMA = date(2020, 1, 1)
# Meses hacia adelante que se pueden elegir además del mes actual.
MESES_ADELANTE = 2


def fecha_maxima(hoy=None):
    """Último día del mes subsiguiente a `hoy`."""
    hoy = hoy or timezone.localdate()
    indice = hoy.month - 1 + MESES_ADELANTE
    anio, mes = hoy.year + indice // 12, indice % 12 + 1
    return date(anio, mes, calendar.monthrange(anio, mes)[1])


def validar_fecha_matricula(fecha):
    if fecha is None:
        return fecha
    maxima = fecha_maxima()
    if fecha > maxima:
        raise forms.ValidationError(
            f'La fecha de matrícula ({fecha:%d/%m/%Y}) está muy adelante: se '
            f'aceptan fechas hasta el {maxima:%d/%m/%Y}. Revisa el día, el mes '
            'y el año.'
        )
    if fecha < FECHA_MINIMA:
        raise forms.ValidationError(
            f'La fecha de matrícula ({fecha:%d/%m/%Y}) es demasiado antigua. '
            'Revisa el año.'
        )
    return fecha


def preparar_campo_fecha(campo, fecha_actual=None):
    """Activa la ayuda visual y limita el calendario a fechas válidas.

    Si la matrícula ya tiene una fecha fuera de rango, ese límite se omite para
    que el navegador no impida guardar otros cambios sin tocar la fecha.
    """
    hoy = timezone.localdate()
    maxima = fecha_maxima(hoy)
    attrs = campo.widget.attrs
    attrs['data-fecha-matricula'] = ''
    attrs['data-hoy'] = hoy.isoformat()
    attrs['data-minima'] = FECHA_MINIMA.isoformat()
    if fecha_actual:
        attrs['data-original'] = fecha_actual.isoformat()
    if not fecha_actual or fecha_actual <= maxima:
        attrs['max'] = maxima.isoformat()
    if not fecha_actual or fecha_actual >= FECHA_MINIMA:
        attrs['min'] = FECHA_MINIMA.isoformat()
