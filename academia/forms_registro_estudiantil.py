"""Registro Estudiantil: hoja de matrículas con los datos del Excel del equipo.

Las asesoras solo la consultan. El administrador corrige en la misma hoja,
celda por celda (cada cambio envía la fila completa a este formulario), la fecha,
quién registró, el estudiante, la vendedora, la central, el curso, la
modalidad, la jornada, el tipo de matrícula, el pago hecho al matricular y el
número de factura, con las mismas reglas que el resto del sistema:

- El pago de la matrícula es el mismo que usa «Editar pago inicial»: los
  abonos más antiguos con la fecha de la matrícula. Solo se corrige aquí si es
  un único pago con un solo método; los mixtos o repartidos en varios módulos
  se corrigen en «Editar pago inicial».
- En Reserva / Abono ese pago es de máximo $10 (un pago antiguo mayor se
  respeta mientras no cambien su monto ni el tipo de matrícula).
- Los pagos posteriores nunca se tocan.
- Al cambiar el curso, la modalidad o el tipo de matrícula, el valor del curso
  se recalcula con el precio vigente del curso (como «Aplicar el precio actual
  del curso» en el admin).
- Ningún cambio vuelve a enviar correos al estudiante.
"""
from decimal import Decimal

from django import forms
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import User
from django.db.models import Max, Q, Sum

from .forms import ERROR_TOPE_RESERVA_EDICION, _revisar_banco
from .forms_edicion_venta import limpiar_numero_factura
from .models import (
    Abono, Comprobante, Curso, JornadaCurso, METODOS_PAGO,
    MONTO_RESERVA_MATRICULA, TIPO_MATRICULA, TIPOS_REGISTRO,
    TIPOS_SIN_COBRO_INICIAL, nombre_banco, nombre_metodo_pago,
)
from .permisos import GRUPO_ADMIN, GRUPO_ASESOR


CERO = Decimal('0.00')

MODALIDADES_REGISTRO = [
    ('presencial', 'Presencial'),
    ('online', 'Virtual (online)'),
]


def bloque_pago_inicial(matricula, abonos=None):
    """Abonos del pago hecho al matricular.

    Misma regla que ``views._ids_abonos_pago_inicial``: los abonos más
    antiguos (por orden de creación) con la fecha de la matrícula; el primero
    con otra fecha corta el bloque. ``abonos`` permite pasar la lista ya
    cargada y ordenada por (creado, id) para no consultar fila por fila.
    """
    if abonos is None:
        abonos = matricula.abonos.order_by('creado', 'id')
    bloque = []
    for abono in abonos:
        if abono.fecha != matricula.fecha_matricula:
            break
        bloque.append(abono)
    return bloque


def resumen_pago_inicial(bloque):
    """Valor, forma de pago y banco del pago de la matrícula, para mostrar."""
    if not bloque:
        return None
    metodos, bancos = [], []
    for abono in bloque:
        pares = [(abono.metodo, abono.banco)]
        if (abono.monto_2 or CERO) > 0:
            pares.append((abono.metodo_2, abono.banco_2))
        for metodo, banco in pares:
            etiqueta = nombre_metodo_pago(metodo)
            if etiqueta and etiqueta not in metodos:
                metodos.append(etiqueta)
            etiqueta = nombre_banco(banco)
            if etiqueta and etiqueta not in bancos:
                bancos.append(etiqueta)
    return {
        'monto': sum((a.monto for a in bloque), CERO),
        'forma': ' + '.join(metodos),
        'banco': ' + '.join(bancos),
    }


def pago_inicial_editable(bloque):
    """Solo un pago con un único método se corrige desde el registro."""
    return (
        len(bloque) == 1
        and bloque[0].cuenta_para_saldo
        and not (bloque[0].monto_2 or CERO) > 0
    )


