from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from .models import (
    Abono, CierreCurso, Comprobante, Curso, Estudiante, Matricula,
    MatriculaArchivada,
)


class FacturasBase(TestCase):
    def setUp(self):
        asesores = Group.objects.create(name='Asesores')
        self.admin = User.objects.create_superuser('admin_fact', password='test')
        self.duena = User.objects.create_user('asesora_fact_duena')
        self.otra = User.objects.create_user('asesora_fact_otra')
        self.duena.groups.add(asesores)
        self.otra.groups.add(asesores)
        self.curso = Curso.objects.create(nombre='Curso facturas')
        self.otro_curso = Curso.objects.create(nombre='Otro curso')
        self.estudiante = Estudiante.objects.create(
            cedula='0912345678', nombres='Ana Pérez', correo='ana@example.com',
        )
        # Sin factura, registrada por la asesora dueña.
        self.sin = Matricula.objects.create(
            estudiante=self.estudiante, curso=self.curso, modalidad='presencial',
            fecha_matricula=date(2026, 9, 10), valor_curso=100,
            registrado_por=self.duena, vendedora=self.duena, tipo_registro='central_ia',
        )
        Abono.objects.create(matricula=self.sin, monto=30, fecha=date(2026, 9, 10),
                             metodo='efectivo', tipo_pago='abono')
        # Sin factura, registrada por otra asesora.
        self.ajena = Matricula.objects.create(
            estudiante=Estudiante.objects.create(cedula='0911111111', nombres='Luis Mora'),
            curso=self.otro_curso, modalidad='online',
            fecha_matricula=date(2026, 9, 12), valor_curso=90,
            registrado_por=self.otra, vendedora=self.otra, tipo_registro='central_1',
        )
        # Con factura.
        self.con = Matricula.objects.create(
            estudiante=Estudiante.objects.create(cedula='0922222222', nombres='Eva Ruiz'),
            curso=self.curso, modalidad='presencial',
            fecha_matricula=date(2026, 9, 5), valor_curso=100,
            registrado_por=self.duena, vendedora=self.duena, tipo_registro='central_ia',
            factura_realizada='si', fact_nombres='Eva Ruiz', fact_cedula='0922222222',
            numero_factura='000777',
        )
        self.url_lista = reverse('academia:matricula_facturas')
        self.url_sin = reverse('academia:matricula_sin_factura')

    def url_registrar(self, matricula):
        return reverse('academia:matricula_registrar_factura', args=[matricula.pk])


class ListasFacturasTests(FacturasBase):
    def test_lista_de_facturas_solo_muestra_las_que_tienen_factura(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url_lista)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([m.pk for m in response.context['matriculas']], [self.con.pk])
        self.assertContains(response, 'Datos de factura')
        self.assertContains(response, '000777')
        self.assertContains(response, self.url_sin)
        self.assertContains(response, 'Matrículas sin factura (2)')
        self.assertContains(response, 'editar_seccion=factura&amp;volver=facturas')

    def test_lista_sin_factura_con_boton_solo_para_la_duena(self):
        self.client.force_login(self.duena)
        response = self.client.get(self.url_sin)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {m.pk for m in response.context['matriculas']},
            {self.sin.pk, self.ajena.pk},
        )
        self.assertNotContains(response, 'Datos de factura')
        for columna in ('Valor neto', 'Pagado', 'Saldo pendiente', 'Tipo de pago', 'Método'):
            self.assertContains(response, f'<th>{columna}</th>')
        self.assertContains(response, self.url_registrar(self.sin))
        self.assertNotContains(response, self.url_registrar(self.ajena))
        self.assertContains(response, 'Bloqueado')

    def test_lista_sin_factura_filtra_por_curso(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url_sin, {'curso': self.otro_curso.pk})
        self.assertEqual([m.pk for m in response.context['matriculas']], [self.ajena.pk])
        self.assertContains(
            response,
            f'{self.url_registrar(self.ajena)}?curso={self.otro_curso.pk}',
        )


