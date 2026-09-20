from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User, Group
from django.test import TestCase
from django.urls import reverse

from .models import Curso, JornadaCurso, Estudiante, Matricula, Abono
from .views_pagos import _plan_recaudacion_matricula, _construir_hoja_recaudacion


class ModuloAcademicoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('admin_modulo', password='test')
        self.client.force_login(self.user)
        self.curso = Curso.objects.create(nombre='Servicio técnico', numero_modulos=4)
        self.jornada = JornadaCurso.objects.create(
            curso=self.curso, modalidad='presencial', fecha_inicio=date(2026, 9, 5),
        )
        estudiante = Estudiante.objects.create(cedula='0900000001', nombres='Estudiante')
        self.m = Matricula.objects.create(
            estudiante=estudiante, curso=self.curso, jornada=self.jornada,
            modalidad='presencial', fecha_matricula=date(2026, 8, 31),
            valor_curso=110, valor_pagado=0, tipo_registro='central_ia',
        )
        Abono.objects.create(matricula=self.m, monto=110, fecha=date(2026, 9, 5),
                             tipo_pago='abono', metodo='efectivo')
        self.m.refresh_from_db()
        self.url = reverse('academia:matricula_ajustar_modulo', args=[self.m.pk])

    def plan(self, dia):
        return _plan_recaudacion_matricula(self.m, date(2026, 9, dia))

    def test_pago_completo_sigue_jornada_y_no_cobra(self):
        self.assertEqual(self.m.saldo, 0)
        for dia, modulo in [(1, 1), (5, 1), (12, 2), (19, 3), (26, 4), (30, 4)]:
            plan = self.plan(dia)
            self.assertEqual(plan['modulo'], modulo)
            self.assertEqual(plan['cuota_sugerida'], 0)
            self.assertEqual(plan['saldo_modulo'], 0)
        hoja = _construir_hoja_recaudacion(
            curso=self.curso, matriculas=[self.m], fecha_obj=date(2026, 9, 19),
            ciudad='', jornada=self.jornada,
        )
        self.assertEqual(hoja['items'][0]['modulo'], 3)

    @patch('academia.views_pagos.timezone.localdate', return_value=date(2026, 9, 19))
    def test_periodo_actual_muestra_avance_de_hoy_no_fin_de_mes(self, hoy):
        hoja = _construir_hoja_recaudacion(
            curso=self.curso, matriculas=[self.m], fecha_obj=date(2026, 9, 1),
            fecha_hasta_obj=date(2026, 9, 30), ciudad='', jornada=self.jornada,
        )
        self.assertEqual(hoja['items'][0]['modulo'], 3)

    @patch('academia.views_pagos.timezone.localdate', return_value=date(2026, 9, 19))
    def test_ajuste_avanza_y_se_puede_restaurar(self, hoy):
        pagos = list(self.m.abonos.values())
        response = self.client.post(self.url, {'secuencia': 'manual', 'modulo': '2'})
        self.assertEqual(response.status_code, 302)
        self.m.refresh_from_db()
        self.assertEqual(self.plan(19)['modulo'], 2)
        self.assertEqual(self.plan(26)['modulo'], 3)
        self.assertEqual(self.plan(12)['modulo'], 2)
        self.assertEqual(list(self.m.abonos.values()), pagos)
        self.assertEqual(self.m.valor_pagado, Decimal('110'))
        self.client.post(self.url, {'secuencia': 'jornada'})
        self.m.refresh_from_db()
        self.assertEqual(self.plan(19)['modulo'], 3)
        self.assertIsNone(self.m.desfase_modulo_academico)

    def test_validacion_permiso_y_saldo(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        for modulo in ('0', '5', 'texto'):
            self.client.post(self.url, {'secuencia': 'manual', 'modulo': modulo})
            self.m.refresh_from_db()
            self.assertIsNone(self.m.desfase_modulo_academico)
        Matricula.objects.filter(pk=self.m.pk).update(valor_pagado=35)
        self.client.post(self.url, {'secuencia': 'manual', 'modulo': '2'})
        self.m.refresh_from_db()
        self.assertIsNone(self.m.desfase_modulo_academico)
        usuario = User.objects.create_user('otra_asesora')
        usuario.groups.add(Group.objects.get_or_create(name='Asesores')[0])
        self.client.force_login(usuario)
        self.assertEqual(self.client.post(self.url, {'secuencia': 'jornada'}).status_code, 403)

    def test_pantalla_y_retiro(self):
        url = reverse('academia:matricula_abonos', args=[self.m.pk])
        self.assertContains(self.client.get(url), 'ajustar-modulo-check')
        Matricula.objects.filter(pk=self.m.pk).update(estado='retiro_voluntario')
        self.assertNotContains(self.client.get(url), 'ajustar-modulo-check')
        self.client.post(self.url, {'secuencia': 'manual', 'modulo': '2'})
        self.m.refresh_from_db()
        self.assertIsNone(self.m.desfase_modulo_academico)

    def test_pago_unico_conserva_modulos_academicos(self):
        self.m.modalidad = 'online'
        self.curso.numero_modulos_online = 4
        self.curso.es_ciclo_corto = True
        self.m.curso = self.curso
        self.assertEqual(self.plan(19)['modulo'], 3)
        self.curso.pagos_cada_dos_semanas = True
        self.assertEqual(self.plan(19)['modulo'], 2)
