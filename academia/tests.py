from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth.models import Group, User
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import AbonoForm, AdicionalSupletorioRapidoForm
from .models import (
    Abono, Adicional, AdicionalArchivado, CierreCurso, Comprobante, Curso,
    Estudiante, EstudianteArchivado, JornadaCurso, Matricula,
    MatriculaArchivada, PersonaExterna,
)
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

    def test_lista_matriculas_busqueda_ignora_tildes(self):
        self.estudiante_1.nombres = 'Osmár Jornada Uno'
        self.estudiante_1.save(update_fields=['nombres'])
        self.client.force_login(self.asesor)

        response = self.client.get(
            reverse('academia:matricula_lista', kwargs={'modalidad': 'presencial'}),
            {'q': 'Osmar'},
        )

        self.assertEqual(response.status_code, 200)
        matriculas = list(response.context['matriculas'])
        self.assertEqual(len(matriculas), 1)
        self.assertEqual(matriculas[0].estudiante, self.estudiante_1)

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


class BusquedaSinTildesTests(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user(username='asesor_busqueda')
        grupo = Group.objects.create(name='Asesores')
        self.usuario.groups.add(grupo)
        self.client.force_login(self.usuario)

        self.curso = Curso.objects.create(
            nombre='Técnico Contable',
            ofrece_presencial=True,
            valor_presencial=Decimal('100.00'),
        )
        self.estudiante = Estudiante.objects.create(
            cedula='1207342716',
            nombres='Osmár Dahmér',
            correo='osmar@example.com',
            celular='0999999999',
        )
        self.matricula = Matricula.objects.create(
            estudiante=self.estudiante,
            curso=self.curso,
            modalidad='presencial',
            fecha_matricula=date(2026, 7, 10),
            valor_curso=Decimal('100.00'),
            valor_pagado=Decimal('20.00'),
            tipo_registro='central_ia',
            registrado_por=self.usuario,
        )
        self.persona_externa = PersonaExterna.objects.create(
            cedula='0912345678',
            nombres='Jeffrey Dahmér',
        )
        self.adicional = Adicional.objects.create(
            tipo_adicional='cert_antiguo',
            persona_externa=self.persona_externa,
            curso=self.curso,
            modalidad='presencial',
            fecha=date(2026, 7, 10),
            valor=Decimal('10.00'),
        )
        self.cierre = CierreCurso.objects.create(
            curso=self.curso,
            curso_nombre='Técnico Contable',
            jornada_modalidad='presencial',
            alcance='curso',
            total_matriculas=1,
        )
        self.estudiante_archivado = EstudianteArchivado.objects.create(
            cierre=self.cierre,
            estudiante_original_id=self.estudiante.pk,
            cedula='1207342717',
            nombres='Jazzyel Kleinér',
            correo='jazzy@example.com',
            celular='0888888888',
        )
        self.adicional_archivado = AdicionalArchivado.objects.create(
            cierre=self.cierre,
            tipo_adicional='cert_antiguo',
            tipo_adicional_label='Certificado antiguo',
            persona_nombre='Jazzyel Kleinér',
            persona_cedula='1207342717',
            curso_nombre='Técnico Contable',
            fecha=date(2026, 7, 10),
            valor=Decimal('10.00'),
            metodo_pago='efectivo',
        )

    def test_estudiantes_filtra_nombre_sin_tildes(self):
        response = self.client.get(reverse('academia:estudiantes_lista'), {'q': 'Osmar Dahmer'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['estudiantes']), [self.estudiante])

    def test_pagos_filtra_curso_sin_tildes(self):
        response = self.client.get(reverse('academia:pagos_lista'), {'q': 'Tecnico'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['matriculas'][0].pk, self.matricula.pk)

    def test_historial_filtra_nombre_sin_tildes(self):
        response = self.client.get(reverse('academia:historial_lista'), {'q': 'Osmar'})

        self.assertEqual(response.status_code, 200)
        matriculas = response.context['estructura'][0]['meses'][0]['matriculas']
        self.assertEqual([m.pk for m in matriculas], [self.matricula.pk])

    def test_estudiantes_archivados_filtra_nombre_sin_tildes(self):
        response = self.client.get(reverse('academia:estudiantes_archivados_lista'), {'q': 'Kleiner'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['estudiantes']), [self.estudiante_archivado])

    def test_adicional_filtra_persona_externa_sin_tildes(self):
        response = self.client.get(reverse('academia:adicional_lista'), {'q': 'Jeffrey Dahmer'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['adicionales']), [self.adicional])

    def test_adicional_archivado_filtra_nombre_sin_tildes(self):
        response = self.client.get(reverse('academia:adicionales_archivados_lista'), {'q': 'Kleiner'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['adicionales']), [self.adicional_archivado])


class CierreCursoManualTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='admin_cierre',
            email='admin@example.com',
            password='clave-admin-123',
        )
        self.client.force_login(self.admin)
        self.curso = Curso.objects.create(
            nombre='Asistente Contable Cierre Manual Test',
            ofrece_presencial=True,
            valor_presencial=Decimal('100.00'),
        )
        self.jornada_1 = JornadaCurso.objects.create(
            curso=self.curso,
            modalidad='presencial',
            descripcion='lun_mie_vie',
            fecha_inicio=date(2026, 8, 1),
            ciudad='Guayaquil',
        )
        self.jornada_2 = JornadaCurso.objects.create(
            curso=self.curso,
            modalidad='presencial',
            descripcion='mar_jue',
            fecha_inicio=date(2026, 8, 2),
            ciudad='Guayaquil',
        )
        self.estudiante_1 = Estudiante.objects.create(
            cedula='000001',
            nombres='Osmár Manual',
            celular='0991111111',
        )
        self.estudiante_2 = Estudiante.objects.create(
            cedula='000002',
            nombres='Estudiante Otra Jornada',
            celular='0992222222',
        )
        self.matricula_1 = Matricula.objects.create(
            estudiante=self.estudiante_1,
            curso=self.curso,
            jornada=self.jornada_1,
            modalidad='presencial',
            fecha_matricula=date(2026, 8, 10),
            valor_curso=Decimal('100.00'),
            valor_pagado=Decimal('30.00'),
            tipo_registro='central_ia',
            registrado_por=self.admin,
        )
        self.matricula_2 = Matricula.objects.create(
            estudiante=self.estudiante_2,
            curso=self.curso,
            jornada=self.jornada_2,
            modalidad='presencial',
            fecha_matricula=date(2026, 8, 10),
            valor_curso=Decimal('100.00'),
            valor_pagado=Decimal('100.00'),
            tipo_registro='central_ia',
            registrado_por=self.admin,
        )

    def test_preview_busca_matricula_manual_por_nombre_sin_tilde(self):
        response = self.client.get(
            reverse('academia:cierre_preview', kwargs={'curso_pk': self.curso.pk}),
            {'archivo_mes': '8', 'archivo_anio': '2026', 'manual_q': 'Osmar'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Cierre manual por estudiante')
        self.assertEqual(list(response.context['manual_matriculas']), [self.matricula_1])

    def test_cierre_por_jornada_no_archiva_otras_jornadas(self):
        response = self.client.post(
            reverse('academia:cierre_ejecutar', kwargs={'curso_pk': self.curso.pk}),
            {
                'jornada_id': str(self.jornada_1.pk),
                'archivo_mes': '8',
                'archivo_anio': '2026',
                'admin_password': 'clave-admin-123',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Matricula.objects.filter(pk=self.matricula_1.pk).exists())
        self.assertTrue(Matricula.objects.filter(pk=self.matricula_2.pk).exists())

        cierre = CierreCurso.objects.get()
        self.assertEqual(cierre.alcance, 'jornada')
        self.assertEqual(cierre.jornada, self.jornada_1)
        self.assertEqual(cierre.total_matriculas, 1)
        self.assertEqual(cierre.matriculas_archivadas.count(), 1)

    def test_cierre_manual_estudiante_archiva_solo_esa_matricula(self):
        Abono.objects.create(
            matricula=self.matricula_1,
            fecha=date(2026, 8, 10),
            monto=Decimal('30.00'),
            tipo_pago='abono',
            metodo='efectivo',
            registrado_por=self.admin,
        )

        response = self.client.post(
            reverse(
                'academia:cierre_manual_estudiante_ejecutar',
                kwargs={'curso_pk': self.curso.pk, 'matricula_pk': self.matricula_1.pk},
            ),
            {
                'archivo_mes': '8',
                'archivo_anio': '2026',
                'admin_password': 'clave-admin-123',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Matricula.objects.filter(pk=self.matricula_1.pk).exists())
        self.assertTrue(Matricula.objects.filter(pk=self.matricula_2.pk).exists())

        cierre = CierreCurso.objects.get()
        self.assertEqual(cierre.alcance, 'manual')
        self.assertEqual(cierre.total_matriculas, 1)
        self.assertEqual(cierre.total_estudiantes_archivados, 1)
        self.assertFalse(cierre.limpio_directorio)

        archivada = MatriculaArchivada.objects.get(cierre=cierre)
        self.assertEqual(archivada.matricula_original_id, self.matricula_1.pk)
        self.assertEqual(archivada.nombre_completo, 'Osmár Manual')
        self.assertEqual(archivada.abonos_archivados.count(), 1)

        estudiante_archivado = EstudianteArchivado.objects.get(cierre=cierre)
        self.assertEqual(estudiante_archivado.estudiante_original_id, self.estudiante_1.pk)
        self.assertEqual(estudiante_archivado.nombre_completo, 'Osmár Manual')
        self.assertTrue(Estudiante.objects.filter(pk=self.estudiante_1.pk).exists())

    def test_cierre_manual_con_limpieza_quita_estudiante_sin_matriculas_vivas(self):
        response = self.client.post(
            reverse(
                'academia:cierre_manual_estudiante_ejecutar',
                kwargs={'curso_pk': self.curso.pk, 'matricula_pk': self.matricula_1.pk},
            ),
            {
                'archivo_mes': '8',
                'archivo_anio': '2026',
                'admin_password': 'clave-admin-123',
                'limpiar_directorio': 'on',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Matricula.objects.filter(pk=self.matricula_1.pk).exists())
        self.assertFalse(Estudiante.objects.filter(pk=self.estudiante_1.pk).exists())
        self.assertTrue(Matricula.objects.filter(pk=self.matricula_2.pk).exists())

        cierre = CierreCurso.objects.get()
        self.assertEqual(cierre.alcance, 'manual')
        self.assertEqual(cierre.total_estudiantes_archivados, 1)
        self.assertTrue(cierre.limpio_directorio)

        estudiante_archivado = EstudianteArchivado.objects.get(cierre=cierre)
        self.assertEqual(estudiante_archivado.nombre_completo, 'Osmár Manual')


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

    def test_hoja_recaudacion_separa_jornadas_del_mismo_curso(self):
        segunda_jornada = JornadaCurso.objects.create(
            curso=self.curso,
            modalidad='presencial',
            descripcion='mar_jue',
            fecha_inicio=date(2026, 8, 15),
        )
        segundo_estudiante = Estudiante.objects.create(
            cedula='1207342799',
            nombres='Estudiante Segunda Jornada',
        )
        Matricula.objects.create(
            estudiante=self.estudiante,
            curso=self.curso,
            jornada=self.jornada,
            modalidad='presencial',
            tipo_matricula='reserva_abono',
            forma_pago='abono',
            fecha_matricula=date(2026, 7, 5),
            valor_curso=Decimal('115.00'),
            valor_pagado=Decimal('0.00'),
            tipo_registro='central_ia',
            registrado_por=self.usuario,
        )
        Matricula.objects.create(
            estudiante=segundo_estudiante,
            curso=self.curso,
            jornada=segunda_jornada,
            modalidad='presencial',
            tipo_matricula='reserva_abono',
            forma_pago='abono',
            fecha_matricula=date(2026, 7, 5),
            valor_curso=Decimal('115.00'),
            valor_pagado=Decimal('0.00'),
            tipo_registro='central_ia',
            registrado_por=self.usuario,
        )

        request = RequestFactory().get('/pagos/hoja-recaudacion/', {
            'fecha': '2026-07-10',
            'curso': str(self.curso.id),
        })
        hojas, _filtros = _hojas_recaudacion_data(request)

        self.assertEqual(len(hojas), 2)
        self.assertEqual([h['jornada_id'] for h in hojas], [
            self.jornada.pk,
            segunda_jornada.pk,
        ])
        self.assertEqual([len(h['items']) for h in hojas], [1, 1])

        request_jornada = RequestFactory().get('/pagos/hoja-recaudacion/', {
            'fecha': '2026-07-10',
            'curso': str(self.curso.id),
            'jornada': str(segunda_jornada.id),
        })
        hojas_jornada, _filtros = _hojas_recaudacion_data(request_jornada)

        self.assertEqual(len(hojas_jornada), 1)
        self.assertEqual(hojas_jornada[0]['jornada_id'], segunda_jornada.pk)
        self.assertEqual(
            hojas_jornada[0]['items'][0]['estudiante'],
            segundo_estudiante,
        )

    def test_editar_solo_datos_oculta_campos_de_pago(self):
        admin = User.objects.create_superuser(
            username='admin_edicion_datos',
            password='clave12345',
        )
        matricula = Matricula.objects.create(
            estudiante=self.estudiante,
            curso=self.curso,
            jornada=self.jornada,
            modalidad='presencial',
            tipo_matricula='reserva_modulo_1',
            forma_pago='abono_modulo',
            fecha_matricula=date(2026, 7, 5),
            valor_curso=Decimal('115.00'),
            valor_pagado=Decimal('30.00'),
            tipo_registro='central_ia',
            factura_realizada='no',
            registrado_por=admin,
            vendedora=self.usuario,
        )
        self.client.force_login(admin)

        response = self.client.get(
            reverse(
                'academia:matricula_editar',
                kwargs={'modalidad': 'presencial', 'pk': matricula.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        self.assertIn('Seleccione la jornada', html)
        self.assertIn('¿Factura con datos?', html)
        self.assertIn('Selecciona el asesor', html)
        self.assertNotIn('Valor pagado (USD)', html)
        self.assertNotIn('Forma de pago *', html)
        self.assertNotIn('Distribución de pago', html)
        self.assertNotIn('Método de pago *', html)
        self.assertNotIn('Valor del curso (USD)', html)

    def test_editar_pago_inicial_mantiene_campos_de_pago_visibles(self):
        admin = User.objects.create_superuser(
            username='admin_edicion_pago',
            password='clave12345',
        )
        matricula = Matricula.objects.create(
            estudiante=self.estudiante,
            curso=self.curso,
            jornada=self.jornada,
            modalidad='presencial',
            tipo_matricula='reserva_modulo_1',
            forma_pago='abono_modulo',
            fecha_matricula=date(2026, 7, 5),
            valor_curso=Decimal('115.00'),
            valor_pagado=Decimal('30.00'),
            tipo_registro='central_ia',
            factura_realizada='no',
            registrado_por=admin,
            vendedora=self.usuario,
        )
        self.client.force_login(admin)

        response = self.client.get(
            reverse(
                'academia:matricula_editar',
                kwargs={'modalidad': 'presencial', 'pk': matricula.pk},
            ),
            {'editar_pago': '1'},
        )

        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        self.assertIn('Valor pagado (USD)', html)
        self.assertIn('Forma de pago *', html)
        self.assertIn('Distribución de pago', html)

    def test_comprobante_usa_vendedora_de_matricula(self):
        registrador = User.objects.create_user(username='registrador')
        vendedora_1 = User.objects.create_user(
            username='asesora_uno',
            first_name='Asesora',
            last_name='Uno',
        )
        vendedora_2 = User.objects.create_user(
            username='asesora_dos',
            first_name='Asesora',
            last_name='Dos',
        )
        matricula = Matricula.objects.create(
            estudiante=self.estudiante,
            curso=self.curso,
            jornada=self.jornada,
            modalidad='presencial',
            tipo_matricula='reserva_abono',
            forma_pago='abono',
            fecha_matricula=date(2026, 7, 5),
            valor_curso=Decimal('115.00'),
            valor_pagado=Decimal('30.00'),
            tipo_registro='central_ia',
            factura_realizada='no',
            registrado_por=registrador,
            vendedora=vendedora_1,
        )

        comprobante = Comprobante.objects.get(matricula=matricula)
        self.assertEqual(comprobante.vendedora, vendedora_1)
        self.assertEqual(comprobante.vendedora_nombre, 'Asesora Uno')

        matricula.vendedora = vendedora_2
        matricula.save()
        comprobante.refresh_from_db()

        self.assertEqual(comprobante.vendedora, vendedora_2)
        self.assertEqual(comprobante.vendedora_nombre, 'Asesora Dos')

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
