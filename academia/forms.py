from decimal import Decimal

from django import forms
from django.db.models import Q
from .fecha_matricula import preparar_campo_fecha, validar_fecha_matricula
from .models import (
    Abono, Adicional, BANCOS_PAGO, BANCOS_POR_METODO, CategoriaEgreso,
    Categoria, Comprobante, Curso, Egreso,
    Estudiante, EstudianteArchivado, JornadaCurso, Matricula, MatriculaArchivada,
    METODOS_CON_BANCO, METODOS_PAGO,
    MONTO_RESERVA_MATRICULA, PersonaExterna, RecuperacionPendiente, Sede,
    TIPOS_SIN_COBRO_INICIAL, banco_corresponde_al_metodo, nombre_banco,
    nombre_metodo_pago,
)


def _opciones_banco(valor_actual=''):
    """Opciones del selector de banco de los formularios de pago.

    Incluye todos los bancos del sistema (la pantalla deja visibles solo los
    del método elegido) y el valor ya guardado si se escribió a mano con la
    antigua opción "Otro banco...", para no perderlo al editar.
    """
    opciones = [('', '— Selecciona un banco —')] + list(BANCOS_PAGO)
    if valor_actual and valor_actual not in dict(opciones) and valor_actual != 'OTRO':
        opciones.append((valor_actual, valor_actual))
    return opciones


MENSAJES_FALTA_BANCO = {
    'deposito': 'Debes indicar el banco del depósito.',
    'transferencia': 'Debes indicar el banco cuando el método es Transferencia.',
    'tarjeta': 'Debes indicar la opción de tarjeta o link de pago (Payphone o De una).',
}


def _revisar_banco(form, cleaned, campo_metodo, campo_banco, falta=None):
    """Valida el banco de un pago según su método.

    Depósito y transferencia llevan uno de sus bancos; tarjeta / link de
    pago, Payphone o De una; efectivo no lleva banco y se borra. Un pago
    guardado antes de estas reglas conserva su banco mientras no se cambie
    el método.
    """
    metodo = cleaned.get(campo_metodo) or ''
    if metodo not in METODOS_CON_BANCO:
        cleaned[campo_banco] = ''
        return
    banco = (cleaned.get(campo_banco) or '').strip()
    cleaned[campo_banco] = banco
    if not banco:
        form.add_error(campo_banco, falta or MENSAJES_FALTA_BANCO[metodo])
        return
    guardado = (form.initial.get(campo_metodo), form.initial.get(campo_banco))
    if banco_corresponde_al_metodo(metodo, banco) or (metodo, banco) == guardado:
        return
    admitidos = ', '.join(nombre_banco(b) for b in BANCOS_POR_METODO[metodo])
    form.add_error(
        campo_banco,
        f'{nombre_banco(banco)} no corresponde a {nombre_metodo_pago(metodo)}. '
        f'Elige: {admitidos}.',
    )


def es_ruc_ecuador(valor):
    """Un RUC debe tener exactamente 13 dígitos y terminar en 001."""
    documento = (valor or '').strip()
    return bool(
        documento.isascii()
        and documento.isdigit()
        and len(documento) == 13
        and documento.endswith('001')
    )


def es_cedula_ruc_ecuador_valido(valor, permitir_longitud_flexible=False):
    """
    Valida el formato numérico del documento.

    Por defecto conserva la regla general de cédula/RUC ecuatoriano. El modo
    flexible se usa únicamente al registrar una matrícula, donde la longitud
    no debe impedir buscar o guardar al estudiante.
    """
    documento = (valor or '').strip()
    if permitir_longitud_flexible:
        return bool(
            documento
            and documento.isascii()
            and documento.isdigit()
        )
    return bool(
        documento.isascii()
        and documento.isdigit()
        and (
            len(documento) == 10
            or es_ruc_ecuador(documento)
        )
    )


def _normalizar_digitos_formateados(valor):
    """Quita separadores comunes sin aceptar letras dentro de datos numéricos."""
    texto = (valor or '').strip()
    if any(c.isalpha() for c in texto):
        return texto
    return ''.join(c for c in texto if c.isdigit())


def _normalizar_celular_ecuador(valor):
    """
    Acepta celulares pegados como 0991234567 o +593 99 123 4567 y los deja
    en formato nacional de 10 dígitos.
    """
    texto = (valor or '').strip()
    if any(c.isalpha() for c in texto):
        return texto

    digitos = ''.join(c for c in texto if c.isdigit())
    if digitos.startswith('593'):
        local = digitos[3:]
        if local.startswith('0'):
            digitos = local
        elif len(local) >= 9:
            digitos = '0' + local[:9]
    return digitos


class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ['nombre', 'descripcion', 'color', 'orden', 'activo']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Ej.: Vacacionales'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-input', 'rows': 2}),
            'color': forms.Select(attrs={'class': 'form-input'}),
            'orden': forms.NumberInput(attrs={'class': 'form-input'}),
        }


class CursoForm(forms.ModelForm):
    class Meta:
        model = Curso
        fields = [
            'categoria', 'nombre', 'descripcion',
            'ofrece_presencial', 'valor_presencial', 'valor_anterior_presencial',
            'ofrece_online', 'valor_online', 'valor_anterior_online',
            'duracion', 'numero_modulos', 'numero_modulos_online',
            'es_ciclo_corto', 'pago_unico_online',
            'pagos_cada_dos_semanas',
            'nombrar_modulos', 'activo',
        ]
        widgets = {
            'categoria': forms.Select(attrs={'class': 'form-input', 'id': 'id_categoria'}),
            'nombre': forms.TextInput(attrs={'class': 'form-input'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-input', 'rows': 3}),
            'valor_presencial': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01', 'min': '0'}),
            'valor_online': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01', 'min': '0'}),
            'valor_anterior_presencial': forms.NumberInput(attrs={
                'class': 'form-input', 'step': '0.01', 'min': '0', 'placeholder': 'Opcional',
            }),
            'valor_anterior_online': forms.NumberInput(attrs={
                'class': 'form-input', 'step': '0.01', 'min': '0', 'placeholder': 'Opcional',
            }),
            'duracion': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Ej.: 3 meses, 40 horas…'}),
            'numero_modulos': forms.NumberInput(attrs={
                'class': 'form-input', 'min': '1', 'max': '20', 'step': '1',
                'placeholder': 'Ej.: 4',
            }),
            'numero_modulos_online': forms.NumberInput(attrs={
                'class': 'form-input', 'min': '1', 'max': '20', 'step': '1',
                'placeholder': 'Ej.: 2',
            }),
            'es_ciclo_corto': forms.CheckboxInput(attrs={'class': 'form-checkbox', 'id': 'id_es_ciclo_corto'}),
            'pago_unico_online': forms.CheckboxInput(attrs={
                'class': 'form-checkbox', 'id': 'id_pago_unico_online',
            }),
            'pagos_cada_dos_semanas': forms.CheckboxInput(attrs={
                'class': 'form-checkbox',
                'id': 'id_pagos_cada_dos_semanas',
            }),
            'nombrar_modulos': forms.CheckboxInput(attrs={'class': 'form-checkbox', 'id': 'id_nombrar_modulos'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['categoria'].queryset = Categoria.objects.filter(activo=True)
        self.fields['categoria'].empty_label = '— Selecciona categoría —'

    def clean(self):
        cleaned = super().clean()
        ofrece_pres = cleaned.get('ofrece_presencial')
        ofrece_onl = cleaned.get('ofrece_online')
        if not ofrece_pres and not ofrece_onl:
            raise forms.ValidationError(
                'Debes seleccionar al menos una modalidad (presencial u online).'
            )

        # Valor anterior: opcional; $0 equivale a no tener.
        for campo_valor, campo_anterior in (
            ('valor_presencial', 'valor_anterior_presencial'),
            ('valor_online', 'valor_anterior_online'),
        ):
            anterior = cleaned.get(campo_anterior)
            if anterior is None:
                continue
            if anterior < 0:
                self.add_error(campo_anterior, 'El valor anterior no puede ser negativo.')
            elif anterior == 0:
                cleaned[campo_anterior] = None
            elif anterior == cleaned.get(campo_valor):
                self.add_error(
                    campo_anterior,
                    'Es igual al valor principal. Si el precio no cambió, deja '
                    'el valor anterior vacío.',
                )

        pago_unico_online = cleaned.get('pago_unico_online', False)
        if pago_unico_online and not cleaned.get('es_ciclo_corto'):
            self.add_error(
                'pago_unico_online',
                'El pago único online solo se puede activar en un ciclo corto.',
            )
        if pago_unico_online and not ofrece_onl:
            self.add_error(
                'pago_unico_online',
                'Activa la modalidad online para usar el pago único.',
            )
            
        nombrar = cleaned.get('nombrar_modulos', False)
        nombres_modulos = {'presencial': [], 'online': []}
        
        if nombrar:
            if ofrece_pres:
                num_pres = cleaned.get('numero_modulos') or 0
                for i in range(1, num_pres + 1):
                    val = self.data.get(f'nombre_mod_presencial_{i}', '').strip()
                    nombres_modulos['presencial'].append(val)
                    
            if ofrece_onl:
                num_onl = cleaned.get('numero_modulos_online') or 0
                for i in range(1, num_onl + 1):
                    val = self.data.get(f'nombre_mod_online_{i}', '').strip()
                    nombres_modulos['online'].append(val)
                    
        cleaned['nombres_modulos'] = nombres_modulos
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.nombres_modulos = self.cleaned_data.get('nombres_modulos', {})
        if commit:
            instance.save()
        return instance


class JornadaCursoForm(forms.ModelForm):
    """
    Form para crear/editar una jornada de un curso.
    El campo `descripcion` usa choices estandarizados, e incluye la opción
    'Otros' que habilita un campo de texto libre (`descripcion_otros`).
    La ciudad ahora se elige desde el catálogo de Sedes administrable.
    """
    class Meta:
        model = JornadaCurso
        fields = [
            'modalidad', 'descripcion', 'descripcion_otros', 'fecha_inicio',
            'hora_inicio', 'hora_fin', 'sede', 'activo',
        ]
        widgets = {
            'modalidad': forms.Select(attrs={'class': 'form-input'}),
            # ↓ Antes era TextInput, ahora es Select con los días estándar
            'descripcion': forms.Select(attrs={'class': 'form-input', 'id': 'id_descripcion_dias'}),
            'descripcion_otros': forms.TextInput(attrs={
                'class': 'form-input',
                'id': 'id_descripcion_otros',
                'placeholder': 'Ej. Viernes y Sábado',
            }),
            'fecha_inicio': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'hora_inicio': forms.TimeInput(attrs={'class': 'form-input', 'type': 'time'}),
            'hora_fin': forms.TimeInput(attrs={'class': 'form-input', 'type': 'time'}),
            'sede': forms.Select(attrs={'class': 'form-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Placeholder limpio como primera opción del Select de días
        self.fields['descripcion'].widget.choices = [
            ('', '— Selecciona los días —'),
        ] + list(JornadaCurso._meta.get_field('descripcion').choices)

        # El selector de sede usa solo las sedes activas, más la que ya
        # tuviera la jornada (aunque esté desactivada) para no perderla al editar.
        sede_qs = Sede.objects.filter(activa=True)
        if self.instance and self.instance.pk and self.instance.sede_id:
            sede_qs = Sede.objects.filter(
                Q(activa=True) | Q(pk=self.instance.sede_id)
            )
        self.fields['sede'].queryset = sede_qs.distinct()
        self.fields['sede'].empty_label = '— Selecciona sede —'
        self.fields['sede'].required = False
        self.fields['descripcion_otros'].required = False

    def clean(self):
        cleaned_data = super().clean()
        modalidad = cleaned_data.get('modalidad')
        sede = cleaned_data.get('sede')
        descripcion = cleaned_data.get('descripcion')
        descripcion_otros = (cleaned_data.get('descripcion_otros') or '').strip()

        if modalidad == 'presencial' and not sede:
            self.add_error('sede', 'Debes seleccionar una sede para la modalidad presencial.')

        if descripcion == 'otros' and not descripcion_otros:
            self.add_error(
                'descripcion_otros',
                'Escribe los días personalizados cuando eliges "Otros".'
            )
        # Si no es "otros", limpiamos el texto libre para evitar datos sueltos
        if descripcion != 'otros':
            cleaned_data['descripcion_otros'] = ''

        return cleaned_data


class SedeForm(forms.ModelForm):
    """Form para que el admin cree/edite sedes desde el panel (sin tocar código)."""
    class Meta:
        model = Sede
        fields = ['nombre', 'pais', 'direccion', 'telefono', 'orden', 'activa']
        widgets = {
            'nombre': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'Ej. Guayaquil',
            }),
            'pais': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'Ej. Ecuador',
            }),
            'direccion': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'Dirección (opcional)',
            }),
            'telefono': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'Teléfono (opcional)',
            }),
            'orden': forms.NumberInput(attrs={'class': 'form-input', 'min': 0}),
            'activa': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }
        labels = {
            'nombre': 'Nombre de la sede / ciudad',
            'pais': 'País',
            'direccion': 'Dirección',
            'telefono': 'Teléfono',
            'orden': 'Orden de aparición',
            'activa': 'Sede activa',
        }

    def clean_nombre(self):
        return (self.cleaned_data.get('nombre') or '').strip()

    def clean_pais(self):
        pais = (self.cleaned_data.get('pais') or '').strip()
        return pais or 'Ecuador'


