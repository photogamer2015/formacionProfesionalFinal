import re
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from .admin import MatriculaAdmin
from .models import (
    Abono, Categoria, Comprobante, Curso, Estudiante, JornadaCurso, Matricula,
    Sede,
)
from .views_pagos import _detalle_modulo_pago, _plan_recaudacion_matricula


class AplicarPrecioActualAdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username='admin_precio')
        self.client.force_login(self.admin)
        self.url = reverse('admin:academia_matricula_changelist')
        sede = Sede.objects.create(nombre='Guayaquil', orden=1)
        tecnico, _ = Categoria.objects.get_or_create(nombre='Técnico')
        # El precio del curso ya se cambió de $110 a $90.
        self.curso = Curso.objects.create(
            categoria=tecnico, nombre='Servicio Técnico (prueba precio)',
            ofrece_presencial=True, valor_presencial=Decimal('90.00'),
            ofrece_online=True, valor_online=Decimal('60.00'),
            numero_modulos=4, numero_modulos_online=2,
        )
        self.sin_precio = Curso.objects.create(
            categoria=tecnico, nombre='Curso sin precio (prueba precio)',
            ofrece_presencial=True, numero_modulos=4,
        )
        self.jornada = JornadaCurso.objects.create(
            curso=self.curso, modalidad='presencial', descripcion='sabados_intensivos',
            fecha_inicio=date(2026, 10, 3), sede=sede,
        )
        self.jornada_online = JornadaCurso.objects.create(
            curso=self.curso, modalidad='online', descripcion='domingos_intensivos',
            fecha_inicio=date(2026, 10, 4),
        )
        self.jornada_sin_precio = JornadaCurso.objects.create(
            curso=self.sin_precio, modalidad='presencial', descripcion='mar_jue',
            fecha_inicio=date(2026, 10, 6), sede=sede,
        )
        self._cedula = 1500000000

    def _matricula(self, valor, pagado='10.00', tipo='reserva_abono',
                   jornada=None, **extra):
        self._cedula += 1
        estudiante = Estudiante.objects.create(
            cedula=str(self._cedula), nombres=f'Estudiante {self._cedula}',
        )
        jornada = jornada or self.jornada
        matricula = Matricula.objects.create(
            estudiante=estudiante, curso=jornada.curso, jornada=jornada,
            modalidad=jornada.modalidad, tipo_matricula=tipo,
            fecha_matricula=date(2026, 9, 20), valor_curso=Decimal(valor),
            tipo_registro='central_ia', registrado_por=self.admin, **extra,
        )
        if Decimal(pagado) > 0:
            Abono.objects.create(
                matricula=matricula, fecha=date(2026, 9, 20), monto=Decimal(pagado),
                tipo_pago='abono', metodo='efectivo', registrado_por=self.admin,
            )
        matricula.refresh_from_db()
        return matricula

    def _ver_confirmacion(self, *matriculas):
        """Primer paso: elegir la acción en la lista del admin."""
        return self.client.post(self.url, {
            'action': 'aplicar_precio_actual', 'index': '0',
            '_selected_action': [m.pk for m in matriculas],
        })

    def _confirmar(self, *matriculas):
        """Segundo paso: botón «Sí, actualizar» de la página de confirmación."""
        return self.client.post(self.url, {
            'action': 'aplicar_precio_actual', 'confirmar': '1',
            '_selected_action': [m.pk for m in matriculas],
        })

    def test_primero_muestra_confirmacion_sin_guardar(self):
        m = self._matricula('110.00', pagado='35.00')

        response = self._ver_confirmacion(m)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'admin/academia/matricula/aplicar_precio_actual.html')
        self.assertContains(response, 'Sí, actualizar 1 matrícula(s)')
        self.assertContains(response, '$110,00 → <strong>$90,00</strong>')
        self.assertContains(response, '$75,00 → <strong>$55,00</strong>')
        self.assertContains(response, '$20,00 · $20,00 · $20,00 · $20,00')
        m.refresh_from_db()
        self.assertEqual(m.valor_curso, Decimal('110.00'))

    def test_confirmar_baja_a_90_y_recalcula(self):
        m = self._matricula('110.00', pagado='35.00')

        response = self._confirmar(m)

        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        mensajes = [str(msg) for msg in response.wsgi_request._messages]
        self.assertEqual(
            mensajes, ['Se actualizaron 1 matrícula(s) al precio actual del curso.'],
        )
        m.refresh_from_db()
        self.assertEqual(m.valor_curso, Decimal('90.00'))
        self.assertEqual(m.valor_pagado, Decimal('35.00'))
        self.assertEqual(m.saldo, Decimal('55.00'))
        self.assertEqual(m.cuotas_modulos_objetivo(), [Decimal('20.00')] * 4)
        comprobante = Comprobante.objects.get(matricula=m)
        self.assertEqual(comprobante.diferencia, Decimal('55.00'))
        # Queda en el historial de la matrícula en el admin.
        registro = LogEntry.objects.get(object_id=str(m.pk))
        self.assertEqual(registro.user, self.admin)
        self.assertIn('$110,00 → $90,00', registro.change_message)

    def test_inscripcion_gratis_y_online_usan_su_precio(self):
        gratis = self._matricula('100.00', pagado='0.00', tipo='inscripcion_gratis')
        online = self._matricula('110.00', jornada=self.jornada_online)

        self._confirmar(gratis, online)

        gratis.refresh_from_db()
        online.refresh_from_db()
        self.assertEqual(gratis.valor_curso, Decimal('80.00'))
        self.assertEqual(gratis.cuotas_modulos_objetivo(), [Decimal('20.00')] * 4)
        self.assertEqual(online.valor_curso, Decimal('60.00'))
        self.assertEqual(online.cuotas_modulos_objetivo(), [Decimal('25.00')] * 2)

    def test_deja_igual_los_casos_que_no_corresponden(self):
        casos = {
            'Retiro voluntario': self._matricula('110.00', estado='retiro_voluntario'),
            'Tipo «Otros» (sin costo)': self._matricula('0.00', pagado='0.00', tipo='otros'),
            'Ya tiene el precio actual': self._matricula('90.00'),
            'Su valor es menor al precio actual ($90,00); no se sube': self._matricula('80.00'),
            'Tiene un descuento de $20,00: revísala a mano': self._matricula(
                '110.00', descuento=Decimal('20.00'),
            ),
            'Ya pagó $100,00, más que el nuevo valor': self._matricula(
                '110.00', pagado='100.00',
            ),
            'El curso no tiene precio en presencial': self._matricula(
                '110.00', jornada=self.jornada_sin_precio,
            ),
        }
        valores = {m.pk: m.valor_curso for m in casos.values()}

        response = self._ver_confirmacion(*casos.values())
        self.assertContains(response, 'Ninguna de las matrículas seleccionadas cambia de valor.')
        self.assertNotContains(response, 'Sí, actualizar')
        for motivo in casos:
            self.assertContains(response, motivo)

        self._confirmar(*casos.values())
        for m in casos.values():
            m.refresh_from_db()
            self.assertEqual(m.valor_curso, valores[m.pk])
        self.assertFalse(LogEntry.objects.exists())

    def test_seleccionar_todas_las_paginas_respeta_la_busqueda(self):
        # Como en la nube: hay más resultados de los que caben en una página
        # y se usa «seleccionar todas» sobre una búsqueda.
        excel = Curso.objects.create(
            nombre='Excel (prueba precio)', ofrece_presencial=True,
            valor_presencial=Decimal('90.00'), numero_modulos=4,
        )
        fuera_de_busqueda = self._matricula('110.00', jornada=JornadaCurso.objects.create(
            curso=excel, modalidad='presencial', descripcion='mar_jue',
            fecha_inicio=date(2026, 10, 6), sede=self.jornada.sede,
        ))
        servicio = [self._matricula('110.00') for _ in range(7)]
        url = f'{self.url}?q=Servicio'

        with patch.object(MatriculaAdmin, 'list_per_page', 5):
            response = self.client.post(url, {
                'action': 'aplicar_precio_actual', 'index': '0',
                'select_across': '1',
                '_selected_action': [m.pk for m in servicio[:5]],
            })
            self.assertContains(response, 'Sí, actualizar 7 matrícula(s)')
            seleccionadas = [
                int(pk) for pk in re.findall(
                    r'name="_selected_action" value="(\d+)"',
                    response.content.decode(),
                )
            ]
            self.assertCountEqual(seleccionadas, [m.pk for m in servicio])

            self.client.post(url, {
                'action': 'aplicar_precio_actual', 'confirmar': '1',
                '_selected_action': seleccionadas,
            })

        for m in servicio:
            m.refresh_from_db()
            self.assertEqual(m.valor_curso, Decimal('90.00'))
        fuera_de_busqueda.refresh_from_db()
        self.assertEqual(fuera_de_busqueda.valor_curso, Decimal('110.00'))

    def test_solo_aparece_con_permiso_de_cambiar(self):
        m = self._matricula('110.00')
        solo_lectura = User.objects.create_user(username='solo_lectura', is_staff=True)
        solo_lectura.user_permissions.add(
            Permission.objects.get(codename='view_matricula'),
        )
        self.client.force_login(solo_lectura)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'aplicar_precio_actual')

        self._confirmar(m)
        m.refresh_from_db()
        self.assertEqual(m.valor_curso, Decimal('110.00'))