def usuarios_editables(*actuales):
    """Asesoras y administradores activos, más los ya asignados (aunque estén
    inactivos), para elegir quién registra y quién vendió."""
    return User.objects.filter(
        Q(pk__in=[pk for pk in actuales if pk])
        | Q(is_active=True) & (
            Q(is_superuser=True)
            | Q(groups__name__in=[GRUPO_ADMIN, GRUPO_ASESOR])
        )
    ).distinct().order_by('first_name', 'last_name', 'username')


def cursos_editables(*actuales):
    """Cursos activos que se ofrecen en alguna modalidad, más los ya usados."""
    return Curso.objects.filter(
        Q(pk__in=[pk for pk in actuales if pk])
        | Q(activo=True) & (Q(ofrece_presencial=True) | Q(ofrece_online=True))
    ).order_by('nombre')


def jornadas_editables(cursos, *actuales):
    """Jornadas activas de esos cursos, más las ya asignadas."""
    return JornadaCurso.objects.filter(
        Q(pk__in=[pk for pk in actuales if pk])
        | Q(activo=True, curso__in=cursos)
    ).select_related('sede').order_by('fecha_inicio', 'pk')


def nombre_usuario(usuario):
    if not usuario:
        return ''
    return usuario.get_full_name().strip() or usuario.username


def etiqueta_jornada(jornada):
    """Días, fecha de inicio, horario y sede de una jornada."""
    partes = [jornada.descripcion_legible]
    if jornada.fecha_inicio:
        partes.append(f'inicia {jornada.fecha_inicio:%d/%m/%Y}')
    if jornada.hora_inicio and jornada.hora_fin:
        partes.append(f'{jornada.hora_inicio:%H:%M}–{jornada.hora_fin:%H:%M}')
    if jornada.sede_nombre:
        partes.append(jornada.sede_nombre)
    if not jornada.activo:
        partes.append('(desactivada)')
    return ' · '.join(partes)


def _dinero(valor):
    return f'${valor or CERO:.2f}'