class EstudianteForm(forms.ModelForm):
    # Campo extra (no del modelo): permite al usuario confirmar que quiere
    # usar un celular que ya pertenece a otro estudiante (familia, padres
    # que registran varios hijos con el mismo número, etc.).
    permitir_celular_duplicado = forms.BooleanField(
        required=False,
        label='Confirmo: número compartido (familia, hijos del mismo padre, etc.)',
        widget=forms.CheckboxInput(attrs={
            'id': 'id_est-permitir_celular_duplicado',
            'class': 'form-checkbox',
        }),
    )

    def __init__(self, *args, **kwargs):
        # Cuando la matrícula lleva factura con datos, celular/ciudad pasan a
        # ser obligatorios. El correo queda opcional y solo se usa si existe.
        self.factura_si = kwargs.pop('factura_si', False)
        # Solo el alta de matrícula permite documentos con una cantidad de
        # dígitos distinta de 10/13. Los demás usos mantienen la regla normal.
        self.documento_flexible = kwargs.pop('documento_flexible', False)
        super().__init__(*args, **kwargs)
        if self.documento_flexible:
            cedula_attrs = self.fields['cedula'].widget.attrs
            cedula_attrs.pop('pattern', None)
            cedula_attrs['maxlength'] = '20'
            cedula_attrs['placeholder'] = 'Cédula o RUC'
            cedula_attrs['title'] = (
                'Ingresa el número sin letras. Solo se identificará como RUC '
                'si tiene exactamente 13 dígitos y termina en 001.'
            )
        else:
            self.fields['cedula'].widget.attrs['maxlength'] = '13'
        # El modelo conserva hasta 20 caracteres por compatibilidad, pero el
        # formulario de matrícula trabaja con celulares nacionales de 10 dígitos.
        self.fields['celular'].widget.attrs['maxlength'] = '10'

    def clean(self):
        cleaned = super().clean()
        if self.factura_si:
            faltantes = []
            for campo, etiqueta in (
                ('celular', 'Celular'),
                ('ciudad', 'Ciudad'),
            ):
                if not (cleaned.get(campo) or '').strip():
                    self.add_error(campo, 'Obligatorio cuando la factura lleva datos.')
                    faltantes.append(etiqueta)
        return cleaned

    def clean_cedula(self):
        cedula = _normalizar_digitos_formateados(
            self.cleaned_data.get('cedula')
        )
        if cedula and (not cedula.isascii() or not cedula.isdigit()):
            raise forms.ValidationError(
                'La cédula o RUC debe contener únicamente números.'
            )
        if self.documento_flexible:
            return cedula
        if len(cedula) < 10:
            raise forms.ValidationError(
                'La cédula debe tener 10 dígitos.'
            )
        if len(cedula) == 10:
            return cedula
        if len(cedula) < 13:
            raise forms.ValidationError(
                'El RUC debe tener 13 dígitos y terminar en 001.'
            )
        if len(cedula) == 13 and not cedula.endswith('001'):
            raise forms.ValidationError(
                'El RUC debe terminar en 001.'
            )
        if len(cedula) > 13:
            raise forms.ValidationError(
                'El RUC debe tener 13 dígitos y terminar en 001.'
            )
        return cedula

    class Meta:
        model = Estudiante
        fields = [
            'cedula', 'nombres', 'edad',
            'correo', 'celular', 'nivel_formacion',
            'titulo_profesional', 'ciudad',
        ]
        widgets = {
            'cedula': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': '0102030405',
                'id': 'id_est-cedula',
                'autocomplete': 'off',
                'inputmode': 'numeric',
                'pattern': '(?:[0-9]{10}|[0-9]{10}001)',
                'maxlength': '13',
                'title': 'Ingresa una cédula de 10 dígitos o un RUC de 13 dígitos terminado en 001.',
                'data-digits-only': 'true',
            }),
            'nombres': forms.TextInput(attrs={'class': 'form-input'}),
            'edad': forms.TextInput(attrs={
                'class': 'form-input',
                'inputmode': 'numeric',
                'pattern': '[0-9]*',
                'maxlength': '3',
                'data-digits-only': 'true',
            }),
            'correo': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'correo@ejemplo.com'}),
            'celular': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': '0991234567',
                'id': 'id_est-celular',
                'autocomplete': 'off',
                'inputmode': 'numeric',
                'pattern': '[0-9]*',
                'maxlength': '10',
                'data-digits-only': 'true',
                'data-phone-ecuador': 'true',
            }),
            'nivel_formacion': forms.Select(attrs={'class': 'form-input'}),
            'titulo_profesional': forms.TextInput(attrs={'class': 'form-input'}),
            'ciudad': forms.TextInput(attrs={'class': 'form-input'}),
        }

    def clean_celular(self):
        """
        Validación: si el celular ya pertenece a OTRO estudiante con cédula
        diferente, devolvemos un error claro indicando a quién pertenece,
        para evitar duplicados accidentales por confusión de números.

        El usuario puede marcar el checkbox "permitir_celular_duplicado"
        para confirmar que es intencional (familia, hijos, etc.) y saltarse
        esta validación.
        """
        celular = _normalizar_celular_ecuador(
            self.cleaned_data.get('celular')
        )
        if not celular:
            return celular  # opcional, se permite vacío

        if not celular.isascii() or not celular.isdigit():
            raise forms.ValidationError(
                'El celular debe contener únicamente números.'
            )
        if len(celular) < 10:
            raise forms.ValidationError("Por favor ingrese los diez dígitos completos.")
        elif len(celular) > 10:
            raise forms.ValidationError("Hay más de 10 dígitos, por favor verifique.")


        # Si el usuario marcó el checkbox de "número compartido", se permite
        # el duplicado sin más preguntas. Leemos del POST crudo porque el
        # orden de procesamiento de los campos puede variar.
        permitir = self.data.get(self.add_prefix('permitir_celular_duplicado'))
        if permitir in ('on', 'true', 'True', '1', True):
            return celular

        cedula = (self.cleaned_data.get('cedula') or '').strip()
        qs = Estudiante.objects.filter(celular=celular)
        if cedula:
            # Si estamos editando o el mismo estudiante (misma cédula), no duplica
            qs = qs.exclude(cedula=cedula)
        # También excluir la propia instancia si existe
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        otro = qs.first()
        if otro:
            raise forms.ValidationError(
                f'⚠ Este número ya está registrado a {otro.nombre_completo} '
                f'(cédula {otro.cedula}). Si es un número compartido (familia, '
                f'hijos, etc.) marca la casilla "Confirmo: número compartido" '
                f'que aparece junto al campo y vuelve a guardar.'
            )
        return celular


# Reserva / Abono: al matricular se cobra solo la reserva, desde $0.01 hasta
# $10.00. Lo que el estudiante pague de más se registra después en Gestionar
# Pagos, para que quede en el módulo que corresponde.
ERROR_TOPE_RESERVA = (
    f'En Reserva / Abono el valor pagado es de máximo ${MONTO_RESERVA_MATRICULA}. '
    'Si paga el curso completo, elige «Programa Completo»; si paga más que la '
    'reserva, registra el resto en Gestionar Pagos.'
)
ERROR_TOPE_RESERVA_EDICION = (
    f'En Reserva / Abono el pago inicial es de máximo ${MONTO_RESERVA_MATRICULA}. '
    'Si el estudiante pagó más, registra el resto en Gestionar Pagos.'
)


def textos_tope_pago_modulo(matricula, tope):
    """(aviso, error) del tope de un pago «Solo Módulo» de la matrícula.

    Cuando el tope sube a $25 por ser una matrícula de $110 (p. ej. en un
    curso que bajó a $90) se dice el motivo.
    """
    tope = f'${tope:.2f}'
    if matricula.usa_tope_modulo_de_25:
        valor = f'${matricula.valor_curso_lista:.2f}'
        if matricula.es_inscripcion_gratis:
            # Se guarda $10 menos ($100), pero el curso es de $110.
            aviso = f'Máximo por módulo: {tope} (curso de {valor} con inscripción gratis).'
            error = f'Esta matrícula es de un curso de {valor} con inscripción gratis: cada módulo se paga hasta {tope}.'
        elif matricula.tiene_valor_anterior_del_curso:
            aviso = f'Máximo por módulo: {tope} (matrícula con el valor anterior del curso, {valor}).'
            error = f'Esta matrícula tiene el valor anterior del curso ({valor}): cada módulo se paga hasta {tope}.'
        else:
            aviso = f'Máximo por módulo: {tope} (matrícula de {valor}).'
            error = f'Esta matrícula es de {valor}: cada módulo se paga hasta {tope}.'
    else:
        modalidad = matricula.get_modalidad_display()
        aviso = f'Máximo por módulo en {modalidad}: {tope}.'
        error = f'En {modalidad} cada módulo se paga hasta {tope}.'
    return aviso, error + ' Si paga más de un módulo, registra cada módulo por separado.'