class RegistrarFacturaTests(FacturasBase):
    def _post(self, matricula, **datos):
        return self.client.post(self.url_registrar(matricula), datos)

    def test_formulario_trae_los_datos_del_estudiante(self):
        self.client.force_login(self.duena)
        response = self.client.get(self.url_registrar(self.sin))
        self.assertEqual(response.status_code, 200)
        for valor in ('Ana Pérez', '0912345678', 'ana@example.com'):
            self.assertContains(response, f'value="{valor}"')
        self.assertContains(response, 'name="numero_factura"')
        self.assertContains(response, 'Cambiar los datos')

    def test_registra_con_datos_del_estudiante_sin_tocar_lo_demas(self):
        self.client.force_login(self.duena)
        self.sin.refresh_from_db()
        antes = Matricula.objects.values().get(pk=self.sin.pk)
        pagos = list(self.sin.abonos.values())
        # Sin «Cambiar los datos» se ignora lo que llegue en los campos del
        # titular, y nada fuera de la factura se puede alterar desde aquí.
        response = self._post(
            self.sin, numero_factura='001-001-000000123', cambiar_datos='0',
            fact_nombres='Otra persona', fact_cedula='0999999999',
            valor_pagado='999', estado='retiro_voluntario', vendedora=self.otra.pk,
        )
        self.assertRedirects(response, self.url_sin, fetch_redirect_response=False)
        despues = Matricula.objects.values().get(pk=self.sin.pk)
        self.assertEqual(
            sorted(k for k in antes if antes[k] != despues[k]),
            ['actualizado', 'fact_cedula', 'fact_correo', 'fact_nombres',
             'factura_realizada', 'numero_factura'],
        )
        self.sin.refresh_from_db()
        self.assertEqual(self.sin.factura_realizada, 'si')
        self.assertEqual(self.sin.fact_nombres, 'Ana Pérez')
        self.assertEqual(self.sin.fact_cedula, '0912345678')
        self.assertEqual(self.sin.fact_correo, 'ana@example.com')
        self.assertEqual(self.sin.numero_factura, '001001000000123')
        self.assertEqual(list(self.sin.abonos.values()), pagos)
        comprobante = Comprobante.objects.get(matricula=self.sin)
        self.assertEqual(comprobante.factura_realizada, 'si')
        self.assertEqual(comprobante.fact_nombres, 'Ana Pérez')
        # Ya está en la Lista de Facturas y sale de las que no tienen factura.
        self.assertIn(self.sin, self.client.get(self.url_lista).context['matriculas'])
        self.assertNotIn(self.sin, self.client.get(self.url_sin).context['matriculas'])

    def test_cambiar_los_datos_factura_a_otra_persona(self):
        self.client.force_login(self.duena)
        self._post(
            self.sin, numero_factura='000124', cambiar_datos='1',
            fact_nombres='Empresa XYZ', fact_cedula='0990000000001', fact_correo='',
        )
        self.sin.refresh_from_db()
        self.assertEqual(self.sin.factura_realizada, 'si')
        self.assertEqual(self.sin.fact_nombres, 'Empresa XYZ')
        self.assertEqual(self.sin.fact_cedula, '0990000000001')
        self.assertEqual(self.sin.fact_correo, '')
        self.assertEqual(self.sin.numero_factura, '000124')

    def test_cedula_pegada_con_espacios_se_normaliza(self):
        self.client.force_login(self.duena)
        self._post(
            self.sin, numero_factura='5', cambiar_datos='1',
            fact_nombres='Cliente Factura', fact_cedula='010 203 0405',
        )
        self.sin.refresh_from_db()
        self.assertEqual(self.sin.fact_cedula, '0102030405')

    def test_numero_de_factura_obligatorio_y_solo_numeros(self):
        self.client.force_login(self.duena)
        for numero in ('', 'ABC-123', '12a4'):
            response = self._post(self.sin, numero_factura=numero, cambiar_datos='0')
            self.assertEqual(response.status_code, 200)
            self.assertIn('numero_factura', response.context['form'].errors)
        response = self._post(
            self.sin, numero_factura='555', cambiar_datos='1',
            fact_nombres='', fact_cedula='09AB',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.context['form'].errors), {'fact_nombres', 'fact_cedula'},
        )
        self.assertTrue(response.context['form'].titular_editable)
        self.sin.refresh_from_db()
        self.assertEqual(self.sin.factura_realizada, 'no')
        self.assertEqual(self.sin.numero_factura, '')

    def test_otra_asesora_no_puede_registrar(self):
        self.client.force_login(self.otra)
        self.assertRedirects(
            self.client.get(self.url_registrar(self.sin)), self.url_sin,
            fetch_redirect_response=False,
        )
        self._post(self.sin, numero_factura='999', cambiar_datos='0')
        self.sin.refresh_from_db()
        self.assertEqual(self.sin.factura_realizada, 'no')
        self.assertEqual(self.sin.numero_factura, '')

    def test_admin_registra_cualquier_matricula(self):
        self.client.force_login(self.admin)
        self._post(self.ajena, numero_factura='888', cambiar_datos='0')
        self.ajena.refresh_from_db()
        self.assertEqual(self.ajena.factura_realizada, 'si')
        self.assertEqual(self.ajena.fact_nombres, 'Luis Mora')

    def test_no_vuelve_a_registrar_una_factura_existente(self):
        self.client.force_login(self.duena)
        response = self._post(self.con, numero_factura='1', cambiar_datos='0')
        self.assertRedirects(response, self.url_lista, fetch_redirect_response=False)
        self.con.refresh_from_db()
        self.assertEqual(self.con.numero_factura, '000777')

    def test_numero_repetido_se_guarda_con_aviso(self):
        self.client.force_login(self.duena)
        response = self._post(self.sin, numero_factura='000777', cambiar_datos='0')
        self.assertEqual(response.status_code, 302)
        avisos = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any(f'matrícula #{self.con.pk}' in a for a in avisos), avisos)
        self.sin.refresh_from_db()
        self.assertEqual(self.sin.numero_factura, '000777')

    def test_regresa_a_la_lista_con_los_mismos_filtros(self):
        self.client.force_login(self.duena)
        response = self.client.get(self.url_registrar(self.sin), {'curso': self.curso.pk, 'otro': 'x'})
        self.assertEqual(response.context['volver'], f'curso={self.curso.pk}')
        response = self._post(
            self.sin, numero_factura='42', cambiar_datos='0',
            volver=f'curso={self.curso.pk}&evil=https://example.com',
        )
        self.assertRedirects(
            response, f'{self.url_sin}?curso={self.curso.pk}',
            fetch_redirect_response=False,
        )


