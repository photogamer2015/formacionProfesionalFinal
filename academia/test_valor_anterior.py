"""Valor anterior del curso y tope de los pagos «Solo Módulo».

El valor anterior es el precio que tenía antes el curso (p. ej. $110 antes de
bajar a $90): no se usa al matricular y se puede intercambiar con el valor
principal desde la lista de cursos. El tope por módulo depende solo del valor
de cada matrícula: las de $110 pagan hasta $25 y las demás presenciales (p. ej.
las de $90) hasta $20, con o sin valor anterior en el curso."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from .forms import AbonoForm, CursoForm
from .models import Abono, Categoria, Curso, Estudiante, JornadaCurso, Matricula, Sede
from .permisos import GRUPO_ASESOR


def _pago_modulo(monto, modulo='3', **overrides):
    return {
        'fecha': '2026-10-03', 'monto': monto, 'tipo_pago': 'solo_modulo',
        'numero_modulo': modulo, 'cuenta_para_saldo': 'True',
        'metodo': 'efectivo', 'banco': '', 'numero_recibo': '',
        'observaciones': '', 'tipo_cobro': 'un_solo_metodo',
        'monto_pago_1': '', 'metodo_pago_1': '', 'banco_1': '',
        'monto_pago_2': '', 'metodo_pago_2': '', 'banco_2': '',
        **overrides,
    }


class ValorAnteriorBase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin_valor_anterior')
        self.sede = Sede.objects.create(nombre='Guayaquil')
        self.categoria = Categoria.objects.get_or_create(nombre='Técnico')[0]
        # Servicio Técnico bajó de $110 (módulos de $25) a $90 (módulos de $20).
        self.curso = Curso.objects.create(
            nombre='Servicio Técnico (prueba valor anterior)', categoria=self.categoria,
            ofrece_presencial=True, valor_presencial=Decimal('90.00'),
            valor_anterior_presencial=Decimal('110.00'),
            ofrece_online=True, valor_online=Decimal('60.00'),
            numero_modulos=4, numero_modulos_online=2,
        )
        self.jornada = JornadaCurso.objects.create(
            curso=self.curso, modalidad='presencial',
            descripcion='sabados_intensivos', fecha_inicio=date(2026, 9, 19),
            sede=self.sede,
        )
        self.cedulas = iter(range(950000001, 950000100))

    def _matricula(self, valor, tipo='reserva_abono', descuento='0.00', curso=None, jornada=None):
        return Matricula.objects.create(
            estudiante=Estudiante.objects.create(
                cedula=f'0{next(self.cedulas)}', nombres='Estudiante Valor Anterior',
            ),
            curso=curso or self.curso, jornada=jornada or self.jornada,
            modalidad=(jornada or self.jornada).modalidad,
            tipo_matricula=tipo, forma_pago='abono',
            fecha_matricula=date(2026, 9, 12), valor_curso=Decimal(valor),
            descuento=Decimal(descuento), tipo_registro='central_ia',
            registrado_por=self.admin,
        )

    def _kevin(self):
        """Matrícula de $110 con reserva de $10 y los módulos 1 y 2 a $25."""
        matricula = self._matricula('110.00')
        for fecha, monto, tipo, modulo in (
            (date(2026, 9, 12), '10.00', 'abono', None),
            (date(2026, 9, 19), '25.00', 'solo_modulo', 1),
            (date(2026, 9, 26), '25.00', 'solo_modulo', 2),
        ):
            Abono.objects.create(
                matricula=matricula, fecha=fecha, monto=Decimal(monto),
                tipo_pago=tipo, numero_modulo=modulo, metodo='efectivo',
            )
        matricula.refresh_from_db()
        return matricula


class CursoValorAnteriorTests(ValorAnteriorBase):
    def test_valor_anterior_por_modalidad(self):
        self.assertEqual(self.curso.valor_anterior_para('presencial'), Decimal('110.00'))
        self.assertIsNone(self.curso.valor_anterior_para('online'))
        self.curso.valor_anterior_online = Decimal('0.00')
        self.assertIsNone(self.curso.valor_anterior_para('online'))

    def test_intercambiar_valores(self):
        campos = self.curso.intercambiar_valores('presencial')
        self.assertEqual(campos, ['valor_presencial', 'valor_anterior_presencial'])
        self.assertEqual(self.curso.valor_presencial, Decimal('110.00'))
        self.assertEqual(self.curso.valor_anterior_presencial, Decimal('90.00'))
        self.assertEqual(self.curso.valor_online, Decimal('60.00'))

    def test_intercambiar_sin_valor_anterior_falla(self):
        with self.assertRaises(ValueError):
            self.curso.intercambiar_valores('online')
        self.assertEqual(self.curso.valor_online, Decimal('60.00'))


class TopeModuloValor110Tests(ValorAnteriorBase):
    def test_tope_segun_el_valor_de_la_matricula(self):
        casos = [
            ('110.00', 'reserva_abono', '0.00', Decimal('25.00')),
            ('90.00', 'reserva_abono', '0.00', Decimal('20.00')),
            # Inscripción gratis guarda $10 menos: $100 es un curso de $110.
            ('100.00', 'inscripcion_gratis', '0.00', Decimal('25.00')),
            ('80.00', 'inscripcion_gratis', '0.00', Decimal('20.00')),
            # El descuento no cambia el valor del curso de la matrícula.
            ('110.00', 'reserva_abono', '15.00', Decimal('25.00')),
            ('110.00', 'reserva_modulo_1', '0.00', Decimal('25.00')),
            ('110.00', 'programa_completo', '0.00', Decimal('25.00')),
            # Cualquier otro valor sigue con el tope de $20.
            ('100.00', 'reserva_abono', '0.00', Decimal('20.00')),
            ('105.00', 'reserva_abono', '0.00', Decimal('20.00')),
            ('120.00', 'reserva_abono', '0.00', Decimal('20.00')),
        ]
        for valor, tipo, descuento, tope in casos:
            with self.subTest(valor=valor, tipo=tipo, descuento=descuento):
                matricula = self._matricula(valor, tipo, descuento)
                self.assertEqual(matricula.tope_pago_modulo, tope)

    def test_con_o_sin_valor_anterior_la_de_110_paga_hasta_25(self):
        de_110, de_90 = self._matricula('110.00'), self._matricula('90.00')
        for anterior in (None, Decimal('110.00')):
            with self.subTest(valor_anterior=anterior):
                self.curso.valor_anterior_presencial = anterior
                self.curso.save()
                self.assertEqual(
                    Matricula.objects.get(pk=de_110.pk).tope_pago_modulo, Decimal('25.00'),
                )
                self.assertEqual(
                    Matricula.objects.get(pk=de_90.pk).tope_pago_modulo, Decimal('20.00'),
                )

    def test_todos_los_de_110_con_o_sin_valor_anterior(self):
        # Todas las matrículas de $110 (no solo una) pagan hasta $25 y las de
        # $90 hasta $20, con el valor anterior vacío o en $110.
        de_110 = [
            self._matricula('110.00'),
            self._matricula('110.00', descuento='10.00'),
            self._matricula('100.00', tipo='inscripcion_gratis'),
        ]
        de_90 = self._matricula('90.00')

        def puede_pagar(monto):
            return [
                AbonoForm(
                    _pago_modulo(monto, modulo='1'),
                    matricula=Matricula.objects.get(pk=m.pk),
                ).is_valid()
                for m in de_110 + [de_90]
            ]

        for anterior in (None, Decimal('110.00')):
            with self.subTest(valor_anterior=anterior):
                self.curso.valor_anterior_presencial = anterior
                self.curso.save()
                self.assertEqual(puede_pagar('20.00'), [True, True, True, True])
                self.assertEqual(puede_pagar('20.01'), [True, True, True, False])
                self.assertEqual(puede_pagar('25.00'), [True, True, True, False])
                self.assertEqual(puede_pagar('25.01'), [False, False, False, False])

    def test_el_valor_anterior_no_da_25_si_la_matricula_no_es_de_110(self):
        otro = Curso.objects.create(
            nombre='Curso que bajó de $100', categoria=self.categoria,
            ofrece_presencial=True, valor_presencial=Decimal('90.00'),
            valor_anterior_presencial=Decimal('100.00'), numero_modulos=4,
        )
        jornada = JornadaCurso.objects.create(
            curso=otro, modalidad='presencial', descripcion='mar_jue',
            fecha_inicio=date(2026, 9, 22), sede=self.sede,
        )
        de_100 = self._matricula('100.00', curso=otro, jornada=jornada)
        self.assertTrue(de_100.tiene_valor_anterior_del_curso)
        self.assertEqual(de_100.tope_pago_modulo, Decimal('20.00'))
        # Y en Servicio Técnico, con valor anterior $110, la de $90 sigue en $20.
        self.assertEqual(self._matricula('90.00').tope_pago_modulo, Decimal('20.00'))

    def test_al_intercambiar_los_valores_las_de_110_siguen_con_veinticinco(self):
        de_110, de_90 = self._matricula('110.00'), self._matricula('90.00')
        self.curso.save(update_fields=self.curso.intercambiar_valores('presencial'))
        de_110, de_90 = Matricula.objects.get(pk=de_110.pk), Matricula.objects.get(pk=de_90.pk)
        self.assertEqual(de_110.tope_pago_modulo, Decimal('25.00'))
        self.assertFalse(de_110.tiene_valor_anterior_del_curso)
        self.assertEqual(de_90.tope_pago_modulo, Decimal('20.00'))

    def test_online_no_cambia(self):
        self.curso.valor_anterior_online = Decimal('70.00')
        self.curso.save()
        jornada = JornadaCurso.objects.create(
            curso=self.curso, modalidad='online', descripcion='mar_jue',
            fecha_inicio=date(2026, 9, 22),
        )
        for valor in ('70.00', '110.00', '60.00'):
            with self.subTest(valor=valor):
                matricula = self._matricula(valor, jornada=jornada)
                self.assertEqual(matricula.tope_pago_modulo, Decimal('25.00'))
                self.assertFalse(matricula.usa_tope_modulo_de_25)

    def test_ivan_de_90_paga_cada_modulo_hasta_20(self):
        # Como Iván: valor del curso $90, pagó la reserva de $10, saldo $80.
        matricula = self._matricula('90.00')
        Abono.objects.create(
            matricula=matricula, fecha=date(2026, 10, 4), monto=Decimal('10.00'),
            tipo_pago='abono', metodo='efectivo',
        )
        matricula.refresh_from_db()
        self.assertEqual(matricula.saldo, Decimal('80.00'))
        form = AbonoForm(_pago_modulo('20.00', modulo='1'), matricula=matricula)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.fields['monto'].widget.attrs['data-tope-modulo'], '20.00')
        for monto in ('20.01', '25.00'):
            with self.subTest(monto=monto):
                form = AbonoForm(_pago_modulo(monto, modulo='1'), matricula=matricula)
                self.assertFalse(form.is_valid())
                self.assertIn('hasta $20.00', form.errors['monto'][0])

    def test_avisos_de_110_sin_valor_anterior_y_con_inscripcion_gratis(self):
        self.curso.valor_anterior_presencial = None
        self.curso.save()
        form = AbonoForm(matricula=self._matricula('110.00'))
        self.assertEqual(
            form.fields['monto'].widget.attrs['data-tope-aviso'],
            'Máximo por módulo: $25.00 (matrícula de $110.00).',
        )
        gratis = self._matricula('100.00', tipo='inscripcion_gratis')
        form = AbonoForm(_pago_modulo('25.50', modulo='1'), matricula=gratis)
        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.fields['monto'].widget.attrs['data-tope-aviso'],
            'Máximo por módulo: $25.00 (curso de $110.00 con inscripción gratis).',
        )
        self.assertEqual(form.errors['monto'], [
            'Esta matrícula es de un curso de $110.00 con inscripción gratis: '
            'cada módulo se paga hasta $25.00. Si paga más de un módulo, '
            'registra cada módulo por separado.'
        ])

    def test_kevin_puede_pagar_el_modulo_3_a_veinticinco(self):
        matricula = self._kevin()
        form = AbonoForm(_pago_modulo('25.00'), matricula=matricula)
        self.assertTrue(form.is_valid(), form.errors)
        attrs = form.fields['monto'].widget.attrs
        self.assertEqual(attrs['data-tope-modulo'], '25.00')
        self.assertEqual(
            attrs['data-tope-aviso'],
            'Máximo por módulo: $25.00 (matrícula con el valor anterior del curso, $110.00).',
        )

        form = AbonoForm(_pago_modulo('25.01'), matricula=matricula)
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['monto'], [
            'Esta matrícula tiene el valor anterior del curso ($110.00): cada '
            'módulo se paga hasta $25.00. Si paga más de un módulo, registra '
            'cada módulo por separado.'
        ])

    def test_matricula_de_90_sigue_con_el_tope_de_veinte(self):
        matricula = self._matricula('90.00')
        form = AbonoForm(_pago_modulo('25.00', modulo='1'), matricula=matricula)
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['monto'], [
            'En Presencial cada módulo se paga hasta $20.00. Si paga más de un '
            'módulo, registra cada módulo por separado.'
        ])
        self.assertEqual(
            form.fields['monto'].widget.attrs['data-tope-aviso'],
            'Máximo por módulo en Presencial: $20.00.',
        )

    def test_cabecera_de_la_pantalla_de_pagos(self):
        self.client.force_login(self.admin)

        def pagina(matricula):
            return self.client.get(
                reverse('academia:matricula_abonos', args=[matricula.pk]),
            ).content.decode()

        de_90 = pagina(self._matricula('90.00'))
        self.assertIn('data-tope-modulo="20.00"', de_90)
        self.assertNotIn('Módulos hasta', de_90)

        self.curso.valor_anterior_presencial = None
        self.curso.save()
        de_110 = pagina(self._matricula('110.00'))
        self.assertIn('data-tope-modulo="25.00"', de_110)
        self.assertIn('Módulos hasta $25', de_110)
        self.assertNotIn('Valor anterior del curso', de_110)
        gratis = pagina(self._matricula('100.00', tipo='inscripcion_gratis'))
        self.assertIn('Curso de $110,00 con inscripción gratis · Módulos hasta $25', gratis)
        for resto in ('{#', '{%', '{{'):
            self.assertNotIn(resto, de_110)

    def test_registrar_pago_de_veinticinco_desde_gestionar_pagos(self):
        matricula = self._kevin()
        self.client.force_login(self.admin)
        pagina = self.client.get(reverse('academia:matricula_abonos', args=[matricula.pk]))
        self.assertContains(pagina, 'Valor anterior del curso · Módulos hasta $25')
        self.assertContains(pagina, 'data-tope-modulo="25.00"')

        response = self.client.post(
            reverse('academia:abono_crear', args=[matricula.pk]),
            _pago_modulo('25.00'), follow=True,
        )
        self.assertEqual(response.status_code, 200)
        matricula.refresh_from_db()
        self.assertTrue(matricula.abonos.filter(numero_modulo=3, monto=Decimal('25.00')).exists())
        self.assertEqual(matricula.valor_pagado, Decimal('85.00'))
        self.assertEqual(matricula.saldo, Decimal('25.00'))


class IntercambiarValorTests(ValorAnteriorBase):
    def _url(self):
        return reverse('academia:curso_intercambiar_valor', args=[self.curso.pk])

    def test_intercambia_y_vuelve_a_la_tarjeta(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            self._url(), {'modalidad': 'presencial', 'valor_actual': '90.00'},
        )
        self.assertRedirects(
            response,
            reverse('academia:cursos_lista', args=['presencial']) + f'#curso-{self.curso.pk}',
            fetch_redirect_response=False,
        )
        self.curso.refresh_from_db()
        self.assertEqual(self.curso.valor_presencial, Decimal('110.00'))
        self.assertEqual(self.curso.valor_anterior_presencial, Decimal('90.00'))
        self.assertEqual(self.curso.valor_online, Decimal('60.00'))

    def test_doble_clic_no_lo_vuelve_a_intercambiar(self):
        self.client.force_login(self.admin)
        datos = {'modalidad': 'presencial', 'valor_actual': '90.00'}
        self.client.post(self._url(), datos)
        response = self.client.post(self._url(), datos, follow=True)
        self.assertContains(response, 'cambiaron mientras tanto')
        self.curso.refresh_from_db()
        self.assertEqual(self.curso.valor_presencial, Decimal('110.00'))

    def test_valor_de_la_tarjeta_ilegible_no_cambia_nada(self):
        self.client.force_login(self.admin)
        for valor in ('', 'sNaN', 'NaN', 'abc'):
            with self.subTest(valor=valor):
                response = self.client.post(
                    self._url(), {'modalidad': 'presencial', 'valor_actual': valor},
                    follow=True,
                )
                self.assertContains(response, 'Recarga la página')
        self.curso.refresh_from_db()
        self.assertEqual(self.curso.valor_presencial, Decimal('90.00'))

    def test_sin_valor_anterior_no_cambia_nada(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            self._url(), {'modalidad': 'online', 'valor_actual': '60.00'}, follow=True,
        )
        self.assertContains(response, 'no tiene valor anterior')
        self.curso.refresh_from_db()
        self.assertEqual(self.curso.valor_online, Decimal('60.00'))

    def test_solo_por_post_y_con_permiso_de_editar_cursos(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self._url()).status_code, 405)

        asesora = User.objects.create_user('asesora_valor_anterior')
        asesora.groups.add(Group.objects.get_or_create(name=GRUPO_ASESOR)[0])
        self.client.force_login(asesora)
        self.client.post(self._url(), {'modalidad': 'presencial', 'valor_actual': '90.00'})
        self.curso.refresh_from_db()
        self.assertEqual(self.curso.valor_presencial, Decimal('90.00'))

    def test_lista_de_cursos_muestra_el_valor_anterior(self):
        url = reverse('academia:cursos_lista', args=['presencial'])
        self.client.force_login(self.admin)
        html = self.client.get(url).content.decode()
        self.assertIn('Valor anterior: <strong>$110,00</strong>', html)
        self.assertIn(self._url(), html)
        self.assertIn('name="valor_actual" value="90.00"', html)
        for resto in ('{#', '{%', '{{'):
            self.assertNotIn(resto, html)

        # La asesora ve el valor anterior, pero no la flecha.
        asesora = User.objects.create_user('asesora_lista_valor')
        asesora.groups.add(Group.objects.get_or_create(name=GRUPO_ASESOR)[0])
        self.client.force_login(asesora)
        html = self.client.get(url).content.decode()
        self.assertIn('Valor anterior: <strong>$110,00</strong>', html)
        self.assertNotIn(self._url(), html)

        # En Online el curso no tiene valor anterior.
        self.client.force_login(self.admin)
        html = self.client.get(reverse('academia:cursos_lista', args=['online'])).content.decode()
        self.assertNotIn('Valor anterior:', html)

    def test_al_matricular_solo_se_usa_el_valor_principal(self):
        self.client.force_login(self.admin)
        datos = self.client.get(
            reverse('academia:api_curso_detalle', args=[self.curso.pk]),
            {'modalidad': 'presencial'},
        ).json()['curso']
        self.assertEqual(datos['valor'], '90.00')
        self.assertNotIn('110', str(datos))


class CursoFormValorAnteriorTests(ValorAnteriorBase):
    def _datos(self, **overrides):
        return {
            'categoria': str(self.categoria.pk), 'nombre': 'Curso con valor anterior',
            'descripcion': '', 'ofrece_presencial': 'on', 'valor_presencial': '90.00',
            'valor_anterior_presencial': '110.00', 'valor_online': '0.00',
            'valor_anterior_online': '', 'duracion': '', 'numero_modulos': '4',
            'numero_modulos_online': '2', 'activo': 'on',
            **overrides,
        }

    def test_guarda_el_valor_anterior(self):
        form = CursoForm(self._datos())
        self.assertTrue(form.is_valid(), form.errors)
        curso = form.save()
        self.assertEqual(curso.valor_anterior_presencial, Decimal('110.00'))
        self.assertIsNone(curso.valor_anterior_online)

    def test_vaciar_el_valor_anterior_lo_quita(self):
        form = CursoForm(self._datos(valor_anterior_presencial=''), instance=self.curso)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.save().valor_anterior_presencial)
        # El tope no depende del valor anterior: $110 → $25 y $90 → $20.
        self.assertEqual(self._matricula('110.00').tope_pago_modulo, Decimal('25.00'))
        self.assertEqual(self._matricula('90.00').tope_pago_modulo, Decimal('20.00'))

    def test_cero_es_lo_mismo_que_vacio(self):
        form = CursoForm(self._datos(valor_anterior_presencial='0'))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.save().valor_anterior_presencial)

    def test_no_acepta_igual_al_principal_ni_negativo(self):
        form = CursoForm(self._datos(valor_anterior_presencial='90.00'))
        self.assertFalse(form.is_valid())
        self.assertIn('Es igual al valor principal', form.errors['valor_anterior_presencial'][0])
        form = CursoForm(self._datos(valor_anterior_presencial='-5'))
        self.assertFalse(form.is_valid())
        self.assertIn('valor_anterior_presencial', form.errors)

    def test_pantalla_editar_muestra_los_campos(self):
        self.client.force_login(self.admin)
        html = self.client.get(
            reverse('academia:curso_editar', args=[self.curso.pk]),
        ).content.decode()
        self.assertIn('Valor anterior presencial (USD)', html)
        self.assertIn('name="valor_anterior_presencial"', html)
        self.assertIn('value="110.00"', html)
        self.assertIn('data-intercambiar-valor', html)
        for resto in ('{#', '{%', '{{'):
            self.assertNotIn(resto, html)
