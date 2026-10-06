"""Filtro «Descuento» de Gestión de Pagos y del Historial.

Antes filtraba por `tiene_descuento`, que es una propiedad y no un campo:
elegir «Con descuento» o «Sin descuento» daba error 500."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import CierreCurso, Curso, Estudiante, Matricula, MatriculaArchivada


class FiltroDescuentoTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin_filtro_descuento')
        self.client.force_login(self.admin)
        curso = Curso.objects.create(
            nombre='Curso filtro descuento', ofrece_presencial=True,
            valor_presencial=Decimal('90.00'), numero_modulos=4,
        )
        for nombre, cedula, descuento in (
            ('Viva Con Descuento', '0911111111', '10.00'),
            ('Viva Sin Descuento', '0922222222', '0.00'),
        ):
            Matricula.objects.create(
                estudiante=Estudiante.objects.create(cedula=cedula, nombres=nombre),
                curso=curso, modalidad='presencial', tipo_matricula='reserva_abono',
                fecha_matricula=date(2026, 9, 20), valor_curso=Decimal('90.00'),
                descuento=Decimal(descuento), registrado_por=self.admin,
            )
        cierre = CierreCurso.objects.create(curso_nombre='Curso filtro descuento')
        for nombre, cedula, descuento in (
            ('Archivada Con Descuento', '0933333333', '5.00'),
            ('Archivada Sin Descuento', '0944444444', '0.00'),
        ):
            MatriculaArchivada.objects.create(
                cierre=cierre, cedula=cedula, nombres=nombre,
                curso_nombre='Curso filtro descuento', modalidad='presencial',
                fecha_matricula=date(2026, 8, 15), estado_pago='Pagado',
                valor_curso=Decimal('90.00'), descuento=Decimal(descuento),
            )

    def test_historial_filtra_vivas_y_archivadas_por_descuento(self):
        url = reverse('academia:historial_lista')
        con = self.client.get(url, {'descuento': 'si'})
        self.assertEqual(con.status_code, 200)
        self.assertContains(con, 'Viva Con Descuento')
        self.assertContains(con, 'Archivada Con Descuento')
        self.assertNotContains(con, 'Viva Sin Descuento')
        self.assertNotContains(con, 'Archivada Sin Descuento')

        sin = self.client.get(url, {'descuento': 'no'})
        self.assertEqual(sin.status_code, 200)
        self.assertContains(sin, 'Viva Sin Descuento')
        self.assertContains(sin, 'Archivada Sin Descuento')
        self.assertNotContains(sin, 'Viva Con Descuento')
        self.assertNotContains(sin, 'Archivada Con Descuento')

        todos = self.client.get(url)
        for nombre in ('Viva Con', 'Viva Sin', 'Archivada Con', 'Archivada Sin'):
            self.assertContains(todos, f'{nombre} Descuento')

    def test_pagos_y_exportaciones_con_filtro_de_descuento(self):
        for nombre in ('pagos_lista', 'pagos_export', 'pagos_export_pdf', 'historial_export'):
            for valor in ('si', 'no'):
                with self.subTest(vista=nombre, descuento=valor):
                    response = self.client.get(reverse(f'academia:{nombre}'), {'descuento': valor})
                    self.assertEqual(response.status_code, 200)

        con = self.client.get(reverse('academia:pagos_lista'), {'descuento': 'si'})
        self.assertContains(con, 'Viva Con Descuento')
        self.assertNotContains(con, 'Viva Sin Descuento')