class EditarFacturaNumeroTests(FacturasBase):
    def setUp(self):
        super().setUp()
        self.url_editar = reverse('academia:matricula_editar', args=['presencial', self.con.pk])

    def test_corrige_el_numero_y_regresa_a_la_lista_de_facturas(self):
        self.client.force_login(self.duena)
        response = self.client.get(self.url_editar, {'editar_seccion': 'factura', 'volver': 'facturas'})
        self.assertContains(response, 'name="numero_factura"')
        self.assertContains(response, 'name="volver" value="facturas"')
        response = self.client.post(self.url_editar, {
            'editar_seccion': 'factura', 'volver': 'facturas', 'factura_realizada': 'si',
            'fact_nombres': 'Eva Ruiz', 'fact_cedula': '0922222222', 'fact_correo': '',
            'numero_factura': '000778',
        })
        self.assertRedirects(response, self.url_lista, fetch_redirect_response=False)
        self.con.refresh_from_db()
        self.assertEqual(self.con.numero_factura, '000778')

    def test_numero_con_letras_no_se_guarda(self):
        self.client.force_login(self.duena)
        response = self.client.post(self.url_editar, {
            'editar_seccion': 'factura', 'factura_realizada': 'si',
            'fact_nombres': 'Eva Ruiz', 'fact_cedula': '0922222222',
            'numero_factura': '77A',
        })
        self.assertEqual(response.status_code, 200)
        self.con.refresh_from_db()
        self.assertEqual(self.con.numero_factura, '000777')

    def test_factura_no_borra_el_numero(self):
        self.client.force_login(self.duena)
        self.client.post(self.url_editar, {
            'editar_seccion': 'factura', 'factura_realizada': 'no',
            'fact_nombres': 'Eva Ruiz', 'fact_cedula': '0922222222',
            'numero_factura': '000777',
        })
        self.con.refresh_from_db()
        self.assertEqual(self.con.factura_realizada, 'no')
        self.assertEqual(self.con.numero_factura, '')

    def test_otra_asesora_no_ve_ni_puede_editar_la_factura(self):
        self.client.force_login(self.otra)
        response = self.client.get(self.url_lista)
        self.assertEqual([m.pk for m in response.context['matriculas']], [self.con.pk])
        self.assertNotContains(response, 'editar_seccion=factura')
        response = self.client.get(self.url_editar, {'editar_seccion': 'factura'})
        self.assertEqual(response.status_code, 302)
        response = self.client.post(self.url_editar, {
            'editar_seccion': 'factura', 'factura_realizada': 'si',
            'fact_nombres': 'Otro titular', 'fact_cedula': '0933333333',
            'numero_factura': '000999',
        })
        self.assertEqual(response.status_code, 302)
        self.con.refresh_from_db()
        self.assertEqual(self.con.numero_factura, '000777')
        self.assertEqual(self.con.fact_nombres, 'Eva Ruiz')

    def test_el_cierre_conserva_el_numero_de_factura(self):
        from .views_cierre import _snapshot_matricula
        cierre = CierreCurso.objects.create(curso=self.curso, curso_nombre=self.curso.nombre)
        archivada = _snapshot_matricula(self.con, cierre)
        self.assertEqual(MatriculaArchivada.objects.get(pk=archivada.pk).numero_factura, '000777')


class MenuFacturasTests(FacturasBase):
    def test_menu_ofrece_registrar_o_ver_la_lista(self):
        self.client.force_login(self.duena)
        response = self.client.get(reverse('academia:matricula_menu', args=['presencial']))
        self.assertContains(response, '¿Qué deseas hacer?')
        self.assertContains(response, self.url_sin)
        self.assertContains(response, self.url_lista)
