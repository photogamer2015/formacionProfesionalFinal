"""Asistente local: intenciones explícitas, formularios y datos reales, sin LLM.

El estado vive en la sesión. Ampliar intent()/SECTIONS y los flujos explícitos;
los mensajes y los datos almacenados nunca se ejecutan como instrucciones.
"""
import re
from datetime import datetime

from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.urls import reverse
from django.utils import timezone

from .busqueda import normalizar_texto_busqueda as norm, filtrar_queryset_busqueda
from .forms import RecuperacionPendienteForm
from .models import Abono, Estudiante, Matricula, Curso, RecuperacionPendiente
from .permisos import puede_gestionar_matriculas, es_admin
from .mercybot_matricula import (ALIASES as MATRICULA_ALIASES, LABELS as MATRICULA_LABELS,
                                 enrollment_step, remember, step_back)

STATE = 'mercybot_state_v1'
OUTSIDE = 'Eso no se encuentra en el sistema, lo siento, no te puedo ayudar.'
# Detener un registro debe funcionar con las formas naturales de pedirlo, no
# solo con la palabra exacta: de lo contrario la frase se guarda como un dato.
_CANCEL_TAIL = (r'(?:\s+(?:el|la|lo|los|las|un|una|este|esta|esto|eso|todo|nada|registro|matricula|'
                r'inscripcion|proceso|recuperacion|estudiante|pendiente|ahora|hoy|por favor|gracias))*$')
# Peticiones inequívocas: detienen el registro en cualquier momento.
CANCEL = re.compile(r'^(?:/clear|cancel\w*|anul\w*|detener|deten|reinici\w*|'
                    r'empezar de nuevo|borrar todo|'
                    r'(?:ya )?no (?:lo )?(?:quiero|queria|deseo|voy a|vamos a) '
                    r'(?:registrar\w*|matricular\w*|inscribir\w*|seguir|continuar))' + _CANCEL_TAIL)
# Formas breves de desistir: no se aplican cuando el dato pedido es texto libre,
# donde la frase podría ser el valor real (una observación, un nombre).
CANCEL_SOFT = re.compile(
    r'^(?:olvida(?:lo|te)?|dejalo|dejemoslo|mejor no|ya no|'
    r'no (?:lo )?(?:quiero|deseo))' + _CANCEL_TAIL)
# Órdenes y preguntas al sistema: mientras haya un registro pendiente se avisa
# en vez de guardarlas como respuesta al campo solicitado.
COMMAND = re.compile(
    r'^(?:ver|buscar|busca|abrir|abre|ir a|llevame|consultar|consulta|muestrame|mostrar|dime|'
    r'necesito|quiero ver|cuantos|cuantas|cual|cuales|quien|donde|cuando|ayuda|menu|'
    r'que puedes|como funciona|explica)\b')
# Volver al paso anterior cuando el dato se escribió mal.
BACK = re.compile(r'^(?:atras|volver|volvamos|regresar|regresa|vuelve|retroced\w*|deshacer|undo|'
                  r'paso anterior|anterior|me equivoque|equivocado|escribi mal|corregir|correccion)'
                  r'(?:\s+(?:al|el|la|lo|un|de|paso|dato|campo|anterior|atras|ultimo|'
                  r'de nuevo|otra vez|por favor))*$')
# Saludos: Mercy se presenta en vez de responder con el listado seco de ayuda.
GREETING = re.compile(r'^(?:hola+|holi|ola|buenas|buen dia|buenos dias|buenas tardes|buenas noches|'
                      r'que tal|que mas|como estas|saludos|hey|ey|mercy|mercybot)'
                      r'(?:[\s,]+(?:mercy|mercybot|bot|como estas|que tal|buenas|buenos dias|'
                      r'buenas tardes|buenas noches|a todos|por favor))*'
                      r'(?:[\s,]+(?:soy|me llamo|mi nombre es|habla|te habla)\s+.{1,40})?$')
