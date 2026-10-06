"""Descargas en Excel cuyo nombre de hoja sale de los datos.

Excel no acepta \\ / : * ? [ ] en el nombre de una hoja: un estudiante con
«:» en el nombre hacía fallar «Exportar» de su ficha (error 500)."""
from datetime import date
from decimal import Decimal
from io import BytesIO

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from openpyxl import load_workbook

from .models import Curso, Estudiante, Matricula
from .views_pagos import _titulo_hoja_excel


class TituloHojaExcelTests(SimpleTestCase):
    def test_quita_caracteres_no_validos_y_recorta(self):
        self.assertEqual(_titulo_hoja_excel('Ana: Pérez/López [2]?*'), 'Ana_ Pérez_López _2___')
        self.assertEqual(len(_titulo_hoja_excel('x' * 50)), 31)
        self.assertEqual(_titulo_hoja_excel("'Nombre'"), 'Nombre')
        self.assertEqual(_titulo_hoja_excel(''), 'Hoja')
        self.assertEqual(_titulo_hoja_excel(None), 'Hoja')
        self.assertEqual(_titulo_hoja_excel('Reporte de Pagos'), 'Reporte de Pagos')


class DescargasExcelConNombresRarosTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin_titulo_hoja')
        self.client.force_login(self.admin)
        self.curso = Curso.objects.create(
            nombre='Excel: Básico / Avanzado', ofrece_presencial=True,
            valor_presencial=Decimal('90.00'), numero_modulos=4,
        )
        self.estudiante = Estudiante.objects.create(
            cedula='0955555555', nombres='Ana María: Pérez/López',
        )
        Matricula.objects.create(
            estudiante=self.estudiante, curso=self.curso, modalidad='presencial',
            tipo_matricula='reserva_abono', fecha_matricula=date(2026, 9, 20),
            valor_curso=Decimal('90.00'), registrado_por=self.admin,
        )

    def _hoja(self, response):
        self.assertEqual(response.status_code, 200)
        return load_workbook(BytesIO(response.content)).active.title

    def test_exportar_ficha_del_estudiante(self):
        response = self.client.get(reverse('academia:estudiante_export', args=[self.estudiante.pk]))
        self.assertEqual(self._hoja(response), 'Ana María_ Pérez_López')

    def test_exportar_pagos_por_modulo_de_un_curso_con_dos_puntos(self):
        response = self.client.get(
            reverse('academia:pagos_por_modulo_export_excel'), {'curso': self.curso.pk},
        )
        self.assertEqual(self._hoja(response), 'Pagos por Módulo - Excel_ Básic')
