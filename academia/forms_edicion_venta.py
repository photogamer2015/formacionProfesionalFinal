from django import forms
from django.contrib.auth.models import User

from .fecha_matricula import preparar_campo_fecha, validar_fecha_matricula
from .forms import _normalizar_digitos_formateados
from .models import Matricula
from .permisos import es_admin


SECCIONES_VENTA = {
    'registro': ('Editar tipo de registro', ('tipo_registro',)),
    'vendedora': ('Editar vendedora', ('vendedora',)),
    'factura': ('Editar factura', (
        'factura_realizada', 'fact_nombres', 'fact_cedula', 'fact_correo',
        'numero_factura',
    )),
    'matricula': ('Editar matrícula', ('estado', 'fecha_matricula')),
}

# El número de factura se escribe a mano y solo admite dígitos.
ATTRS_NUMERO_FACTURA = {
    'inputmode': 'numeric', 'pattern': '[0-9]*', 'maxlength': '20',
    'autocomplete': 'off', 'data-solo-numeros': 'true',
    'placeholder': 'Ej.: 001001000000123',
}


def limpiar_numero_factura(valor):
    """Quita espacios y guiones; conserva los ceros iniciales."""
    numero = _normalizar_digitos_formateados(valor)
    if numero and (not numero.isascii() or not numero.isdigit()):
        raise forms.ValidationError(
            'El número de factura debe contener únicamente números.'
        )
    return numero


def limpiar_cedula_factura(valor):
    """Misma regla que el registro de matrícula: cédula o RUC solo con números."""
    cedula = _normalizar_digitos_formateados(valor)
    if cedula and (not cedula.isascii() or not cedula.isdigit()):
        raise forms.ValidationError(
            'La cédula o RUC de factura debe contener únicamente números.'
        )
    return cedula


