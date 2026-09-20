from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Abono, Curso, Estudiante, Matricula


class EdicionVentaTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin_venta', password='test')
        self.asesora = User.objects.create_user('asesora_venta')
        self.client.force_login(self.admin)
        self.m = Matricula.objects.create(
            estudiante=Estudiante.objects.create(cedula='0900000001', nombres='Prueba'),
            curso=Curso.objects.create(nombre='Curso'), modalidad='presencial',
            fecha_matricula=date(2026, 9, 19), valor_curso=100,
            registrado_por=self.admin, vendedora=self.admin, tipo_registro='central_ia',
        )
        Abono.objects.create(matricula=self.m, monto=20, fecha=date(2026, 9, 19),
                             metodo='efectivo', tipo_pago='abono')
        self.url = reverse('academia:matricula_editar', args=['presencial', self.m.pk])

    def test_secciones_aisladas_y_comprobante_sin_cambiar_pagos(self):
        self.m.refresh_from_db()
        pagos = list(self.m.abonos.values())
        pagado = self.m.valor_pagado
        for seccion, datos in [
            ('registro', {'tipo_registro': 'central_ia'}),
            ('vendedora', {'vendedora': self.asesora.pk}),
            ('factura', {'factura_realizada': 'si', 'fact_nombres': 'Titular',
                         'fact_cedula': '0900000001', 'fact_correo': ''}),
        ]:
            self.assertEqual(self.client.get(self.url, {'editar_seccion': seccion}).status_code, 200)
            response = self.client.post(self.url, {
                'editar_seccion': seccion, 'valor_pagado': '999',
                'descuento': '99', 'estado': 'retiro_voluntario', **datos,
            })
            self.assertEqual(response.status_code, 302)
        self.m.refresh_from_db()
        self.assertEqual(self.m.vendedora_id, self.asesora.pk)
        self.assertEqual(self.m.comprobante.vendedora_id, self.asesora.pk)
        self.assertEqual(self.m.comprobante.fact_nombres, 'Titular')
        self.assertEqual(self.m.registrado_por_id, self.admin.pk)
        self.assertEqual(self.m.valor_pagado, pagado)
        self.assertEqual(self.m.descuento, 0)
        self.assertEqual(self.m.estado, 'activa')
        self.assertEqual(list(self.m.abonos.values()), pagos)

    def test_factura_y_vendedora_invalidas_no_guardan(self):
        for datos in [
            {'editar_seccion': 'factura', 'factura_realizada': 'si'},
            {'editar_seccion': 'vendedora', 'vendedora': '999999'},
            {'editar_seccion': 'registro', 'tipo_registro': 'invalido'},
        ]:
            self.assertEqual(self.client.post(self.url, datos).status_code, 200)
        self.m.refresh_from_db()
        self.assertEqual(self.m.factura_realizada, 'no')
        self.assertEqual(self.m.vendedora_id, self.admin.pk)

    def test_otra_asesora_no_puede_editar(self):
        self.client.force_login(self.asesora)
        self.client.post(self.url, {'editar_seccion': 'vendedora', 'vendedora': self.asesora.pk})
        self.m.refresh_from_db()
        self.assertEqual(self.m.vendedora_id, self.admin.pk)