NAME_SAID = re.compile(r'\b(?:soy|me llamo|mi nombre es|habla|te habla)\s+(.{1,40})$', re.IGNORECASE)
# Campos de texto libre: ahí una frase suelta puede ser el dato real, no una
# orden. El resto de campos (nombres, ciudad, bancos) nunca contienen frases
# como «ya no» o «mejor no», así que en ellos sí se atiende como desistimiento.
FREE_TEXT = {'observaciones', 'titulo_profesional'}
HELP = ('Puedo registrar estudiantes con su matrícula completa, buscar sus datos, consultar pagos y saldos, '
        'consultar o registrar recuperaciones y mostrar cursos.\n'
        'Por ejemplo: «quiero agregar un nuevo estudiante», «ver pagos de Andrés Guevara», '
        '«recuperaciones de 0912345678» o «registrar recuperación».\n'
        'Te pediré todos los datos de matrícula, mostraré las jornadas con sus fechas y registraré el pago inicial al completar el formulario. '
        'Si te equivocas escribe «atrás» y volvemos al paso anterior; «cancelar» detiene el registro. '
        'Para abrir una sección, escribe «abrir pagos», «abrir matrícula» o «abrir cursos».')
ALIASES = {
    'cedula': 'cedula', 'ruc': 'cedula', 'documento': 'cedula',
    'nombre': 'nombres', 'nombres': 'nombres', 'nombres completos': 'nombres',
    'nombre completo': 'nombres', 'nombres y apellidos': 'nombres',
    'edad': 'edad', 'email': 'correo', 'correo': 'correo',
    'telefono': 'celular', 'celular': 'celular', 'ciudad': 'ciudad', 'sede': 'ciudad',
    'nivel': 'nivel_formacion', 'nivel de formacion': 'nivel_formacion',
    'nivel_formacion': 'nivel_formacion', 'titulo': 'titulo_profesional',
    'titulo profesional': 'titulo_profesional',
    'modulo': 'numero_modulo', 'numero de modulo': 'numero_modulo',
    'fecha de falta': 'fecha_marcada', 'fecha falta': 'fecha_marcada',
    'fecha de la falta': 'fecha_marcada', 'fecha marcada': 'fecha_marcada',
    'fecha programada': 'fecha_programada', 'fecha para recuperar': 'fecha_programada',
    'fecha de recuperacion': 'fecha_programada',
    'equipo': 'tipo_equipo', 'tipo de equipo': 'tipo_equipo',
    'observaciones': 'observaciones',
    'numero compartido': 'permitir_celular_duplicado',
}
ALIASES.update(MATRICULA_ALIASES)
LABELS = {'cedula': 'cédula o RUC', 'nombres': 'nombres y apellidos completos',
          'nivel_formacion': 'nivel de formación', 'titulo_profesional': 'título profesional',
          'numero_modulo': 'módulo', 'fecha_marcada': 'fecha de la falta',
          'fecha_programada': 'fecha para recuperar', 'tipo_equipo': 'clase / equipo'}
ALL_LABELS = {**LABELS, **MATRICULA_LABELS}
SECTIONS = [
    ('registro administrativo', 'admin_dashboard', {}, 'admin'),
    ('archivo', 'archivo_index', {}, 'admin'),
    ('sede', 'sedes_lista', {}, 'admin'),
    ('recuperacion', 'recuperaciones_lista', {}, 'staff'),
    ('estudiante', 'estudiantes_lista', {}, 'staff'),
    ('pago', 'pagos_lista', {}, 'staff'),
    ('abono', 'pagos_lista', {}, 'staff'),
    ('matricula', 'matricula_registrar', {'modalidad': 'presencial'}, 'staff'),
    ('curso', 'cursos_lista', {'modalidad': 'presencial'}, 'all'),
    ('comprobante', 'comprobante_lista', {}, 'staff'),
    ('adicional', 'adicional_lista', {}, 'staff'),
    ('historial', 'historial_lista', {}, 'staff'),
    ('recordatorio', 'recordatorio_lista', {}, 'all'),
    ('aviso', 'avisos_lista', {}, 'admin'),
    ('ayuda', 'ayuda', {}, 'all'), ('inicio', 'bienvenida', {}, 'all'),
]