class MatriculaForm(forms.ModelForm):
    """
    Formulario unificado de matrícula + comprobante.

    Cambios:
    - Acepta TODOS los cursos activos (no filtra por modalidad de URL).
      La modalidad final se infiere de la jornada elegida.
    - Acepta TODAS las jornadas activas del curso (presenciales + online).
    - Incluye `tipo_matricula` (Reserva/Abono, Inscripción gratis, Programa
      Completo y Otros).
    - Incluye los datos de Comprobante: tipo_registro y link al comprobante.
      La vendedora se asigna automáticamente desde request.user en la vista
      (no es un campo del form).
    - La factura NO se registra aquí: la matrícula queda con factura «No» y
      se factura después en Matrícula › Facturas › Registrar factura.
    """

    metodo_pago = forms.ChoiceField(
        choices=[], required=False,
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_metodo_pago'})
    )
    banco = forms.CharField(
        required=False,
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_banco'})
    )
    
    # --- PAGO MIXTO ---
    tipo_cobro = forms.ChoiceField(
        choices=[('un_solo_metodo', 'Un solo método'), ('mixto', 'Pago Mixto')],
        required=False, initial='un_solo_metodo',
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_tipo_cobro'})
    )
    monto_pago_1 = forms.DecimalField(
        required=False, min_value=0, decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-input', 'step': '0.01', 'id': 'id_monto_pago_1',
            'inputmode': 'decimal', 'data-decimal-only': 'true',
        })
    )
    metodo_pago_1 = forms.ChoiceField(
        choices=[], required=False,
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_metodo_pago_1'})
    )
    banco_1 = forms.CharField(
        required=False,
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_banco_1'})
    )
    monto_pago_2 = forms.DecimalField(
        required=False, min_value=0, decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-input', 'step': '0.01', 'id': 'id_monto_pago_2',
            'inputmode': 'decimal', 'data-decimal-only': 'true',
        })
    )
    metodo_pago_2 = forms.ChoiceField(
        choices=[], required=False,
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_metodo_pago_2'})
    )
    banco_2 = forms.CharField(
        required=False,
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_banco_2'})
    )

    # Campo heredado para poder editar matrículas antiguas registradas como
    # "Reserva + Módulo". Las matrículas nuevas ya no ofrecen ese flujo.
    modulos_a_pagar = forms.IntegerField(
        required=False, min_value=1,
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_modulos_a_pagar'})
    )



    class Meta:
        model = Matricula
        fields = [
            # Datos académicos
            'curso', 'jornada',
            'estado', 'tipo_matricula',
            'forma_pago',
            'fecha_matricula', 'talla_camiseta',
            'valor_curso', 'descuento', 'valor_pagado', 'observaciones',
            # Datos de comprobante
            'tipo_registro',
            'link_comprobante',
        ]
        widgets = {
            'curso': forms.Select(attrs={'class': 'form-input', 'id': 'id_curso'}),
            'jornada': forms.RadioSelect(attrs={'class': 'jornada-radio'}),
            'estado': forms.Select(attrs={
                'class': 'form-input', 'id': 'id_estado',
            }),
            'tipo_matricula': forms.Select(attrs={
                'class': 'form-input', 'id': 'id_tipo_matricula',
            }),
            'forma_pago': forms.Select(attrs={
                'class': 'form-input', 'id': 'id_forma_pago',
            }),
            'fecha_matricula': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}, format='%Y-%m-%d'),
            'talla_camiseta': forms.RadioSelect(attrs={'class': 'talla-radio'}),
            'valor_curso': forms.NumberInput(attrs={
                'class': 'form-input', 'step': '0.01', 'id': 'id_valor_curso',
                'inputmode': 'decimal', 'data-decimal-only': 'true',
            }),
            'descuento': forms.NumberInput(attrs={
                'class': 'form-input', 'step': '0.01', 'min': '0',
                'id': 'id_descuento', 'placeholder': '0.00',
                'inputmode': 'decimal', 'data-decimal-only': 'true',
            }),
            'valor_pagado': forms.NumberInput(attrs={
                'class': 'form-input', 'step': '0.01', 'min': '0.01',
                'id': 'id_valor_pagado',
                'inputmode': 'decimal', 'data-decimal-only': 'true',
            }),
            'observaciones': forms.Textarea(attrs={'class': 'form-input', 'rows': 3}),
            # Comprobante
            'tipo_registro': forms.Select(attrs={'class': 'form-input'}),
            'link_comprobante': forms.URLInput(attrs={
                'class': 'form-input',
                'placeholder': 'https://… (Drive / Imgur / WhatsApp Web)',
            }),
        }

    def __init__(self, *args, modalidad='presencial', captura_pago=True, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in ('banco', 'banco_1', 'banco_2'):
            self.fields[campo].widget.choices = _opciones_banco(
                self.initial.get(campo)
            )

        for campo in ('metodo_pago', 'metodo_pago_1', 'metodo_pago_2'):
            self.fields[campo].choices = [('', 'Seleccione')] + list(METODOS_PAGO)
        # "Reserva + Módulo 1" se retiró del registro nuevo. Se conserva solo
        # al editar una matrícula antigua para no volver inválido su historial.
        if 'tipo_matricula' in self.fields:
            from .models import TIPO_MATRICULA
            conservar_reserva_modulo = bool(
                self.instance
                and self.instance.pk
                and self.instance.tipo_matricula == 'reserva_modulo_1'
            )
            tipo_choices = [
                choice for choice in TIPO_MATRICULA
                if choice[0] != 'reserva_modulo_1' or conservar_reserva_modulo
            ]
            self.fields['tipo_matricula'].choices = [('', '---------')] + tipo_choices
            self.fields['tipo_matricula'].initial = ''

        self.modalidad = modalidad
        # captura_pago=True (registro): el "Valor pagado" se cobra ahora y se
        # convierte en el primer Abono. captura_pago=False (edición): el valor
        # pagado ya lo controlan los Abonos existentes, no se toca aquí.
        self.captura_pago = captura_pago

        if captura_pago:
            self.initial['valor_pagado'] = ''
            self.fields['valor_pagado'].initial = ''
            self.fields['valor_pagado'].required = True
            self.fields['valor_pagado'].label = 'Valor pagado (USD)'
            self.fields['valor_pagado'].help_text = (
                'Debe ser un valor mayor a $0.00 para poder matricular. '
                'En Reserva / Abono es de $0.01 hasta $10.00 como máximo; el '
                'saldo se cobra después según los módulos del curso.'
            )
        else:
            self.fields['valor_pagado'].required = False
            # En edición el monto pagado se gestiona en la sección de Abonos.
            self.fields['valor_pagado'].widget.attrs['readonly'] = True
            self.fields['valor_pagado'].help_text = (
                'Los pagos se gestionan en la sección de Abonos.'
            )

        # Cursos: TODOS los activos que ofrezcan al menos una modalidad.
        self.fields['curso'].queryset = Curso.objects.filter(
            activo=True,
        ).filter(Q(ofrece_presencial=True) | Q(ofrece_online=True))
        self.fields['curso'].empty_label = '— Selecciona un curso —'
        self.fields['curso'].label_from_instance = lambda obj: f"{obj.nombre} (Ciclo Corto)" if obj.es_ciclo_corto else obj.nombre

        # Jornadas: Si no hay curso seleccionado, no mostramos ninguna inicialmente.
        # El frontend (AJAX) las cargará al elegir un curso.
        if self.instance and self.instance.pk and self.instance.curso_id:
            # Al editar se conserva la jornada actual aunque ya esté inactiva:
            # desactivar una jornada no debe impedir corregir el pago inicial.
            self.fields['jornada'].queryset = JornadaCurso.objects.filter(
                Q(activo=True) | Q(pk=self.instance.jornada_id),
                curso_id=self.instance.curso_id,
            )
        elif self.data and self.data.get('mat-curso'):
            # Si el form fue enviado (is_bound) y tiene curso, cargamos sus jornadas
            self.fields['jornada'].queryset = JornadaCurso.objects.filter(
                curso_id=self.data.get('mat-curso'),
                activo=True,
            )
        else:
            self.fields['jornada'].queryset = JornadaCurso.objects.none()

        # Tipo de registro: empty_label
        self.fields['tipo_registro'].empty_label = '— Selecciona origen —'

        # Required flags
        self.fields['jornada'].required = captura_pago
        self.fields['talla_camiseta'].required = False
        self.fields['tipo_matricula'].required = captura_pago
        self.fields['forma_pago'].required = captura_pago
        self.fields['tipo_registro'].required = True

        # «Otros» no tiene costo e «Inscripción (gratis)» no cobra los $10 de
        # inscripción: ninguno cobra al matricular, así que la forma de pago y
        # el pago inicial dejan de ser obligatorios (clean los fija en $0).
        tipo_enviado = self.data.get(self.add_prefix('tipo_matricula'))
        self.es_sin_costo = tipo_enviado == 'otros'
        self.sin_cobro_inicial = tipo_enviado in TIPOS_SIN_COBRO_INICIAL
        if self.sin_cobro_inicial:
            self.fields['forma_pago'].required = False
            self.fields['valor_pagado'].required = False
        if self.es_sin_costo:
            self.fields['valor_curso'].required = False

        # Forma de pago: obligar elección manual (opción vacía al inicio).
        self.fields['forma_pago'].initial = ''
        self.fields['forma_pago'].label = 'Forma de pago'
        if hasattr(self.fields['forma_pago'], 'choices'):
            conservar_abono_modulo = bool(
                self.instance
                and self.instance.pk
                and self.instance.forma_pago == 'abono_modulo'
            )
            fp_choices = [
                c for c in self.fields['forma_pago'].choices
                if c[0] not in ('', None)
                and (c[0] != 'abono_modulo' or conservar_abono_modulo)
            ]
            self.fields['forma_pago'].choices = (
                [('', '---------')] + fp_choices
            )

        # Tipo de matrícula: forzar que el usuario elija manualmente.
        self.fields['tipo_matricula'].initial = ''
        if hasattr(self.fields['tipo_matricula'], 'choices'):
            choices = list(self.fields['tipo_matricula'].choices)
            if not choices or choices[0][0] != '':
                self.fields['tipo_matricula'].choices = (
                    [('', '— Selecciona el tipo de matrícula —')] + choices
                )
        if not (self.instance and self.instance.pk):
            if 'tipo_matricula' in self.initial:
                self.initial['tipo_matricula'] = ''
            self.fields['tipo_matricula'].widget.attrs.pop('value', None)

        # Descuento es opcional (default 0)
        self.fields['descuento'].required = False
        self.fields['descuento'].label = 'Descuento (USD)'
        self.fields['descuento'].help_text = (
            'Descuento opcional sobre el valor del curso. Se resta automáticamente '
            'del valor a pagar. Déjalo en 0 si no aplica.'
        )

        self.fields['link_comprobante'].required = False
        preparar_campo_fecha(
            self.fields['fecha_matricula'],
            self.instance.fecha_matricula if self.instance.pk else None,
        )

    def clean_fecha_matricula(self):
        fecha = self.cleaned_data.get('fecha_matricula')
        # Al editar sin cambiar la fecha no se revisa: una matrícula antigua
        # con una fecha rara no debe impedir corregir el pago u otros datos.
        if self.instance.pk and fecha == self.instance.fecha_matricula:
            return fecha
        return validar_fecha_matricula(fecha)

    def clean_valor_pagado(self):
        valor = self.cleaned_data.get('valor_pagado')
        if self.captura_pago and not self.sin_cobro_inicial:
            if valor is None or valor <= 0:
                raise forms.ValidationError("Para registrar una matrícula es obligatorio realizar un pago inicial mayor a $0.")
        return valor

    def clean_descuento(self):
        """El descuento no puede ser negativo ni mayor al valor del curso."""
        from decimal import Decimal
        if self.es_sin_costo:
            return Decimal('0.00')
        desc = self.cleaned_data.get('descuento') or Decimal('0.00')
        if desc < 0:
            raise forms.ValidationError('El descuento no puede ser negativo.')
        valor = self.cleaned_data.get('valor_curso')
        if valor is not None and desc > valor:
            raise forms.ValidationError(
                f'El descuento (${desc}) no puede ser mayor al valor del curso (${valor}).'
            )
        return desc

    def clean(self):
        from decimal import Decimal
        cleaned = super().clean()

        if self.captura_pago:
            jornada = cleaned.get('jornada')
            if not jornada:
                self.add_error('jornada', 'Debes seleccionar una jornada con sede o plataforma.')
            elif jornada.modalidad == 'presencial' and not jornada.sede_id:
                self.add_error('jornada', 'La jornada presencial seleccionada debe tener sede.')

        # ── Coherencia entre forma de pago y el monto pagado ──────────────
        # Solo aplica al registrar (captura_pago=True). En edición el valor
        # pagado lo determinan los Abonos ya existentes.
        if self.captura_pago and self.sin_cobro_inicial:
            # No se cobra nada al matricular: no se valida ningún pago y la
            # matrícula queda sin abono inicial.
            if self.es_sin_costo:
                # Otros: sin valor ni saldo.
                cleaned.update(
                    valor_curso=Decimal('0.00'), descuento=Decimal('0.00'),
                )
            elif not self.instance.pk and cleaned.get('valor_curso') is not None:
                # Inscripción gratis: los $10 de inscripción se restan del
                # valor del curso (solo al registrar, para no restarlos dos
                # veces) y el resto se paga por módulos.
                valor_curso = cleaned['valor_curso']
                desc = cleaned.get('descuento') or Decimal('0.00')
                if valor_curso - desc <= MONTO_RESERVA_MATRICULA:
                    self.add_error(
                        'valor_curso',
                        'Con la inscripción gratis de $10.00 no queda valor '
                        'por pagar en módulos. Si no se cobra nada, usa «Otros».'
                    )
                else:
                    cleaned['valor_curso'] = valor_curso - MONTO_RESERVA_MATRICULA
            cleaned.update(
                forma_pago='',
                valor_pagado=Decimal('0.00'),
                tipo_cobro='un_solo_metodo',
            )
        elif self.captura_pago:
            forma = cleaned.get('forma_pago')
            valor_curso = cleaned.get('valor_curso') or Decimal('0.00')
            desc = cleaned.get('descuento') or Decimal('0.00')
            neto = valor_curso - desc
            if neto < 0:
                neto = Decimal('0.00')

            curso = cleaned.get('curso')
            jornada = cleaned.get('jornada')
            tipo_cobro = cleaned.get('tipo_cobro') or 'un_solo_metodo'
            metodo_pago = cleaned.get('metodo_pago')
            monto_pago_1 = cleaned.get('monto_pago_1') or Decimal('0.00')
            metodo_pago_1 = cleaned.get('metodo_pago_1')
            monto_pago_2 = cleaned.get('monto_pago_2') or Decimal('0.00')
            metodo_pago_2 = cleaned.get('metodo_pago_2')
            modalidad = jornada.modalidad if jornada else self.modalidad

            if tipo_cobro != 'mixto':
                if not metodo_pago:
                    self.add_error('metodo_pago', 'Selecciona el método de pago.')
                _revisar_banco(self, cleaned, 'metodo_pago', 'banco')
            else:
                if monto_pago_1 <= 0:
                    self.add_error('monto_pago_1', 'El Monto 1 debe ser mayor a cero.')
                if monto_pago_2 <= 0:
                    self.add_error('monto_pago_2', 'El Monto 2 debe ser mayor a cero.')
                if not metodo_pago_1:
                    self.add_error('metodo_pago_1', 'Selecciona el método del Monto 1.')
                if not metodo_pago_2:
                    self.add_error('metodo_pago_2', 'Selecciona el método del Monto 2.')
                _revisar_banco(
                    self, cleaned, 'metodo_pago_1', 'banco_1',
                    'Selecciona el banco o app del Monto 1.',
                )
                _revisar_banco(
                    self, cleaned, 'metodo_pago_2', 'banco_2',
                    'Selecciona el banco o app del Monto 2.',
                )

            vp = cleaned.get('valor_pagado')
            tipo_matricula = cleaned.get('tipo_matricula')
            es_reserva_nueva = bool(
                not self.instance.pk
                and tipo_matricula == 'reserva_abono'
            )

            if vp is None:
                if forma == 'pago_completo':
                    vp = neto
                elif forma == 'modulo':
                    n = curso.get_numero_modulos(modalidad) if curso else 1
                    n = n or 1
                    vp = (neto / Decimal(n)).quantize(Decimal('0.01'))
                else:
                    vp = Decimal('0.00')

            if es_reserva_nueva:
                if forma != 'abono':
                    self.add_error(
                        'forma_pago',
                        'La matrícula con reserva utiliza la forma de pago Abono.'
                    )
                if neto < MONTO_RESERVA_MATRICULA:
                    self.add_error(
                        'valor_curso',
                        'El valor a pagar no puede ser menor a la reserva fija de $10.00.'
                    )
            # La reserva va de $0.01 (lo exige clean_valor_pagado) a $10.00.
            excede_reserva = es_reserva_nueva and vp > MONTO_RESERVA_MATRICULA
            if excede_reserva:
                self.add_error('valor_pagado', ERROR_TOPE_RESERVA)

            if vp < 0:
                vp = Decimal('0.00')
            if vp > neto and not excede_reserva:
                self.add_error(
                    'valor_pagado',
                    f'El valor pagado (${vp}) no puede ser mayor al valor a pagar '
                    f'con descuento (${neto}).'
                )
            cleaned['valor_pagado'] = vp

            if tipo_cobro == 'mixto':
                suma_mixta = (monto_pago_1 + monto_pago_2).quantize(Decimal('0.01'))
                vp_principal = vp.quantize(Decimal('0.01')) if vp is not None else None
                if vp_principal is not None and suma_mixta != vp_principal:
                    self.add_error(
                        'monto_pago_2',
                        'La suma del Monto 1 y Monto 2 debe ser exactamente igual al valor pagado.'
                    )
        return cleaned


class AbonoForm(forms.ModelForm):
    """Formulario para registrar/editar un pago (Abono / Pago Completo / Por Módulo / Recuperación)."""
    # Los <input type="date"> solo aceptan AAAA-MM-DD; con el formato local
    # (dd/mm/aaaa) el navegador descarta el valor y el campo se ve vacío.
    fecha_marcada = forms.DateField(
        required=False,
        label='Fecha de la falta',
        widget=forms.DateInput(attrs={
            'class': 'form-input',
            'type': 'date',
            'id': 'id_fecha_marcada',
        }, format='%Y-%m-%d'),
    )
    fecha_programada = forms.DateField(
        required=False,
        label='Fecha para recuperar',
        widget=forms.DateInput(attrs={
            'class': 'form-input',
            'type': 'date',
            'id': 'id_fecha_programada',
        }, format='%Y-%m-%d'),
    )
    tipo_cobro = forms.ChoiceField(
        choices=[('un_solo_metodo', 'Un solo método'), ('mixto', 'Pago Mixto')],
        required=False, initial='un_solo_metodo',
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_tipo_cobro_abono'})
    )
    monto_pago_1 = forms.DecimalField(
        required=False, min_value=0, decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01', 'id': 'id_monto_pago_1_abono'})
    )
    metodo_pago_1 = forms.ChoiceField(
        choices=[], required=False,
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_metodo_pago_1_abono'})
    )
    banco_1 = forms.CharField(
        required=False,
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_banco_1_abono'})
    )
    monto_pago_2 = forms.DecimalField(
        required=False, min_value=0, decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01', 'id': 'id_monto_pago_2_abono'})
    )
    metodo_pago_2 = forms.ChoiceField(
        choices=[], required=False,
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_metodo_pago_2_abono'})
    )
    banco_2 = forms.CharField(
        required=False,
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_banco_2_abono'})
    )

    class Meta:
        model = Abono
        fields = [
            'fecha', 'monto', 'tipo_pago', 'numero_modulo',
            'cuenta_para_saldo',
            'metodo', 'banco',
            'numero_recibo', 'observaciones',
        ]
        widgets = {
            'fecha': forms.DateInput(
                attrs={'class': 'form-input', 'type': 'date'},
                format='%Y-%m-%d',
            ),
            'monto': forms.NumberInput(attrs={
                'class': 'form-input', 'step': '0.01', 'min': '0.01',
                'placeholder': '0.00',
            }),
            'tipo_pago': forms.Select(attrs={
                'class': 'form-input', 'id': 'id_tipo_pago',
            }),
            'numero_modulo': forms.Select(attrs={
                'class': 'form-input', 'id': 'id_numero_modulo',
            }),
            'cuenta_para_saldo': forms.Select(
                attrs={'class': 'form-input', 'id': 'id_cuenta_para_saldo'},
                choices=[
                    ('True', 'Sí — Sumar al pago del curso'),
                    ('False', 'No — Cobrar aparte (no afecta el saldo)'),
                ],
            ),
            'metodo': forms.Select(attrs={'class': 'form-input', 'id': 'id_metodo'}),
            'banco': forms.Select(attrs={'class': 'form-input', 'id': 'id_banco'}),
            'numero_recibo': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Se genera automáticamente si lo dejas vacío',
            }),
            'observaciones': forms.Textarea(attrs={
                'class': 'form-input', 'rows': 2,
                'placeholder': 'Detalles del pago, referencia bancaria, etc.',
            }),
        }
        labels = {
            'tipo_pago': 'Tipo de pago',
            'numero_modulo': 'Módulo',
            'cuenta_para_saldo': '¿Suma al pago del curso?',
            'metodo': 'Método de pago',
            'numero_recibo': 'Nº de recibo',
            'banco': 'Banco',
        }

    def __init__(self, *args, matricula=None, **kwargs):
        super().__init__(*args, **kwargs)
        if 'metodo' in self.fields:
            metodo_choices = [('', 'Seleccione')] + list(METODOS_PAGO)
            self.fields['metodo'].choices = metodo_choices
            self.fields['metodo'].required = False
            self.fields['metodo_pago_1'].choices = metodo_choices
            self.fields['metodo_pago_2'].choices = metodo_choices
            if not self.is_bound and not (self.instance and self.instance.pk):
                self.initial.setdefault('metodo', '')

        if self.instance and self.instance.pk and self.instance.monto_2:
            self.initial['tipo_cobro'] = 'mixto'
            self.initial['monto_pago_1'] = self.instance.monto - self.instance.monto_2
            self.initial['metodo_pago_1'] = self.instance.metodo
            self.initial['banco_1'] = self.instance.banco
            self.initial['monto_pago_2'] = self.instance.monto_2
            self.initial['metodo_pago_2'] = self.instance.metodo_2
            self.initial['banco_2'] = self.instance.banco_2

        for campo in ('banco', 'banco_1', 'banco_2'):
            self.fields[campo].widget.choices = _opciones_banco(
                self.initial.get(campo)
            )

        if self.instance and self.instance.pk:
            recuperacion = self.instance.recuperaciones.order_by(
                '-actualizado', '-pk'
            ).first()
            if recuperacion:
                self.initial.setdefault(
                    'fecha_marcada', recuperacion.fecha_marcada
                )
                self.initial.setdefault(
                    'fecha_programada', recuperacion.fecha_programada
                )

        self.matricula = matricula
        self.es_pago_unico_online = bool(
            matricula and matricula.tiene_pago_unico_online
        )
        # Tope de cada pago «Solo Módulo»: $20 presencial y $25 online, y $25
        # en las matrículas con valor del curso de $110.
        # No aplica al «Un solo pago» del ciclo corto online (no es por
        # módulo). Un pago «Solo Módulo» antiguo mayor al tope se puede volver
        # a guardar mientras no se cambie su monto.
        self.tope_pago_modulo = None
        self.monto_modulo_original = None
        if matricula and not self.es_pago_unico_online:
            self.tope_pago_modulo = matricula.tope_pago_modulo
        if self.instance and self.instance.pk and self.instance.tipo_pago == 'solo_modulo':
            self.monto_modulo_original = self.instance.monto
        if self.tope_pago_modulo is not None:
            aviso, error = textos_tope_pago_modulo(matricula, self.tope_pago_modulo)
            self.error_tope_pago_modulo = error
            attrs = self.fields['monto'].widget.attrs
            attrs['data-tope-modulo'] = f'{self.tope_pago_modulo:.2f}'
            attrs['data-modalidad-label'] = matricula.get_modalidad_display()
            attrs['data-tope-aviso'] = aviso
            attrs['data-tope-error'] = error
            if self.monto_modulo_original is not None:
                attrs['data-monto-modulo-original'] = f'{self.monto_modulo_original:.2f}'
        self.fields['numero_recibo'].required = False
        self.fields['banco'].required = False
        self.fields['banco'].empty_label = '— Selecciona un banco —'
        self.fields['numero_modulo'].required = False
        self.modulos_con_pago_registrado = []
        self.modulos_con_recuperacion_pendiente = []

        if matricula:
            pagos_modulo_qs = matricula.abonos.filter(
                tipo_pago__in=('por_modulo', 'solo_modulo', 'recuperacion'),
                numero_modulo__isnull=False,
            )
            if self.instance and self.instance.pk:
                pagos_modulo_qs = pagos_modulo_qs.exclude(pk=self.instance.pk)
            self.modulos_con_pago_registrado = sorted(
                set(pagos_modulo_qs.values_list('numero_modulo', flat=True))
            )
            self.modulos_con_recuperacion_pendiente = sorted(
                set(
                    matricula.recuperaciones_pendientes.filter(
                        pagada=False,
                        numero_modulo__isnull=False,
                    ).values_list('numero_modulo', flat=True)
                )
            )

        # "Abono + Módulo" se retiró del registro de pagos nuevos. Se conserva
        # solo al editar recibos antiguos de ese tipo para no romper historial.
        conservar_abono_modulo = bool(
            self.instance
            and self.instance.pk
            and self.instance.tipo_pago == 'por_modulo'
        )
        self.fields['tipo_pago'].choices = [
            choice for choice in Abono.TIPOS_PAGO
            if choice[0] != 'por_modulo' or conservar_abono_modulo
        ]
        if self.es_pago_unico_online and not conservar_abono_modulo:
            self.fields['tipo_pago'].choices = [
                (valor, 'Un solo pago' if valor == 'solo_modulo' else label)
                for valor, label in self.fields['tipo_pago'].choices
            ]

        # Construir choices de módulos según el curso de la matrícula
        modulo_choices = [('', '— Selecciona módulo —')]
        if matricula and matricula.curso_id:
            n = matricula.curso.get_numero_modulos(matricula.modalidad)
            if matricula.curso.nombrar_modulos and matricula.curso.nombres_modulos:
                nombres = matricula.curso.nombres_modulos.get(matricula.modalidad, [])
            else:
                nombres = []
            for i in range(1, n + 1):
                nombre_per = nombres[i-1] if i - 1 < len(nombres) else None
                label = f'Módulo {i} - {nombre_per}' if nombre_per else f'Módulo {i}'
                if i in self.modulos_con_recuperacion_pendiente:
                    label = f'{label} - recuperación'
                modulo_choices.append((i, label))
        else:
            # Fallback genérico
            modulo_choices += [(i, f'Módulo {i}') for i in range(1, 6)]
        self.fields['numero_modulo'].widget.choices = modulo_choices
        self.fields['numero_modulo'].widget.attrs['data-pago-unico-online'] = (
            '1' if self.es_pago_unico_online else '0'
        )

    def clean_monto(self):
        monto = self.cleaned_data.get('monto')
        if monto is not None and monto <= 0:
            raise forms.ValidationError('El monto debe ser mayor a cero.')
        return monto

    def clean(self):
        cleaned = super().clean()
        monto = cleaned.get('monto')
        metodo = cleaned.get('metodo')
        tipo_cobro = cleaned.get('tipo_cobro') or 'un_solo_metodo'
        tipo_pago = cleaned.get('tipo_pago') or 'abono'
        numero_modulo = cleaned.get('numero_modulo')
        cuenta = cleaned.get('cuenta_para_saldo')
        fecha_marcada = cleaned.get('fecha_marcada')
        fecha_programada = cleaned.get('fecha_programada')
        # cuenta_para_saldo viene como string 'True'/'False' por el Select widget;
        # Django convierte 'True'/'False' al BooleanField, pero por seguridad:
        if isinstance(cuenta, str):
            cuenta = cuenta.lower() in ('true', '1', 'sí', 'si', 'yes')
            cleaned['cuenta_para_saldo'] = cuenta

        # Si NO es recuperación, siempre cuenta para saldo
        if tipo_pago != 'recuperacion':
            cleaned['cuenta_para_saldo'] = True
            cleaned['fecha_marcada'] = None
            cleaned['fecha_programada'] = None
        else:
            if not fecha_marcada:
                self.add_error(
                    'fecha_marcada',
                    'Debes indicar la fecha de la falta.',
                )
            if (
                fecha_marcada
                and fecha_programada
                and fecha_programada < fecha_marcada
            ):
                self.add_error(
                    'fecha_programada',
                    'La fecha para recuperar no puede ser anterior a la fecha de la falta.',
                )

        # Si tipo es por_modulo, solo_modulo o recuperacion, el módulo es obligatorio
        if tipo_pago in ('por_modulo', 'solo_modulo', 'recuperacion') and not numero_modulo:
            self.add_error('numero_modulo',
                           'Debes seleccionar un módulo para este tipo de pago.')

        if (
            tipo_pago in ('por_modulo', 'solo_modulo', 'recuperacion')
            and numero_modulo
            and numero_modulo in self.modulos_con_pago_registrado
        ):
            self.add_error(
                'numero_modulo',
                (
                    f'No se puede registrar este pago porque el Módulo '
                    f'{numero_modulo} ya se encuentra registrado en el '
                    f'historial de pagos.'
                ),
            )

        if (
            tipo_pago in ('por_modulo', 'solo_modulo')
            and numero_modulo
            and numero_modulo in self.modulos_con_recuperacion_pendiente
        ):
            self.add_error(
                'numero_modulo',
                (
                    f'El Módulo {numero_modulo} está marcado como '
                    f'recuperación. No se puede tomar como pago normal; '
                    f'cóbralo desde la recuperación correspondiente.'
                ),
            )

        # Validar que el número de módulo esté en rango [1..n_mod] del curso.
        # Solo aplica cuando el tipo de pago realmente usa el módulo. Para
        # tipos abono/pago_completo el módulo se ignora (se limpia abajo),
        # así que no tiene sentido bloquear el envío por un valor que no
        # va a guardarse. La UI ya previene módulos inválidos en el
        # <select>; esta validación protege contra envíos manipulados.
        if (tipo_pago in ('por_modulo', 'solo_modulo', 'recuperacion')
                and numero_modulo
                and self.matricula and self.matricula.curso_id):
            n_mod_curso = self.matricula.curso.get_numero_modulos(self.matricula.modalidad)
            if not (1 <= numero_modulo <= n_mod_curso):
                self.add_error(
                    'numero_modulo',
                    f'El módulo {numero_modulo} no existe. Este curso tiene '
                    f'{n_mod_curso} módulo(s); elige uno entre 1 y {n_mod_curso}.'
                )

        # En el ciclo corto online con pago único solo existe la obligación
        # económica N.º 1. El Módulo 2 continúa existiendo académicamente y
        # puede usarse en Recuperación, pero nunca como una segunda cuota.
        if (
            tipo_pago in ('por_modulo', 'solo_modulo')
            and numero_modulo
            and self.es_pago_unico_online
            and numero_modulo != 1
        ):
            self.add_error(
                'numero_modulo',
                'Este ciclo corto online tiene un solo pago. El Módulo 2 '
                'es académico y no tiene una cuota independiente.',
            )

        tope = self.tope_pago_modulo
        if (
            tipo_pago == 'solo_modulo'
            and tope is not None
            and monto is not None
            and monto > tope
            and monto != self.monto_modulo_original
        ):
            self.add_error('monto', self.error_tope_pago_modulo)

        # Si tipo es abono o pago_completo, el módulo se limpia
        if tipo_pago in ('abono', 'pago_completo'):
            cleaned['numero_modulo'] = None

        if tipo_cobro != 'mixto':
            if not metodo:
                self.add_error('metodo', 'Selecciona el método de pago.')
            _revisar_banco(self, cleaned, 'metodo', 'banco')

        if tipo_cobro == 'mixto':
            monto_1 = cleaned.get('monto_pago_1') or Decimal('0.00')
            monto_2 = cleaned.get('monto_pago_2') or Decimal('0.00')
            metodo_1 = cleaned.get('metodo_pago_1')
            metodo_2 = cleaned.get('metodo_pago_2')

            if monto_1 <= 0:
                self.add_error('monto_pago_1', 'El Monto 1 debe ser mayor a cero.')
            if monto_2 <= 0:
                self.add_error('monto_pago_2', 'El Monto 2 debe ser mayor a cero.')
            suma_mixta = (monto_1 + monto_2).quantize(Decimal('0.01'))
            monto_principal = monto.quantize(Decimal('0.01')) if monto is not None else None
            if monto_principal is not None and suma_mixta != monto_principal:
                self.add_error(
                    'monto_pago_2',
                    'La suma del Monto 1 y Monto 2 debe ser exactamente igual al Monto (USD).'
                )
            if not metodo_1:
                self.add_error('metodo_pago_1', 'Selecciona el método del Monto 1.')
            if not metodo_2:
                self.add_error('metodo_pago_2', 'Selecciona el método del Monto 2.')
            _revisar_banco(
                self, cleaned, 'metodo_pago_1', 'banco_1',
                'Selecciona el banco o app del Monto 1.',
            )
            _revisar_banco(
                self, cleaned, 'metodo_pago_2', 'banco_2',
                'Selecciona el banco o app del Monto 2.',
            )

        # Validación de saldo: solo aplica si el pago cuenta para el saldo del curso.
        # Recuperaciones cobradas APARTE no se validan contra el saldo.
        if (self.matricula and monto and
                cleaned.get('cuenta_para_saldo', True)):
            valor_neto = self.matricula.valor_neto
            otros = self.matricula.abonos.filter(cuenta_para_saldo=True)
            if self.instance and self.instance.pk:
                otros = otros.exclude(pk=self.instance.pk)
            total_otros = sum((a.monto for a in otros), Decimal('0.00'))
            if total_otros + monto > valor_neto:
                disponible = valor_neto - total_otros
                raise forms.ValidationError(
                    f'El monto excede el saldo. Máximo permitido: ${disponible:.2f} '
                    f'(valor a pagar ${valor_neto:.2f} − ya pagado ${total_otros:.2f}). '
                    f'Si es una clase de recuperación que se cobra aparte, '
                    f'cambia "¿Suma al pago del curso?" a "No".'
                )
        return cleaned


