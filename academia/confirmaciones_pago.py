"""Confirmaciones de pagos nuevos, enviadas únicamente después del commit."""
import logging
from decimal import Decimal
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, formatdate
from io import BytesIO
from xml.sax.saxutils import escape

from django.core.validators import validate_email
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from .authentication import config_correo_mfa
from .correos_pago import _conexion_smtp
from .models import Abono, ConfirmacionPagoCorreo

logger = logging.getLogger(__name__)


def concepto_pago(abono):
    return 'Pago de recuperación' if abono.tipo_pago == 'recuperacion' else abono.get_tipo_pago_display()


def comprobante_pdf(abono):
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    m = abono.matricula
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=42, leftMargin=42, topMargin=42, bottomMargin=42,
                           title=f'Comprobante {abono.numero_recibo}')
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='Marca', fontName='Helvetica-Bold', fontSize=18, leading=24, textColor=colors.HexColor('#1a237e')))
    styles.add(ParagraphStyle(name='Monto', fontName='Helvetica-Bold', fontSize=28, leading=36, textColor=colors.HexColor('#268337')))
    def p(value): return Paragraph(escape(str(value)), styles['Normal'])
    story = [Paragraph('Formación Técnica y Profesional EC', styles['Marca']), Spacer(1, 10),
             p('Comprobante de pago de recuperación' if abono.tipo_pago == 'recuperacion' else 'Comprobante de pago'),
             p(f'Recibo: {abono.numero_recibo}'), Spacer(1, 22)]
    rows = [('Estudiante', m.estudiante.nombre_completo), ('Cédula', m.estudiante.cedula),
            ('Curso', m.curso.nombre), ('Modalidad', m.get_modalidad_display()),
            ('Fecha de pago', abono.fecha.strftime('%d/%m/%Y')), ('Concepto', concepto_pago(abono))]
    if abono.numero_modulo: rows.append(('Módulo', abono.get_modulo_display))
    if abono.tipo_pago == 'recuperacion':
        for rec in abono.recuperaciones.all():
            rows.append(('Clase pendiente', rec.fecha_marcada.strftime('%d/%m/%Y')))
            if rec.fecha_programada: rows.append(('Recuperación programada', rec.fecha_programada.strftime('%d/%m/%Y')))
    rows.append(('Aplicación del pago', 'Se aplica al saldo del curso' if abono.cuenta_para_saldo else 'Cobro aparte; no reduce el saldo del curso'))
    from .views_pagos import _partes_pago_abono
    for parte in _partes_pago_abono(abono):
        rows.append(('Método de pago', f'{parte["metodo_display"]} {parte["banco_display"] or ""} - ${parte["monto"]:.2f}'))
    table = Table([[p(k),p(v)] for k,v in rows], colWidths=[140,371])
    table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(0,-1),colors.HexColor('#f2f5fa')),('BOTTOMPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),10),('LINEBELOW',(0,0),(-1,-1),.4,colors.HexColor('#e1e6ed'))]))
    story += [table, Spacer(1,22),p('MONTO RECIBIDO'),Paragraph(f'${abono.monto:.2f}',styles['Monto']),Spacer(1,18)]
    for text in [f'Valor neto del curso: ${m.valor_neto:.2f}', f'Total aplicado al curso a la fecha de emisión: ${m.valor_pagado:.2f}', f'Saldo del curso a la fecha de emisión: ${m.saldo:.2f}']:
        story.append(p(text));story.append(Spacer(1,6))
    story += [Spacer(1,20),p('Pago registrado exitosamente. Gracias por tu puntualidad.'),Spacer(1,8),p('Este documento es un comprobante interno del sistema académico.'),p('Consultas: +593 96 271 6288.' )]
    doc.build(story)
    return buf.getvalue()


def crear_mensaje(abono, destinatario, config):
    context = {'abono': abono, 'matricula': abono.matricula, 'concepto': concepto_pago(abono)}
    msg = EmailMessage()
    msg['Subject'] = f'Pago registrado exitosamente - {abono.numero_recibo}'
    msg['From'] = formataddr(('Formación Técnica y Profesional EC', config['from_email']))
    msg['To'] = destinatario
    msg['Date'] = formatdate(localtime=True)
    msg['Message-ID'] = make_msgid()
    msg.set_content(render_to_string('correos/confirmacion_pago.txt', context))
    msg.add_alternative(render_to_string('correos/confirmacion_pago.html', context), subtype='html')
    msg.add_attachment(comprobante_pdf(abono), maintype='application', subtype='pdf', filename=f'Comprobante-{abono.numero_recibo}.pdf')
    return msg


def programar_confirmacion(abono, using='default'):
    registro = ConfirmacionPagoCorreo.objects.using(using).create(abono=abono, destinatario=(abono.matricula.estudiante.correo or '').strip())
    transaction.on_commit(lambda: enviar_confirmacion(registro.pk, using), using=using, robust=True)


def enviar_confirmacion(pk, using='default'):
    registros = ConfirmacionPagoCorreo.objects.using(using)
    if not registros.filter(pk=pk, estado='pendiente').update(estado='procesando'):
        return
    registro = registros.select_related('abono__matricula__estudiante','abono__matricula__curso').get(pk=pk)
    try:
        validate_email(registro.destinatario)
    except Exception:
        registros.filter(pk=pk).update(estado='sin_correo', ultimo_error='El estudiante no tiene un correo válido.')
        return
    try:
        config = config_correo_mfa()
        mensaje = crear_mensaje(registro.abono, registro.destinatario, config)
        with _conexion_smtp(config) as smtp:
            rechazados = smtp.send_message(mensaje)
            if rechazados: raise RuntimeError('El servidor rechazó al destinatario.')
        registros.filter(pk=pk).update(estado='enviado', enviado_en=timezone.now(), ultimo_error='')
    except Exception:
        registros.filter(pk=pk).update(estado='fallido', ultimo_error='No se pudo confirmar el envío. El pago permanece registrado.')
        logger.warning('No se pudo enviar la confirmación del pago %s', registro.abono_id)