# Guías locales basadas en templates/ayuda.html y los formularios del sistema.
# No se busca texto arbitrario en el código ni se ejecuta contenido del usuario.
KNOWLEDGE = [
    (('recaudacion',), 'La Hoja de Recaudación genera un formato imprimible por fecha y curso, con control de asistencia y totales de efectivo y transferencia.', 'recaudacion'),
    (('pagos por modulo', 'pago por modulo', 'color verde', 'color rojo'), 'Pagos por Módulo muestra el avance de cada estudiante: verde indica módulo cubierto y rojo indica pendiente. La reserva se aplica al primer módulo y el sobrante al siguiente.', 'por-modulo'),
    (('recuperacion', 'recuperaciones'), 'Una recuperación registra la matrícula, módulo pendiente, fecha de falta y fecha programada. Puedo registrarla por chat: escribe «registrar recuperación». El cobro se completa en Recuperaciones y puede contar para el saldo o ser un ingreso aparte.', 'recuperaciones'),
    (('pago', 'abono', 'saldo'), 'En Pagos puedes consultar al estudiante y abrir sus abonos. El formulario permite registrar monto, fecha, tipo y método de pago. Para consultar aquí, escribe «ver pagos de» seguido del nombre o cédula.', 'pagos'),
    (('factura',), 'En el registro de matrícula, si eliges factura con datos, completa los campos de facturación que solicita el formulario. También exige celular y ciudad del estudiante.', 'matriculas'),
    (('matricula', 'descuento'), 'La matrícula asocia el estudiante con un curso y jornada activa. El chat recoge todos los datos del formulario: curso, jornada, fecha, valores, pago simple o mixto, asesora, origen y factura. Escribe «registrar matrícula» para completarla aquí.', 'matriculas'),
    (('jornada', 'categoria', 'curso'), 'En Cursos puedes buscar por nombre, cambiar entre presencial y online y abrir las jornadas de cada curso. Para agregar una fecha, abre sus jornadas y completa Nueva jornada; los botones de modalidad permiten pasar al mismo curso online o presencial.', 'cursos'),
    (('adicional', 'certificado', 'supletorio', 'camisa'), 'Adicional registra certificados, exámenes supletorios y camisas extra para estudiantes o personas externas. El supletorio también se puede registrar desde la ficha del estudiante.', 'adicional'),
    (('comprobante', 'ranking'), 'Comprobantes registra ventas por asesora y permite adjuntar el enlace de respaldo. Los registros alimentan el ranking de ventas por asesora y central.', 'comprobantes'),
    (('administrativo', 'egreso', 'ingreso', 'alerta'), 'Registro Administrativo muestra ingresos, egresos y métricas mensuales, según tus permisos. Las alertas de pagos ayudan a revisar estudiantes con módulos pendientes.', 'alertas'),
    (('estudiante', 'alumno'), 'Puedo registrar al estudiante con su matrícula completa por chat y consultarlo por nombre o cédula. Escribe «registrar estudiante» o «buscar estudiante» y te pediré los datos faltantes.', 'matriculas'),
    (('recordatorio', 'aviso', 'historial', 'archivo', 'sede'), 'Puedes abrir esa sección escribiendo «abrir» y su nombre. Los permisos de tu usuario se mantienen en cada pantalla.', None),
]


def knowledge_answer(message):
    for words, text, anchor in KNOWLEDGE:
        if any(re.search(r'\b' + re.escape(word) + r'\b', message) for word in words):
            target = link('Consultar guía del sistema', 'ayuda')
            if anchor:
                target['url'] += '#ayuda-' + anchor
            return answer(text, [target])
    return None


def answer(text, links=None):
    return {'reply': text, 'links': links or []}


def link(label, route, **kwargs):
    return {'label': label, 'url': reverse('academia:' + route, kwargs=kwargs)}


def display_name(request, message):
    """Nombre para el saludo: el que dice la persona o el de su usuario."""
    said = NAME_SAID.search(message.strip())
    name = said.group(1) if said else ''
    if not name:
        user = request.user
        name = user.first_name or user.get_full_name() or user.get_username()
    name = re.sub(r'[^\w\s.\-áéíóúüñÁÉÍÓÚÜÑ]', '', name).strip(' .-')[:40]
    return (name[:1].upper() + name[1:]) if name else ''


