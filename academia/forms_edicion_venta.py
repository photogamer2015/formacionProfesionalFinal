from django import forms
from django.contrib.auth.models import User

from .models import Matricula


SECCIONES_VENTA = {
    'registro': ('Editar tipo de registro', ('tipo_registro',)),
    'vendedora': ('Editar vendedora', ('vendedora',)),
    'factura': ('Editar factura', (
        'factura_realizada', 'fact_nombres', 'fact_cedula', 'fact_correo',
    )),
}


class EdicionVentaForm(forms.ModelForm):
    class Meta:
        model = Matricula
        fields = ('tipo_registro', 'vendedora', 'factura_realizada',
                  'fact_nombres', 'fact_cedula', 'fact_correo')
        labels = {
            'tipo_registro': 'Tipo de registro (origen de la venta)',
            'vendedora': 'Vendedora (asesor)',
            'factura_realizada': '¿Factura con datos?',
            'fact_nombres': 'Nombres del titular de factura',
            'fact_cedula': 'Número de cédula / RUC',
            'fact_correo': 'Correo electrónico (opcional)',
        }

    def __init__(self, *args, seccion, **kwargs):
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

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('factura_realizada') == 'si':
            for name in ('fact_nombres', 'fact_cedula'):
                if not cleaned.get(name):
                    self.add_error(name, 'Este dato es obligatorio para la factura.')
        return cleaned
