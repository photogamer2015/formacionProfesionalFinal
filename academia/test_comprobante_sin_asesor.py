"""Registrar / editar un comprobante sin elegir asesor.

El formulario es «novalidate», así que se puede enviar con «— Selecciona un
asesor —» (valor vacío). Antes buscar el usuario con id='' daba error 500;
ahora se muestra «Debes seleccionar un asesor válido.»."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Comprobante, Curso


class ComprobanteSinAsesorTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin_comprobante_sin_asesor')
        self.client.force_login(self.admin)
        self.curso = Curso.objects.create(
            nombre='Curso comprobante', ofrece_presencial=True,
            valor_presencial=Decimal('90.00'),
        )

    def test_registrar_sin_asesor_muestra_el_aviso(self):
        for valor in ('', 'abc'):
            with self.subTest(vendedora_id=valor):
                response = self.client.post(
                    reverse('academia:comprobante_registrar'), {'vendedora_id': valor},
                )
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'Debes seleccionar un asesor válido.')
        self.assertFalse(Comprobante.objects.exists())

    def test_editar_sin_asesor_muestra_el_aviso(self):
        comp = Comprobante.objects.create(
            curso=self.curso, modalidad='presencial', fecha_inscripcion=date(2026, 10, 2),
            inicio_curso=date(2026, 10, 10), jornada='Sábados',
            nombre_persona='María Manual', celular='0991234567',
            pago_abono=Decimal('25.00'), diferencia=Decimal('65.00'), vendedora=self.admin,
        )
        response = self.client.post(
            reverse('academia:comprobante_editar', args=[comp.pk]), {'vendedora_id': ''},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Debes seleccionar un asesor válido.')
        comp.refresh_from_db()
        self.assertEqual(comp.vendedora, self.admin)

    def test_registrar_matricula_con_asesor_invalido_no_falla(self):
        response = self.client.post(
            reverse('academia:matricula_registrar', args=['presencial']),
            {'vendedora_id': 'abc'},
        )
        self.assertLess(response.status_code, 500)