def greeting_answer(request, message):
    hour = timezone.localtime().hour
    moment = 'Buenos días' if hour < 12 else ('Buenas tardes' if hour < 19 else 'Buenas noches')
    name = display_name(request, message)
    lines = [f'{moment}{", " + name if name else ""}. Soy Mercy, tu asistente de la academia; un gusto saludarte.',
             'Puedo registrar una matrícula completa con su pago, buscar estudiantes, '
             'consultar pagos y saldos, y gestionar recuperaciones.',
             '¿Con qué empezamos? Escribe «registrar matrícula», «ver pagos de…» o «ayuda» '
             'para conocer todo lo que hago.']
    return answer('\n'.join(lines))


def undo_answer(request, state, renderer, labels):
    """Deshace el último dato y vuelve a preguntarlo con el mismo flujo."""
    undone = step_back(state)
    request.session[STATE] = state
    if not undone:
        return answer('Todavía no hay ningún dato que deshacer: seguimos en el primer paso. '
                      'Responde el dato solicitado o escribe «cancelar» para salir.')
    result = renderer(request, state, '')
    label = labels.get(undone, undone.replace('_', ' '))
    result['reply'] = f'Listo, descarté {label} y volvemos a ese paso.\n' + result['reply']
    return result


def extract_fields(message):
    pattern = r'(?<!\w)(' + '|'.join(sorted(map(re.escape, ALIASES), key=len, reverse=True)) + r')\s*(?::|=|\bes\b)\s*'
    matches = list(re.finditer(pattern, norm(message)))
    # norm preserves positions for Spanish accented characters (ñ/á/etc.).
    return {ALIASES[m.group(1)]: message[m.end():matches[i+1].start() if i+1 < len(matches) else len(message)].strip(' ,;\n')
            for i, m in enumerate(matches)}


def intent(message):
    text = norm(re.split(r'[;\n]', message, maxsplit=1)[0])
    create = bool(re.search(r'\b(agregar|registrar|crear|anadir|inscribir|marcar|nuevo|nueva)\b', text))
    if 'recuper' in text:
        return 'new_recovery' if create else 'recoveries'
    if ((any(word in text for word in ('estudiante', 'alumno', 'matricula')) and create)
            or re.search(r'\b(matricular|matriculame|inscribir)\b', text)):
        return 'new_enrollment'
    if re.search(r'\b(pagos?|abonos?|saldo|deuda|debe)\b', text):
        return 'payments'
    if re.search(r'\b(buscar|busca|estudiantes?|alumnos?|datos)\b', text):
        return 'student'
    if 'curso' in text:
        return 'courses'
    return None


def search_term(message):
    text = norm(message)
    document = re.search(r'\b\d{10}(?:\d{3})?\b', text)
    if document:
        return document.group()
    text = re.sub(r'\b(yo|quiero|quisiera|como|por favor|puedes|podrias|ver|consultar|consulta|muestrame|mostrar|busca|buscar|pagos?|abonos?|saldo|deuda|cuanto|debe|datos|del|de|la|el|los|las|estudiantes?|alumnos?|recuperacion(?:es)?|registrar|agregar|marcar|una|un|nueva|para|y|cedula)\b', ' ', text)
    return ' '.join(text.strip(' :,.?¿').split())