class RegistroEstudiantilForm(forms.Form):
    # Marca de la última modificación: si otra persona guarda la matrícula
    # mientras el formulario está abierto, no se pisan sus cambios.
    version = forms.CharField()
    fecha_matricula = forms.DateField(label='Fecha de matrícula')
    registrado_por = forms.ModelChoiceField(
        queryset=User.objects.none(), label='Registra', required=False,
    )
    nombres = forms.CharField(label='Nombres del estudiante', max_length=200)
    vendedora = forms.ModelChoiceField(
        queryset=User.objects.none(), label='Vendedora', required=False,
    )
    tipo_registro = forms.ChoiceField(label='Central', required=False)
    curso = forms.ModelChoiceField(
        queryset=Curso.objects.none(), label='Programa / Curso',
    )
    modalidad = forms.ChoiceField(label='Modalidad', choices=MODALIDADES_REGISTRO)
    # En la hoja, «Jornada» y «Fecha de inicio» eligen juntas esta jornada.
    jornada = forms.ModelChoiceField(
        queryset=JornadaCurso.objects.none(), label='Jornada y fecha de inicio',
        required=False,
    )
    tipo_matricula = forms.ChoiceField(label='Matrícula')
    valor_pago = forms.DecimalField(
        label='Valor', min_value=Decimal('0.01'), max_digits=10,
        decimal_places=2,
    )
    metodo_pago = forms.ChoiceField(label='Forma de pago', choices=METODOS_PAGO)
    banco = forms.CharField(label='Banco', required=False)
    numero_factura = forms.CharField(
        label='No. de factura', required=False, max_length=20,
    )

    def __init__(self, data=None, *, matricula, **kwargs):
        self.matricula = m = matricula
        self.bloque_pago = bloque_pago_inicial(m)
        self.pago_editable = pago_inicial_editable(self.bloque_pago)
        self.conflicto = False
        abono = self.bloque_pago[0] if self.pago_editable else None
        self.abono_inicial = abono
        initial = {
            'version': self.version_actual,
            'fecha_matricula': m.fecha_matricula,
            'registrado_por': m.registrado_por_id,
            'nombres': ' '.join((m.estudiante.nombres or '').split()),
            'vendedora': m.vendedora_id,
            'tipo_registro': m.tipo_registro,
            'curso': m.curso_id,
            'modalidad': m.modalidad,
            'jornada': m.jornada_id,
            'tipo_matricula': m.tipo_matricula,
            'numero_factura': m.numero_factura,
        }
        if abono:
            initial.update(
                valor_pago=abono.monto, metodo_pago=abono.metodo,
                banco=abono.banco,
            )
        super().__init__(data, initial=initial, **kwargs)

        usuarios = usuarios_editables(m.registrado_por_id, m.vendedora_id)
        # Un dato que ya existe se puede cambiar, pero no dejar vacío.
        for campo, actual in (
            ('registrado_por', m.registrado_por_id),
            ('vendedora', m.vendedora_id),
        ):
            field = self.fields[campo]
            field.queryset = usuarios
            field.required = bool(actual)

        self.fields['tipo_registro'].required = bool(m.tipo_registro)
        self.fields['tipo_registro'].choices = (
            [] if m.tipo_registro else [('', '— Sin central —')]
        ) + list(TIPOS_REGISTRO)

        cursos = cursos_editables(m.curso_id)
        self.fields['curso'].queryset = cursos
        self.fields['jornada'].queryset = jornadas_editables(cursos, m.jornada_id)

        # «Reserva + Módulo 1» ya no se ofrece; solo la conserva quien la tiene.
        self.fields['tipo_matricula'].choices = [
            choice for choice in TIPO_MATRICULA
            if choice[0] != 'reserva_modulo_1'
            or m.tipo_matricula == 'reserva_modulo_1'
        ]

        if not self.pago_editable:
            for campo in ('valor_pago', 'metodo_pago', 'banco'):
                del self.fields[campo]

    @property
    def version_actual(self):
        return self.matricula.actualizado.isoformat()

    # ── Validación ───────────────────────────────────────────────────

    def clean_nombres(self):
        nombres = ' '.join((self.cleaned_data.get('nombres') or '').split())
        if not nombres:
            raise forms.ValidationError('Escribe los nombres del estudiante.')
        return nombres

    def clean_numero_factura(self):
        return limpiar_numero_factura(self.cleaned_data.get('numero_factura'))

    def clean(self):
        cleaned = super().clean()
        m = self.matricula

        self.conflicto = cleaned.get('version') != self.version_actual
        if self.conflicto:
            raise forms.ValidationError(
                'Otra persona modificó esta matrícula mientras la editabas. '
                'Recarga la hoja para ver los datos actuales.'
            )

        curso = cleaned.get('curso')
        modalidad = cleaned.get('modalidad')
        tipo = cleaned.get('tipo_matricula')
        if 'jornada' in self.errors or not (curso and modalidad and tipo):
            return cleaned
        jornada = cleaned.get('jornada')

        self.curso_cambia = curso.pk != m.curso_id
        self.modalidad_cambia = modalidad != m.modalidad
        self.tipo_cambia = tipo != m.tipo_matricula
        jornada_cambia = (jornada.pk if jornada else None) != m.jornada_id
        campo_precio = 'curso' if self.curso_cambia else (
            'modalidad' if self.modalidad_cambia else 'tipo_matricula'
        )

        # ── Jornada: siempre del curso y la modalidad elegidos ──
        if jornada is None:
            if m.jornada_id or self.curso_cambia or self.modalidad_cambia:
                self.add_error(
                    'jornada',
                    'Elige la jornada (fecha de inicio) del curso en esa modalidad.',
                )
        elif jornada.curso_id != curso.pk or jornada.modalidad != modalidad:
            self.add_error(
                'jornada', 'La jornada elegida no es de ese curso y modalidad.',
            )
        elif jornada_cambia and jornada.modalidad == 'presencial' and not jornada.sede_id:
            self.add_error(
                'jornada', 'La jornada presencial seleccionada debe tener sede.',
            )

        # ── Cambio de curso o modalidad: lo ya registrado debe seguir cuadrando ──
        if self.curso_cambia and m.recuperaciones_pendientes.exists():
            self.add_error(
                'curso',
                'Tiene clases en recuperación del curso actual. Resuélvelas en '
                'Recuperaciones antes de cambiar el curso.',
            )
        if self.curso_cambia or self.modalidad_cambia:
            numero_modulos = curso.get_numero_modulos(modalidad)
            modulo_pagado = m.abonos.filter(
                numero_modulo__gt=numero_modulos,
            ).aggregate(n=Max('numero_modulo'))['n']
            if modulo_pagado:
                self.add_error(
                    campo_precio,
                    f'Tiene pagos del módulo {modulo_pagado}, pero {curso.nombre} '
                    f'en {dict(MODALIDADES_REGISTRO)[modalidad].lower()} tiene '
                    f'{numero_modulos} módulo(s).',
                )

        # ── Valor del curso según el curso, la modalidad y el tipo ──
        valor_curso, descuento = m.valor_curso or CERO, m.descuento or CERO
        if tipo == 'otros':
            if m.abonos.exists():
                self.add_error(
                    'tipo_matricula',
                    '«Otros» es sin costo y esta matrícula ya tiene pagos '
                    'registrados. Elimínalos en Pagos antes de cambiar el tipo.',
                )
            valor_curso = descuento = CERO
        else:
            # En «Inscripción (gratis)» el valor guardado ya descuenta los $10.
            ajuste = MONTO_RESERVA_MATRICULA if tipo == 'inscripcion_gratis' else CERO
            if self.curso_cambia or self.modalidad_cambia or m.tipo_matricula == 'otros':
                precio = curso.valor_para(modalidad) or CERO
                if precio <= 0:
                    self.add_error(
                        campo_precio,
                        f'{curso.nombre} no tiene precio en modalidad '
                        f'{dict(MODALIDADES_REGISTRO)[modalidad].lower()}. '
                        'Configúralo en Cursos Disponibles.',
                    )
                valor_curso = precio - ajuste
            elif self.tipo_cambia:
                if tipo == 'inscripcion_gratis':
                    valor_curso -= MONTO_RESERVA_MATRICULA
                elif m.tipo_matricula == 'inscripcion_gratis':
                    valor_curso += MONTO_RESERVA_MATRICULA
            if tipo == 'inscripcion_gratis' and valor_curso - descuento <= 0:
                self.add_error(
                    campo_precio,
                    'Con la inscripción gratis de $10.00 no queda valor por '
                    'pagar en módulos. Si no se cobra nada, usa «Otros».',
                )
            elif descuento > valor_curso:
                self.add_error(
                    campo_precio,
                    f'El descuento ({_dinero(descuento)}) sería mayor que el '
                    f'valor del curso ({_dinero(valor_curso)}).',
                )
        self.valor_curso_nuevo = valor_curso
        self.descuento_nuevo = descuento
        neto = max(valor_curso - descuento, CERO)

        # ── Pago de la matrícula ──
        monto_inicial = sum(
            (a.monto for a in self.bloque_pago if a.cuenta_para_saldo), CERO,
        )
        monto_nuevo = monto_inicial
        if self.pago_editable:
            _revisar_banco(self, cleaned, 'metodo_pago', 'banco')
            if cleaned.get('valor_pago') is not None:
                monto_nuevo = cleaned['valor_pago']
        # Reserva / Abono: el pago de la matrícula es de máximo $10, igual que
        # en el registro y en «Editar pago inicial». Un pago antiguo mayor se
        # respeta mientras no cambien su monto ni el tipo de matrícula.
        if tipo == 'reserva_abono' and monto_nuevo > MONTO_RESERVA_MATRICULA:
            if monto_nuevo != monto_inicial:
                self.add_error('valor_pago', ERROR_TOPE_RESERVA_EDICION)
            elif self.tipo_cambia:
                self.add_error(
                    'tipo_matricula',
                    f'En Reserva / Abono el pago de la matrícula es de máximo '
                    f'${MONTO_RESERVA_MATRICULA} y esta matrícula tiene '
                    f'{_dinero(monto_nuevo)}. Si el estudiante pagó más, deja '
                    'el tipo que tiene o corrige primero el pago de la matrícula.',
                )
        pagado = m.abonos.filter(cuenta_para_saldo=True).aggregate(
            s=Sum('monto'),
        )['s'] or CERO
        pagado_nuevo = pagado - monto_inicial + monto_nuevo
        # Solo se frena lo que deja pagado de más (o aumenta un exceso que ya
        # existía, p. ej. tras bajar el precio del curso).
        exceso_nuevo = pagado_nuevo - neto
        if tipo != 'otros' and exceso_nuevo > 0 and exceso_nuevo > pagado - m.valor_neto:
            self.add_error(
                'valor_pago' if monto_nuevo != monto_inicial else campo_precio,
                f'Los pagos registrados ({_dinero(pagado_nuevo)}) superarían '
                f'el valor a pagar con descuento ({_dinero(neto)}).',
            )

        # ── Fecha: el pago de la matrícula se mueve con ella ──
        fecha = cleaned.get('fecha_matricula')
        if fecha and fecha != m.fecha_matricula:
            posterior = m.abonos.exclude(
                pk__in=[a.pk for a in self.bloque_pago],
            ).filter(fecha__lte=fecha).order_by('fecha', 'creado').first()
            if posterior:
                self.add_error(
                    'fecha_matricula',
                    f'Hay un pago posterior del {posterior.fecha:%d/%m/%Y} '
                    f'(recibo {posterior.numero_recibo}). La fecha de matrícula '
                    'debe ser anterior a ese pago.',
                )
        return cleaned

    # ── Guardado ─────────────────────────────────────────────────────

    def guardar(self, usuario):
        """Aplica los cambios y devuelve la lista de lo que cambió."""
        m = self.matricula
        cd = self.cleaned_data
        estudiante = m.estudiante
        cambios = []

        def anotar(etiqueta, antes, despues, cambia=None):
            if cambia is None:
                cambia = antes != despues
            if cambia:
                cambios.append(f'{etiqueta}: {antes or "—"} → {despues or "—"}')

        def pk(objeto):
            return objeto.pk if objeto else None

        # 1) Nombre del estudiante (se corrige en todas sus matrículas).
        nombres = cd['nombres']
        if nombres != ' '.join((estudiante.nombres or '').split()):
            anotar('Estudiante', estudiante.nombres, nombres)
            estudiante.nombres = nombres
            estudiante.save(update_fields=['nombres'])
            Comprobante.objects.filter(matricula__estudiante=estudiante).update(
                nombre_persona=nombres,
            )

        # 2) Pago de la matrícula. Abono.save() recalcula el valor pagado y, al
        #    no ser un pago nuevo, no vuelve a enviar el recibo por correo.
        fecha = cd['fecha_matricula']
        fecha_cambia = fecha != m.fecha_matricula
        abono = self.abono_inicial
        if abono:
            antes = (abono.monto, abono.metodo, abono.banco)
            abono.monto = cd['valor_pago']
            abono.metodo = cd['metodo_pago']
            abono.banco = cd['banco']
            abono.fecha = fecha
            anotar('Valor', _dinero(antes[0]), _dinero(abono.monto))
            anotar('Forma de pago', nombre_metodo_pago(antes[1]),
                   nombre_metodo_pago(abono.metodo))
            anotar('Banco', nombre_banco(antes[2]), nombre_banco(abono.banco))
            if fecha_cambia or (abono.monto, abono.metodo, abono.banco) != antes:
                abono.save(update_fields=[
                    'monto', 'metodo', 'banco', 'fecha', 'actualizado',
                ])
        elif fecha_cambia and self.bloque_pago:
            Abono.objects.filter(
                pk__in=[a.pk for a in self.bloque_pago],
            ).update(fecha=fecha)

        # 3) Datos de la matrícula.
        anotar('Fecha de matrícula', f'{m.fecha_matricula:%d/%m/%Y}',
               f'{fecha:%d/%m/%Y}')
        anotar('Registra', nombre_usuario(m.registrado_por),
               nombre_usuario(cd['registrado_por']),
               m.registrado_por_id != pk(cd['registrado_por']))
        anotar('Vendedora', nombre_usuario(m.vendedora),
               nombre_usuario(cd['vendedora']),
               m.vendedora_id != pk(cd['vendedora']))
        tipos_registro = dict(TIPOS_REGISTRO)
        anotar('Central', tipos_registro.get(m.tipo_registro, ''),
               tipos_registro.get(cd['tipo_registro'], ''),
               m.tipo_registro != cd['tipo_registro'])
        anotar('Curso', m.curso.nombre, cd['curso'].nombre,
               m.curso_id != cd['curso'].pk)
        modalidades = dict(MODALIDADES_REGISTRO)
        anotar('Modalidad', modalidades.get(m.modalidad, m.modalidad),
               modalidades[cd['modalidad']], m.modalidad != cd['modalidad'])
        anotar('Jornada',
               etiqueta_jornada(m.jornada) if m.jornada_id else '',
               etiqueta_jornada(cd['jornada']) if cd['jornada'] else '',
               m.jornada_id != pk(cd['jornada']))
        tipos = dict(TIPO_MATRICULA)
        anotar('Matrícula', tipos.get(m.tipo_matricula, m.tipo_matricula),
               tipos[cd['tipo_matricula']])
        anotar('Valor del curso', _dinero(m.valor_curso),
               _dinero(self.valor_curso_nuevo))
        anotar('Descuento', _dinero(m.descuento), _dinero(self.descuento_nuevo))
        anotar('No. de factura', m.numero_factura, cd['numero_factura'])

        m.fecha_matricula = fecha
        m.registrado_por = cd['registrado_por']
        m.vendedora = cd['vendedora']
        m.tipo_registro = cd['tipo_registro']
        m.curso = cd['curso']
        m.jornada = cd['jornada']
        m.modalidad = cd['modalidad']
        m.tipo_matricula = cd['tipo_matricula']
        m.valor_curso = self.valor_curso_nuevo
        m.descuento = self.descuento_nuevo
        if m.tipo_matricula in TIPOS_SIN_COBRO_INICIAL:
            m.forma_pago = ''
        if cd['numero_factura'] != m.numero_factura:
            m.numero_factura = cd['numero_factura']
            # Escribir un número es registrar la factura: el titular sale de
            # los datos del estudiante, igual que en «Registrar factura».
            if m.numero_factura and m.factura_realizada != 'si':
                anotar('Factura', 'No', 'Sí')
                m.factura_realizada = 'si'
                m.fact_nombres = m.fact_nombres or estudiante.nombres.strip()
                m.fact_cedula = m.fact_cedula or estudiante.cedula
                m.fact_correo = m.fact_correo or estudiante.correo

        if cambios:
            # save() de Matricula también actualiza su Comprobante con el
            # valor pagado que dejó el paso 2. No se reescribe valor_pagado.
            m.save(update_fields=[
                'fecha_matricula', 'registrado_por', 'vendedora',
                'tipo_registro', 'curso', 'jornada', 'modalidad',
                'tipo_matricula', 'valor_curso', 'descuento', 'forma_pago',
                'numero_factura', 'factura_realizada', 'fact_nombres',
                'fact_cedula', 'fact_correo', 'actualizado',
            ])
            LogEntry.objects.log_actions(
                usuario.pk, [m], CHANGE,
                'Registro Estudiantil: ' + '; '.join(cambios) + '.',
                single_object=True,
            )
        return cambios
