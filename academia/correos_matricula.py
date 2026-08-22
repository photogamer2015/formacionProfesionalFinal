"""Confirmación profesional de matrícula enviada al estudiante."""

from datetime import timedelta
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
import logging
import os
import re
import unicodedata

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from .authentication import config_correo_mfa
from .correos_pago import _conexion_smtp
from .models import ConfirmacionMatriculaCorreo, Matricula


logger = logging.getLogger(__name__)


# Los prefijos incluyen los nombres usados actualmente en el sistema y las
# denominaciones completas entregadas por la institución. El orden evita que
# una coincidencia genérica gane antes que la variante correcta.
FORMULARIOS_INSCRIPCION = (
    {
        'nombre': 'Talento Humano y Gestión de Nómina',
        'prefijos': ('gestion de talento humano', 'talento humano'),
        'url': 'https://forms.gle/9m2at3GA65RrUyQN6',
    },
    {
        'nombre': 'Aires Acondicionados e Introducción a Neveras',
        'prefijos': (
            'refrigeracion y aires acondicionados',
            'aires acondicionados',
        ),
        'url': 'https://forms.gle/ohbk6fEmRaQdNw34A',
    },
    {
        'nombre': 'Servicio Técnico Integral',
        'prefijos': ('servicio tecnico integral', 'servicio tecnico'),
        'url': 'https://forms.gle/RvghnEhRuNHZfwfX7',
    },
    {
        'nombre': 'Tributación Contable y Manejo del SRI',
        'prefijos': ('tributacion contable', 'tributacion'),
        'url': 'https://forms.gle/vKZRUPWh6eSSHAn26',
    },
    {
        'nombre': 'Asistente Contable: Tributario, Laboral y Financiero',
        'prefijos': ('asistente contable',),
        'url': 'https://forms.gle/QsYEbKLveSy8TDjH8',
    },
    {
        'nombre': 'Marketing Digital para Emprendedores',
        'prefijos': ('marketing digital',),
        'url': 'https://forms.gle/2weGDubEMpJUo5qy5',
    },
    {
        'nombre': 'Línea Blanca y Reparación de Electrodomésticos',
        'prefijos': ('linea blanca',),
        'url': 'https://forms.gle/pw8V2Jj7twumbMhx6',
    },
    {
        'nombre': 'Electricidad Residencial y Domótica',
        'prefijos': ('electricidad residencial',),
        'url': 'https://forms.gle/QvsStr8ERDM62mNm9',
    },
    {
        'nombre': 'Impresión 3D y Prototipado de Piezas',
        'prefijos': ('impresion 3d',),
        'url': 'https://forms.gle/oev5HpfrZuez6utq5',
    },
    {
        'nombre': 'Mecánica de Motos',
        'prefijos': ('mecanica de motos',),
        'url': 'https://forms.gle/azR9AtMRw5rQciL77',
    },
    {
        'nombre': 'Corte y Confección',
        'prefijos': ('corte y confeccion',),
        'url': 'https://forms.gle/Z1HshJtL1p9yej4R8',
    },
    {
        'nombre': 'Excel Administrativo y Gerencial',
        'prefijos': ('excel administrativo', 'excel'),
        'url': 'https://forms.gle/HsfHYm5NF14a92ZMA',
    },
    {
        'nombre': 'Ebanistería con Melamina',
        'prefijos': ('ebanisteria con melamina', 'ebanisteria integral', 'ebanisteria'),
        'url': 'https://forms.gle/ZFXH2zy9KTa7zdePA',
    },
    {
        'nombre': 'Python Profesional y Automatización',
        'prefijos': ('python profesional', 'automatizacion con python'),
        'url': 'https://forms.gle/qvUb589ueCvb8Ng69',
    },
)


def _env(name, default=''):
    return (os.environ.get(name, default) or '').strip()


def _normalizar_nombre_curso(nombre):
    texto = unicodedata.normalize('NFKD', nombre or '')
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    texto = texto.casefold()
    return re.sub(r'[^a-z0-9]+', ' ', texto).strip()


