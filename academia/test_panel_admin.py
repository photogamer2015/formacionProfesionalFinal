"""Panel de administración: el detalle de movimientos y el libro mayor
muestran todas las clases de ingreso sin fallar, y la vista previa del
cierre global abre en cada modalidad."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import (
    Abono, Adicional, CategoriaEgreso, Comprobante, Curso, Egreso, Estudiante,
    Matricula,
)


class MovimientosPanelAdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin_panel_mov', first_name='Ana')
        self.client.force_login(self.admin)
        self.curso = Curso.objects.create(nombre='Contabilidad Básica', valor_presencial=Decimal('90.00'))
        self.estudiante = Estudiante.objects.create(cedula='0911111111', nombres='Luis Pérez')
        matricula = Matricula.objects.create(
            estudiante=self.estudiante, curso=self.curso, modalidad='presencial',
            tipo_matricula='reserva_abono', forma_pago='abono',
            fecha_matricula=date(2026, 10, 1), valor_curso=Decimal('90.00'),
            tipo_registro='central_1', registrado_por=self.admin,
        )
        Abono.objects.create(
            matricula=matricula, fecha=date(2026, 10, 1), monto=Decimal('10.00'),
            tipo_pago='abono', metodo='efectivo', observaciones='Reserva en caja',
        )
        # Venta cargada a mano en Comprobantes (sin matrícula).
        Comprobante.objects.create(
            curso=self.curso, modalidad='presencial', fecha_inscripcion=date(2026, 10, 2),
            inicio_curso=date(2026, 10, 10), jornada='Sábados',
            nombre_persona='María Manual', celular='0991234567',
            pago_abono=Decimal('25.00'), diferencia=Decimal('65.00'), vendedora=self.admin,
        )
        Adicional.objects.create(
            tipo_adicional='camisa', estudiante=self.estudiante, fecha=date(2026, 10, 2),
            valor=Decimal('8.00'), metodo_pago='efectivo', observaciones='Talla M',
        )
        Egreso.objects.create(
            fecha=date(2026, 10, 3), categoria=CategoriaEgreso.objects.create(nombre='Servicios'),
            concepto='Internet', monto=Decimal('30.00'), registrado_por=self.admin,
        )
        self.rango = {'desde': '2026-10-01', 'hasta': '2026-10-31'}

    def test_panel_lista_todos_los_movimientos(self):
        response = self.client.get(reverse('academia:admin_dashboard'), self.rango)
        self.assertEqual(response.status_code, 200)
        movimientos = {
            (m['categoria'], m['concepto'], m['involucrado'])
            for m in response.context['movimientos_rango']
        }
        self.assertIn(('Venta (Comprobante)', 'Contabilidad Básica', 'María Manual'), movimientos)
        self.assertIn(('Abono (Abono)', 'Contabilidad Básica - Reserva en caja', 'Luis Pérez'), movimientos)
        self.assertIn(('Adicional', 'Camisa (Talla M)', 'Luis Pérez'), movimientos)

    def test_libro_mayor_exporta_todos_los_movimientos(self):
        response = self.client.get(reverse('academia:admin_export_libro_mayor'), self.rango)
        self.assertEqual(response.status_code, 200)
        contenido = response.content.decode('utf-8-sig')
        self.assertIn('Contabilidad Básica - Reserva en caja,Luis Pérez,10.00', contenido)
        self.assertIn('Venta (Comprobante),Contabilidad Básica,María Manual,25.00', contenido)
        self.assertIn('Camisa (Talla M),Luis Pérez,8.00', contenido)
        self.assertIn('Internet,Ana,-30.00', contenido)


class CierreGlobalPreviewTests(TestCase):
    def test_abre_en_cada_modalidad(self):
        self.client.force_login(User.objects.create_superuser('admin_cierre_global'))
        for modalidad in ('presencial', 'online', 'todas'):
            url = reverse('academia:cierre_global_preview', kwargs={'modalidad': modalidad})
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, modalidad)
            # «Limpiar» vuelve a la misma modalidad.
            self.assertContains(response, f'href="{url}" class="btn btn-sm btn-secondary">Limpiar')