def find_student(request, state, term):
    if not term:
        request.session[STATE] = state
        return answer('Dime el nombre y apellido o la cédula del estudiante.')
    qs = Estudiante.objects.all()
    if term.isdigit():
        qs = qs.filter(cedula=term)
    else:
        qs = filtrar_queryset_busqueda(qs, term, ['nombres'])
    students = list(qs[:6])
    if not students:
        request.session[STATE] = state
        return answer('No encontré estudiantes con esos datos. Prueba con la cédula o con nombre y apellido; también puedes escribir «registrar estudiante».')
    if len(students) > 1:
        request.session[STATE] = state
        return answer('Hay varias coincidencias; dime la cédula exacta:\n' + '\n'.join(
            f'• {s.nombres} — {s.cedula}' for s in students[:5]) +
            ('\nHay más resultados; precisa la búsqueda.' if len(students) > 5 else ''))
    student = students[0]
    request.session['mercybot_student'] = student.pk
    if state['intent'] == 'new_recovery':
        state['student_id'] = student.pk
        state['stage'] = 'enrollment'
        request.session[STATE] = state
        return choose_enrollment(request, state, '')
    request.session.pop(STATE, None)
    return student_answer(student, state['intent'])


def student_answer(student, action):
    lines = [f'{student.nombres} — Cédula: {student.cedula}']
    links = [link('Ver estudiante', 'estudiante_detalle', pk=student.pk)]
    # Una sola consulta por relación: evita N+1 al listar abonos o recuperaciones.
    qs = student.matriculas.select_related('curso', 'jornada')
    if action == 'recoveries':
        qs = qs.prefetch_related('recuperaciones_pendientes')
    elif action == 'payments':
        qs = qs.prefetch_related(Prefetch('abonos', queryset=Abono.objects.order_by('-fecha', '-pk')))
    enrollments = list(qs[:21])
    if action == 'student':
        lines.append(f'Celular: {student.celular or "Sin registrar"} · Ciudad: {student.ciudad or "Sin registrar"}')
    if not enrollments:
        lines.append('No tiene matrículas registradas.')
    for m in enrollments[:20]:
        lines.append(f'\n{m.curso.nombre} ({m.get_modalidad_display()}) — {m.get_estado_display()}')
        if action == 'recoveries':
            records = list(m.recuperaciones_pendientes.all())
            if not records:
                lines.append('Sin recuperaciones registradas.')
            for r in records[:20]:
                lines.append(f'• Módulo {r.numero_modulo}: falta {r.fecha_marcada:%d/%m/%Y}; '
                             f'programada {r.fecha_programada.strftime("%d/%m/%Y") if r.fecha_programada else "sin fecha"}; '
                             f'{"pagada" if r.pagada else "pendiente"}.')
            links.append(link('Ver recuperaciones / pagos', 'matricula_abonos', pk=m.pk))
        else:
            lines.append(f'Pagado: ${m.valor_pagado:.2f} · Saldo: ${m.saldo:.2f}')
            if action == 'payments':
                payments = list(m.abonos.all())[:20]
                if not payments:
                    lines.append('Sin abonos registrados.')
                for p in payments:
                    lines.append(f'• {p.fecha:%d/%m/%Y}: ${p.monto:.2f} — {p.get_tipo_pago_display()} / {p.get_metodo_display()}'
                                 + (' (no cuenta para saldo)' if not p.cuenta_para_saldo else ''))
                lines.append('Se muestran hasta 20 abonos recientes; abre el detalle para el historial completo.')
            links.append(link('Ver pagos de ' + m.curso.nombre, 'matricula_abonos', pk=m.pk))
    if len(enrollments) > 20:
        lines.append('Se muestran las primeras 20 matrículas. Abre el estudiante para ver todas.')
    return answer('\n'.join(lines), links)


def choose_enrollment(request, state, message):
    qs = Matricula.objects.filter(estudiante_id=state['student_id']).select_related('curso', 'estudiante')
    enrollments = list(qs)
    if not enrollments:
        request.session.pop(STATE, None)
        return answer('Este estudiante no tiene matrícula. Escribe «registrar matrícula» para crearla aquí '
                      'o ábrela en el formulario del sistema.',
                      [link('Registrar matrícula', 'matricula_registrar', modalidad='presencial')])
    selected = None
    if len(enrollments) == 1:
        selected = enrollments[0]
    elif message:
        matches = [m for m in enrollments if str(m.pk) == message.strip() or norm(m.curso.nombre) == norm(message.strip())]
        if len(matches) == 1:
            selected = matches[0]
    if not selected:
        return answer('¿Para cuál matrícula? Responde con su número:\n' + '\n'.join(
            f'• {m.pk}: {m.curso.nombre} — {m.get_modalidad_display()} — {m.jornada or "Sin jornada"}' for m in enrollments))
    state.update(stage='form', matricula_id=selected.pk)
    request.session[STATE] = state
    return form_step(request, state, '')