def formulario_inscripcion_para_curso(nombre_curso):
    """Devuelve el formulario correcto según el inicio del nombre del curso."""
    normalizado = _normalizar_nombre_curso(nombre_curso)
    for formulario in FORMULARIOS_INSCRIPCION:
        if any(normalizado.startswith(prefijo) for prefijo in formulario['prefijos']):
            return {
                'nombre': formulario['nombre'],
                'url': formulario['url'],
            }
    return None


def _correo_valido(correo):
    correo = (correo or '').strip().lower()
    if not correo:
        return ''
    try:
        validate_email(correo)
    except ValidationError:
        return ''
    return correo


def _texto_o_no_registrado(valor):
    texto = str(valor or '').strip()
    return texto or 'No registrado'


def _contexto_matricula(matricula):
    estudiante = matricula.estudiante
    curso = matricula.curso
    jornada = matricula.jornada
    formulario = formulario_inscripcion_para_curso(curso.nombre)

    horario = 'No especificado'
    if jornada and jornada.hora_inicio and jornada.hora_fin:
        horario = (
            f'{jornada.hora_inicio:%H:%M} a {jornada.hora_fin:%H:%M}'
        )

    nivel_formacion = 'No registrado'
    if estudiante.nivel_formacion:
        nivel_formacion = estudiante.get_nivel_formacion_display()

    talla_camiseta = 'No registrada'
    if matricula.talla_camiseta:
        talla_camiseta = matricula.get_talla_camiseta_display()

    return {
        'nombre_estudiante': estudiante.nombre_completo,
        'cedula': estudiante.cedula,
        'edad': estudiante.edad,
        'correo': estudiante.correo,
        'celular': _texto_o_no_registrado(estudiante.celular),
        'nivel_formacion': nivel_formacion,
        'titulo_profesional': _texto_o_no_registrado(
            estudiante.titulo_profesional
        ),
        'ciudad': _texto_o_no_registrado(estudiante.ciudad),
        'fecha_matricula': matricula.fecha_matricula,
        'estado_matricula': matricula.get_estado_display(),
        'tipo_matricula': matricula.get_tipo_matricula_display(),
        'modalidad': matricula.get_modalidad_display(),
        'talla_camiseta': talla_camiseta,
        'curso_nombre': curso.nombre,
        'categoria_curso': (
            curso.categoria.nombre if curso.categoria_id else 'No especificada'
        ),
        'jornada_dias': (
            jornada.descripcion_legible if jornada else 'No especificada'
        ),
        'fecha_inicio': jornada.fecha_inicio if jornada else None,
        'horario': horario,
        'sede': (
            _texto_o_no_registrado(jornada.sede_nombre)
            if jornada else 'No especificada'
        ),
        'valor_curso': matricula.valor_curso,
        'descuento': matricula.descuento,
        'valor_neto': matricula.valor_neto,
        'valor_pagado': matricula.valor_pagado,
        'saldo': matricula.saldo,
        'formulario': formulario,
    }


def _crear_mensaje(matricula, destinatario, config):
    contexto = _contexto_matricula(matricula)
    from_name = _env(
        'ENROLLMENT_CONFIRMATION_EMAIL_FROM_NAME',
        _env('MFA_EMAIL_FROM_NAME', 'Formación Profesional EC'),
    )
    reply_to = _env(
        'ENROLLMENT_CONFIRMATION_EMAIL_REPLY_TO',
        _env('MFA_EMAIL_REPLY_TO', config['from_email']),
    )
    sender_domain = config['from_email'].partition('@')[2] or None

    message = EmailMessage()
    message['Subject'] = f'Confirmación de matrícula — {matricula.curso.nombre}'
    message['From'] = formataddr((from_name, config['from_email']))
    message['To'] = destinatario
    message['Reply-To'] = reply_to
    message['Date'] = formatdate(localtime=True)
    message['Message-ID'] = make_msgid(domain=sender_domain)
    message.set_content(render_to_string(
        'correos/confirmacion_matricula.txt', contexto,
    ))
    message.add_alternative(render_to_string(
        'correos/confirmacion_matricula.html', contexto,
    ), subtype='html')
    return message, contexto['formulario']


