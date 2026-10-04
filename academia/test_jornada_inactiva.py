from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .forms import MatriculaForm
from .models import Abono, Curso, Estudiante, JornadaCurso, Matricula, Sede
from .views_pagos import _calcular_alertas_pago


class JornadaInactivaTests(TestCase):
    """Desactivar una jornada no debe esconder ni bloquear a sus estudiantes."""

    def setUp(self):
        self.admin = User.objects.create_superuser('admin_jornada_inactiva')
        self.client.force_login(self.admin)
        sede = Sede.objects.create(nombre='Guayaquil')
        self.curso = Curso.objects.create(
            nombre='Curso jornada inactiva', ofrece_presencial=True,
            valor_presencial=Decimal('80.00'), numero_modulos=4,
        )
        self.jornada = JornadaCurso.objects.create(
            curso=self.curso, modalidad='presencial',
            descripcion='domingos_intensivos', fecha_inicio=date(2026, 9, 27),
            sede=sede, activo=False,
        )
        self.activa = JornadaCurso.objects.create(
            curso=self.curso, modalidad='presencial',
            descripcion='sabados_intensivos', fecha_inicio=date(2026, 10, 10),
            sede=sede,
        )
        self.mat = Matricula.objects.create(
            estudiante=Estudiante.objects.create(cedula='0922222222', nombres='Jornada Inactiva'),
            curso=self.curso, jornada=self.jornada, modalidad='presencial',
            tipo_matricula='reserva_abono', forma_pago='abono',
            fecha_matricula=date(2026, 9, 20), valor_curso=Decimal('80.00'),
            tipo_registro='central_ia', factura_realizada='no', vendedora=self.admin,
        )
        self.inicial = Abono.objects.create(
            matricula=self.mat, fecha=date(2026, 9, 20), monto=Decimal('10.00'),
            tipo_pago='abono', metodo='efectivo',
        )
        Abono.objects.filter(pk=self.inicial.pk).update(creado=self.mat.creado)
        self.mat.recalcular_valor_pagado()

    def test_panel_gestion_matriculas_muestra_jornada_inactiva(self):
        with patch('academia.views_pagos.date') as fecha_mock:
            fecha_mock.today.return_value = date(2026, 10, 4)
            alertas = _calcular_alertas_pago()
        alerta = next(a for a in alertas if a['matricula'].pk == self.mat.pk)
        self.assertEqual(alerta['numero_modulo'], 1)
        self.assertEqual(alerta['dias_atraso'], 7)

    def test_editar_pago_inicial_con_jornada_inactiva(self):
        # Antes fallaba con «Escoja una opción válida» en la jornada.
        url = reverse('academia:matricula_editar', args=['presencial', self.mat.pk])
        self.assertEqual(self.client.get(url, {'editar_pago': '1'}).status_code, 200)
        response = self.client.post(url, {
            'editar_pago': '1', 'mat-valor_pagado': '8', 'mat-forma_pago': 'abono',
            'mat-descuento': '0', 'mat-tipo_cobro': 'un_solo_metodo',
            'mat-metodo_pago': 'efectivo',
        })
        self.assertEqual(
            response.status_code, 302,
            getattr(response, 'context', None) and response.context['mat_form'].errors,
        )
        self.mat.refresh_from_db()
        self.assertEqual(self.mat.jornada_id, self.jornada.pk)
        self.assertEqual(self.mat.valor_pagado, Decimal('8.00'))

    def test_jornada_inactiva_no_se_ofrece_a_otras_matriculas(self):
        edicion = MatriculaForm(prefix='mat', instance=self.mat, captura_pago=False)
        self.assertEqual(
            set(edicion.fields['jornada'].queryset),
            {self.jornada, self.activa},
        )
        nueva = MatriculaForm({'mat-curso': str(self.curso.pk)}, prefix='mat')
        self.assertEqual(list(nueva.fields['jornada'].queryset), [self.activa])
        otra = Matricula.objects.create(
            estudiante=Estudiante.objects.create(cedula='0933333333', nombres='Otra'),
            curso=self.curso, jornada=self.activa, modalidad='presencial',
            fecha_matricula=date(2026, 10, 1), valor_curso=Decimal('80.00'),
        )
        edicion_otra = MatriculaForm(prefix='mat', instance=otra, captura_pago=False)
        self.assertEqual(list(edicion_otra.fields['jornada'].queryset), [self.activa])