# ─────────────────────────────────────────────────────────
# Comprobante de Venta
# ─────────────────────────────────────────────────────────

class ComprobanteForm(forms.ModelForm):
    """
    Formulario de Comprobante de Venta.
    TODOS los campos son obligatorios (según requerimiento).
    El campo `vendedora` NO se incluye: se asigna automáticamente
    desde request.user en la vista.
    """

    class Meta:
        model = Comprobante
        fields = [
            'curso', 'modalidad', 'fecha_inscripcion',
            'nombre_persona', 'celular',
            'tipo_registro',
            'pago_abono', 'diferencia',
            'link_comprobante',
            'jornada', 'inicio_curso',
            'factura_realizada',
            'fact_nombres',
            'fact_cedula', 'fact_correo',
        ]
        widgets = {
            'curso': forms.Select(attrs={
                'class': 'form-input', 'required': 'required',
            }),
            'modalidad': forms.Select(attrs={
                'class': 'form-input', 'required': 'required',
            }),
            'fecha_inscripcion': forms.DateInput(attrs={
                'class': 'form-input', 'type': 'date', 'required': 'required',
            }),
            'nombre_persona': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'Nombre completo del cliente',
                'required': 'required',
            }),
            'celular': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': '0991234567',
                'required': 'required',
            }),
            'tipo_registro': forms.Select(attrs={
                'class': 'form-input', 'required': 'required',
            }),
            'pago_abono': forms.NumberInput(attrs={
                'class': 'form-input', 'step': '0.01', 'min': '0',
                'placeholder': '0.00', 'required': 'required',
            }),
            'diferencia': forms.NumberInput(attrs={
                'class': 'form-input', 'step': '0.01', 'min': '0',
                'placeholder': '0.00', 'required': 'required',
            }),
            'link_comprobante': forms.URLInput(attrs={
                'class': 'form-input',
                'placeholder': 'https://… (opcional)',
            }),
            'jornada': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Ej.: Sábados 08:00–12:00',
                'required': 'required',
            }),
            'inicio_curso': forms.DateInput(attrs={
                'class': 'form-input', 'type': 'date', 'required': 'required',
            }),
            'factura_realizada': forms.Select(attrs={
                'class': 'form-input', 'required': 'required',
            }),
            'fact_nombres': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'Nombres del titular de factura',
                'required': 'required',
            }),
            'fact_cedula': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'Cédula / RUC',
                'required': 'required',
            }),
            'fact_correo': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'correo@ejemplo.com',
                'required': 'required',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'banco' in self.fields:
            banco_val = self.initial.get('banco')
            if self.instance and hasattr(self.instance, 'banco') and getattr(self.instance, 'banco'):
                banco_val = getattr(self.instance, 'banco')
            bancos_list = _opciones_banco(banco_val)
            self.fields['banco'].widget.choices = bancos_list

        self.fields['curso'].queryset = Curso.objects.filter(activo=True)
        self.fields['curso'].empty_label = '— Selecciona un curso —'
        self.fields['tipo_registro'].empty_label = '— Selecciona tipo —'

        OPCIONALES = {'link_comprobante'}
        for name, field in self.fields.items():
            field.required = name not in OPCIONALES

    def clean_celular(self):
        cel = (self.cleaned_data.get('celular') or '').strip()
        if not cel:
            raise forms.ValidationError('El celular es obligatorio.')
        return cel

    def clean_pago_abono(self):
        valor = self.cleaned_data.get('pago_abono')
        if valor is None or valor < 0:
            raise forms.ValidationError('El pago o abono debe ser un valor válido (≥ 0).')
        return valor

    def clean_diferencia(self):
        valor = self.cleaned_data.get('diferencia')
        if valor is None or valor < 0:
            raise forms.ValidationError('La diferencia debe ser un valor válido (≥ 0).')
        return valor


