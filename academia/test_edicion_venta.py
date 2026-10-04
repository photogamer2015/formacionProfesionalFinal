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


class EdicionMatriculaSeccionTests(TestCase):
    """Sección «Editar matrícula»: solo estado y fecha de matrícula."""

    def setUp(self):
        from django.contrib.auth.models import Group
        asesores = Group.objects.create(name='Asesores')
        self.admin = User.objects.create_superuser('admin_mat', password='test')
        self.duena = User.objects.create_user('asesora_duena_mat')
        self.otra = User.objects.create_user('asesora_otra_mat')
        self.duena.groups.add(asesores)
        self.otra.groups.add(asesores)
        self.m = Matricula.objects.create(
            estudiante=Estudiante.objects.create(cedula='0900000002', nombres='Prueba'),
            curso=Curso.objects.create(nombre='Curso'), modalidad='presencial',
            fecha_matricula=date(2026, 9, 19), valor_curso=100,
            registrado_por=self.duena, vendedora=self.duena, tipo_registro='central_ia',
        )
        Abono.objects.create(matricula=self.m, monto=20, fecha=date(2026, 9, 19),
                             metodo='efectivo', tipo_pago='abono')
        self.url = reverse('academia:matricula_editar', args=['presencial', self.m.pk])

    def _post(self, **datos):
        return self.client.post(self.url, {'editar_seccion': 'matricula', **datos})

    def test_duena_cambia_estado_y_fecha_sin_tocar_lo_demas(self):
        self.client.force_login(self.duena)
        response = self.client.get(self.url, {'editar_seccion': 'matricula'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="estado"')
        self.assertContains(response, 'value="2026-09-19"')
        self.assertNotContains(response, 'name="vendedora"')

        self.m.refresh_from_db()
        antes = Matricula.objects.values().get(pk=self.m.pk)
        pagos = list(self.m.abonos.values())
        response = self._post(
            estado='retiro_voluntario', fecha_matricula='2026-08-05',
            valor_pagado='999', descuento='50', vendedora=self.otra.pk,
            tipo_registro='seguimiento', factura_realizada='si',
        )
        self.assertEqual(response.status_code, 302)
        despues = Matricula.objects.values().get(pk=self.m.pk)
        self.assertEqual(
            sorted(k for k in antes if antes[k] != despues[k]),
            ['estado', 'fecha_matricula'],
        )
        self.m.refresh_from_db()
        self.assertEqual(self.m.estado, 'retiro_voluntario')
        self.assertEqual(self.m.fecha_matricula, date(2026, 8, 5))
        self.assertEqual(self.m.comprobante.fecha_inscripcion, date(2026, 8, 5))
        # El pago hecho al matricular pasa a la nueva fecha (sigue siendo el
        # pago inicial); nada más del pago cambia.
        for pago in pagos:
            pago['fecha'] = date(2026, 8, 5)
        self.assertEqual(list(self.m.abonos.values()), pagos)
        from .views import _ids_abonos_pago_inicial
        self.assertEqual(_ids_abonos_pago_inicial(self.m), [p['id'] for p in pagos])

    def test_fecha_no_puede_pasar_un_pago_posterior(self):
        Abono.objects.create(matricula=self.m, monto=15, fecha=date(2026, 9, 26),
                             metodo='efectivo', tipo_pago='abono')
        self.client.force_login(self.duena)
        response = self._post(estado='activa', fecha_matricula='2026-09-26')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Hay un pago posterior del 26/09/2026')
        self.m.refresh_from_db()
        self.assertEqual(self.m.fecha_matricula, date(2026, 9, 19))
        self.assertEqual(
            sorted(self.m.abonos.values_list('fecha', flat=True)),
            [date(2026, 9, 19), date(2026, 9, 26)],
        )

        # Una fecha anterior sí se acepta y solo mueve el pago de la matrícula.
        self.assertEqual(self._post(estado='activa', fecha_matricula='2026-09-20').status_code, 302)
        self.m.refresh_from_db()
        self.assertEqual(self.m.fecha_matricula, date(2026, 9, 20))
        self.assertEqual(
            sorted(self.m.abonos.values_list('fecha', flat=True)),
            [date(2026, 9, 20), date(2026, 9, 26)],
        )

    def test_solo_estado_no_mueve_pagos(self):
        self.client.force_login(self.duena)
        self.assertEqual(
            self._post(estado='retiro_voluntario', fecha_matricula='2026-09-19').status_code, 302,
        )
        self.assertEqual(
            list(self.m.abonos.values_list('fecha', flat=True)), [date(2026, 9, 19)],
        )

    def test_fecha_invalida_no_guarda(self):
        self.client.force_login(self.duena)
        for fecha in ('', '2026-13-40'):
            self.assertEqual(self._post(estado='activa', fecha_matricula=fecha).status_code, 200)
        self.m.refresh_from_db()
        self.assertEqual(self.m.fecha_matricula, date(2026, 9, 19))

    def test_otra_asesora_no_puede_editar(self):
        self.client.force_login(self.otra)
        self.assertEqual(self.client.get(self.url, {'editar_seccion': 'matricula'}).status_code, 302)
        self._post(estado='retiro_voluntario', fecha_matricula='2026-01-01')
        self.m.refresh_from_db()
        self.assertEqual(self.m.estado, 'activa')
        self.assertEqual(self.m.fecha_matricula, date(2026, 9, 19))

    def test_solo_admin_revierte_retiro(self):
        Matricula.objects.filter(pk=self.m.pk).update(estado='retiro_voluntario')
        self.client.force_login(self.duena)
        response = self.client.get(self.url, {'editar_seccion': 'matricula'})
        self.assertContains(response, 'solo un administrador puede volver a activarla')
        self.assertEqual(self._post(estado='activa', fecha_matricula='2026-08-05').status_code, 302)
        self.m.refresh_from_db()
        self.assertEqual(self.m.estado, 'retiro_voluntario')
        self.assertEqual(self.m.fecha_matricula, date(2026, 8, 5))

        self.client.force_login(self.admin)
        self.assertEqual(self._post(estado='activa', fecha_matricula='2026-08-05').status_code, 302)
        self.m.refresh_from_db()
        self.assertEqual(self.m.estado, 'activa')
