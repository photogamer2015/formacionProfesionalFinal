"""Captura conversacional completa del formulario de matrícula.

No escribe registros parciales. Los formularios y el guardado son los mismos
que usa la pantalla normal de registro; las opciones se consultan en cada paso.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from .busqueda import normalizar_texto_busqueda as norm, filtrar_queryset_busqueda
from .forms import EstudianteForm, MatriculaForm, _normalizar_digitos_formateados
from .models import Curso, JornadaCurso, Estudiante, Matricula

STUDENT_FIELDS = list(EstudianteForm.Meta.fields)
# Todo campo del formulario de alta tiene una ruta explícita en este flujo.
# modulos_a_pagar es exclusivamente de matrículas antiguas (no del alta).
LEGACY_FIELDS = {'modulos_a_pagar'}
ACADEMIC_FIELDS = ['curso', 'jornada', 'estado', 'tipo_matricula', 'fecha_matricula',
                   'valor_curso', 'descuento', 'forma_pago', 'valor_pagado', 'tipo_cobro']
PAYMENT_FIELDS = ['metodo_pago', 'banco', 'monto_pago_1', 'metodo_pago_1', 'banco_1',
                  'monto_pago_2', 'metodo_pago_2', 'banco_2']
CLOSING_FIELDS = ['talla_camiseta', 'observaciones', 'tipo_registro', 'vendedora_id',
                  'factura_realizada', 'fact_nombres', 'fact_cedula', 'fact_correo', 'link_comprobante']
LABELS = {
    'cedula': 'cédula / RUC', 'nombres': 'nombres y apellidos',
    'nivel_formacion': 'nivel de formación', 'titulo_profesional': 'título profesional',
    'curso': 'curso', 'jornada': 'jornada y fecha de inicio', 'estado': 'estado de la matrícula',
    'tipo_matricula': 'tipo de matrícula', 'fecha_matricula': 'fecha de matrícula',
    'valor_curso': 'valor del curso (USD)', 'descuento': 'descuento (USD)',
    'forma_pago': 'forma de pago', 'valor_pagado': 'valor pagado inicialmente (USD)',
    'tipo_cobro': 'distribución del pago', 'metodo_pago': 'método de pago',
    'banco': 'banco / aplicación', 'monto_pago_1': 'monto 1 (USD)',
    'metodo_pago_1': 'método de pago 1', 'banco_1': 'banco / aplicación 1',
    'monto_pago_2': 'monto 2 (USD)', 'metodo_pago_2': 'método de pago 2',
    'banco_2': 'banco / aplicación 2', 'talla_camiseta': 'talla de camiseta',
    'tipo_registro': 'origen de la venta', 'vendedora_id': 'asesora / vendedora',
    'factura_realizada': 'factura con datos', 'fact_nombres': 'nombres del titular de factura',
    'fact_cedula': 'cédula / RUC de factura', 'fact_correo': 'correo de factura',
    'link_comprobante': 'enlace del comprobante de pago',
}
ALIASES = {
    'curso': 'curso', 'jornada': 'jornada', 'fecha de inicio': 'jornada',
    'estado': 'estado', 'tipo de matricula': 'tipo_matricula',
    'fecha de matricula': 'fecha_matricula', 'fecha matricula': 'fecha_matricula',
    'valor del curso': 'valor_curso', 'valor curso': 'valor_curso',
    'precio': 'valor_curso', 'descuento': 'descuento', 'forma de pago': 'forma_pago',
    'valor pagado': 'valor_pagado', 'pago inicial': 'valor_pagado',
    'distribucion de pago': 'tipo_cobro', 'distribucion del pago': 'tipo_cobro',
    'tipo de cobro': 'tipo_cobro', 'metodo de pago': 'metodo_pago',
    'metodo': 'metodo_pago', 'banco': 'banco', 'aplicacion': 'banco',
    'monto 1': 'monto_pago_1', 'metodo 1': 'metodo_pago_1', 'banco 1': 'banco_1',
    'monto 2': 'monto_pago_2', 'metodo 2': 'metodo_pago_2', 'banco 2': 'banco_2',
    'metodo de pago 1': 'metodo_pago_1', 'metodo de pago 2': 'metodo_pago_2',
    'talla': 'talla_camiseta', 'talla de camiseta': 'talla_camiseta',
    'origen': 'tipo_registro', 'tipo de registro': 'tipo_registro',
    'asesor': 'vendedora_id', 'asesora': 'vendedora_id', 'vendedora': 'vendedora_id',
    'factura': 'factura_realizada', 'factura con datos': 'factura_realizada',
    'factura realizada': 'factura_realizada', 'nombre factura': 'fact_nombres',
    'nombres factura': 'fact_nombres', 'nombres de factura': 'fact_nombres',
    'cedula factura': 'fact_cedula', 'cedula de factura': 'fact_cedula', 'ruc factura': 'fact_cedula',
    'correo factura': 'fact_correo', 'correo de factura': 'fact_correo',
    'comprobante': 'link_comprobante', 'link comprobante': 'link_comprobante',
    'enlace comprobante': 'link_comprobante',
}
for _field in STUDENT_FIELDS + ['permitir_celular_duplicado'] + ACADEMIC_FIELDS + PAYMENT_FIELDS + CLOSING_FIELDS:
    ALIASES.setdefault(_field, _field)


def remember(state, names):
    """Orden real en que se capturaron los datos, para poder deshacerlos."""
    names = [name for name in names if name]
    if not names:
        return
    filled = [name for name in (state.get('filled') or []) if name not in names]
    state['filled'] = filled + names


def step_back(state):
    """Descarta el último dato capturado y devuelve su nombre, o None."""
    data = state.setdefault('data', {})
    filled = list(state.get('filled') or [])
    while filled:
        name = filled.pop()
        if name not in data:
            continue
        data.pop(name, None)
        if name == 'curso':
            # La jornada y el precio dependen del curso: vuelven a preguntarse.
            for dependent in ('jornada', 'valor_curso', 'talla_camiseta'):
                data.pop(dependent, None)
            filled = [f for f in filled if f not in ('jornada', 'valor_curso', 'talla_camiseta')]
            state.pop('curso_pk', None)
            state.pop('jornada_pk', None)
        elif name == 'jornada':
            state.pop('jornada_pk', None)
        # Volver atrás reabre la pregunta: los opcionales dejan de saltarse.
        state['skip_optional'] = False
        state['filled'] = filled
        return name
    state['filled'] = filled
    return None


def field_value(name, value, field):
    value = value.strip()
    normalized = norm(value)
    if normalized in ('omitir', 'sin dato', 'ninguno', 'ninguna', 'no tengo', 'no tiene'):
        return ''
    if isinstance(field, forms.BooleanField):
        return normalized in ('si', 'true', 'confirmo', '1')
    if isinstance(field, forms.DateField):
        if normalized == 'hoy':
            return timezone.localdate().isoformat()
        for fmt in ('%d/%m/%Y', '%d-%m-%Y'):
            try:
                return datetime.strptime(value, fmt).date().isoformat()
            except ValueError:
                pass
    if isinstance(field, forms.DecimalField):
        return value.replace('$', '').strip().replace(',', '.')
    aliases = {
        'tipo_matricula': {'reserva': 'reserva_abono', 'abono': 'reserva_abono', 'completo': 'programa_completo'},
        'forma_pago': {'completo': 'pago_completo', 'contado': 'pago_completo'},
        'tipo_cobro': {'simple': 'un_solo_metodo', 'un solo': 'un_solo_metodo', 'pago mixto': 'mixto'},
    }
    if normalized in aliases.get(name, {}):
        return aliases[name][normalized]
    if not isinstance(field, forms.ModelChoiceField):
        choices = getattr(field, 'choices', None) or getattr(field.widget, 'choices', [])
        for key, label in choices:
            if normalized in (norm(key), norm(label)):
                return str(key)
    return value


def jornada_label(j, numbered=True):
    description = j.descripcion_otros if j.descripcion == 'otros' else j.get_descripcion_display()
    location = str(j.sede) if j.sede_id else ('Plataforma online' if j.modalidad == 'online' else 'Sin sede')
    label = f'{description} · {j.fecha_inicio:%d/%m/%Y} · {j.get_modalidad_display()} · {location}'
    return f'{j.pk}: {label}' if numbered else label


def resolve_reference(qs, value, kind):
    if not value:
        return None
    value = str(value).strip()
    if value.isascii() and value.isdigit() and len(value) <= 12:
        return qs.filter(pk=int(value)).first()
    if kind == 'jornada':
        parsed = None
        for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d'):
            try:
                parsed = datetime.strptime(value, fmt).date()
                break
            except ValueError:
                pass
        matches = list(qs.filter(fecha_inicio=parsed)[:2]) if parsed else [
            j for j in qs if norm(value) in norm(jornada_label(j))
        ][:2]
    else:
        fields = ['nombre'] if kind == 'curso' else ['first_name', 'last_name', 'username']
        exact = [o for o in qs if norm(value) == norm(o.nombre if kind == 'curso' else (o.get_full_name() or o.username))]
        matches = exact or list(filtrar_queryset_busqueda(qs, value, fields)[:2])
    return matches[0] if len(matches) == 1 else None


def amount(data, name):
    """Valor numérico ya capturado, o None si aún no es un número válido."""
    try:
        return Decimal(str(data.get(name) or '0'))
    except (InvalidOperation, ValueError):
        return None


def net_amount(data):
    """Valor a pagar con descuento, tal como lo calcula el formulario."""
    total, discount = amount(data, 'valor_curso'), amount(data, 'descuento')
    if total is None or discount is None:
        return None
    return max(total - discount, Decimal('0'))


def active_fields(data, course):
    fields = STUDENT_FIELDS + ACADEMIC_FIELDS
    if data.get('tipo_cobro') == 'mixto':
        for suffix in ('1', '2'):
            fields += ['monto_pago_' + suffix, 'metodo_pago_' + suffix]
            if data.get('metodo_pago_' + suffix) in ('transferencia', 'tarjeta'):
                fields += ['banco_' + suffix]
    elif data.get('tipo_cobro') == 'un_solo_metodo':
        fields += ['metodo_pago']
        if data.get('metodo_pago') in ('transferencia', 'tarjeta'):
            fields += ['banco']
    # Igual que el formulario: camiseta para categoría Técnico.
    if course and course.categoria and norm(course.categoria.nombre.strip()) == 'tecnico':
        fields += ['talla_camiseta']
    fields += ['observaciones', 'tipo_registro', 'vendedora_id', 'factura_realizada']
    if data.get('factura_realizada') == 'si':
        fields += ['fact_nombres', 'fact_cedula', 'fact_correo']
    return fields + ['link_comprobante']


def required(name, field, data):
    if name in ('tipo_cobro', 'vendedora_id') or name in PAYMENT_FIELDS:
        return True
    if data.get('factura_realizada') == 'si' and name in ('celular', 'ciudad', 'fact_nombres', 'fact_cedula'):
        return True
    return field.required


def enrollment_step(request, state, message):
    from .mercybot import STATE, answer, extract_fields, link
    data = state.setdefault('data', {})
    state['intent'] = 'new_enrollment'
    state['stage'] = 'form'
    request.session[STATE] = state
    template_student = EstudianteForm(documento_flexible=True)
    template_enrollment = MatriculaForm(prefix='mat')
    definitions = {**template_student.fields, **template_enrollment.fields,
                   'vendedora_id': forms.CharField(label='Asesora / vendedora')}
    incoming = extract_fields(message)
    if norm(message).strip() == 'omitir opcionales':
        state['skip_optional'] = True
    elif message and not incoming and state.get('waiting'):
        incoming[state['waiting']] = message
    # Se comparan las opciones ya resueltas: escribir la misma jornada de otra
    # forma (fecha y luego número) no debe borrar el valor del curso ya indicado.
    old_course, old_jornada = state.get('curso_pk'), state.get('jornada_pk')
    old_document = data.get('cedula')
    captured = []
    for name, value in incoming.items():
        if name in definitions and name not in LEGACY_FIELDS:
            data[name] = field_value(name, value, definitions[name])
            captured.append(name)
    remember(state, captured)
    if data.get('cedula'):
        data['cedula'] = _normalizar_digitos_formateados(data['cedula'])
    if old_document and data.get('cedula') != old_document:
        for name in STUDENT_FIELDS + ['permitir_celular_duplicado']:
            if name != 'cedula' and name not in incoming:
                data.pop(name, None)
        state.pop('loaded_document', None)
    notices = []
    existing = None
    if data.get('cedula'):
        existing = Estudiante.objects.filter(cedula=data['cedula']).first()
        if existing and state.get('loaded_document') != data['cedula']:
            for name in STUDENT_FIELDS:
                value = getattr(existing, name)
                data.setdefault(name, str(value) if value is not None else '')
            state['loaded_document'] = data['cedula']
            notices.append(f'Encontré a {existing.nombres}. Usaré sus datos actuales; puedes corregirlos con «campo: valor».')

    courses = template_enrollment.fields['curso'].queryset.select_related('categoria').order_by('nombre')
    course = resolve_reference(courses, data.get('curso'), 'curso')
    if course:
        data['curso'] = str(course.pk)
        if old_course and old_course != data['curso']:
            for name in ('jornada', 'valor_curso', 'talla_camiseta'):
                if name not in incoming:
                    data.pop(name, None)
            if 'jornada' not in data:
                state.pop('jornada_pk', None)
                old_jornada = None
        state['curso_pk'] = data['curso']
    jornadas = JornadaCurso.objects.filter(curso=course, activo=True).select_related('sede').order_by('fecha_inicio', 'pk') if course else JornadaCurso.objects.none()
    jornada = resolve_reference(jornadas, data.get('jornada'), 'jornada')
    if jornada:
        data['jornada'] = str(jornada.pk)
        if old_jornada and old_jornada != data['jornada'] and 'valor_curso' not in incoming:
            data.pop('valor_curso', None)
        if old_jornada != data['jornada']:
            state['jornada_pk'] = data['jornada']
            notices.append('Jornada seleccionada: ' + jornada_label(jornada, numbered=False) + f'. Precio del curso: ${course.valor_para(jornada.modalidad):.2f}.')
        if norm(str(data.get('valor_curso', ''))) in ('usar valor', 'valor del curso', 'precio del curso', 'usar precio', 'precio sugerido'):
            data['valor_curso'] = str(course.valor_para(jornada.modalidad))
    advisors = User.objects.all().order_by('first_name', 'username')
    advisor = request.user if norm(str(data.get('vendedora_id', ''))) == 'yo' else resolve_reference(advisors, data.get('vendedora_id'), 'asesor')
    if advisor:
        data['vendedora_id'] = str(advisor.pk)

    fields = active_fields(data, course)
    for name in fields:
        if state.get('skip_optional') and name not in data and not required(name, definitions[name], data):
            data[name] = ''
    # Los campos no aplicables no viajan con valores de selecciones anteriores.
    allowed = set(fields) | {'permitir_celular_duplicado'}
    post = {('est-' if name in template_student.fields else 'mat-') + name: value
            for name, value in data.items() if name in allowed and name != 'vendedora_id'}
    post['mat-curso'] = str(course.pk) if course else ''
    post['mat-jornada'] = str(jornada.pk) if jornada else ''
    student_form = EstudianteForm(post, prefix='est', instance=existing,
                                  documento_flexible=True, factura_si=data.get('factura_realizada') == 'si')
    enrollment_form = MatriculaForm(post, prefix='mat', modalidad=jornada.modalidad if jornada else 'presencial')
    student_form.is_valid()
    enrollment_form.is_valid()
    errors = {**student_form.errors, **enrollment_form.errors}
    # La factura genera error global en el formulario. Señalar sus campos exactos.
    for name in fields:
        if required(name, definitions[name], data) and name in data and data[name] in ('', None):
            errors.setdefault(name, ['Este dato es obligatorio.'])
    if data.get('curso') and not course:
        errors['curso'] = ['No hay una coincidencia única entre los cursos disponibles. Selecciona por su número.']
    if course and not jornadas.exists():
        errors['curso'] = ['Este curso no tiene jornadas activas. Elige otro o configura sus jornadas antes de matricular.']
    if data.get('jornada') and not jornada:
        errors['jornada'] = ['La jornada o fecha no identifica una única jornada activa de este curso. Selecciona su número.']
    if jornada and ((jornada.modalidad == 'online' and not course.ofrece_online) or
                    (jornada.modalidad == 'presencial' and not course.ofrece_presencial)):
        errors['jornada'] = ['El curso ya no ofrece la modalidad de esta jornada. Selecciona otra.']
    if data.get('vendedora_id') and not advisor:
        errors['vendedora_id'] = ['No encontré una asesora única con ese dato. Selecciona su número.']

    # No se pierde la pregunta actual cuando se proporcionan otros campos.
    invalid = [name for name in fields if name in data and name in errors]
    missing = [name for name in fields if name not in data]
    if invalid or missing:
        name = (invalid or missing)[0]
        state['waiting'] = name
        request.session[STATE] = state
        lines = notices + (list(errors.get(name, [])) if name in invalid else [])
        lines.append('Indica ' + LABELS.get(name, name) + '.')
        if name == 'curso':
            shown = courses
            raw = data.get('curso', '')
            if raw and not course and not str(raw).isdigit():
                narrowed = filtrar_queryset_busqueda(courses, raw, ['nombre'])
                if narrowed.exists():
                    shown = narrowed
            lines += [f'• {c.pk}: {c.nombre}' for c in shown[:25]]
            lines.append('Escribe el nombre o el número del curso. Puedes escribir parte del nombre para buscar.')
        elif name == 'jornada':
            lines += [f'• {jornada_label(j)}' for j in jornadas[:30]]
            lines.append('Estas son las fechas activas del curso. Responde con el número de jornada o su fecha (DD/MM/AAAA).')
            if jornadas.count() > 30:
                lines.append('Se muestran las primeras 30; puedes buscar otra por fecha.')
        elif name == 'vendedora_id':
            lines += [f'• {a.pk}: {a.get_full_name() or a.username}' for a in advisors[:30]]
            lines.append('Escribe el número, nombre o «yo» para asignarte la venta.')
        else:
            field = definitions[name]
            choices = getattr(field, 'choices', None) or getattr(field.widget, 'choices', [])
            lines += [f'• {key}: {label}' for key, label in choices if key]
            if name == 'fecha_matricula':
                lines.append('Usa DD/MM/AAAA o «hoy». Es la fecha del registro; la fecha de inicio la determina la jornada.')
            if name == 'valor_curso' and jornada:
                lines.append(f'Precio del curso para {jornada.get_modalidad_display()}: ${course.valor_para(jornada.modalidad):.2f}. Escribe «usar valor» o indica el valor acordado.')
            if name == 'forma_pago' and data.get('tipo_matricula') == 'reserva_abono':
                lines.append('La matrícula con Reserva / Abono utiliza la forma de pago «abono».')
            if name == 'valor_pagado':
                limits = ['Debe ser mayor a $0']
                if data.get('tipo_matricula') == 'reserva_abono':
                    limits.append('la reserva inicial es de al menos $10.00')
                net = net_amount(data)
                if net is not None:
                    limits.append(f'el máximo a registrar ahora es ${net:.2f} (valor con descuento)')
                lines.append('; '.join(limits) + '.')
            if name in ('monto_pago_1', 'monto_pago_2') and data.get('valor_pagado'):
                lines.append(f'La suma del monto 1 y el monto 2 debe ser exactamente ${amount(data, "valor_pagado") or 0:.2f}.')
            if name.startswith('banco'):
                lines.append('Si es otro banco, escribe su nombre completo.')
            if name == 'celular' and name in invalid and 'compartido' in ' '.join(errors[name]):
                lines.append('Si es intencional, escribe «número compartido: sí» o indica otro celular.')
            if not required(name, field, data):
                lines.append('Es opcional: puedes escribir «omitir» o «omitir opcionales».')
        # El recordatorio acompaña la primera pregunta y cada corrección, no
        # todas las respuestas: repetirlo 25 veces seguidas estorba la lectura.
        if invalid or not state.get('tip_shown'):
            lines.append('Puedes corregir cualquier dato con «campo: valor», escribir «atrás» para volver '
                         'al paso anterior o «cancelar» para descartar esta matrícula pendiente.')
            state['tip_shown'] = True
            request.session[STATE] = state
        return answer('\n'.join(lines))
    if not student_form.is_valid() or not enrollment_form.is_valid():
        return answer('Revisa los datos antes de registrar:\n' + '\n'.join(
            str(error) for form in (student_form, enrollment_form) for field_errors in form.errors.values() for error in field_errors))

    with transaction.atomic():
        # Serializa altas de la misma jornada, incluso entre distintos asesores.
        locked = JornadaCurso.objects.select_for_update().get(pk=jornada.pk)
        locked_course = Curso.objects.select_for_update().get(pk=course.pk)
        if not locked.activo or locked.curso_id != course.pk or not locked_course.activo:
            data.pop('jornada', None)
            return answer('El curso o la jornada cambió mientras completabas la matrícula. Escribe «jornada:» con otra opción o «curso:» con otro curso.')
        if existing:
            Estudiante.objects.select_for_update().get(pk=existing.pk)
            duplicate = Matricula.objects.filter(estudiante=existing, jornada=locked, estado='activa').first()
            if duplicate:
                request.session.pop(STATE, None)
                return answer('El estudiante ya tiene una matrícula activa en esta misma jornada. No generé otra matrícula ni otro pago.',
                              [link('Ver matrícula existente', 'matricula_abonos', pk=duplicate.pk)])
        from .views import _guardar_matricula_formularios
        matricula = _guardar_matricula_formularios(student_form, enrollment_form, advisor, request.user)
    request.session.pop(STATE, None)
    request.session['mercybot_student'] = matricula.estudiante_id
    summary = [f'Matrícula #{matricula.pk} registrada para {matricula.estudiante.nombres}.',
               f'Cédula: {matricula.estudiante.cedula}', f'Curso: {course.nombre}',
               'Jornada: ' + jornada_label(jornada, numbered=False),
               f'Inicio de clases: {jornada.fecha_inicio:%d/%m/%Y} · Modalidad: {matricula.get_modalidad_display()}',
               f'Fecha de matrícula: {matricula.fecha_matricula:%d/%m/%Y}',
               f'Estado: {matricula.get_estado_display()} · Tipo: {matricula.get_tipo_matricula_display()}',
               f'Valor: ${matricula.valor_curso:.2f} · Descuento: ${matricula.descuento:.2f}',
               f'Pago inicial registrado: ${matricula.valor_pagado:.2f} · Saldo: ${matricula.saldo:.2f}',
               f'Asesora: {advisor.get_full_name() or advisor.username}',
               f'Origen: {matricula.get_tipo_registro_display()} · Factura con datos: {matricula.get_factura_realizada_display()}',
               'La matrícula y su pago inicial ya están en el sistema.']
    return answer('\n'.join(summary), [link('Ver matrícula y pagos', 'matricula_abonos', pk=matricula.pk),
                                      link('Ver estudiante', 'estudiante_detalle', pk=matricula.estudiante_id)])
