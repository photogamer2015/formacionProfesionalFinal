import json
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth.models import User, Group
from django.db import connection
from django.test import TestCase, Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse, resolve
from django.utils import timezone

from .models import Estudiante, Curso, JornadaCurso, Sede, Matricula, Abono, RecuperacionPendiente
from .mercybot import STATE, OUTSIDE, SECTIONS


class MercyBotTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('mercy-admin', 'test@example.com', 'test')
        self.client.force_login(self.user)
        self.url = reverse('academia:assistant_simple_chat')
        self.student = Estudiante.objects.create(cedula='0912345678', nombres='Andrés Guevara')
        self.course = Curso.objects.create(nombre='Curso Mercy Contabilidad', ofrece_presencial=True,
                                           valor_presencial=Decimal('100'), numero_modulos=5)
        self.enrollment = Matricula.objects.create(estudiante=self.student, curso=self.course,
            fecha_matricula=date(2026, 9, 1), modalidad='presencial', valor_curso=Decimal('100'), valor_pagado=Decimal('0'))
        self.sede = Sede.objects.create(nombre='Sede Mercy Chat')
        self.jornada = JornadaCurso.objects.create(curso=self.course, modalidad='presencial',
            descripcion='sabados_intensivos', fecha_inicio=date(2026, 10, 3), sede=self.sede)
        notify = patch('academia.views._programar_confirmacion_matricula')
        self.notify = notify.start(); self.addCleanup(notify.stop)

    def chat(self, message, **kwargs):
        response = self.client.post(self.url, json.dumps({'message': message, 'request_id': str(uuid4()), **kwargs}), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def enrollment_payload(self, omit=(), **overrides):
        """Resto del formulario de matrícula: curso, fechas, valores, pago y factura."""
        values = {'curso': str(self.course.pk), 'jornada': str(self.jornada.pk), 'estado': 'activa',
                  'tipo_matricula': 'programa_completo', 'fecha_matricula': 'hoy', 'valor_curso': '100',
                  'descuento': '0', 'forma_pago': 'pago_completo', 'valor_pagado': '100',
                  'tipo_cobro': 'un_solo_metodo', 'metodo_pago': 'efectivo', 'observaciones': 'omitir',
                  'tipo_registro': 'central_2', 'vendedora_id': 'yo', 'factura_realizada': 'no',
                  'link_comprobante': 'omitir'}
        values.update(overrides)
        return '; '.join(f'{name}: {value}' for name, value in values.items() if name not in omit)

    def student_payload(self):
        return ('cédula: 0999999999; nombres: Ana Pérez; edad: omitir; correo: omitir; celular: omitir; '
                'nivel: omitir; titulo: omitir; ciudad: Quito')

    def test_outside_and_help(self):
        self.assertEqual(self.chat('cuál es la capital de Francia')['reply'], OUTSIDE)
        self.assertIn('registrar estudiantes', self.chat('ayuda')['reply'])

    def test_greeting_introduces_mercy_and_uses_the_name(self):
        for saludo in ['hola', 'qué tal', 'buenas', 'hola mercy', 'hey']:
            reply = self.chat(saludo)['reply']
            self.assertIn('Soy Mercy', reply, saludo)
            self.assertIn('registrar matrícula', reply, saludo)
        self.user.first_name = 'Yandri'; self.user.save()
        self.assertIn('Yandri', self.chat('hola')['reply'])
        self.assertIn('Carolina', self.chat('hola soy Carolina')['reply'])
        self.assertNotIn(STATE, self.client.session)

    def test_greeting_during_registration_keeps_the_pending_data(self):
        self.chat('registrar estudiante')
        self.chat('0999999999')
        reply = self.chat('hola')['reply']
        self.assertIn('Seguimos con el registro', reply)
        self.assertEqual(self.client.session[STATE]['data'], {'cedula': '0999999999'})

    def test_back_undoes_the_last_answer_and_asks_it_again(self):
        self.chat('registrar estudiante')
        self.chat('0999999999')
        self.chat('Ana Pérez')
        result = self.chat('atrás')
        self.assertIn('descarté nombres y apellidos', result['reply'])
        self.assertIn('Indica nombres y apellidos', result['reply'])
        self.assertEqual(self.client.session[STATE]['data'], {'cedula': '0999999999'})
        self.chat('Ana Corregida')
        self.assertEqual(self.client.session[STATE]['data']['nombres'], 'Ana Corregida')
        for phrase in ['volver', 'regresar', 'me equivoqué', 'paso anterior', 'deshacer']:
            self.chat('Nombre ' + phrase)
            self.assertIn('descarté', self.chat(phrase)['reply'], phrase)

    def test_back_on_the_course_also_reopens_the_jornada(self):
        self.chat('registrar estudiante; ' + self.student_payload())
        self.chat(str(self.course.pk))
        self.chat(str(self.jornada.pk))
        data = self.client.session[STATE]['data']
        self.assertEqual(data['jornada'], str(self.jornada.pk))
        self.assertIn('Indica jornada', self.chat('atrás')['reply'])
        self.assertNotIn('jornada', self.client.session[STATE]['data'])
        result = self.chat('atrás')
        self.assertIn('Indica curso', result['reply'])
        self.assertNotIn('curso', self.client.session[STATE]['data'])
        self.chat(str(self.course.pk))
        self.chat(str(self.jornada.pk))
        self.assertEqual(self.client.session[STATE]['data']['jornada'], str(self.jornada.pk))

    def test_back_without_data_explains_instead_of_failing(self):
        self.chat('registrar estudiante')
        result = self.chat('atrás')
        self.assertIn('no hay ningún dato que deshacer', result['reply'])
        self.assertIn(STATE, self.client.session)

    def test_back_also_works_while_registering_a_recovery(self):
        self.chat('registrar recuperación para 0912345678')
        self.chat('módulo: 1')
        self.chat('19/09/2026')
        result = self.chat('atrás')
        self.assertIn('descarté fecha de la falta', result['reply'])
        self.assertNotIn('fecha_marcada', self.client.session[STATE]['data'])

    def test_payments_name_accent_order_and_document(self):
        Abono.objects.create(matricula=self.enrollment, monto=Decimal('25'), fecha=date(2026, 9, 19), registrado_por=self.user)
        for query in ['ver pagos del estudiante Andrés Guevara', 'ver pagos de Guevara Andres', 'ver pagos 0912345678']:
            result = self.chat(query)
            self.assertIn('Andrés Guevara', result['reply'])
            self.assertIn('$25.00', result['reply'])
            self.assertIn('$75.00', result['reply'])
            for item in result['links']:
                resolve(item['url'])

    def test_followup_and_ambiguous(self):
        Estudiante.objects.create(cedula='0922222222', nombres='Andrés Guevara Segundo')
        self.assertIn('cédula exacta', self.chat('pagos de Andres Guevara')['reply'])
        self.assertIn('Andrés Guevara —', self.chat('0912345678')['reply'])
        self.assertIn('Sin recuperaciones', self.chat('y sus recuperaciones')['reply'])

    def test_search_without_term_and_not_found(self):
        self.assertIn('nombre y apellido', self.chat('ver pagos')['reply'])
        self.assertIn('No encontré', self.chat('Persona inexistente')['reply'])
        self.assertIn('Andrés Guevara', self.chat('Andres Guevara')['reply'])

    def test_enrollment_conversation_validates_then_saves_student_and_matricula(self):
        self.assertIn('cédula', self.chat('yo quiero agregar un nuevo estudiante')['reply'])
        self.assertIn('únicamente números', self.chat('ABC123')['reply'])
        self.chat('0999999999')
        self.chat('Ana Pérez')
        result = self.chat('omitir opcionales')
        # El alta no termina en el estudiante: continúa con el curso y sus fechas.
        self.assertIn('curso', result['reply'])
        self.assertFalse(Estudiante.objects.filter(cedula='0999999999').exists())
        result = self.chat(self.enrollment_payload())
        self.assertIn('Matrícula #', result['reply'])
        self.assertIn('03/10/2026', result['reply'])
        created = Estudiante.objects.get(cedula='0999999999')
        self.assertEqual(created.nombres, 'Ana Pérez')
        self.assertEqual(created.correo, '')
        self.assertEqual(created.registrado_por, self.user)
        enrollment = created.matriculas.get()
        self.assertEqual(enrollment.jornada, self.jornada)
        self.assertEqual(enrollment.fecha_matricula, timezone.localdate())
        self.assertEqual(enrollment.vendedora, self.user)
        self.assertEqual(enrollment.valor_pagado, Decimal('100'))
        self.assertEqual(enrollment.saldo, Decimal('0'))
        self.assertEqual(Abono.objects.get(matricula=enrollment).monto, Decimal('100'))

    def test_bulk_fields_and_existing_student_is_reused(self):
        self.chat('registrar estudiante; cédula: 0999999999; nombres: Ana Pérez; celular: 0998765432; ciudad: Quito; correo: ana@example.com; edad: 25; nivel: Técnico; título: Contabilidad')
        # Sin el resto de la matrícula no se escribe ningún registro.
        self.assertFalse(Estudiante.objects.filter(cedula='0999999999').exists())
        self.chat(self.enrollment_payload())
        created = Estudiante.objects.get(cedula='0999999999')
        self.assertEqual(created.nivel_formacion, 'tecnico')
        self.assertEqual(created.matriculas.count(), 1)
        result = self.chat('registrar estudiante; cédula: 0999999999')
        self.assertIn('Ana Pérez', result['reply'])
        self.assertEqual(Estudiante.objects.filter(cedula='0999999999').count(), 1)
        self.assertEqual(Estudiante.objects.get(cedula='0999999999').nombres, 'Ana Pérez')

    def test_cancel_reset_and_sessions(self):
        self.chat('registrar estudiante')
        self.chat('0999999999')
        other = Client(); other.force_login(self.user)
        self.assertNotIn(STATE, other.session)
        self.chat('/clear')
        self.assertNotIn(STATE, self.client.session)
        self.assertFalse(Estudiante.objects.filter(cedula='0999999999').exists())

    def test_recovery_create_validate_dates_and_duplicate(self):
        self.assertIn('módulo', self.chat('registrar recuperación para Andres Guevara')['reply'])
        self.chat('módulo: 1; fecha de falta: 19/09/2026; fecha programada: 18/09/2026; observaciones: Falta')
        self.assertFalse(RecuperacionPendiente.objects.exists())
        result = self.chat('fecha programada: 20/09/2026')
        self.assertIn('Recuperación registrada', result['reply'])
        recovery = RecuperacionPendiente.objects.get()
        self.assertEqual(recovery.matricula, self.enrollment)
        self.assertEqual(recovery.saldo_pendiente_al_marcar, self.enrollment.saldo)
        self.chat('registrar recuperación para 0912345678')
        result = self.chat('módulo: 1; fecha de falta: 19/09/2026; fecha programada: 20/09/2026; observaciones: Falta')
        self.assertIn('Ya existe', result['reply'])
        self.assertEqual(RecuperacionPendiente.objects.count(), 1)

    def test_paid_module_rejected(self):
        Abono.objects.create(matricula=self.enrollment, monto=Decimal('20'), fecha=date(2026, 9, 1), numero_modulo=1, registrado_por=self.user)
        self.chat('registrar recuperación para 0912345678')
        result = self.chat('módulo: 1; fecha de falta: 19/09/2026; fecha programada: omitir; observaciones: omitir')
        self.assertIn('ya tiene un pago', result['reply'])
        self.assertFalse(RecuperacionPendiente.objects.exists())

    def test_choose_enrollment(self):
        another = Matricula.objects.create(estudiante=self.student, curso=self.course, modalidad='online', fecha_matricula=date(2026, 9, 1))
        self.assertIn('cuál matrícula', self.chat('registrar recuperación para 0912345678')['reply'])
        self.chat(str(another.pk))
        self.assertEqual(self.client.session[STATE]['matricula_id'], another.pk)

    def test_permission_checked_each_turn(self):
        advisor = User.objects.create_user('advisor', password='test')
        group = Group.objects.create(name='Asesores'); advisor.groups.add(group)
        self.client.force_login(advisor)
        self.chat('registrar estudiante')
        advisor.groups.clear()
        self.assertIn('No tienes permiso', self.chat('0999999999')['reply'])
        self.assertNotIn(STATE, self.client.session)
        self.assertIn('No tienes permiso', self.chat('ver pagos 0912345678')['reply'])

    def test_unauthenticated_csrf_and_invalid_payload(self):
        guest = Client()
        self.assertEqual(guest.post(self.url, {'message': 'hola'}).status_code, 302)
        csrf = Client(enforce_csrf_checks=True); csrf.force_login(self.user)
        self.assertEqual(csrf.post(self.url, json.dumps({'message': 'hola'}), content_type='application/json').status_code, 403)
        for payload in ['[]', '{', '{"message":3}', '{"message":""}']:
            self.assertEqual(self.client.post(self.url, payload, content_type='application/json').status_code, 400)

    def test_both_endpoints_are_local_and_retry_idempotent(self):
        with patch('openai.OpenAI', side_effect=AssertionError('No API allowed')):
            self.chat('ver pagos 0912345678')
            self.url = reverse('academia:assistant_llm_chat')
            self.chat('registrar estudiante')
            first = self.chat('0999999999', request_id='retry-1')
            self.assertEqual(first, self.chat('0999999999', request_id='retry-1'))
            self.assertEqual(self.client.session[STATE]['waiting'], 'nombres')

    def test_navigation_and_courses(self):
        for word, route, kwargs, access in SECTIONS:
            result = self.chat('abrir ' + word)
            self.assertEqual(result['redirect'], reverse('academia:' + route, kwargs=kwargs))
        self.assertIn('Curso Mercy Contabilidad', self.chat('cursos disponibles')['reply'])

    def test_navigation_prefers_the_most_specific_section(self):
        self.assertEqual(self.chat('abrir historial de pagos')['redirect'], reverse('academia:historial_lista'))
        self.assertEqual(self.chat('abrir pagos')['redirect'], reverse('academia:pagos_lista'))

    def test_transaction_rolls_back_failed_write(self):
        self.chat('registrar estudiante')
        message = ('cedula: 0999999999; nombres: Ana; celular: omitir; ciudad: omitir; correo: omitir; '
                   'edad: omitir; nivel: omitir; titulo: omitir; ' + self.enrollment_payload())
        with patch('academia.models.Estudiante.save', side_effect=RuntimeError('error simulado')), \
                self.assertLogs('academia.views', level='ERROR'):
            response = self.client.post(self.url, json.dumps({'message': message}), content_type='application/json')
        self.assertEqual(response.status_code, 500)
        self.assertFalse(Estudiante.objects.filter(cedula='0999999999').exists())
        self.assertFalse(Matricula.objects.filter(jornada=self.jornada).exists())
        self.assertFalse(Abono.objects.exists())
        self.assertEqual(self.client.session[STATE]['waiting'], 'cedula')

    def test_shared_phone_requires_explicit_consent(self):
        self.student.celular = '0998765432'
        self.student.save()
        response = self.chat('registrar estudiante; cedula: 0999999999; nombres: Ana; celular: 0998765432; '
                             'ciudad: omitir; correo: omitir; edad: omitir; nivel: omitir; titulo: omitir; '
                             + self.enrollment_payload())
        self.assertIn('número compartido: sí', response['reply'])
        self.assertFalse(Estudiante.objects.filter(cedula='0999999999').exists())
        self.assertIn('Matrícula #', self.chat('número compartido: sí')['reply'])
        self.assertTrue(Estudiante.objects.filter(cedula='0999999999').exists())

    def test_natural_field_values_and_names_are_not_commands(self):
        self.chat('registrar estudiante')
        self.chat('mi cédula es 0999999999')
        self.chat('Estudiante Prueba Chat')
        self.assertIn('curso', self.chat('omitir opcionales')['reply'])
        self.assertIn('Matrícula #', self.chat(self.enrollment_payload())['reply'])
        self.assertEqual(Estudiante.objects.get(cedula='0999999999').nombres, 'Estudiante Prueba Chat')

    def test_cancel_phrases_stop_any_pending_registration(self):
        for phrase in ['cancelar matrícula', 'ya no quiero registrar', 'olvídalo', 'anular el registro',
                       'mejor no', 'detener', 'no quiero', 'reiniciar']:
            self.chat('registrar estudiante')
            self.chat('0999999999')
            self.assertIn('Cancelado', self.chat(phrase)['reply'], phrase)
            self.assertNotIn(STATE, self.client.session, phrase)
        self.assertFalse(Estudiante.objects.filter(cedula='0999999999').exists())

    def test_free_text_answer_is_not_mistaken_for_a_cancel(self):
        self.chat('registrar estudiante; ' + self.student_payload() + '; '
                  + self.enrollment_payload(omit=('observaciones',)))
        self.assertEqual(self.client.session[STATE]['waiting'], 'observaciones')
        self.assertIn('Matrícula #', self.chat('ya no')['reply'])
        self.assertEqual(Estudiante.objects.get(cedula='0999999999').matriculas.get().observaciones, 'ya no')

    def test_questions_during_registration_are_not_stored_as_answers(self):
        self.chat('registrar estudiante')
        self.chat('0999999999')
        result = self.chat('cuántos cursos hay')
        self.assertIn('pendiente', result['reply'])
        self.assertNotIn('nombres', self.client.session[STATE]['data'])
        self.chat('Ana Pérez')
        self.assertEqual(self.client.session[STATE]['data']['nombres'], 'Ana Pérez')

    def test_widget_reports_pending_registration_and_offers_cancel(self):
        self.assertFalse(self.chat('hola')['pending'])
        self.assertTrue(self.chat('registrar estudiante')['pending'])
        self.assertFalse(self.chat('cancelar')['pending'])
        page = self.client.get(reverse('academia:bienvenida'))
        self.assertContains(page, 'assistant-pending')
        self.assertContains(page, 'Cancelar registro')
        self.assertContains(page, 'assistant-back')
        self.assertContains(page, 'Atrás')

    def test_payment_query_does_not_grow_with_the_number_of_enrollments(self):
        """Los abonos se traen agrupados: más matrículas no añaden consultas."""
        def consultar(cuantas):
            Matricula.objects.filter(estudiante=self.student).exclude(pk=self.enrollment.pk).delete()
            for _ in range(cuantas):
                extra = Matricula.objects.create(estudiante=self.student, curso=self.course, modalidad='online',
                                                 fecha_matricula=date(2026, 9, 1), valor_curso=Decimal('50'))
                Abono.objects.create(matricula=extra, monto=Decimal('10'), fecha=date(2026, 9, 20), registrado_por=self.user)
            with CaptureQueriesContext(connection) as capturadas:
                resultado = self.chat('ver pagos 0912345678')
            return len(capturadas), resultado
        Abono.objects.create(matricula=self.enrollment, monto=Decimal('25'), fecha=date(2026, 9, 19), registrado_por=self.user)
        pocas, resultado = consultar(1)
        muchas, _ = consultar(6)
        self.assertIn('$25.00', resultado['reply'])
        self.assertEqual(pocas, muchas)

    def test_unsupported_mutations_do_not_change_payments(self):
        self.assertIn('formulario', self.chat('eliminar pagos de Andres Guevara')['reply'])
        self.assertIn('formulario', self.chat('registrar pago de 25 para Andres Guevara')['reply'])
        self.assertFalse(Abono.objects.exists())
        self.assertTrue(Matricula.objects.filter(pk=self.enrollment.pk).exists())

    def test_system_help_is_local_and_does_not_start_writes(self):
        for question in ['cómo funcionan los pagos por modulo', 'cómo registrar una recuperación', 'factura', 'certificado', 'hoja de recaudación']:
            result = self.chat(question)
            self.assertNotEqual(result['reply'], OUTSIDE)
            self.assertTrue(result['links'])
            self.assertNotIn(STATE, self.client.session)
        self.assertFalse(RecuperacionPendiente.objects.exists())
