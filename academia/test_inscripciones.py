"""Pestaña «Pagos inscripciones»: el pago de inscripción (Reserva / Abono)
cobrado al matricular, por día (fecha de matrícula), con el total del día."""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Abono, AbonoArchivado, CierreCurso, Curso, Estudiante, JornadaCurso,
    Matricula, MatriculaArchivada, Sede,
)
from .permisos import GRUPO_ASESOR
from .views_inscripciones import _totales_por_dia

DIA_A = date(2026, 10, 5)
DIA_B = date(2026, 10, 4)
DIA_C = date(2026, 9, 20)


class PagosInscripcionesTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin_inscripciones', first_name='Ana', last_name='Admin')
        self.asesora = User.objects.create_user('asesora_inscripciones', first_name='Kim')
        self.asesora.groups.add(Group.objects.get_or_create(name=GRUPO_ASESOR)[0])
        self.curso = Curso.objects.create(
            nombre='Curso inscripciones', ofrece_presencial=True,
            valor_presencial=Decimal('90.00'), numero_modulos=4,
        )
        self.jornada = JornadaCurso.objects.create(
            curso=self.curso, modalidad='presencial', descripcion='sabados_intensivos',
            fecha_inicio=date(2026, 10, 10), sede=Sede.objects.create(nombre='Guayaquil'),
        )
        self.cedulas = iter(range(960000001, 960000100))

        # Día A: tres inscripciones de $10 (una mixta y otra con un módulo
        # pagado el mismo día), un Programa Completo y una inscripción gratis.
        self.efectivo = self._matricula('Ana Efectivo', DIA_A, pagos=[('10.00', 'efectivo', 'abono', None)])
        self.mixta = self._matricula('Beto Mixto', DIA_A, pagos=[('10.00', 'efectivo', 'abono', None)], mixto=('4.00', 'transferencia', 'pichincha'))
        self.con_modulo = self._matricula('Carla Modulo', DIA_A, pagos=[
            ('10.00', 'efectivo', 'abono', None), ('20.00', 'efectivo', 'solo_modulo', 1),
        ], registra=self.asesora)
        self._matricula('Dario Completo', DIA_A, tipo='programa_completo', pagos=[('90.00', 'efectivo', 'pago_completo', None)])
        self._matricula('Eva Gratis', DIA_A, tipo='inscripcion_gratis', valor='80.00')
        # Día B: una inscripción de $5 por depósito.
        self._matricula('Fabian Deposito', DIA_B, pagos=[('5.00', 'deposito', 'abono', None)])
        # Día C: una inscripción que pasó al archivo por un cierre.
        cierre = CierreCurso.objects.create(curso_nombre='Curso inscripciones')
        archivada = MatriculaArchivada.objects.create(
            cierre=cierre, cedula='0977777777', nombres='Gina Archivada',
            curso_nombre='Curso inscripciones', modalidad='presencial',
            fecha_matricula=DIA_C, estado_pago='Pagado', tipo_matricula='reserva_abono',
            registrado_por_nombre='Shirley Mora',
            creado_original=timezone.make_aware(datetime(2026, 9, 20, 9, 30)),
        )
        AbonoArchivado.objects.create(
            matricula_archivada=archivada, cierre=cierre, fecha=DIA_C,
            monto=Decimal('10.00'), tipo_pago='abono', metodo='efectivo',
            metodo_label='Efectivo', numero_recibo='REC-ARCH-1',
        )

    def _matricula(self, nombre, dia, *, tipo='reserva_abono', valor='90.00', pagos=(), mixto=None, registra=None):
        m = Matricula.objects.create(
            estudiante=Estudiante.objects.create(cedula=f'0{next(self.cedulas)}', nombres=nombre),
            curso=self.curso, jornada=self.jornada, modalidad='presencial',
            tipo_matricula=tipo, forma_pago='abono', fecha_matricula=dia,
            valor_curso=Decimal(valor), registrado_por=registra or self.admin,
        )
        for indice, (monto, metodo, tipo_pago, modulo) in enumerate(pagos):
            extra = {}
            if mixto and indice == 0:
                extra = {'monto_2': Decimal(mixto[0]), 'metodo_2': mixto[1], 'banco_2': mixto[2]}
            Abono.objects.create(
                matricula=m, fecha=dia, monto=Decimal(monto), metodo=metodo,
                tipo_pago=tipo_pago, numero_modulo=modulo, registrado_por=registra or self.admin,
                **extra,
            )
        return m

    def _get(self, usuario, **params):
        self.client.force_login(usuario)
        return self.client.get(reverse('academia:matricula_inscripciones'), params)

    def test_dia_con_total_y_por_metodo(self):
        response = self._get(self.admin, dia=DIA_A.isoformat())
        self.assertEqual(response.status_code, 200)
        filas = response.context['filas']
        self.assertEqual([f['estudiante'] for f in filas], ['Ana Efectivo', 'Beto Mixto', 'Carla Modulo'])
        self.assertEqual([f['monto'] for f in filas], [Decimal('10.00')] * 3)
        self.assertEqual(response.context['total'], Decimal('30.00'))
        self.assertEqual(response.context['cantidad'], 3)
        self.assertEqual(dict(response.context['metodos']), {
            'Efectivo': Decimal('26.00'), 'Transferencia bancaria': Decimal('4.00'),
        })
        html = response.content.decode()
        self.assertNotIn('Dario Completo', html)
        self.assertNotIn('Eva Gratis', html)
        self.assertIn('Total del día', html)
        for resto in ('{#', '{%', '{{'):
            self.assertNotIn(resto, html)

    def test_pestanas_por_dia_con_su_total(self):
        totales = _totales_por_dia()
        self.assertEqual(totales[DIA_A], {'cantidad': 3, 'total': Decimal('30.00')})
        self.assertEqual(totales[DIA_B], {'cantidad': 1, 'total': Decimal('5.00')})
        self.assertEqual(totales[DIA_C], {'cantidad': 1, 'total': Decimal('10.00')})
        pestanas = self._get(self.admin, dia=DIA_B.isoformat()).context['pestanas']
        por_dia = {p['fecha']: p for p in pestanas}
        self.assertTrue(por_dia[DIA_B]['activa'])
        self.assertEqual(por_dia[DIA_A]['total'], Decimal('30.00'))
        self.assertIn(timezone.localdate(), por_dia)  # la de hoy siempre está
        fechas = [p['fecha'] for p in pestanas]
        self.assertEqual(fechas, sorted(fechas, reverse=True))

    def test_dia_archivado_por_un_cierre(self):
        response = self._get(self.admin, dia=DIA_C.isoformat())
        filas = response.context['filas']
        self.assertEqual(len(filas), 1)
        self.assertTrue(filas[0]['archivada'])
        self.assertEqual(filas[0]['monto'], Decimal('10.00'))
        self.assertContains(response, 'Gina Archivada')
        self.assertContains(response, 'REC-ARCH-1')

    def test_la_asesora_ve_lo_mismo(self):
        response = self._get(self.asesora, dia=DIA_A.isoformat())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total'], Decimal('30.00'))
        self.assertEqual(len(response.context['filas']), 3)

    def test_sin_dia_o_dia_invalido_muestra_hoy(self):
        for params in ({}, {'dia': 'no-es-fecha'}):
            with self.subTest(params=params):
                response = self._get(self.admin, **params)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['dia'], timezone.localdate())

    def test_pestana_en_la_lista_de_matriculados(self):
        self.client.force_login(self.asesora)
        response = self.client.get(reverse('academia:matricula_lista', args=['todos']))
        self.assertContains(response, reverse('academia:matricula_inscripciones'))
        self.assertContains(response, 'Pagos inscripciones')
        retirados = self.client.get(reverse('academia:matricula_retirados', args=['todos']))
        self.assertNotContains(retirados, 'Pagos inscripciones')

    def test_sin_sesion_pide_iniciar(self):
        response = self.client.get(reverse('academia:matricula_inscripciones'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])