class ExcedenteModuloTests(TestCase):
    """Un módulo cobrado a $25 antes de bajar el curso a módulos de $20."""

    def setUp(self):
        self.usuario = User.objects.create_superuser(username='admin_excedente')
        sede = Sede.objects.create(nombre='Guayaquil', orden=1)
        self.curso = Curso.objects.create(
            nombre='Servicio Técnico (prueba excedente)', ofrece_presencial=True,
            valor_presencial=Decimal('90.00'), numero_modulos=4,
        )
        self.jornada = JornadaCurso.objects.create(
            curso=self.curso, modalidad='presencial', descripcion='sabados_intensivos',
            fecha_inicio=date(2026, 10, 3), sede=sede,
        )
        estudiante = Estudiante.objects.create(cedula='1600000001', nombres='Estudiante Excedente')
        self.m = Matricula.objects.create(
            estudiante=estudiante, curso=self.curso, jornada=self.jornada,
            modalidad='presencial', tipo_matricula='reserva_abono',
            fecha_matricula=date(2026, 9, 20), valor_curso=Decimal('90.00'),
            tipo_registro='central_ia',
        )
        self._pagar('10.00', 'abono', None)

    def _pagar(self, monto, tipo='por_modulo', modulo=1):
        Abono.objects.create(
            matricula=self.m, fecha=date(2026, 10, 3), monto=Decimal(monto),
            tipo_pago=tipo, numero_modulo=modulo, metodo='efectivo',
        )
        self.m.refresh_from_db()

    def _modulos(self):
        return [(d['pagado'], d['estado']) for d in self.m.desglose_pagos_por_modulo()]

    def test_excedente_pasa_al_siguiente_modulo_como_en_la_hoja(self):
        self._pagar('25.00', modulo=1)

        self.assertEqual(self._modulos(), [
            (Decimal('20.00'), 'Pagado'), (Decimal('5.00'), 'Pendiente'),
            (Decimal('0.00'), 'Pendiente'), (Decimal('0.00'), 'Pendiente'),
        ])
        self.assertEqual(self.m.desglose_pagos_por_modulo()[0]['pagado_directo'], Decimal('25.00'))
        self.assertEqual(_detalle_modulo_pago(self.m, 2)['saldo'], Decimal('15.00'))
        plan = _plan_recaudacion_matricula(self.m, date(2026, 10, 10))
        self.assertEqual((plan['modulo'], plan['cuota_sugerida']), (2, Decimal('15.00')))

        self._pagar('15.00', modulo=2)

        self.assertEqual(self._modulos()[1], (Decimal('20.00'), 'Pagado'))
        self.assertEqual(_detalle_modulo_pago(self.m, 2)['saldo'], Decimal('0.00'))
        plan = _plan_recaudacion_matricula(self.m, date(2026, 10, 10))
        self.assertEqual((plan['modulo'], plan['cuota_sugerida']), (3, Decimal('20.00')))

    def test_excedente_grande_cubre_modulos_completos(self):
        self._pagar('50.00', modulo=1)

        self.assertEqual(self._modulos(), [
            (Decimal('20.00'), 'Pagado'), (Decimal('20.00'), 'Pagado'),
            (Decimal('10.00'), 'Pendiente'), (Decimal('0.00'), 'Pendiente'),
        ])

    def test_ultimo_modulo_conserva_lo_pagado_de_mas(self):
        self._pagar('30.00', modulo=4)

        self.assertEqual(self._modulos()[3], (Decimal('30.00'), 'Pagado'))

    def test_matriz_indica_lo_abonado_en_el_modulo_pendiente(self):
        self._pagar('25.00', modulo=1)
        self.client.force_login(self.usuario)

        response = self.client.get(
            reverse('academia:pagos_por_modulo'), {'curso': self.curso.pk},
        )

        self.assertContains(response, 'Abonado: $5,00')