@transaction.atomic
def _reservar_envio(matricula, destinatario, formulario_url):
    ahora = timezone.now()
    registro, creado = ConfirmacionMatriculaCorreo.objects.get_or_create(
        matricula=matricula,
        defaults={
            'destinatario': destinatario,
            'formulario_url': formulario_url,
            'estado': ConfirmacionMatriculaCorreo.ESTADO_PROCESANDO,
            'intentos': 1,
        },
    )
    if creado:
        return registro
    if registro.estado == ConfirmacionMatriculaCorreo.ESTADO_ENVIADO:
        return None
    if (
        registro.estado == ConfirmacionMatriculaCorreo.ESTADO_PROCESANDO
        and registro.actualizado >= ahora - timedelta(minutes=10)
    ):
        return None

    registro.destinatario = destinatario
    registro.formulario_url = formulario_url
    registro.estado = ConfirmacionMatriculaCorreo.ESTADO_PROCESANDO
    registro.intentos += 1
    registro.ultimo_error = ''
    registro.save(update_fields=[
        'destinatario', 'formulario_url', 'estado', 'intentos',
        'ultimo_error', 'actualizado',
    ])
    return registro


def _marcar_fallido(registro, error):
    ConfirmacionMatriculaCorreo.objects.filter(pk=registro.pk).update(
        estado=ConfirmacionMatriculaCorreo.ESTADO_FALLIDO,
        ultimo_error=str(error)[:1000],
        actualizado=timezone.now(),
    )


def _marcar_enviado(registro):
    ahora = timezone.now()
    ConfirmacionMatriculaCorreo.objects.filter(pk=registro.pk).update(
        estado=ConfirmacionMatriculaCorreo.ESTADO_ENVIADO,
        ultimo_error='',
        enviado_en=ahora,
        actualizado=ahora,
    )


def enviar_confirmacion_matricula(matricula_id, *, forzar=False):
    """Envía una sola confirmación sin alterar matrícula, pagos ni alertas."""
    resultado = {
        'estado': 'omitido',
        'matricula_id': matricula_id,
        'destinatario': '',
    }
    if not (
        forzar
        or getattr(settings, 'ENROLLMENT_CONFIRMATION_EMAIL_ENABLED', False)
    ):
        resultado['estado'] = 'deshabilitado'
        return resultado

    try:
        matricula = Matricula.objects.select_related(
            'estudiante', 'curso', 'curso__categoria', 'jornada',
            'jornada__sede',
        ).get(pk=matricula_id)
    except Matricula.DoesNotExist:
        resultado['estado'] = 'no_existe'
        return resultado

    destinatario = _correo_valido(matricula.estudiante.correo)
    resultado['destinatario'] = destinatario
    if not destinatario:
        resultado['estado'] = 'sin_correo'
        return resultado

    formulario = formulario_inscripcion_para_curso(matricula.curso.nombre)
    formulario_url = formulario['url'] if formulario else ''
    registro = _reservar_envio(matricula, destinatario, formulario_url)
    if registro is None:
        resultado['estado'] = 'duplicado'
        return resultado

    try:
        config = config_correo_mfa()
        mensaje, _formulario = _crear_mensaje(
            matricula, destinatario, config,
        )
        with _conexion_smtp(config) as server:
            server.send_message(mensaje)
    except Exception as exc:
        logger.warning(
            'Falló la confirmación de matrícula %s: %s', matricula_id, exc,
        )
        _marcar_fallido(registro, exc)
        resultado['estado'] = 'fallido'
        return resultado

    _marcar_enviado(registro)
    resultado['estado'] = 'enviado'
    return resultado
