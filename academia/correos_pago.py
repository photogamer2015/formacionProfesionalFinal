"""Envío idempotente de recordatorios de pago a estudiantes."""

from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
import logging
import os
import smtplib

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from .authentication import EmailCodeDeliveryError, config_correo_mfa
from .models import RecordatorioPagoCorreo


logger = logging.getLogger(__name__)


class RecordatorioPagoEmailError(Exception):
    """Error controlado al preparar o enviar recordatorios de pago."""


def _env(name, default=''):
    return (os.environ.get(name, default) or '').strip()


def _correo_valido(correo):
    correo = (correo or '').strip().lower()
    if not correo:
        return ''
    try:
        validate_email(correo)
    except ValidationError:
        return ''
    return correo


def _contexto_recordatorio(alerta):
    estudiante = alerta['estudiante']
    curso = alerta['curso']
    numero_modulo = alerta['numero_modulo']
    total_modulos = alerta.get('total_modulos') or 1
    hito = alerta.get('hito') or 'modulo'

    if hito == 'pago_unico':
        pago_correspondiente = 'Pago único del curso'
    elif hito == 'saldo_restante':
        pago_correspondiente = 'Saldo restante del curso'
    elif total_modulos > 1:
        pago_correspondiente = f'Módulo {numero_modulo} de {total_modulos}'
    else:
        pago_correspondiente = 'Pago del curso'

    monto = Decimal(alerta.get('saldo_m1') or '0.00').quantize(
        Decimal('0.01')
    )
    saldo_total = Decimal(alerta.get('saldo_total') or '0.00').quantize(
        Decimal('0.01')
    )
    return {
        'nombre_estudiante': estudiante.nombre_completo,
        'curso_nombre': curso.nombre,
        'modalidad': alerta.get('modalidad_label') or 'Online',
        'pago_correspondiente': pago_correspondiente,
        'fecha_pago': alerta['fecha_pago'],
        'monto': monto,
        'saldo_total': saldo_total,
    }


def _crear_mensaje(alerta, destinatario, config, fecha_envio):
    contexto = _contexto_recordatorio(alerta)
    contexto['recordatorio_atrasado'] = alerta['fecha_alerta'] < fecha_envio
    from_name = _env(
        'PAYMENT_REMINDER_EMAIL_FROM_NAME',
        _env('MFA_EMAIL_FROM_NAME', 'Formación Profesional EC'),
    )
    reply_to = _env(
        'PAYMENT_REMINDER_EMAIL_REPLY_TO',
        _env('MFA_EMAIL_REPLY_TO', config['from_email']),
    )
    sender_domain = config['from_email'].partition('@')[2] or None

    message = EmailMessage()
    message['Subject'] = (
        f'Recordatorio de pago — {contexto["curso_nombre"]}'
    )
    message['From'] = formataddr((from_name, config['from_email']))
    message['To'] = destinatario
    message['Reply-To'] = reply_to
    message['Date'] = formatdate(localtime=True)
    message['Message-ID'] = make_msgid(domain=sender_domain)
    message.set_content(render_to_string(
        'correos/recordatorio_pago.txt', contexto,
    ))
    message.add_alternative(render_to_string(
        'correos/recordatorio_pago.html', contexto,
    ), subtype='html')
    return message


@contextmanager
def _conexion_smtp(config):
    timeout = getattr(settings, 'PAYMENT_REMINDER_EMAIL_TIMEOUT', 15)
    server = None
    try:
        if config['use_ssl']:
            server = smtplib.SMTP_SSL(
                config['host'], config['port'], timeout=timeout,
            )
        else:
            server = smtplib.SMTP(
                config['host'], config['port'], timeout=timeout,
            )
            if config['use_tls']:
                server.starttls()
        server.login(config['username'], config['password'])
        yield server
    except Exception as exc:
        raise RecordatorioPagoEmailError(
            'No se pudo conectar con el servidor de correo.'
        ) from exc
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass


@transaction.atomic
def _reservar_envio(alerta, destinatario):
    """Reserva un envío y evita duplicados entre procesos concurrentes."""
    ahora = timezone.now()
    matricula = alerta['matricula']
    numero_modulo = alerta['numero_modulo']
    monto = Decimal(alerta.get('saldo_m1') or '0.00').quantize(
        Decimal('0.01')
    )
    registro, creado = RecordatorioPagoCorreo.objects.get_or_create(
        matricula=matricula,
        numero_modulo=numero_modulo,
        fecha_alerta=alerta['fecha_alerta'],
        defaults={
            'fecha_pago': alerta['fecha_pago'],
            'destinatario': destinatario,
            'monto': monto,
            'estado': RecordatorioPagoCorreo.ESTADO_PROCESANDO,
            'intentos': 1,
        },
    )
    if creado:
        return registro

    if registro.estado == RecordatorioPagoCorreo.ESTADO_ENVIADO:
        return None

    # Una reserva reciente pertenece a otro proceso que todavía está enviando.
    if (
        registro.estado == RecordatorioPagoCorreo.ESTADO_PROCESANDO
        and registro.actualizado >= ahora - timedelta(minutes=10)
    ):
        return None

    registro.fecha_pago = alerta['fecha_pago']
    registro.destinatario = destinatario
    registro.monto = monto
    registro.estado = RecordatorioPagoCorreo.ESTADO_PROCESANDO
    registro.intentos += 1
    registro.ultimo_error = ''
    registro.save(update_fields=[
        'fecha_pago', 'destinatario', 'monto', 'estado', 'intentos',
        'ultimo_error', 'actualizado',
    ])
    return registro