def normalize_value(field, value, form):
    if norm(value) in ('omitir', 'sin dato', 'ninguno', 'ninguna', 'no tengo', 'no tiene'):
        return ''
    if field in ('fecha_marcada', 'fecha_programada'):
        for fmt in ('%d/%m/%Y', '%d-%m-%Y'):
            try:
                return datetime.strptime(value, fmt).date().isoformat()
            except ValueError:
                pass
    choices = getattr(form.fields[field], 'choices', [])
    for key, label in choices:
        if norm(value) in (norm(key), norm(label)):
            return str(key)
    return value


def form_step(request, state, message):
    """Captura de recuperaciones. El alta del estudiante vive en la matrícula."""
    enrollment = Matricula.objects.select_for_update().filter(pk=state['matricula_id'], estudiante_id=state['student_id']).first()
    if not enrollment:
        request.session.pop(STATE, None)
        return answer('La matrícula ya no existe. Inicia de nuevo la consulta.')
    form = RecuperacionPendienteForm(matricula=enrollment)
    fields = ['numero_modulo', 'fecha_marcada', 'fecha_programada', 'observaciones']
    if form.fields['tipo_equipo'].choices:
        fields.insert(2, 'tipo_equipo')
    if not form.modulos_pendientes:
        request.session.pop(STATE, None)
        return answer('Esta matrícula no tiene módulos pendientes disponibles para recuperación.')
    data = state.setdefault('data', {})
    incoming = extract_fields(message)
    if message and norm(message) != 'omitir opcionales' and not incoming and state.get('waiting'):
        incoming[state['waiting']] = message
    captured = []
    for field, value in incoming.items():
        if field in fields:
            data[field] = normalize_value(field, value, form)
            captured.append(field)
    remember(state, captured)
    # "omitir opcionales" explicitly skips remaining optional fields.
    if norm(message) == 'omitir opcionales':
        for field in fields:
            if not form.fields[field].required and field != 'tipo_equipo':
                data.setdefault(field, '')
    missing = [f for f in fields if f not in data]
    bound = RecuperacionPendienteForm(data, matricula=enrollment)
    bound.is_valid()
    invalid = [f for f in fields if f in data and f in bound.errors]
    if invalid or missing:
        field = (invalid or missing)[0]
        state['waiting'] = field
        request.session[STATE] = state
        prefix = ' '.join(bound.errors.get(field, [])) + '\n' if invalid else ''
        optional = not form.fields[field].required and field != 'tipo_equipo'
        choices = (form.fields[field].widget.choices if field == 'numero_modulo'
                   else getattr(form.fields[field], 'choices', []))
        options = ' / '.join(f'{key}: {label}' for key, label in choices if key)
        hint = '\nOpciones: ' + options if options else ''
        if field.startswith('fecha_'):
            hint += '\nUsa DD/MM/AAAA.'
        return answer(prefix + 'Indica ' + LABELS.get(field, field) + '.' + hint +
                      (' Puedes escribir «omitir» o «omitir opcionales».' if optional else '') +
                      '\nTambién puedes enviar varios datos: campo: valor; campo: valor. Para detenerte: cancelar.')
    if not bound.is_valid():
        return answer('No se pudo registrar: ' + ' '.join(str(e) for errors in bound.errors.values() for e in errors))
    try:
        with transaction.atomic():
            obj = bound.save(commit=False)
            obj.matricula = enrollment
            obj.saldo_pendiente_al_marcar = enrollment.saldo
            duplicate = RecuperacionPendiente.objects.filter(
                matricula=enrollment, numero_modulo=obj.numero_modulo, fecha_marcada=obj.fecha_marcada,
                tipo_equipo=obj.tipo_equipo,
            ).exists()
            if duplicate:
                request.session.pop(STATE, None)
                return answer('Ya existe una recuperación para esa matrícula, módulo, clase y fecha. No la dupliqué.',
                              [link('Ver recuperación', 'matricula_abonos', pk=enrollment.pk)])
            obj.save()
    except IntegrityError:
        return answer('El registro ya existe o cambió mientras lo completabas. Revisa los datos o escribe «cancelar» y consulta el registro.')
    request.session.pop(STATE, None)
    return answer(f'Recuperación registrada para {enrollment.estudiante.nombres}, {enrollment.curso.nombre}, módulo {obj.numero_modulo}. '
                  f'Saldo al marcar: ${obj.saldo_pendiente_al_marcar:.2f}.',
                  [link('Ver recuperación', 'matricula_abonos', pk=enrollment.pk)])