# ─────────────────────────────────────────────────────────
# Registro Administrativo: Egresos
# ─────────────────────────────────────────────────────────

class EgresoForm(forms.ModelForm):
    """Formulario para registrar/editar un egreso (gasto)."""

    class Meta:
        model = Egreso
        fields = ['fecha', 'categoria', 'concepto', 'monto', 'notas']
        widgets = {
            'fecha': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'categoria': forms.Select(attrs={'class': 'form-input'}),
            'concepto': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Ej.: Sueldo Mayo - Ana López',
            }),
            'monto': forms.NumberInput(attrs={
                'class': 'form-input', 'step': '0.01', 'min': '0.01',
                'placeholder': '0.00',
            }),
            'notas': forms.Textarea(attrs={
                'class': 'form-input', 'rows': 3,
                'placeholder': 'Nº de factura, beneficiario, referencia bancaria…',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['categoria'].queryset = CategoriaEgreso.objects.filter(activo=True)
        self.fields['categoria'].empty_label = '— Selecciona categoría —'

    def clean_monto(self):
        monto = self.cleaned_data.get('monto')
        if monto is not None and monto <= 0:
            raise forms.ValidationError('El monto debe ser mayor a cero.')
        return monto


class CategoriaEgresoForm(forms.ModelForm):
    class Meta:
        model = CategoriaEgreso
        fields = ['nombre', 'descripcion', 'color', 'icono', 'orden', 'activo']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-input'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-input', 'rows': 2}),
            'color': forms.Select(attrs={'class': 'form-input'}),
            'icono': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': '💼',
                'maxlength': '4',
            }),
            'orden': forms.NumberInput(attrs={'class': 'form-input'}),
        }


