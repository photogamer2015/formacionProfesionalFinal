from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import AbonoForm, AdicionalSupletorioRapidoForm
from .models import Abono, Curso, Estudiante, JornadaCurso, Matricula
from .permisos import puede_gestionar_jornadas, puede_ver_jornadas
from .views import _registrar_pago_inicial


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

    def _mat_form(self, modulos_a_pagar=1):
        return SimpleNamespace(cleaned_data={
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
        })

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
        self.assertEqual(montos, [Decimal('28.75'), Decimal('21.25')])

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
