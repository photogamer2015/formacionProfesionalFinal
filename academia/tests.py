from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth.models import Group, User
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import AbonoForm, AdicionalSupletorioRapidoForm
from .models import Abono, Curso, Estudiante, JornadaCurso, Matricula
from .permisos import puede_gestionar_jornadas, puede_ver_jornadas
from .views import _registrar_pago_inicial
from .views_pagos import _hojas_recaudacion_data, _plan_recaudacion_matricula


class SessionKeepaliveTests(TestCase):
    def test_keepalive_requiere_login(self):
        response = self.client.get(reverse('academia:session_keepalive'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])

    def test_keepalive_refresca_sesion_autenticada(self):
        usuario = User.objects.create_user(username='soporte', password='clave12345')
        self.client.force_login(usuario)

        response = self.client.get(reverse('academia:session_keepalive'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'ok': True})


class JornadaMatriculasAccessTests(TestCase):
    def setUp(self):
        self.asesor = User.objects.create_user(username='asesor')
        grupo = Group.objects.create(name='Asesores')
        self.asesor.groups.add(grupo)
        self.curso = Curso.objects.create(
            nombre='Curso Jornadas Test',
            ofrece_presencial=True,
            valor_presencial=Decimal('100.00'),
        )
        self.jornada_1 = JornadaCurso.objects.create(
            curso=self.curso,
            modalidad='presencial',
            descripcion='lun_mie_vie',
            fecha_inicio=date(2026, 7, 5),
        )
        self.jornada_2 = JornadaCurso.objects.create(
            curso=self.curso,
            modalidad='presencial',
            descripcion='mar_jue',
            fecha_inicio=date(2026, 7, 6),
        )
        self.estudiante_1 = Estudiante.objects.create(
            cedula='1207342716',
            nombres='Estudiante Jornada Uno',
        )
        self.estudiante_2 = Estudiante.objects.create(
            cedula='1207342717',
            nombres='Estudiante Jornada Dos',
        )
        Matricula.objects.create(
            estudiante=self.estudiante_1,
            curso=self.curso,
            jornada=self.jornada_1,
            modalidad='presencial',
            fecha_matricula=date(2026, 7, 5),
            valor_curso=Decimal('100.00'),
            valor_pagado=Decimal('100.00'),
            tipo_registro='central_ia',
            registrado_por=self.asesor,
        )
        Matricula.objects.create(
            estudiante=self.estudiante_2,
            curso=self.curso,
            jornada=self.jornada_2,
            modalidad='presencial',
            fecha_matricula=date(2026, 7, 5),
            valor_curso=Decimal('100.00'),
            valor_pagado=Decimal('100.00'),
            tipo_registro='central_ia',
            registrado_por=self.asesor,
        )

    def test_asesor_puede_ver_panel_de_jornadas(self):
        self.assertTrue(puede_ver_jornadas(self.asesor))
        self.assertTrue(puede_gestionar_jornadas(self.asesor))

    def test_lista_matriculas_filtra_por_jornada(self):
        self.client.force_login(self.asesor)

        response = self.client.get(
            reverse('academia:matricula_lista', kwargs={'modalidad': 'presencial'}),
            {'jornada': str(self.jornada_1.id)},
        )

        self.assertEqual(response.status_code, 200)
        matriculas = list(response.context['matriculas'])
        self.assertEqual(len(matriculas), 1)
        self.assertEqual(matriculas[0].estudiante, self.estudiante_1)
        self.assertEqual(response.context['jornada_filtrada'], self.jornada_1)

    def test_listas_muestran_ultimo_registro_primero_aunque_fecha_sea_anterior(self):
        self.client.force_login(self.asesor)
        vieja = Matricula.objects.get(estudiante=self.estudiante_1)
        nueva = Matricula.objects.get(estudiante=self.estudiante_2)
        ahora = timezone.now()
        Matricula.objects.filter(pk=vieja.pk).update(
            fecha_matricula=date(2026, 7, 6),
            creado=ahora - timezone.timedelta(minutes=10),
        )
        Matricula.objects.filter(pk=nueva.pk).update(
            fecha_matricula=date(2026, 7, 1),
            creado=ahora,
        )

        matricula_response = self.client.get(
            reverse('academia:matricula_lista', kwargs={'modalidad': 'presencial'})
        )
        pagos_response = self.client.get(reverse('academia:pagos_lista'))

        self.assertEqual(matricula_response.status_code, 200)
        self.assertEqual(pagos_response.status_code, 200)
        self.assertEqual(
            list(matricula_response.context['matriculas'])[0].estudiante,
            self.estudiante_2,
        )
        self.assertEqual(pagos_response.context['matriculas'][0].estudiante, self.estudiante_2)