# ─────────────────────────────────────────────────────────
# Recuperación de clases
# ─────────────────────────────────────────────────────────

class RecuperacionPendienteForm(forms.ModelForm):
    """
    Formulario para marcar una clase a recuperación.
    Se usa en la edición de matrícula y en el listado de pagos.
    """
    class Meta:
        model = RecuperacionPendiente
        fields = [
            'numero_modulo', 'fecha_marcada', 'fecha_programada',
            'tipo_equipo', 'observaciones',
        ]
        widgets = {
            'numero_modulo': forms.Select(attrs={'class': 'form-input'}),
            # AAAA-MM-DD: el único formato que acepta <input type="date">.
            'fecha_marcada': forms.DateInput(attrs={
                'class': 'form-input', 'type': 'date',
            }, format='%Y-%m-%d'),
            'fecha_programada': forms.DateInput(attrs={
                'class': 'form-input', 'type': 'date',
            }, format='%Y-%m-%d'),
            'tipo_equipo': forms.RadioSelect(attrs={'class': 'tipo-equipo-radio'}),
            'observaciones': forms.Textarea(attrs={
                'class': 'form-input', 'rows': 2,
                'placeholder': 'Motivo de la falta u otra información relevante.',
            }),
        }
        labels = {
            'numero_modulo': 'Módulo de la clase a recuperar',
            'fecha_marcada': 'Fecha de la falta',
            'fecha_programada': 'Fecha para recuperar',
            'tipo_equipo': '¿Qué clase va a recuperar?',
        }

    def __init__(self, *args, matricula=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.matricula = matricula
        self.modulos_pendientes = []
        self.modulos_seleccionables = set()

        # Construir las opciones según el curso. Al crear una recuperación,
        # solo se muestran módulos que todavía no tienen un pago válido
        # asociado. En edición se conserva además el módulo del registro actual
        # para poder corregir su fecha u observaciones sin invalidarlo.
        choices = [('', '— Selecciona módulo —')]
        if matricula and matricula.curso_id:
            n = matricula.curso.get_numero_modulos(matricula.modalidad)
            modulos_con_pago = set(
                matricula.abonos.filter(
                    cuenta_para_saldo=True,
                    monto__gt=0,
                    numero_modulo__gte=1,
                    numero_modulo__lte=n,
                ).values_list('numero_modulo', flat=True)
            )
            self.modulos_pendientes = [
                i for i in range(1, n + 1)
                if i not in modulos_con_pago
            ]
            modulo_actual = (
                self.instance.numero_modulo
                if self.instance and self.instance.pk
                else None
            )
            modulos_mostrados = [
                i for i in range(1, n + 1)
                if i in self.modulos_pendientes or i == modulo_actual
            ]
            self.modulos_seleccionables = set(modulos_mostrados)

            if matricula.curso.nombrar_modulos and matricula.curso.nombres_modulos:
                nombres = matricula.curso.nombres_modulos.get(matricula.modalidad, [])
            else:
                nombres = []
            for i in modulos_mostrados:
                nombre_per = nombres[i-1] if i - 1 < len(nombres) else None
                label = f'Módulo {i} - {nombre_per}' if nombre_per else f'Módulo {i}'
                choices.append((i, label))
        else:
            self.modulos_pendientes = list(range(1, 6))
            self.modulos_seleccionables = set(self.modulos_pendientes)
            choices += [(i, f'Módulo {i}') for i in self.modulos_pendientes]
        self.fields['numero_modulo'].widget.choices = choices
        
        # El tipo_equipo no es obligatorio por defecto porque no todos los cursos lo usan.
        self.fields['tipo_equipo'].required = False
        
        # Filtramos las opciones según el curso. Se toman del modelo para que
        # el valor enviado siempre sea uno que RecuperacionPendiente acepta.
        equipo_choices = []
        if self.matricula and self.matricula.curso:
            nombre_curso = (self.matricula.curso.nombre or '').lower()
            if 'servicio t' in nombre_curso:
                equipo_choices = RecuperacionPendiente.TIPO_EQUIPO_SERVICIO_TECNICO
            elif 'blanca' in nombre_curso:
                equipo_choices = RecuperacionPendiente.TIPO_EQUIPO_LINEA_BLANCA
            if equipo_choices:
                equipo_choices = (
                    equipo_choices + RecuperacionPendiente.TIPO_EQUIPO_NO_ESPECIFICAR
                )
        self.fields['tipo_equipo'].choices = equipo_choices

    def clean(self):
        cleaned_data = super().clean()
        tipo_equipo = cleaned_data.get('tipo_equipo')
        numero_modulo = cleaned_data.get('numero_modulo')
        fecha_marcada = cleaned_data.get('fecha_marcada')
        fecha_programada = cleaned_data.get('fecha_programada')

        if (
            fecha_marcada
            and fecha_programada
            and fecha_programada < fecha_marcada
        ):
            self.add_error(
                'fecha_programada',
                'La fecha para recuperar no puede ser anterior a la fecha de la falta.',
            )

        if (
            self.matricula
            and numero_modulo
            and numero_modulo not in self.modulos_seleccionables
        ):
            self.add_error(
                'numero_modulo',
                'Ese módulo ya tiene un pago registrado. Selecciona únicamente '
                'uno de los módulos pendientes.',
            )
        
        if self.matricula and self.matricula.curso:
            nombre_curso = (self.matricula.curso.nombre or '').lower()
            if 'servicio t' in nombre_curso or 'blanca' in nombre_curso:
                if not tipo_equipo:
                    self.add_error('tipo_equipo', 'Debes seleccionar la clase a recuperar para este curso.')

        return cleaned_data
        self.fields['observaciones'].required = False


# ─────────────────────────────────────────────────────────
# Adicional: Certificados, Examen Supletorio, Camisas extra
# ─────────────────────────────────────────────────────────

class PersonaExternaForm(forms.ModelForm):
    """
    Formulario para registrar/editar a una persona EXTERNA a la academia
    (alguien que compra un certificado, examen supletorio o camisa
    sin estar matriculado).
    """
    class Meta:
        model = PersonaExterna
        fields = [
            'cedula', 'nombres',
            'correo', 'celular', 'ciudad', 'observaciones',
        ]
        widgets = {
            'cedula': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'Ej.: 0912345678',
                'autocomplete': 'off',
            }),
            'nombres': forms.TextInput(attrs={'class': 'form-input'}),
            'correo': forms.TextInput(attrs={'class': 'form-input'}),
            'celular': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': '0991234567',
            }),
            'ciudad': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'Ej.: Guayaquil',
            }),
            'observaciones': forms.Textarea(attrs={
                'class': 'form-input', 'rows': 2,
                'placeholder': 'Notas adicionales sobre esta persona (opcional).',
            }),
        }
        labels = {
            'cedula': 'Cédula *',
            
            'nombres': 'Nombres *',
            'correo': 'Correo (opcional)',
            'celular': 'Celular (opcional)',
            'ciudad': 'Ciudad (opcional)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo cédula y nombres son obligatorios
        self.fields['correo'].required = False
        self.fields['celular'].required = False
        self.fields['ciudad'].required = False
        self.fields['observaciones'].required = False

    def clean_cedula(self):
        cedula = (self.cleaned_data.get('cedula') or '').strip()
        if not cedula:
            return cedula

        # Validar que no sea un estudiante ya registrado
        if Estudiante.objects.filter(cedula=cedula).exists():
            raise forms.ValidationError(
                'Esta cédula ya pertenece a un ESTUDIANTE matriculado. '
                'Debes registrar el adicional en la opción "Estudiante Interno".'
            )
        if _buscar_estudiante_archivado(cedula):
            raise forms.ValidationError(
                'Esta cédula pertenece a un ESTUDIANTE archivado. '
                'Debes registrar el adicional en la opción "Estudiante Interno"; '
                'el sistema lo recuperará del archivo al guardar.'
            )

        # Si estamos creando, validar que no exista otra persona externa
        if not self.instance.pk and PersonaExterna.objects.filter(cedula=cedula).exists():
            raise forms.ValidationError('Ya existe una persona externa registrada con esta cédula.')

        return cedula


class _AdicionalBaseForm(forms.ModelForm):
    """
    Base común para los formularios de adicional (interno y externo).
    Maneja la lógica condicional de campos según el tipo_adicional.
    """
    tipo_cobro = forms.ChoiceField(
        choices=[('un_solo_metodo', 'Un solo método'), ('mixto', 'Pago Mixto')],
        required=False, initial='un_solo_metodo',
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_tipo_cobro_adicional'})
    )
    monto_pago_1 = forms.DecimalField(
        required=False, min_value=0, decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01', 'id': 'id_monto_pago_1_adicional'})
    )
    metodo_pago_1 = forms.ChoiceField(
        choices=[], required=False,
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_metodo_pago_1_adicional'})
    )
    banco_1 = forms.CharField(
        required=False,
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_banco_1_adicional'})
    )
    monto_pago_2 = forms.DecimalField(
        required=False, min_value=0, decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01', 'id': 'id_monto_pago_2_adicional'})
    )
    metodo_pago_2 = forms.ChoiceField(
        choices=[], required=False,
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_metodo_pago_2_adicional'})
    )
    banco_2 = forms.CharField(
        required=False,
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_banco_2_adicional'})
    )

    class Meta:
        model = Adicional
        fields = [
            'tipo_adicional',
            'curso', 'modalidad',
            'talla_camiseta',
            'numero_modulo',
            'fecha', 'valor', 'metodo_pago', 'banco',
            'numero_recibo',
            'factura_realizada',
            'fact_nombres', 'fact_cedula', 'fact_correo',
            'observaciones',
        ]
        widgets = {
            'tipo_adicional': forms.Select(attrs={
                'class': 'form-input', 'id': 'id_tipo_adicional',
            }),
            'curso': forms.Select(attrs={'class': 'form-input'}),
            'modalidad': forms.Select(attrs={'class': 'form-input'}),
            'talla_camiseta': forms.Select(attrs={'class': 'form-input'}),
            'numero_modulo': forms.NumberInput(attrs={
                'class': 'form-input', 'min': 1, 'max': 10,
                'placeholder': 'Ej.: 1',
            }),
            'fecha': forms.DateInput(attrs={
                'class': 'form-input', 'type': 'date',
            }),
            'valor': forms.NumberInput(attrs={
                'class': 'form-input', 'step': '0.01', 'min': '0',
                'placeholder': 'Ej.: 15.00',
            }),
            'metodo_pago': forms.Select(attrs={'class': 'form-input', 'id': 'id_metodo_pago'}),
            'banco': forms.Select(attrs={'class': 'form-input', 'id': 'id_banco'}),
            'numero_recibo': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Se genera automáticamente si lo dejas vacío',
            }),
            'factura_realizada': forms.Select(attrs={
                'class': 'form-input',
                'id': 'id_factura_realizada',
            }),
            'fact_nombres': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Nombres del titular de factura',
            }),
            'fact_cedula': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Cédula / RUC',
            }),
            'fact_correo': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'correo@ejemplo.com',
            }),
            'observaciones': forms.Textarea(attrs={
                'class': 'form-input', 'rows': 2,
            }),
        }
        labels = {
            'tipo_adicional': 'Tipo de adicional *',
            'curso': 'Curso (si aplica)',
            'modalidad': 'Modalidad del curso',
            'talla_camiseta': 'Talla de camiseta',
            'numero_modulo': 'Módulo del examen supletorio',
            'fecha': 'Fecha *',
            'valor': 'Valor (USD) *',
            'metodo_pago': 'Método de pago *',
            'banco': 'Banco',
            'numero_recibo': 'Nº de recibo',
            'factura_realizada': '¿Factura realizada? *',
            'fact_nombres': 'Nombres',
            
            'fact_cedula': 'Número de cédula / RUC',
            'fact_correo': 'Correo electrónico',
            'observaciones': 'Observaciones',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        metodos = list(METODOS_PAGO)
        self.fields['metodo_pago_1'].choices = [('', '— Método 1 —')] + metodos
        self.fields['metodo_pago_2'].choices = [('', '— Método 2 —')] + metodos

        for campo in ('banco', 'banco_1', 'banco_2'):
            self.fields[campo].widget.choices = _opciones_banco(
                self.initial.get(campo)
            )

        # Solo cursos activos en el desplegable
        self.fields['curso'].queryset = Curso.objects.filter(activo=True).order_by('nombre')
        self.fields['curso'].required = False
        self.fields['curso'].empty_label = '— Sin curso —'

        self.fields['modalidad'].required = False
        self.fields['metodo_pago'].required = False
        self.fields['modalidad'].choices = [
            ('', '— Sin modalidad —'),
            ('presencial', 'Presencial'),
            ('online', 'Online'),
        ]
        self.fields['talla_camiseta'].required = False
        self.fields['talla_camiseta'].choices = [
            ('', '— Sin talla —')
        ] + list(Adicional.TALLAS_CAMISETA)

        self.fields['numero_modulo'].required = False
        self.fields['banco'].required = False
        self.fields['banco'].empty_label = '— Selecciona un banco —'
        self.fields['numero_recibo'].required = False
        self.fields['factura_realizada'].required = True
        for fname in ('fact_nombres', 'fact_cedula', 'fact_correo'):
            self.fields[fname].required = False
        self.fields['observaciones'].required = False

    def clean(self):
        cleaned = super().clean()
        if not cleaned:
            return cleaned

        tipo = cleaned.get('tipo_adicional')
        curso = cleaned.get('curso')
        modalidad = cleaned.get('modalidad')
        talla = cleaned.get('talla_camiseta')
        factura = cleaned.get('factura_realizada')

        # Validaciones de montos y métodos para pago mixto
        valor = cleaned.get('valor') or Decimal('0.00')
        tipo_cobro = cleaned.get('tipo_cobro')

        if tipo_cobro == 'mixto':
            m1 = cleaned.get('monto_pago_1') or Decimal('0.00')
            m2 = cleaned.get('monto_pago_2') or Decimal('0.00')
            metodo1 = cleaned.get('metodo_pago_1')
            metodo2 = cleaned.get('metodo_pago_2')

            if m1 + m2 != valor:
                self.add_error(None, f'La suma de Monto 1 (${m1}) y Monto 2 (${m2}) debe ser igual al Valor Total (${valor}).')

            if not metodo1:
                self.add_error('metodo_pago_1', 'Requerido para pago mixto.')
            if not metodo2:
                self.add_error('metodo_pago_2', 'Requerido para pago mixto.')
            _revisar_banco(
                self, cleaned, 'metodo_pago_1', 'banco_1',
                'Selecciona el banco o app del Monto 1.',
            )
            _revisar_banco(
                self, cleaned, 'metodo_pago_2', 'banco_2',
                'Selecciona el banco o app del Monto 2.',
            )

            # Si es mixto, vaciar el principal
            cleaned['metodo_pago'] = ''
            cleaned['banco'] = ''

        else:
            # Un solo método
            if not cleaned.get('metodo_pago'):
                self.add_error('metodo_pago', 'Requerido para pago único.')
                
            cleaned['monto_pago_1'] = None
            cleaned['metodo_pago_1'] = ''
            cleaned['banco_1'] = ''
            cleaned['monto_pago_2'] = None
            cleaned['metodo_pago_2'] = ''
            cleaned['banco_2'] = ''
            
            # Validación de banco según método principal
            _revisar_banco(self, cleaned, 'metodo_pago', 'banco')

        # Validaciones según tipo
        if tipo in ('cert_matricula', 'cert_asistencia', 'cert_antiguo', 'examen_supletorio'):
            if not curso:
                self.add_error('curso', 'Selecciona el curso al que se refiere este adicional.')
            if not modalidad:
                self.add_error('modalidad', 'Indica si era presencial u online.')

        if tipo == 'camisa':
            if not talla:
                self.add_error('talla_camiseta', 'Selecciona la talla de la camisa.')

        if factura == 'si':
            faltantes = []
            for fname, label in (
                ('fact_nombres', 'Nombres'),
                
                ('fact_cedula', 'Cédula / RUC'),
                ('fact_correo', 'Correo'),
            ):
                if not cleaned.get(fname):
                    self.add_error(fname, 'Este dato es obligatorio cuando la factura está realizada.')
                    faltantes.append(label)
            if faltantes:
                self.add_error(
                    None,
                    'Si marcas "Factura realizada = Sí", debes llenar los datos de factura: '
                    + ', '.join(faltantes) + '.'
                )

        return cleaned


def _nivel_formacion_codigo(valor):
    valor = (valor or '').strip()
    if not valor:
        return ''
    for codigo, label in Estudiante.NIVELES_FORMACION:
        if valor == codigo or valor == label:
            return codigo
    return ''


def _edad_entera(valor):
    if valor in (None, ''):
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _buscar_estudiante_archivado(cedula):
    archivado = (
        EstudianteArchivado.objects
        .filter(cedula=cedula)
        .order_by('-archivado_en')
        .first()
    )
    if archivado:
        return archivado
    return (
        MatriculaArchivada.objects
        .filter(cedula=cedula)
        .order_by('-archivado_en')
        .first()
    )


def _crear_estudiante_desde_archivo(archivado):
    ciudad = getattr(archivado, 'ciudad', getattr(archivado, 'ciudad_estudiante', '')) or ''
    titulo = getattr(archivado, 'titulo_profesional', '') or ''
    return Estudiante.objects.create(
        cedula=archivado.cedula,
        
        nombres=archivado.nombres,
        edad=_edad_entera(getattr(archivado, 'edad', None)),
        correo=archivado.correo or '',
        celular=archivado.celular or '',
        nivel_formacion=_nivel_formacion_codigo(getattr(archivado, 'nivel_formacion', '')),
        titulo_profesional=titulo,
        ciudad=ciudad,
    )


class AdicionalInternoForm(_AdicionalBaseForm):
    """
    Formulario para crear un Adicional para un ESTUDIANTE INTERNO de la academia.
    Selecciona el estudiante por cédula (con autocompletar).
    """
    cedula_estudiante = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'Cédula del estudiante',
            'autocomplete': 'off',
            'id': 'id_cedula_estudiante',
        }),
        label='Cédula del estudiante *',
        help_text='Escribe la cédula y se autocompletarán los datos.',
    )

    def clean_cedula_estudiante(self):
        cedula = (self.cleaned_data.get('cedula_estudiante') or '').strip()
        if not cedula:
            raise forms.ValidationError('Debes ingresar la cédula del estudiante.')
        try:
            est = Estudiante.objects.get(cedula=cedula)
        except Estudiante.DoesNotExist:
            archivado = _buscar_estudiante_archivado(cedula)
            if not archivado:
                raise forms.ValidationError(
                    'No existe un estudiante con esa cédula. '
                    'Si la persona no está matriculada, registra el adicional como "Persona externa".'
                )
            self.estudiante_obj = None
            self.estudiante_archivado_obj = archivado
            return cedula
        self.estudiante_obj = est
        self.estudiante_archivado_obj = None
        return cedula

    def save(self, commit=True):
        instance = super().save(commit=False)
        estudiante = getattr(self, 'estudiante_obj', None)
        if estudiante is None:
            archivado = getattr(self, 'estudiante_archivado_obj', None)
            if archivado:
                estudiante = (
                    Estudiante.objects.filter(cedula=archivado.cedula).first()
                    or _crear_estudiante_desde_archivo(archivado)
                )
        instance.estudiante = estudiante
        instance.persona_externa = None
        if commit:
            instance.save()
        return instance


