from datetime import date

from django.test import TestCase

from .forms import RecuperacionPendienteForm
from .models import Curso, Estudiante, Matricula


class RecuperacionPendienteFormTests(TestCase):
    def setUp(self):
        self.curso = Curso.objects.create(
            nombre='Servicio Técnico - prueba recuperación',
            numero_modulos=4,
        )
        estudiante = Estudiante.objects.create(
            cedula='9999999999',
            nombres='Estudiante de prueba',
        )
        self.matricula = Matricula.objects.create(
            estudiante=estudiante,
            curso=self.curso,
            modalidad='presencial',
            fecha_matricula=date(2026, 9, 1),
            valor_curso=0,
        )

    def test_consolas_de_videojuegos_usa_un_valor_valido_del_modelo(self):
        form = RecuperacionPendienteForm(
            data={
                'numero_modulo': '2',
                'fecha_marcada': '2026-09-26',
                'fecha_programada': '2026-10-24',
                'tipo_equipo': 'consolas_videojuegos',
                'observaciones': 'Reposo',
            },
            matricula=self.matricula,
        )

        self.assertTrue(form.is_valid(), form.errors.as_text())
        self.assertEqual(
            form.cleaned_data['tipo_equipo'],
            'consolas_videojuegos',
        )
        self.assertIn(
            ('consolas_videojuegos', 'Consolas de videojuegos'),
            form.fields['tipo_equipo'].choices,
        )

    def test_fecha_de_recuperacion_no_puede_ser_anterior_a_la_falta(self):
        form = RecuperacionPendienteForm(
            data={
                'numero_modulo': '2',
                'fecha_marcada': date(2026, 9, 26),
                'fecha_programada': date(2026, 9, 25),
                'tipo_equipo': 'laptops_computadora',
                'observaciones': '',
            },
            matricula=self.matricula,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('fecha_programada', form.errors)
