import json
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth.models import User, Group
from django.test import TestCase
from django.urls import reverse

from .forms import MatriculaForm, EstudianteForm
from .models import Curso, Categoria, JornadaCurso, Sede, Estudiante, Matricula, Abono, Comprobante
from .mercybot import STATE
from .mercybot_matricula import (STUDENT_FIELDS, ACADEMIC_FIELDS, PAYMENT_FIELDS, CLOSING_FIELDS,
                                 LEGACY_FIELDS, FACTURA_FIELDS)


class MercyBotMatriculaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('mercy-matricula', 'mercy@example.test', 'test')
        self.advisor = User.objects.create_user('asesora-mercy', first_name='Asesora', last_name='Prueba')
        self.client.force_login(self.user)
        self.url = reverse('academia:assistant_simple_chat')
        category, _ = Categoria.objects.get_or_create(nombre='Técnico')
        self.course = Curso.objects.create(nombre='Curso Matrícula Mercy Completa', categoria=category,
            ofrece_presencial=True, ofrece_online=True, valor_presencial=100, valor_online=60, numero_modulos=4)
        self.sede = Sede.objects.create(nombre='Sede Mercy Prueba')
        self.jornada = JornadaCurso.objects.create(curso=self.course, modalidad='presencial',
            descripcion='sabados_intensivos', fecha_inicio=date(2026, 10, 3), sede=self.sede)
        self.online = JornadaCurso.objects.create(curso=self.course, modalidad='online',
            descripcion='domingos_intensivos', fecha_inicio=date(2026, 10, 4))
        self.data = {
            'cedula': '0999999999', 'nombres': 'Ana Prueba Completa', 'edad': '26',
            'correo': 'ana@example.test', 'celular': '0998765432', 'nivel_formacion': 'tecnico',
            'titulo_profesional': 'Contabilidad', 'ciudad': 'Quito',
            'curso': str(self.course.pk), 'jornada': str(self.jornada.pk), 'estado': 'activa',
            'tipo_matricula': 'reserva_abono', 'fecha_matricula': '2026-09-19',
            'valor_curso': '100', 'descuento': '10', 'forma_pago': 'abono', 'valor_pagado': '10',
            'tipo_cobro': 'un_solo_metodo', 'metodo_pago': 'transferencia', 'banco': 'pichincha',
            'talla_camiseta': 'M', 'observaciones': 'Inscripción desde el chat',
            'tipo_registro': 'central_2', 'vendedora_id': str(self.advisor.pk),
            'link_comprobante': 'https://example.test/recibo',
        }
        notify = patch('academia.views._programar_confirmacion_matricula')
        self.notify = notify.start(); self.addCleanup(notify.stop)

    def chat(self, message, request_id=None):
        response = self.client.post(self.url, json.dumps({'message': message, 'request_id': request_id or str(uuid4())}), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def payload(self, data=None):
        return '; '.join(f'{k}: {v if v != "" else "omitir"}' for k, v in (self.data if data is None else data).items())

    def register(self, data=None, request_id=None):
        return self.chat('registrar estudiante; ' + self.payload(data), request_id)

    def test_all_form_fields_have_a_capture_path(self):
        self.assertEqual(set(EstudianteForm.Meta.fields), set(STUDENT_FIELDS))
        self.assertEqual(set(MatriculaForm().fields),
                         (set(ACADEMIC_FIELDS + PAYMENT_FIELDS + CLOSING_FIELDS) - {'vendedora_id'}) | LEGACY_FIELDS)

    def test_complete_enrollment_payment_and_audit(self):
        result = self.register()
        self.assertIn('Matrícula #', result['reply'])
        self.assertIn('03/10/2026', result['reply'])
        self.assertIn('$80.00', result['reply'])
        m = Matricula.objects.get()
        self.assertEqual(m.estudiante.nombres, self.data['nombres'])
        self.assertEqual(m.estudiante.edad, 26)
        self.assertEqual(m.estudiante.titulo_profesional, 'Contabilidad')
        self.assertEqual(m.estudiante.registrado_por, self.user)
        self.assertEqual(m.registrado_por, self.user)
        self.assertEqual(m.vendedora, self.advisor)
        self.assertEqual(m.jornada, self.jornada)
        self.assertEqual(m.modalidad, 'presencial')
        self.assertEqual(m.fecha_matricula, date(2026, 9, 19))
        self.assertEqual(m.talla_camiseta, 'M')
        self.assertEqual(m.observaciones, self.data['observaciones'])
        self.assertEqual(m.tipo_registro, 'central_2')
        # La factura se registra después, en Matrícula › Facturas.
        self.assertEqual((m.factura_realizada, m.fact_nombres, m.fact_cedula), ('no', '', ''))
        self.assertIn('Matrícula › Facturas › Registrar factura', result['reply'])
        self.assertIn(reverse('academia:matricula_registrar_factura', args=[m.pk]),
                      [enlace['url'] for enlace in result['links']])
        self.assertEqual(m.link_comprobante, self.data['link_comprobante'])
        self.assertEqual(m.valor_pagado, Decimal('10'))
        self.assertEqual(m.saldo, Decimal('80'))
        p = Abono.objects.get(matricula=m)
        self.assertEqual(p.monto, Decimal('10'))
        self.assertEqual(p.metodo, 'transferencia')
        self.assertEqual(p.banco, 'pichincha')
        self.assertEqual(p.registrado_por, self.user)
        self.assertTrue(Comprobante.objects.filter(matricula=m).exists())
        self.notify.assert_called_once()
        self.assertNotIn(STATE, self.client.session)

    def test_course_shows_dates_and_modalities_then_loads_price(self):
        self.chat('registrar matrícula')
        student_data = {k:v for k,v in self.data.items() if k in STUDENT_FIELDS}
        self.chat(self.payload(student_data))
        result = self.chat(self.course.nombre)
        for text in ['03/10/2026', '04/10/2026', 'Presencial', 'Online', self.sede.nombre]:
            self.assertIn(text, result['reply'])
        result = self.chat('04/10/2026')
        self.assertIn('$60.00', result['reply'])
        self.assertEqual(self.client.session[STATE]['data']['jornada'], str(self.online.pk))
        self.assertFalse(Estudiante.objects.exists())
        self.assertFalse(Matricula.objects.exists())

    def test_one_field_at_a_time_captures_entire_form(self):
        self.chat('quiero agregar un nuevo estudiante')
        for _ in range(50):
            state = self.client.session.get(STATE)
            if not state:
                break
            waiting = state['waiting']
            self.assertIn(waiting, self.data)
            self.chat(self.data[waiting])
        self.assertNotIn(STATE, self.client.session)
        self.assertEqual(Matricula.objects.count(), 1)
        self.assertEqual(Abono.objects.count(), 1)

    def answer_until_done(self, data):
        """Responde solo lo que el bot pregunta; falla si pide otro dato."""
        self.chat('quiero agregar un nuevo estudiante')
        asked, result = [], None
        for _ in range(50):
            state = self.client.session.get(STATE)
            if not state:
                break
            waiting = state['waiting']
            self.assertIn(waiting, data)
            asked.append(waiting)
            result = self.chat(data[waiting])
        return asked, result

    def test_otros_enrollment_never_asks_for_payment(self):
        payment = {'valor_curso', 'descuento', 'forma_pago', 'valor_pagado',
                   'tipo_cobro', 'metodo_pago', 'banco'}
        data = {k: v for k, v in self.data.items() if k not in payment}
        data['tipo_matricula'] = 'Otros'
        _, result = self.answer_until_done(data)
        self.assertIn('no se le cobra nada', result['reply'])
        m = Matricula.objects.get()
        self.assertEqual(m.tipo_matricula, 'otros')
        self.assertEqual(m.valor_curso, Decimal('0'))
        self.assertEqual(m.saldo, Decimal('0'))
        self.assertFalse(Abono.objects.exists())

    def test_free_registration_asks_price_but_no_initial_payment(self):
        payment = {'forma_pago', 'valor_pagado', 'tipo_cobro', 'metodo_pago', 'banco'}
        data = {k: v for k, v in self.data.items() if k not in payment}
        data['tipo_matricula'] = 'inscripción gratis'
        asked, result = self.answer_until_done(data)
        self.assertIn('valor_curso', asked)
        self.assertIn('Inscripción gratis', result['reply'])
        m = Matricula.objects.get()
        self.assertEqual(m.tipo_matricula, 'inscripcion_gratis')
        # $100 del curso − $10 de inscripción; el descuento de $10 se aplica aparte.
        self.assertEqual(m.valor_curso, Decimal('90'))
        self.assertEqual(m.saldo, Decimal('80'))
        self.assertFalse(Abono.objects.exists())

    def test_missing_final_field_never_creates_student_or_payment(self):
        values = dict(self.data); values.pop('link_comprobante')
        self.register(values)
        self.assertFalse(Estudiante.objects.exists())
        self.assertFalse(Matricula.objects.exists())
        self.assertFalse(Abono.objects.exists())
        self.assertEqual(self.client.session[STATE]['waiting'], 'link_comprobante')
        self.chat('omitir')
        self.assertEqual(Matricula.objects.count(), 1)

    def test_existing_student_prefill_does_not_duplicate(self):
        student = Estudiante.objects.create(cedula=self.data['cedula'], nombres='Nombre Existente', celular='0998765432', ciudad='Quito')
        result = self.chat('registrar estudiante; cédula: ' + student.cedula)
        self.assertIn('Nombre Existente', result['reply'])
        values = {k:v for k,v in self.data.items() if k not in STUDENT_FIELDS}
        self.chat(self.payload(values))
        self.assertEqual(Estudiante.objects.count(), 1)
        self.assertEqual(Matricula.objects.get().estudiante_id, student.pk)
        student.refresh_from_db(); self.assertEqual(student.nombres, 'Nombre Existente')

    def test_reserva_above_ten_dollars_is_rejected_until_corrected(self):
        result = self.register(dict(self.data, valor_pagado='20'))
        self.assertIn('máximo $10.00', result['reply'])
        self.assertEqual(self.client.session[STATE]['waiting'], 'valor_pagado')
        self.assertFalse(Estudiante.objects.exists())
        self.assertFalse(Matricula.objects.exists())
        self.assertFalse(Abono.objects.exists())
        result = self.chat('10')
        self.assertIn('Matrícula #', result['reply'])
        self.assertEqual(Abono.objects.get().monto, Decimal('10'))

    def test_mixed_payment_sum_bank_and_no_partial_records(self):
        values = dict(self.data, tipo_cobro='mixto', monto_pago_1='6', metodo_pago_1='efectivo',
                      monto_pago_2='5', metodo_pago_2='tarjeta', banco_2='payphone')
        result = self.register(values)
        self.assertIn('suma', result['reply'])
        self.assertFalse(Matricula.objects.exists())
        result = self.chat('monto 2: 4')
        self.assertIn('Matrícula #', result['reply'])
        p = Abono.objects.get()
        self.assertEqual(p.monto, Decimal('10'))
        self.assertEqual(p.monto_2, Decimal('4'))
        self.assertEqual(p.metodo, 'efectivo')
        self.assertEqual(p.metodo_2, 'tarjeta')
        self.assertEqual(p.banco_2, 'payphone')

    def test_bank_question_lists_only_the_banks_of_the_method(self):
        values = dict(self.data, metodo_pago='deposito')
        values.pop('banco')
        result = self.register(values)
        self.assertEqual(self.client.session[STATE]['waiting'], 'banco')
        for banco in ('Guayaquil', 'Pichincha', 'Banco del Pacífico', 'Produbanco'):
            self.assertIn(banco, result['reply'])
        for banco in ('Interbancario', 'Payphone', 'De una', 'Otro banco'):
            self.assertNotIn(banco, result['reply'])
        self.assertFalse(Matricula.objects.exists())
        result = self.chat('de una')
        self.assertIn('no corresponde', result['reply'])
        self.assertFalse(Matricula.objects.exists())
        result = self.chat('pacifico')
        self.assertIn('Matrícula #', result['reply'])
        p = Abono.objects.get()
        self.assertEqual((p.metodo, p.banco), ('deposito', 'banco_pacifico'))

    def test_factura_ya_no_se_pide_y_se_ignora_con_aviso(self):
        result = self.chat('registrar estudiante; cédula: 0999999999; factura: si; nombres factura: Otra Persona')
        self.assertIn('Matrícula › Facturas › Registrar factura', result['reply'])
        self.assertFalse(set(FACTURA_FIELDS) & set(self.client.session[STATE]['data']))
        # Sin factura en la matrícula, celular y ciudad ya no son obligatorios.
        values = {k: v for k, v in self.data.items() if k != 'cedula'}
        result = self.chat(self.payload(dict(values, celular='', ciudad='')))
        self.assertIn('Matrícula #', result['reply'])
        m = Matricula.objects.get()
        self.assertEqual((m.factura_realizada, m.fact_nombres), ('no', ''))

    def test_full_payment_online_and_suggested_course_price(self):
        values = dict(self.data, jornada=str(self.online.pk), tipo_matricula='programa_completo',
                      forma_pago='pago_completo', valor_curso='usar valor', descuento='0', valor_pagado='60',
                      factura_realizada='no', metodo_pago='efectivo')
        self.register(values)
        m = Matricula.objects.get()
        self.assertEqual(m.valor_curso, Decimal('60'))
        self.assertEqual(m.modalidad, 'online')
        self.assertEqual(m.saldo, Decimal('0'))
        self.assertEqual(Abono.objects.get().tipo_pago, 'pago_completo')
        self.assertEqual(m.fact_nombres, '')
        self.assertEqual(Abono.objects.get().banco, '')

    def test_invalid_jornada_from_another_course_and_inactive(self):
        other = Curso.objects.create(nombre='Otro Curso Mercy Prueba')
        j = JornadaCurso.objects.create(curso=other, modalidad='online', descripcion='sabados_intensivos', fecha_inicio=date(2026, 10, 3))
        result = self.register(dict(self.data, jornada=str(j.pk)))
        self.assertIn('jornada', result['reply'])
        self.assertFalse(Matricula.objects.exists())
        self.jornada.activo = False; self.jornada.save()
        self.chat('jornada: ' + str(self.jornada.pk))
        self.assertFalse(Matricula.objects.exists())

    def test_duplicate_dates_require_jornada_id(self):
        JornadaCurso.objects.create(curso=self.course, modalidad='online', descripcion='sabados_intensivos', fecha_inicio=self.jornada.fecha_inicio)
        self.register(dict(self.data, jornada='03/10/2026'))
        self.assertFalse(Matricula.objects.exists())
        self.assertEqual(self.client.session[STATE]['waiting'], 'jornada')
        self.chat(str(self.jornada.pk))
        self.assertEqual(Matricula.objects.get().jornada_id, self.jornada.pk)

    def test_same_request_and_new_request_cannot_duplicate_active_enrollment(self):
        result = self.register(request_id='enrollment-1')
        self.assertEqual(result, self.register(request_id='enrollment-1'))
        result = self.register()
        self.assertIn('ya tiene una matrícula activa', result['reply'])
        self.assertEqual(Matricula.objects.count(), 1)
        self.assertEqual(Abono.objects.count(), 1)

    def test_failure_in_payment_rolls_back_everything(self):
        with patch('academia.views._registrar_pago_inicial', side_effect=RuntimeError('fallo simulado')), self.assertLogs('academia.views', level='ERROR'):
            response = self.client.post(self.url, json.dumps({'message': 'registrar matrícula; ' + self.payload()}), content_type='application/json')
        self.assertEqual(response.status_code, 500)
        for model in (Estudiante, Matricula, Abono, Comprobante):
            self.assertFalse(model.objects.exists())
        self.notify.assert_not_called()

    def test_permissions_and_cancel(self):
        self.chat('registrar estudiante')
        self.chat('cédula: 0999999999; nombres: Ana')
        self.chat('cancelar')
        self.assertFalse(Estudiante.objects.exists())
        advisor_group = Group.objects.create(name='Asesores')
        self.advisor.groups.add(advisor_group)
        self.client.force_login(self.advisor)
        self.chat('registrar matrícula')
        self.advisor.groups.clear()
        self.assertIn('No tienes permiso', self.chat('0999999999')['reply'])
        self.assertNotIn(STATE, self.client.session)