class AdicionalExternoForm(_AdicionalBaseForm):
    """
    Formulario para crear un Adicional para una PERSONA EXTERNA.
    Permite seleccionar una persona externa ya registrada (por cédula).
    Si no existe, hay que registrarla primero.
    """
    cedula_externa = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'Cédula de la persona externa',
            'autocomplete': 'off',
            'id': 'id_cedula_externa',
        }),
        label='Cédula de la persona externa *',
        help_text='La persona debe estar registrada previamente. Si no existe, regístrala primero.',
    )

    def clean_cedula_externa(self):
        cedula = (self.cleaned_data.get('cedula_externa') or '').strip()
        if not cedula:
            raise forms.ValidationError('Debes ingresar la cédula de la persona.')
        try:
            persona = PersonaExterna.objects.get(cedula=cedula)
        except PersonaExterna.DoesNotExist:
            raise forms.ValidationError(
                'No existe una persona externa con esa cédula. '
                'Regístrala primero en "+ Registrar Persona Externa".'
            )
        self.persona_obj = persona
        return cedula

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.persona_externa = getattr(self, 'persona_obj', None)
        instance.estudiante = None
        if commit:
            instance.save()
        return instance


class AdicionalSupletorioRapidoForm(forms.Form):
    """
    Formulario rápido para crear un Adicional tipo 'examen_supletorio'
    desde la vista de pagos de una matrícula. Solo pide módulo, fecha y valor.
    El estudiante, curso, modalidad y matricula_origen se infieren de la matrícula.
    """
    METODOS_PAGO = Adicional.METODOS_PAGO

    numero_modulo = forms.IntegerField(
        min_value=1, max_value=10,
        widget=forms.Select(attrs={'class': 'form-input'}),
        label='Módulo del examen supletorio *',
    )
    fecha = forms.DateField(
        widget=forms.DateInput(attrs={
            'class': 'form-input', 'type': 'date',
        }),
        label='Fecha del cobro *',
    )
    valor = forms.DecimalField(
        max_digits=10, decimal_places=2, min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-input', 'step': '0.01', 'min': '0',
            'placeholder': 'Ej.: 15.00',
        }),
        label='Valor del examen supletorio (USD) *',
    )
    metodo_pago = forms.ChoiceField(
        choices=METODOS_PAGO,
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_metodo_pago'}),
        label='Método de pago *',
        initial='efectivo',
    )
    banco = forms.CharField(
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_banco'}),
        label='Banco',
        required=False,
    )
    tipo_cobro = forms.ChoiceField(
        choices=[('un_solo_metodo', 'Un solo método'), ('mixto', 'Pago Mixto')],
        required=False,
        initial='un_solo_metodo',
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_tipo_cobro_adicional'}),
        label='Distribución de pago *',
    )
    monto_pago_1 = forms.DecimalField(
        required=False, min_value=0, decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-input', 'step': '0.01', 'id': 'id_monto_pago_1_adicional',
        }),
        label='Monto 1 (USD) *',
    )
    metodo_pago_1 = forms.ChoiceField(
        choices=[], required=False,
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_metodo_pago_1_adicional'}),
        label='Método 1 *',
    )
    banco_1 = forms.CharField(
        required=False,
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_banco_1_adicional'}),
        label='Banco 1',
    )
    monto_pago_2 = forms.DecimalField(
        required=False, min_value=0, decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-input', 'step': '0.01', 'id': 'id_monto_pago_2_adicional',
        }),
        label='Monto 2 (USD) *',
    )
    metodo_pago_2 = forms.ChoiceField(
        choices=[], required=False,
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_metodo_pago_2_adicional'}),
        label='Método 2 *',
    )
    banco_2 = forms.CharField(
        required=False,
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_banco_2_adicional'}),
        label='Banco 2',
    )
    numero_recibo = forms.CharField(
        max_length=30,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'Se genera automáticamente si lo dejas vacío',
        }),
        label='Nº de recibo',
    )
    observaciones = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-input', 'rows': 2,
            'placeholder': 'Notas adicionales (opcional).',
        }),
        label='Observaciones',
    )

    def __init__(self, *args, matricula=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.matricula = matricula
        metodos = list(METODOS_PAGO)
        self.fields['metodo_pago_1'].choices = [('', '— Método 1 —')] + metodos
        self.fields['metodo_pago_2'].choices = [('', '— Método 2 —')] + metodos
        bancos_list = _opciones_banco()
        self.fields['banco'].widget.choices = bancos_list
        self.fields['banco_1'].widget.choices = bancos_list
        self.fields['banco_2'].widget.choices = bancos_list

        # Construir choices del módulo según el curso
        choices = [('', '— Selecciona módulo —')]
        if matricula and matricula.curso_id:
            n = matricula.curso.get_numero_modulos(matricula.modalidad)
            if matricula.curso.nombrar_modulos and matricula.curso.nombres_modulos:
                nombres = matricula.curso.nombres_modulos.get(matricula.modalidad, [])
            else:
                nombres = []
            for i in range(1, n + 1):
                nombre_per = nombres[i-1] if i - 1 < len(nombres) else None
                label = f'Módulo {i} - {nombre_per}' if nombre_per else f'Módulo {i}'
                choices.append((i, label))
        else:
            choices += [(i, f'Módulo {i}') for i in range(1, 6)]
        self.fields['numero_modulo'].widget.choices = choices

    def clean(self):
        cleaned = super().clean()
        valor = cleaned.get('valor') or Decimal('0.00')
        tipo_cobro = cleaned.get('tipo_cobro') or 'un_solo_metodo'

        if tipo_cobro == 'mixto':
            m1 = cleaned.get('monto_pago_1') or Decimal('0.00')
            m2 = cleaned.get('monto_pago_2') or Decimal('0.00')
            metodo1 = cleaned.get('metodo_pago_1')
            metodo2 = cleaned.get('metodo_pago_2')

            if m1 <= 0:
                self.add_error('monto_pago_1', 'El Monto 1 debe ser mayor a cero.')
            if m2 <= 0:
                self.add_error('monto_pago_2', 'El Monto 2 debe ser mayor a cero.')
            if (m1 + m2).quantize(Decimal('0.01')) != valor.quantize(Decimal('0.01')):
                self.add_error(
                    'monto_pago_2',
                    'La suma del Monto 1 y Monto 2 debe ser exactamente igual al valor del supletorio.'
                )
            if not metodo1:
                self.add_error('metodo_pago_1', 'Selecciona el método del Monto 1.')
            if not metodo2:
                self.add_error('metodo_pago_2', 'Selecciona el método del Monto 2.')
            _revisar_banco(
                self, cleaned, 'metodo_pago_1', 'banco_1',
                'Selecciona el banco o app del Monto 1.',
            )
            _revisar_banco(
                self, cleaned, 'metodo_pago_2', 'banco_2',
                'Selecciona el banco o app del Monto 2.',
            )
            cleaned['metodo_pago'] = ''
            cleaned['banco'] = ''
        else:
            _revisar_banco(self, cleaned, 'metodo_pago', 'banco')
            cleaned['monto_pago_1'] = None
            cleaned['metodo_pago_1'] = ''
            cleaned['banco_1'] = ''
            cleaned['monto_pago_2'] = None
            cleaned['metodo_pago_2'] = ''
            cleaned['banco_2'] = ''

        return cleaned


# ─────────────────────────────────────────────────────────
# Avisos / Anuncios (solo admin)
# ─────────────────────────────────────────────────────────
class AvisoForm(forms.ModelForm):
    """
    Form para crear/editar avisos del panel principal.

    El contenido llega como HTML desde un editor visual (contenteditable) y se
    sanitiza en clean_contenido() con la whitelist de academia.sanitizer, de
    modo que solo se conserve formato seguro (negrita, cursiva, subrayado,
    listas, colores).
    """
    class Meta:
        from .models import Aviso
        model = Aviso
        fields = [
            'titulo', 'contenido', 'tema',
            'fecha_inicio', 'fecha_fin', 'fijado', 'activo',
        ]
        widgets = {
            'titulo': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Ej. Cierre de matrículas este viernes',
                'maxlength': 140,
            }),
            # El textarea queda oculto; el editor visual escribe aquí el HTML.
            'contenido': forms.Textarea(attrs={
                'class': 'form-input', 'rows': 6, 'id': 'id_contenido',
            }),
            'tema': forms.Select(attrs={'class': 'form-input'}),
            'fecha_inicio': forms.DateTimeInput(
                attrs={'class': 'form-input', 'type': 'datetime-local'},
                format='%Y-%m-%dT%H:%M',
            ),
            'fecha_fin': forms.DateTimeInput(
                attrs={'class': 'form-input', 'type': 'datetime-local'},
                format='%Y-%m-%dT%H:%M',
            ),
            'fijado': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }
        labels = {
            'titulo': 'Título del aviso',
            'contenido': 'Contenido',
            'tema': 'Color del aviso',
            'fecha_inicio': 'Fecha y hora de inicio',
            'fecha_fin': 'Fecha y hora final (al pasar, desaparece solo)',
            'fijado': 'Fijar arriba (aparece de primero)',
            'activo': 'Activo (visible)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Asegura que los datetime-local rendericen el valor en edición.
        for campo in ('fecha_inicio', 'fecha_fin'):
            self.fields[campo].input_formats = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S']

    def clean_titulo(self):
        titulo = (self.cleaned_data.get('titulo') or '').strip()
        if not titulo:
            raise forms.ValidationError('El título es obligatorio.')
        return titulo

    def clean_contenido(self):
        from .sanitizer import limpiar_html
        crudo = self.cleaned_data.get('contenido') or ''
        limpio = limpiar_html(crudo)
        # Verificar que quede algo de texto real (no solo etiquetas vacías)
        import re
        solo_texto = re.sub(r'<[^>]+>', '', limpio).replace('&nbsp;', ' ').strip()
        if not solo_texto:
            raise forms.ValidationError('El contenido del aviso no puede estar vacío.')
        return limpio

    def clean(self):
        cleaned = super().clean()
        ini = cleaned.get('fecha_inicio')
        fin = cleaned.get('fecha_fin')
        if ini and fin and fin <= ini:
            self.add_error('fecha_fin', 'La fecha final debe ser posterior a la de inicio.')
        return cleaned


# ═════════════════════════════════════════════════════════════════
# Recordatorio / Borrador
# ═════════════════════════════════════════════════════════════════

class RecordatorioForm(forms.ModelForm):
    """
    Form para crear/editar recordatorios (notas internas).

    El destinatario se limita a usuarios reales del sistema. La fecha y la
    fecha de vencimiento se validan para que el vencimiento no sea anterior
    a la fecha del recordatorio.
    """
    class Meta:
        from .models import Recordatorio
        model = Recordatorio
        fields = [
            'titulo', 'contenido', 'prioridad',
            'destinatario', 'fecha', 'fecha_vencimiento',
        ]
        widgets = {
            'titulo': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Ej. Llamar al proveedor de camisetas',
                'maxlength': 140,
            }),
            'contenido': forms.Textarea(attrs={
                'class': 'form-input', 'rows': 5,
                'placeholder': 'Escribe aquí la nota o lo que necesitas recordar…',
            }),
            'prioridad': forms.Select(attrs={'class': 'form-input'}),
            'destinatario': forms.Select(attrs={'class': 'form-input'}),
            'fecha': forms.DateInput(
                attrs={'class': 'form-input', 'type': 'date'},
                format='%Y-%m-%d',
            ),
            'fecha_vencimiento': forms.DateInput(
                attrs={'class': 'form-input', 'type': 'date'},
                format='%Y-%m-%d',
            ),
        }
        labels = {
            'titulo': 'Título',
            'contenido': 'Nota',
            'prioridad': 'Prioridad',
            'destinatario': 'Notificar a',
            'fecha': 'Fecha',
            'fecha_vencimiento': 'Fecha de vencimiento',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.fields['destinatario'].queryset = (
            User.objects
            .filter(is_active=True)
            .select_related('perfil_visual')
            .order_by('first_name', 'username')
        )
        # Mostrar nombre legible en el select de destinatario.
        self.fields['destinatario'].label_from_instance = (
            lambda u: (f'{u.first_name} {u.last_name}'.strip() or u.username)
        )
        for campo in ('fecha', 'fecha_vencimiento'):
            self.fields[campo].input_formats = ['%Y-%m-%d']

    def clean_titulo(self):
        titulo = (self.cleaned_data.get('titulo') or '').strip()
        if not titulo:
            raise forms.ValidationError('El título es obligatorio.')
        return titulo

    def clean_contenido(self):
        contenido = (self.cleaned_data.get('contenido') or '').strip()
        if not contenido:
            raise forms.ValidationError('La nota no puede estar vacía.')
        return contenido

    def clean(self):
        cleaned = super().clean()
        fecha = cleaned.get('fecha')
        vto = cleaned.get('fecha_vencimiento')
        if fecha and vto and vto < fecha:
            self.add_error(
                'fecha_vencimiento',
                'La fecha de vencimiento no puede ser anterior a la fecha del recordatorio.'
            )
        return cleaned