def respond(request, message):
    text = norm(message).strip(' .!?¿¡')
    pending = request.session.get(STATE)
    soft = CANCEL_SOFT.match(text) and (pending or {}).get('waiting') not in FREE_TEXT
    if CANCEL.match(text) or soft:
        request.session.pop(STATE, None)
        request.session.pop('mercybot_student', None)
        request.session.pop('mercybot_history', None)
        if pending:
            return answer('Cancelado. Descarté los datos pendientes y no guardé ningún registro.\n' + HELP)
        return answer('Conversación reiniciada. ' + HELP)
    if text in ('ayuda', 'que puedes hacer', 'menu', 'opciones', 'ayudame'):
        return answer(HELP)
    if GREETING.match(text) and not extract_fields(message):
        if not pending:
            return greeting_answer(request, message)
        # Saludar a mitad de un registro no debe guardarse como respuesta.
        waiting = ALL_LABELS.get(pending.get('waiting') or '', '')
        return answer(f'¡Hola de nuevo, {display_name(request, message)}! Seguimos con el registro'
                      + (f': indica {waiting}' if waiting else '') +
                      '.\nEscribe «atrás» para volver al paso anterior o «cancelar» para descartarlo.')
    if text in ('gracias', 'muchas gracias'):
        return answer('Con gusto. Si necesitas otra consulta del sistema, aquí estoy.')
    state = request.session.get(STATE)
    if state and state.get('intent') == 'new_enrollment':
        if not puede_gestionar_matriculas(request.user):
            request.session.pop(STATE, None)
            return answer('No tienes permiso para registrar matrículas.')
        waiting = state.get('waiting') or ''
        if not extract_fields(message) and BACK.match(text):
            return undo_answer(request, state, enrollment_step, MATRICULA_LABELS)
        if waiting not in FREE_TEXT and not extract_fields(message) and COMMAND.match(text):
            pending = MATRICULA_LABELS.get(waiting, waiting.replace('_', ' '))
            return answer('Tienes una matrícula pendiente' + (f' y falta {pending}' if pending else '') +
                          '. Escribe «cancelar» para descartarla y cambiar de operación, '
                          'o responde el dato solicitado.')
        return enrollment_step(request, state, message)
    action = intent(message)
    if action == 'new_enrollment' and not re.search(r'\b(como|explica|ayuda con)\b', text):
        if not puede_gestionar_matriculas(request.user):
            return answer('No tienes permiso para registrar matrículas.')
        state = {'intent': 'new_enrollment', 'stage': 'form', 'data': {}}
        result = enrollment_step(request, state, message if extract_fields(message) else '')
        if request.session.get(STATE):
            result['reply'] = ('Vamos a registrar la matrícula completa, incluido el pago inicial. '
                               'Guardaré todo junto cuando completes los datos.\n' + result['reply'])
        return result
    if re.match(r'^(abre|abrir|ir a|llevame a)\b', text):
        for word, route, kwargs, access in sorted(SECTIONS, key=lambda item: -len(item[0])):
            if word in text:
                if access == 'admin' and not es_admin(request.user) or access == 'staff' and not puede_gestionar_matriculas(request.user):
                    return answer('No tienes permiso para acceder a esa sección.')
                kwargs = dict(kwargs)
                if 'modalidad' in kwargs and ('online' in text or 'virtual' in text):
                    kwargs['modalidad'] = 'online'
                target = link('Abrir sección', route, **kwargs)
                return dict(answer('Abriendo la sección solicitada.', [target]), redirect=target['url'])
        return answer(OUTSIDE)
    if re.search(r'\b(eliminar|borra|borrar|anular|cerrar|cobrar|editar|modificar)\b', text):
        if not any(word in text for word in ('estudiante', 'matricula', 'recuper', 'pago', 'abono', 'curso', 'jornada')):
            return answer(OUTSIDE)
        if not puede_gestionar_matriculas(request.user):
            return answer('No tienes permiso para realizar esa operación.')
        return answer('Esa operación se realiza desde el formulario correspondiente del sistema. '
                      'En el chat puedo registrar matrículas completas y recuperaciones, o consultar datos, pagos y saldos.',
                      [link('Ver pagos y matrículas', 'pagos_lista'), link('Ver recuperaciones', 'recuperaciones_lista')])
    if re.search(r'\b(registrar|agregar|crear)\b', text) and re.search(r'\b(pago|abono)\b', text) and 'recuper' not in text:
        return answer('Para registrar un pago, selecciona la matrícula y completa el formulario de abonos, con su monto y método de pago.',
                      [link('Abrir pagos', 'pagos_lista')])
    state = request.session.get(STATE)
    if not state and re.search(r'\b(como|que es|para que|explica|ayuda con)\b', text):
        guide = knowledge_answer(text)
        if guide:
            return guide
    if state and not puede_gestionar_matriculas(request.user):
        request.session.pop(STATE, None)
        return answer('No tienes permiso para gestionar estudiantes, pagos o recuperaciones.')
    # Explicit requests can switch searches; unfinished writes require cancel first.
    if state and state['intent'] == 'new_recovery':
        if (action and not extract_fields(message) and action != state['intent']
                and re.search(r'\b(quiero|ver|consultar|buscar|registrar|crear|agregar|marcar)\b', text)):
            return answer('Tienes un registro en curso. Escribe «cancelar» para cambiar de operación o responde al dato pendiente.')
        if state.get('stage') == 'form':
            if not extract_fields(message) and BACK.match(text):
                return undo_answer(request, state, form_step, LABELS)
            return form_step(request, state, message)
        if state.get('stage') == 'enrollment':
            return choose_enrollment(request, state, message)
        return find_student(request, state, search_term(message))
    if state and not action:
        return find_student(request, state, message.strip())
    if not action and re.fullmatch(r'\d{10}(?:\d{3})?', text):
        action = 'student'
    if action == 'courses':
        courses = Curso.objects.filter(activo=True).order_by('nombre')
        lines = []
        for c in courses[:50]:
            modes = []
            if c.ofrece_presencial:
                modes.append(f'Presencial ${c.valor_presencial:.2f}')
            if c.ofrece_online:
                modes.append(f'Online ${c.valor_online:.2f}')
            lines.append(f'• {c.nombre}: {" / ".join(modes)}')
        return answer('Cursos activos (hasta 50):\n' + '\n'.join(lines) if lines else 'No hay cursos activos.',
                      [link('Ver cursos', 'cursos_lista', modalidad='presencial')])
    if action:
        if not puede_gestionar_matriculas(request.user):
            return answer('No tienes permiso para gestionar estudiantes, pagos o recuperaciones.')
        state = {'intent': action, 'stage': 'search', 'data': {}}
        term = search_term(message)
        if term in ('sus', 'su', 'el mismo', 'del mismo') or not term:
            previous = request.session.get('mercybot_student')
            if previous and action != 'new_recovery':
                student = Estudiante.objects.filter(pk=previous).first()
                if student:
                    request.session.pop(STATE, None)
                    return student_answer(student, action)
        return find_student(request, state, term)
    if 'matricul' in text:
        return answer('Escribe «registrar matrícula» para completar todos los datos y guardar la matrícula desde el chat.',
                      [link('Registrar matrícula', 'matricula_registrar', modalidad='online' if 'online' in text else 'presencial')])
    return knowledge_answer(text) or answer(OUTSIDE)