def _marcar_fallido(registro, error):
    RecordatorioPagoCorreo.objects.filter(pk=registro.pk).update(
        estado=RecordatorioPagoCorreo.ESTADO_FALLIDO,
        ultimo_error=str(error)[:1000],
        actualizado=timezone.now(),
    )


def _marcar_enviado(registro):
    ahora = timezone.now()
    RecordatorioPagoCorreo.objects.filter(pk=registro.pk).update(
        estado=RecordatorioPagoCorreo.ESTADO_ENVIADO,
        ultimo_error='',
        enviado_en=ahora,
        actualizado=ahora,
    )


def enviar_recordatorios_pago(
    alertas, *, fecha_envio=None, forzar=False, simular=False,
):
    """Envía una vez los avisos que corresponden a la fecha de ejecución.

    Recibe las mismas alertas que alimentan el panel de inicio. Los correos
    vacíos o inválidos se omiten y una falla SMTP queda registrada para que
    una ejecución posterior del mismo día pueda reintentarla. Si la matrícula
    acaba de crearse con una fecha ya vencida, envía el primer aviso pendiente
    inmediatamente; las matrículas antiguas no generan una salida masiva.
    """
    fecha_envio = fecha_envio or timezone.localdate()
    resumen = {
        'candidatos': 0,
        'enviados': 0,
        'duplicados': 0,
        'sin_correo': 0,
        'fallidos': 0,
        'atrasados_nuevos': 0,
        'deshabilitado': False,
    }

    seleccionados = []
    for alerta in alertas:
        fecha_alerta = alerta.get('fecha_alerta')
        if not fecha_alerta or fecha_alerta > fecha_envio:
            continue
        es_fecha_exacta = fecha_alerta == fecha_envio
        matricula = alerta['matricula']
        es_alta_nueva_atrasada = (
            fecha_alerta < fecha_envio
            and timezone.localdate(matricula.creado) == fecha_envio
        )
        if not es_fecha_exacta and not es_alta_nueva_atrasada:
            continue
        destinatario = _correo_valido(alerta['estudiante'].correo)
        if not destinatario:
            resumen['sin_correo'] += 1
            continue
        if Decimal(alerta.get('saldo_m1') or '0.00') <= 0:
            continue
        resumen['candidatos'] += 1
        if es_alta_nueva_atrasada:
            resumen['atrasados_nuevos'] += 1
        seleccionados.append((alerta, destinatario))

    if simular or not seleccionados:
        return resumen

    if not (
        forzar
        or getattr(settings, 'PAYMENT_REMINDER_EMAIL_ENABLED', False)
    ):
        resumen['deshabilitado'] = True
        return resumen

    reservados = []
    for alerta, destinatario in seleccionados:
        registro = _reservar_envio(alerta, destinatario)
        if registro is None:
            resumen['duplicados'] += 1
        else:
            reservados.append((alerta, destinatario, registro))

    if not reservados:
        return resumen

    try:
        config = config_correo_mfa()
    except EmailCodeDeliveryError as exc:
        for _alerta, _destinatario, registro in reservados:
            _marcar_fallido(registro, exc)
        resumen['fallidos'] += len(reservados)
        return resumen

    try:
        with _conexion_smtp(config) as server:
            for alerta, destinatario, registro in reservados:
                try:
                    server.send_message(
                        _crear_mensaje(
                            alerta, destinatario, config, fecha_envio,
                        )
                    )
                except Exception as exc:
                    logger.warning(
                        'Falló el recordatorio de pago %s: %s',
                        registro.pk, exc,
                    )
                    _marcar_fallido(registro, exc)
                    resumen['fallidos'] += 1
                else:
                    _marcar_enviado(registro)
                    resumen['enviados'] += 1
    except RecordatorioPagoEmailError as exc:
        for _alerta, _destinatario, registro in reservados:
            _marcar_fallido(registro, exc)
        resumen['fallidos'] += len(reservados)

    return resumen
