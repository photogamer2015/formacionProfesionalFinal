from datetime import date, timedelta
from decimal import Decimal

from django import forms
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .fecha_matricula import FECHA_MINIMA, fecha_maxima, validar_fecha_matricula
from .forms import MatriculaForm
from .models import Abono, Curso, Estudiante, JornadaCurso, Matricula, Sede
from .test_registro_estudiantil import RegistroBase


def hoy():
    return timezone.localdate()


class ValidarFechaTests(TestCase):
    def test_fecha_maxima_es_fin_del_mes_subsiguiente(self):
        self.assertEqual(fecha_maxima(date(2026, 10, 7)), date(2026, 12, 31))
        self.assertEqual(fecha_maxima(date(2026, 11, 30)), date(2027, 1, 31))
        self.assertEqual(fecha_maxima(date(2026, 12, 1)), date(2027, 2, 28))
        self.assertEqual(fecha_maxima(date(2027, 12, 31)), date(2028, 2, 29))
        self.assertEqual(fecha_maxima(date(2026, 1, 31)), date(2026, 3, 31))

    def test_desde_la_minima_hasta_fin_del_mes_subsiguiente_son_validas(self):
        for fecha in (
            hoy(), hoy() - timedelta(days=40), FECHA_MINIMA,
            hoy() + timedelta(days=1), fecha_maxima(),
        ):
            self.assertEqual(validar_fecha_matricula(fecha), fecha)

    def test_fecha_muy_adelante_o_muy_antigua_no_es_valida(self):
        for fecha in (
            fecha_maxima() + timedelta(days=1),
            hoy() + timedelta(days=4 * 365),
            FECHA_MINIMA - timedelta(days=1),
        ):
            with self.assertRaises(forms.ValidationError):
                validar_fecha_matricula(fecha)


class MatriculaFormFechaTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin_fecha', password='x')
        self.curso = Curso.objects.create(
            nombre='Curso Fecha', ofrece_presencial=True,
            valor_presencial=Decimal('115.00'), numero_modulos=4,
        )
        self.jornada = JornadaCurso.objects.create(
            curso=self.curso, modalidad='presencial', descripcion='lun_mie_vie',
            fecha_inicio=hoy(), sede=Sede.objects.create(nombre='Guayaquil'),
        )

    def datos(self, fecha):
        return {
            'mat-curso': str(self.curso.pk), 'mat-jornada': str(self.jornada.pk),
            'mat-estado': 'activa', 'mat-tipo_matricula': 'reserva_abono',
            'mat-forma_pago': 'abono', 'mat-fecha_matricula': fecha,
            'mat-valor_curso': '115.00', 'mat-descuento': '0.00',
            'mat-valor_pagado': '10.00', 'mat-tipo_registro': 'central_ia',
            'mat-tipo_cobro': 'un_solo_metodo', 'mat-metodo_pago': 'efectivo',
        }

    def test_registrar_acepta_hasta_fin_del_mes_subsiguiente(self):
        for fecha in (hoy(), hoy() + timedelta(days=20), fecha_maxima()):
            self.assertTrue(
                MatriculaForm(self.datos(fecha.isoformat()), prefix='mat').is_valid()
            )
        siguiente = (fecha_maxima() + timedelta(days=1)).isoformat()
        self.assertFalse(MatriculaForm(self.datos(siguiente), prefix='mat').is_valid())
        futura = (hoy() + timedelta(days=4 * 365)).isoformat()
        form = MatriculaForm(self.datos(futura), prefix='mat')
        self.assertFalse(form.is_valid())
        self.assertIn('se aceptan fechas hasta', form.errors['fecha_matricula'][0])

    def test_editar_sin_cambiar_una_fecha_antigua_rara_no_bloquea(self):
        futura = hoy() + timedelta(days=4 * 365)
        m = Matricula.objects.create(
            estudiante=Estudiante.objects.create(cedula='0900000123', nombres='Ana'),
            curso=self.curso, jornada=self.jornada, modalidad='presencial',
            fecha_matricula=futura, valor_curso=Decimal('115.00'),
        )
        form = MatriculaForm(
            self.datos(futura.isoformat()), prefix='mat', instance=m,
            captura_pago=False,
        )
        form.is_valid()
        self.assertNotIn('fecha_matricula', form.errors)
        # El calendario no limita una fecha que ya está fuera de rango.
        self.assertNotIn('max', form.fields['fecha_matricula'].widget.attrs)

    def test_registrar_llega_con_la_fecha_de_hoy_y_el_calendario_limitado(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse('academia:matricula_registrar', args=['presencial'])
        )
        self.assertEqual(response.status_code, 200)
        campo = str(response.context['mat_form']['fecha_matricula'])
        self.assertIn(f'value="{hoy().isoformat()}"', campo)
        self.assertIn(f'max="{fecha_maxima().isoformat()}"', campo)
        self.assertIn('data-fecha-matricula', campo)
        self.assertContains(response, 'Recuerda poner bien la fecha')


class EdicionVentaFechaTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin_venta_fecha', password='x')
        self.client.force_login(self.admin)
        self.fecha = hoy() - timedelta(days=3)
        self.m = Matricula.objects.create(
            estudiante=Estudiante.objects.create(cedula='0900000124', nombres='Luis'),
            curso=Curso.objects.create(nombre='Curso'), modalidad='presencial',
            fecha_matricula=self.fecha, valor_curso=100,
            registrado_por=self.admin, vendedora=self.admin, tipo_registro='central_ia',
        )
        Abono.objects.create(matricula=self.m, monto=20, fecha=self.fecha,
                             metodo='efectivo', tipo_pago='abono')
        self.url = reverse('academia:matricula_editar', args=['presencial', self.m.pk])

    def _post(self, fecha, estado='activa'):
        return self.client.post(self.url, {
            'editar_seccion': 'matricula', 'estado': estado, 'fecha_matricula': fecha,
        })

    def test_pantalla_muestra_la_ayuda_de_la_fecha(self):
        response = self.client.get(self.url, {'editar_seccion': 'matricula'})
        self.assertContains(response, 'data-fecha-matricula')
        self.assertContains(response, f'max="{fecha_maxima().isoformat()}"')
        self.assertContains(response, 'Recuerda poner bien la fecha')

    def test_fecha_futura_no_guarda(self):
        futura = hoy() + timedelta(days=4 * 365)
        response = self._post(futura.isoformat())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'se aceptan fechas hasta')
        self.m.refresh_from_db()
        self.assertEqual(self.m.fecha_matricula, self.fecha)

    def test_fecha_valida_guarda(self):
        nueva = hoy() - timedelta(days=5)
        self.assertEqual(self._post(nueva.isoformat()).status_code, 302)
        self.m.refresh_from_db()
        self.assertEqual(self.m.fecha_matricula, nueva)

    def test_fecha_futura_ya_guardada_no_impide_cambiar_el_estado(self):
        futura = hoy() + timedelta(days=4 * 365)
        Matricula.objects.filter(pk=self.m.pk).update(fecha_matricula=futura)
        response = self._post(futura.isoformat(), estado='retiro_voluntario')
        self.assertEqual(response.status_code, 302)
        self.m.refresh_from_db()
        self.assertEqual(self.m.estado, 'retiro_voluntario')


class RegistroEstudiantilFechaTests(RegistroBase):
    def test_hoja_rechaza_fecha_futura(self):
        futura = (hoy() + timedelta(days=4 * 365)).isoformat()
        response, datos = self.guardar(fecha_matricula=futura)
        self.assertEqual(response.status_code, 400)
        self.assertIn('fecha_matricula', datos['campos'])
        self.assertTrue(any('se aceptan fechas hasta' in m for m in datos['mensajes']))