class PagoInicialMatriculaTests(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user(username='soporte')
        self.curso = Curso.objects.create(
            nombre='Curso Técnico',
            ofrece_presencial=True,
            valor_presencial=Decimal('115.00'),
            numero_modulos=4,
        )
        self.jornada = JornadaCurso.objects.create(
            curso=self.curso,
            modalidad='presencial',
            descripcion='lun_mie_vie',
            fecha_inicio=date(2026, 7, 5),
        )
        self.estudiante = Estudiante.objects.create(
            cedula='1207342716',
            nombres='Gianny Guevara',
        )

    def _mat_form(self, modulos_a_pagar=1, **overrides):
        data = {
            'tipo_cobro': 'un_solo_metodo',
            'metodo_pago': 'efectivo',
            'banco': '',
            'monto_pago_1': Decimal('0.00'),
            'metodo_pago_1': 'efectivo',
            'banco_1': '',
            'monto_pago_2': Decimal('0.00'),
            'metodo_pago_2': 'efectivo',
            'banco_2': '',
            'modulos_a_pagar': modulos_a_pagar,
        }
        data.update(overrides)
        return SimpleNamespace(cleaned_data=data)

    def test_reserva_modulo_respeta_valor_pagado_digitado(self):
        matricula = Matricula.objects.create(
            estudiante=self.estudiante,
            curso=self.curso,
            jornada=self.jornada,
            modalidad='presencial',
            tipo_matricula='reserva_modulo_1',
            forma_pago='abono_modulo',
            fecha_matricula=date(2026, 7, 5),
            valor_curso=Decimal('115.00'),
            valor_pagado=Decimal('50.00'),
            tipo_registro='central_ia',
            registrado_por=self.usuario,
        )

        _registrar_pago_inicial(matricula, self.usuario, self._mat_form())

        matricula.refresh_from_db()
        abono = Abono.objects.get(matricula=matricula)
        self.assertEqual(matricula.valor_pagado, Decimal('50.00'))
        self.assertEqual(matricula.saldo, Decimal('65.00'))
        self.assertEqual(abono.monto, Decimal('50.00'))
        self.assertEqual(abono.numero_modulo, 1)
        self.assertEqual(abono.tipo_pago, 'por_modulo')

    def test_reserva_modulo_reparte_monto_real_si_hay_varios_modulos(self):
        matricula = Matricula.objects.create(
            estudiante=self.estudiante,
            curso=self.curso,
            jornada=self.jornada,
            modalidad='presencial',
            tipo_matricula='reserva_modulo_1',
            forma_pago='abono_modulo',
            fecha_matricula=date(2026, 7, 5),
            valor_curso=Decimal('115.00'),
            valor_pagado=Decimal('50.00'),
            tipo_registro='central_ia',
            registrado_por=self.usuario,
        )

        _registrar_pago_inicial(matricula, self.usuario, self._mat_form(modulos_a_pagar=2))

        matricula.refresh_from_db()
        montos = list(
            Abono.objects.filter(matricula=matricula)
            .order_by('numero_modulo')
            .values_list('monto', flat=True)
        )
        self.assertEqual(matricula.valor_pagado, Decimal('50.00'))
        self.assertEqual(montos, [Decimal('26.25'), Decimal('23.75')])

    def test_reserva_modulo_mixto_conserva_montos_por_metodo(self):
        curso = Curso.objects.create(
            nombre='Curso Mixto',
            ofrece_presencial=True,
            valor_presencial=Decimal('110.00'),
            numero_modulos=4,
        )
        jornada = JornadaCurso.objects.create(
            curso=curso,
            modalidad='presencial',
            descripcion='lun_mie_vie',
            fecha_inicio=date(2026, 7, 8),
        )
        estudiante = Estudiante.objects.create(
            cedula='1207342717',
            nombres='Randy Mixto',
        )
        matricula = Matricula.objects.create(
            estudiante=estudiante,
            curso=curso,
            jornada=jornada,
            modalidad='presencial',
            tipo_matricula='reserva_modulo_1',
            forma_pago='abono_modulo',
            fecha_matricula=date(2026, 7, 8),
            valor_curso=Decimal('110.00'),
            valor_pagado=Decimal('40.00'),
            tipo_registro='central_ia',
            registrado_por=self.usuario,
        )

        _registrar_pago_inicial(
            matricula,
            self.usuario,
            self._mat_form(
                tipo_cobro='mixto',
                metodo_pago='efectivo',
                banco='',
                monto_pago_1=Decimal('20.00'),
                metodo_pago_1='efectivo',
                banco_1='',
                monto_pago_2=Decimal('20.00'),
                metodo_pago_2='transferencia',
                banco_2='guayaquil',
            ),
        )

        abono = Abono.objects.get(matricula=matricula)
        self.assertEqual(abono.monto, Decimal('40.00'))
        self.assertEqual(abono.monto_2, Decimal('20.00'))
        self.assertEqual(abono.metodo, 'efectivo')
        self.assertEqual(abono.metodo_2, 'transferencia')

        request = RequestFactory().get('/pagos/hoja-recaudacion/', {
            'fecha': '2026-07-08',
            'curso': str(curso.id),
        })
        hojas, _filtros = _hojas_recaudacion_data(request)

        self.assertEqual(hojas[0]['total_efectivo'], Decimal('20.00'))
        self.assertEqual(hojas[0]['total_transferencia'], Decimal('20.00'))

    def _abono_data(self, **overrides):
        data = {
            'fecha': '2026-07-06',
            'monto': '25.00',
            'tipo_pago': 'solo_modulo',
            'numero_modulo': '1',
            'cuenta_para_saldo': 'True',
            'metodo': 'efectivo',
            'banco': '',
            'numero_recibo': '',
            'observaciones': '',
            'tipo_cobro': 'mixto',
            'monto_pago_1': '10.00',
            'metodo_pago_1': 'efectivo',
            'banco_1': '',
            'monto_pago_2': '15.00',
            'metodo_pago_2': 'efectivo',
            'banco_2': '',
        }
        data.update(overrides)
        return data

    def test_abono_mixto_rechaza_suma_distinta_al_monto_principal(self):
        matricula = Matricula.objects.create(
            estudiante=self.estudiante,
            curso=self.curso,
            jornada=self.jornada,
            modalidad='presencial',
            tipo_matricula='reserva_modulo_1',
            forma_pago='abono_modulo',
            fecha_matricula=date(2026, 7, 5),
            valor_curso=Decimal('115.00'),
            valor_pagado=Decimal('40.00'),
            tipo_registro='central_ia',
            registrado_por=self.usuario,
        )

        form = AbonoForm(
            self._abono_data(
                monto='25.00',
                monto_pago_1='15.00',
                monto_pago_2='15.00',
            ),
            matricula=matricula,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('monto_pago_2', form.errors)

    def test_abono_mixto_acepta_suma_igual_al_monto_principal(self):
        matricula = Matricula.objects.create(
            estudiante=self.estudiante,
            curso=self.curso,
            jornada=self.jornada,
            modalidad='presencial',
            tipo_matricula='reserva_modulo_1',
            forma_pago='abono_modulo',
            fecha_matricula=date(2026, 7, 5),
            valor_curso=Decimal('115.00'),
            valor_pagado=Decimal('40.00'),
            tipo_registro='central_ia',
            registrado_por=self.usuario,
        )

        form = AbonoForm(self._abono_data(), matricula=matricula)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['monto'], Decimal('25.00'))
        self.assertEqual(form.cleaned_data['monto_pago_1'], Decimal('10.00'))
        self.assertEqual(form.cleaned_data['monto_pago_2'], Decimal('15.00'))

    def _supletorio_data(self, **overrides):
        data = {
            'numero_modulo': '1',
            'fecha': '2026-07-06',
            'valor': '20.00',
            'metodo_pago': 'efectivo',
            'banco': '',
            'tipo_cobro': 'mixto',
            'monto_pago_1': '10.00',
            'metodo_pago_1': 'efectivo',
            'banco_1': '',
            'monto_pago_2': '10.00',
            'metodo_pago_2': 'efectivo',
            'banco_2': '',
            'numero_recibo': '',
            'observaciones': '',
        }
        data.update(overrides)
        return data

    def test_supletorio_rapido_mixto_rechaza_suma_distinta_al_valor(self):
        matricula = Matricula.objects.create(
            estudiante=self.estudiante,
            curso=self.curso,
            jornada=self.jornada,
            modalidad='presencial',
            tipo_matricula='reserva_abono',
            forma_pago='abono',
            fecha_matricula=date(2026, 7, 5),
            valor_curso=Decimal('115.00'),
            valor_pagado=Decimal('40.00'),
            tipo_registro='central_ia',
            registrado_por=self.usuario,
        )

        form = AdicionalSupletorioRapidoForm(
            self._supletorio_data(
                valor='20.00',
                monto_pago_1='15.00',
                monto_pago_2='10.00',
            ),
            matricula=matricula,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('monto_pago_2', form.errors)

    def test_supletorio_rapido_mixto_acepta_suma_igual_al_valor(self):
        matricula = Matricula.objects.create(
            estudiante=self.estudiante,
            curso=self.curso,
            jornada=self.jornada,
            modalidad='presencial',
            tipo_matricula='reserva_abono',
            forma_pago='abono',
            fecha_matricula=date(2026, 7, 5),
            valor_curso=Decimal('115.00'),
            valor_pagado=Decimal('40.00'),
            tipo_registro='central_ia',
            registrado_por=self.usuario,
        )

        form = AdicionalSupletorioRapidoForm(self._supletorio_data(), matricula=matricula)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['tipo_cobro'], 'mixto')
        self.assertEqual(form.cleaned_data['monto_pago_1'], Decimal('10.00'))
        self.assertEqual(form.cleaned_data['monto_pago_2'], Decimal('10.00'))


class PlanRecaudacionTests(TestCase):
    def setUp(self):
        self._seq = 0

    def _matricula_con_adelanto(self, valor_curso, adelanto, semanas, modalidad='presencial'):
        self._seq += 1
        curso = Curso.objects.create(
            nombre=f'Curso Recaudación Test {self._seq}',
            ofrece_presencial=True,
            ofrece_online=True,
            valor_presencial=valor_curso,
            valor_online=valor_curso,
            numero_modulos=semanas,
            numero_modulos_online=semanas,
        )
        jornada = JornadaCurso.objects.create(
            curso=curso,
            modalidad=modalidad,
            descripcion='domingos_intensivos' if modalidad == 'presencial' else 'mar_mie_jue',
            fecha_inicio=date(2026, 7, 8),
        )
        estudiante = Estudiante.objects.create(
            cedula=f'09{self._seq:08d}',
            nombres=f'Estudiante Recaudación {self._seq}',
        )
        matricula = Matricula.objects.create(
            estudiante=estudiante,
            curso=curso,
            jornada=jornada,
            modalidad=modalidad,
            tipo_matricula='reserva_abono',
            forma_pago='abono',
            fecha_matricula=date(2026, 7, 8),
            valor_curso=valor_curso,
            valor_pagado=Decimal('0.00'),
            tipo_registro='central_ia',
        )
        Abono.objects.create(
            matricula=matricula,
            fecha=date(2026, 7, 8),
            monto=adelanto,
            tipo_pago='abono',
        )
        matricula.refresh_from_db()
        return matricula

    def _assert_plan(self, matricula, saldo_esperado, cuotas_esperadas, modulo_esperado=1):
        plan = _plan_recaudacion_matricula(matricula)
        self.assertEqual(plan['saldo_pendiente'], saldo_esperado)
        self.assertEqual(plan['cuotas'], cuotas_esperadas)
        self.assertEqual(sum(plan['cuotas'], Decimal('0.00')), saldo_esperado)
        self.assertEqual(plan['cuota_sugerida'], cuotas_esperadas[0])
        self.assertEqual(plan['modulo'], modulo_esperado)

    def test_presencial_90_reserva_10_en_4_semanas(self):
        matricula = self._matricula_con_adelanto(
            Decimal('90.00'), Decimal('10.00'), 4
        )

        self._assert_plan(matricula, Decimal('80.00'), [
            Decimal('20.00'), Decimal('20.00'),
            Decimal('20.00'), Decimal('20.00'),
        ])

    def test_virtual_60_reserva_10_en_4_semanas(self):
        matricula = self._matricula_con_adelanto(
            Decimal('60.00'), Decimal('10.00'), 4, modalidad='online'
        )

        self._assert_plan(matricula, Decimal('50.00'), [
            Decimal('12.50'), Decimal('12.50'),
            Decimal('12.50'), Decimal('12.50'),
        ])

    def test_curso_110_reserva_10_en_4_semanas(self):
        matricula = self._matricula_con_adelanto(
            Decimal('110.00'), Decimal('10.00'), 4
        )

        self._assert_plan(matricula, Decimal('100.00'), [
            Decimal('25.00'), Decimal('25.00'),
            Decimal('25.00'), Decimal('25.00'),
        ])

    def test_curso_110_adelanto_35_en_4_semanas(self):
        matricula = self._matricula_con_adelanto(
            Decimal('110.00'), Decimal('35.00'), 4
        )

        # Pagó $35: cubre el módulo 1 ($27.50). $75 ÷ 3 = $25.00 exacto.
        self._assert_plan(matricula, Decimal('75.00'), [
            Decimal('25.00'), Decimal('25.00'), Decimal('25.00'),
        ], modulo_esperado=2)

    def test_curso_110_adelanto_40_cubre_una_semana_y_reparte_en_3(self):
        matricula = self._matricula_con_adelanto(
            Decimal('110.00'), Decimal('40.00'), 4
        )

        # Caso Melanie: $110 en 4 semanas, pagó $40 en matrícula
        # (reserva $10 + módulo 1 $25 + abono $5). Cubrió la semana 1 →
        # $70 ÷ 3 semanas restantes = $23.33 → $23.00 (redondeo abajo a
        # $0.50) y la última cuota absorbe el residuo. Suma exacta: $70.
        self._assert_plan(matricula, Decimal('70.00'), [
            Decimal('23.00'), Decimal('23.00'), Decimal('24.00'),
        ], modulo_esperado=2)

    def test_estudiante_que_paga_menos_sube_la_ultima_cuota(self):
        matricula = self._matricula_con_adelanto(
            Decimal('110.00'), Decimal('40.00'), 4
        )
        Abono.objects.create(
            matricula=matricula,
            fecha=date(2026, 7, 15),
            monto=Decimal('20.00'),
            tipo_pago='abono',
        )
        matricula.refresh_from_db()

        self._assert_plan(matricula, Decimal('50.00'), [
            Decimal('25.00'), Decimal('25.00'),
        ], modulo_esperado=3)

        Abono.objects.create(
            matricula=matricula,
            fecha=date(2026, 7, 22),
            monto=Decimal('20.00'),
            tipo_pago='abono',
        )
        matricula.refresh_from_db()

        # Pagó $80 acumulados: cubre 2 módulos ($27.50 c/u; el 3.º pide
        # $82.50). Saldo $30 ÷ 2 semanas restantes = $15.00 / $15.00.
        self._assert_plan(matricula, Decimal('30.00'), [
            Decimal('15.00'), Decimal('15.00'),
        ], modulo_esperado=3)

    def test_estudiante_que_paga_de_mas_deja_ultima_cuota_menor(self):
        matricula = self._matricula_con_adelanto(
            Decimal('110.00'), Decimal('10.00'), 4
        )
        Abono.objects.create(
            matricula=matricula,
            fecha=date(2026, 7, 15),
            monto=Decimal('40.00'),
            tipo_pago='abono',
        )
        matricula.refresh_from_db()

        # Excepción del que paga de más: pagó $50, cubre el módulo 1.
        # Saldo $60 ÷ 3 semanas restantes → las cuotas futuras BAJAN.
        self._assert_plan(matricula, Decimal('60.00'), [
            Decimal('20.00'), Decimal('20.00'), Decimal('20.00'),
        ], modulo_esperado=2)

        for idx in range(2):
            Abono.objects.create(
                matricula=matricula,
                fecha=date(2026, 7, 22 + idx * 7),
                monto=Decimal('25.00'),
                tipo_pago='abono',
            )
        matricula.refresh_from_db()

        self._assert_plan(matricula, Decimal('10.00'), [
            Decimal('10.00'),
        ], modulo_esperado=4)

    def test_cuota_nunca_supera_saldo_pendiente(self):
        matricula = self._matricula_con_adelanto(
            Decimal('110.00'), Decimal('100.00'), 4
        )

        self._assert_plan(matricula, Decimal('10.00'), [
            Decimal('10.00'),
        ], modulo_esperado=4)

    def test_pagos_exactos_de_cuotas_terminan_en_saldo_cero(self):
        matricula = self._matricula_con_adelanto(
            Decimal('110.00'), Decimal('10.00'), 4
        )
        for idx in range(4):
            Abono.objects.create(
                matricula=matricula,
                fecha=date(2026, 7, 15 + idx),
                monto=Decimal('25.00'),
                tipo_pago='abono',
            )
        matricula.refresh_from_db()

        plan = _plan_recaudacion_matricula(matricula)
        self.assertEqual(matricula.saldo, Decimal('0.00'))
        self.assertEqual(plan['saldo_pendiente'], Decimal('0.00'))
        self.assertEqual(sum(plan['cuotas'], Decimal('0.00')), Decimal('0.00'))
        self.assertEqual(plan['cuota_sugerida'], Decimal('0.00'))