class EdicionVentaForm(forms.ModelForm):
    class Meta:
        model = Matricula
        fields = ('tipo_registro', 'vendedora', 'factura_realizada',
                  'fact_nombres', 'fact_cedula', 'fact_correo',
                  'numero_factura', 'estado', 'fecha_matricula')
        labels = {
            'tipo_registro': 'Tipo de registro (origen de la venta)',
            'vendedora': 'Vendedora (asesor)',
            'factura_realizada': '¿Factura con datos?',
            'fact_nombres': 'Nombres del titular de factura',
            'fact_cedula': 'Número de cédula / RUC',
            'fact_correo': 'Correo electrónico (opcional)',
            'numero_factura': 'Número de factura',
            'estado': 'Estado',
            'fecha_matricula': 'Fecha de matrícula',
        }
        widgets = {
            'numero_factura': forms.TextInput(attrs=ATTRS_NUMERO_FACTURA),
            'fecha_matricula': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }

    def __init__(self, *args, seccion, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.campos_editables = SECCIONES_VENTA[seccion][1]
        for name in list(self.fields):
            if name not in self.campos_editables:
                del self.fields[name]
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-input'
        if 'tipo_registro' in self.fields:
            self.fields['tipo_registro'].required = True
        if 'vendedora' in self.fields:
            field = self.fields['vendedora']
            field.required = True
            field.queryset = User.objects.order_by('first_name', 'username')
            field.label_from_instance = lambda user: user.get_full_name() or user.username
            field.empty_label = '— Selecciona un asesor —'
        if 'factura_realizada' in self.fields:
            self.fields['factura_realizada'].required = True
        # Revertir un retiro voluntario es solo de administradores (igual que
        # el botón REVERTIR de la lista de retirados): para una asesora el
        # estado queda fijo y el servidor ignora lo que se envíe.
        self.estado_bloqueado = bool(
            'estado' in self.fields
            and self.instance.estado == 'retiro_voluntario'
            and not (user and es_admin(user))
        )
        if self.estado_bloqueado:
            self.fields['estado'].disabled = True
        # El pago hecho al matricular se reconoce por tener la fecha de la
        # matrícula; se guarda antes de que el formulario cambie la fecha.
        self.fecha_original = self.instance.fecha_matricula
        self.ids_pago_inicial = []
        if 'fecha_matricula' in self.fields and self.instance.pk:
            from .forms_registro_estudiantil import bloque_pago_inicial
            self.ids_pago_inicial = [a.pk for a in bloque_pago_inicial(self.instance)]
        if 'fecha_matricula' in self.fields:
            preparar_campo_fecha(self.fields['fecha_matricula'], self.fecha_original)

    def clean_fecha_matricula(self):
        fecha = self.cleaned_data.get('fecha_matricula')
        if self.fecha_cambia(fecha):
            validar_fecha_matricula(fecha)
        return fecha

    def clean_numero_factura(self):
        return limpiar_numero_factura(self.cleaned_data.get('numero_factura'))

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('factura_realizada') == 'si':
            for name in ('fact_nombres', 'fact_cedula'):
                if not cleaned.get(name):
                    self.add_error(name, 'Este dato es obligatorio para la factura.')
        elif cleaned.get('factura_realizada') == 'no' and 'numero_factura' in self.fields:
            # Sin factura no hay número: no se deja uno suelto.
            cleaned['numero_factura'] = ''
        fecha = cleaned.get('fecha_matricula')
        if fecha and self.fecha_cambia(fecha):
            # Misma regla que el Registro Estudiantil: el pago de la matrícula
            # se mueve con la fecha, que no puede quedar en o después de un
            # pago posterior (ese pago pasaría a contarse como pago inicial).
            posterior = (
                self.instance.abonos.exclude(pk__in=self.ids_pago_inicial)
                .filter(fecha__lte=fecha).order_by('fecha', 'creado').first()
            )
            if posterior:
                self.add_error(
                    'fecha_matricula',
                    f'Hay un pago posterior del {posterior.fecha:%d/%m/%Y} '
                    f'(recibo {posterior.numero_recibo}). La fecha de matrícula '
                    'debe ser anterior a ese pago.',
                )
        return cleaned

    def fecha_cambia(self, fecha):
        return 'fecha_matricula' in self.fields and fecha != self.fecha_original

    def mover_pago_inicial(self):
        """Pasa el pago hecho al matricular a la nueva fecha de matrícula.

        Sin esto, «Editar pago inicial», el PDF de la matrícula y el Registro
        Estudiantil dejarían de reconocerlo como pago inicial. Solo cambia la
        fecha: los montos quedan igual y no se envían correos. Devuelve True
        si movió algún pago.
        """
        fecha = self.instance.fecha_matricula
        if not (self.ids_pago_inicial and self.fecha_cambia(fecha)):
            return False
        from .models import Abono
        Abono.objects.filter(pk__in=self.ids_pago_inicial).update(fecha=fecha)
        return True


class RegistrarFacturaForm(forms.ModelForm):
    """Registra la factura de una matrícula que todavía no la tiene.

    El titular sale de los datos del estudiante. Solo con «Cambiar los datos»
    (cambiar_datos=1) se aceptan otros; si no, el servidor vuelve a poner los
    del estudiante aunque se envíe otra cosa.
    """

    CAMPOS_TITULAR = ('fact_nombres', 'fact_cedula', 'fact_correo')

    class Meta:
        model = Matricula
        fields = ('fact_nombres', 'fact_cedula', 'fact_correo', 'numero_factura')
        labels = {
            'fact_nombres': 'Nombres',
            'fact_cedula': 'Número de cédula / RUC',
            'fact_correo': 'Correo electrónico (opcional)',
            'numero_factura': 'Número de factura',
        }
        widgets = {
            'fact_nombres': forms.TextInput(attrs={
                'placeholder': 'Nombres del titular de factura',
            }),
            'fact_cedula': forms.TextInput(attrs={
                'placeholder': 'Cédula / RUC', 'inputmode': 'numeric',
                'maxlength': '20', 'data-solo-numeros': 'true',
            }),
            'fact_correo': forms.TextInput(attrs={
                'placeholder': 'correo@ejemplo.com',
            }),
            'numero_factura': forms.TextInput(attrs=ATTRS_NUMERO_FACTURA),
        }

    def __init__(self, data=None, *args, instance, **kwargs):
        estudiante = instance.estudiante
        self.datos_estudiante = {
            'fact_nombres': (estudiante.nombres or '').strip(),
            'fact_cedula': (estudiante.cedula or '').strip(),
            'fact_correo': (estudiante.correo or '').strip(),
        }
        self.cambiar_datos = data is not None and data.get('cambiar_datos') == '1'
        if data is not None and not self.cambiar_datos:
            data = data.copy()
            for name, valor in self.datos_estudiante.items():
                data[name] = valor
        super().__init__(data, *args, instance=instance, **kwargs)
        if not self.is_bound:
            self.initial.update(self.datos_estudiante)
        for name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'
            field.required = name != 'fact_correo'

    @property
    def titular_editable(self):
        """Los datos se muestran abiertos si se pidió cambiarlos o si los del
        estudiante no sirven para facturar (por ejemplo, un documento con letras)."""
        return self.cambiar_datos or (
            self.is_bound and any(name in self.errors for name in self.CAMPOS_TITULAR)
        )

    def clean_fact_cedula(self):
        return limpiar_cedula_factura(self.cleaned_data.get('fact_cedula'))

    def clean_numero_factura(self):
        numero = limpiar_numero_factura(self.cleaned_data.get('numero_factura'))
        if not numero:
            raise forms.ValidationError('Escribe el número de factura.')
        return numero

    def save(self, commit=True):
        matricula = super().save(commit=False)
        matricula.factura_realizada = 'si'
        if commit:
            # save() de Matricula también actualiza su Comprobante.
            matricula.save(update_fields=[
                'factura_realizada', 'fact_nombres', 'fact_cedula',
                'fact_correo', 'numero_factura', 'actualizado',
            ])
        return matricula


class FacturaAlMatricularForm(forms.ModelForm):
    """«¿Deseas registrar la factura ahora mismo?» del registro de matrícula.

    Con «No» (por defecto) no pide nada: la matrícula queda sin factura y se
    factura después en Matrícula › Facturas › Registrar factura. Con «Sí» pide
    lo mismo que esa pantalla: el titular sale de los datos del estudiante del
    formulario y solo con «Cambiar los datos» (cambiar_datos=1) se aceptan
    otros; el número de factura es obligatorio. La matrícula se guarda ya
    facturada, así que no aparece en «Matrículas sin factura».
    """

    CAMPOS_TITULAR = RegistrarFacturaForm.CAMPOS_TITULAR
    CAMPOS_FACTURA = CAMPOS_TITULAR + ('numero_factura',)
    prefix = 'fac'

    registrar = forms.ChoiceField(
        label='¿Deseas registrar la factura ahora mismo?',
        choices=(('no', 'No'), ('si', 'Sí')),
        initial='no',
        widget=forms.RadioSelect,
    )

    class Meta(RegistrarFacturaForm.Meta):
        pass

    def __init__(self, data=None, *args, datos_estudiante=None, **kwargs):
        self.datos_estudiante = dict(datos_estudiante or {})
        self.registra = self.cambiar_datos = False
        if data is not None:
            prefijo = kwargs.get('prefix') or self.prefix
            data = data.copy()
            clave = f'{prefijo}-registrar'
            # Un envío sin la pregunta (formulario en caché) cuenta como «No».
            if data.get(clave) not in ('si', 'no'):
                data[clave] = 'no'
            self.registra = data[clave] == 'si'
            self.cambiar_datos = self.registra and data.get(f'{prefijo}-cambiar_datos') == '1'
            if not self.registra:
                # Con «No» no se valida ni se guarda nada de la factura.
                for name in self.CAMPOS_FACTURA:
                    data[f'{prefijo}-{name}'] = ''
            elif not self.cambiar_datos:
                # Igual que «Registrar factura»: sin «Cambiar los datos» van
                # los del estudiante aunque se envíe otra cosa.
                for name in self.CAMPOS_TITULAR:
                    data[f'{prefijo}-{name}'] = self.datos_estudiante.get(name, '')
        super().__init__(data, *args, **kwargs)
        for name, field in self.fields.items():
            if name == 'registrar':
                continue
            field.widget.attrs['class'] = 'form-input'
            # Los datos del estudiante ya los valida su propio formulario; el
            # titular solo se exige cuando se escribe a mano.
            field.required = self.registra and (
                name == 'numero_factura'
                or (self.cambiar_datos and name != 'fact_correo')
            )

    @property
    def titular_editable(self):
        return self.cambiar_datos

    def clean_fact_cedula(self):
        cedula = self.cleaned_data.get('fact_cedula')
        if not self.cambiar_datos:
            return cedula
        return limpiar_cedula_factura(cedula)

    def clean_numero_factura(self):
        numero = limpiar_numero_factura(self.cleaned_data.get('numero_factura'))
        if self.registra and not numero:
            raise forms.ValidationError('Escribe el número de factura.')
        return numero

    def aplicar(self, matricula):
        """Deja la factura en la matrícula antes de guardarla (solo con «Sí»)."""
        if not self.registra:
            return
        for name in self.CAMPOS_FACTURA:
            setattr(matricula, name, self.cleaned_data[name])
        matricula.factura_realizada = 'si'
