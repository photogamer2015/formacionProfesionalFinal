"""«¿Deseas registrar la factura ahora mismo?» al registrar la matrícula.

Por defecto «No» (la factura se registra después en Facturas). Con «Sí» se
piden los mismos datos que en «Registrar factura» y la matrícula queda ya
facturada: sale en la Lista de Facturas y no en «Matrículas sin factura».
"""
import re
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Abono, Comprobante, Curso, Estudiante, JornadaCurso, Matricula, Sede
from .permisos import GRUPO_ASESOR


class FacturaAlMatricularTests(TestCase):
    def setUp(self):
        self.asesora = User.objects.create_user('asesora_factura_matricula', first_name='Melanie')
        self.asesora.groups.add(Group.objects.get_or_create(name=GRUPO_ASESOR)[0])
        self.curso = Curso.objects.create(
            nombre='Curso factura al matricular', ofrece_presencial=True,
            valor_presencial=Decimal('115.00'), numero_modulos=4,
        )
        self.jornada = JornadaCurso.objects.create(
            curso=self.curso, modalidad='presencial', descripcion='lun_mie_vie',
            fecha_inicio=timezone.localdate(), sede=Sede.objects.create(nombre='Guayaquil'),
        )
        self.url = reverse('academia:matricula_registrar', args=['presencial'])
        self.client.force_login(self.asesora)

    def _post(self, **extra):
        datos = {
            'est-cedula': '0912345678', 'est-nombres': 'Ana Pérez',
            'est-correo': 'ana@example.com', 'est-celular': '0991234567',
            'est-ciudad': 'Guayaquil', 'est-edad': '', 'est-nivel_formacion': '',
            'est-titulo_profesional': '',
            'mat-curso': str(self.curso.pk), 'mat-jornada': str(self.jornada.pk),
            'mat-estado': 'activa', 'mat-tipo_matricula': 'reserva_abono',
            'mat-forma_pago': 'abono', 'mat-fecha_matricula': timezone.localdate().isoformat(),
            'mat-valor_curso': '115.00', 'mat-descuento': '0.00', 'mat-valor_pagado': '10.00',
            'mat-tipo_registro': 'central_ia', 'mat-tipo_cobro': 'un_solo_metodo',
            'mat-metodo_pago': 'efectivo', 'vendedora_id': str(self.asesora.pk),
        }
        datos.update(extra)
        return self.client.post(self.url, datos)

    def _matricula(self):
        return Matricula.objects.get(estudiante__cedula='0912345678')

    def _en_listas(self, matricula):
        con = self.client.get(reverse('academia:matricula_facturas')).context['matriculas']
        sin = self.client.get(reverse('academia:matricula_sin_factura')).context['matriculas']
        return matricula in con, matricula in sin

    def test_la_pregunta_sale_con_no_por_defecto(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('¿Deseas registrar la factura ahora mismo?', html)
        no = re.search(r'<input[^>]*name="fac-registrar"[^>]*value="no"[^>]*>', html).group(0)
        si = re.search(r'<input[^>]*name="fac-registrar"[^>]*value="si"[^>]*>', html).group(0)
        self.assertIn('checked', no)
        self.assertNotIn('checked', si)
        # Los datos de la factura están, pero ocultos hasta elegir «Sí».
        self.assertIn('id="fm-campos" hidden', html)
        for name in ('fac-fact_nombres', 'fac-fact_cedula', 'fac-fact_correo', 'fac-numero_factura'):
            self.assertIn(f'name="{name}"', html)
        self.assertIn('Cambiar los datos', html)
        self.assertNotIn('La factura ya no se registra aquí', html)

    def test_con_no_queda_para_registrar_factura_despues(self):
        response = self._post(**{
            'fac-registrar': 'no', 'fac-numero_factura': '123',
            'fac-cambiar_datos': '1', 'fac-fact_nombres': 'Otra persona',
        })
        self.assertEqual(response.status_code, 302)
        m = self._matricula()
        self.assertEqual(m.factura_realizada, 'no')
        self.assertEqual((m.fact_nombres, m.fact_cedula, m.numero_factura), ('', '', ''))
        self.assertEqual(self._en_listas(m), (False, True))

    def test_con_si_registra_la_factura_con_los_datos_del_estudiante(self):
        # Sin «Cambiar los datos» se ignora lo que llegue en el titular.
        response = self._post(**{
            'fac-registrar': 'si', 'fac-cambiar_datos': '0',
            'fac-fact_nombres': 'Otra persona', 'fac-fact_cedula': '0999999999',
            'fac-numero_factura': '001-001-000000123',
        })
        self.assertEqual(response.status_code, 302)
        m = self._matricula()
        self.assertEqual(m.factura_realizada, 'si')
        self.assertEqual(m.fact_nombres, 'Ana Pérez')
        self.assertEqual(m.fact_cedula, '0912345678')
        self.assertEqual(m.fact_correo, 'ana@example.com')
        self.assertEqual(m.numero_factura, '001001000000123')
        # El pago y lo demás de la matrícula se guardan como siempre.
        self.assertEqual(m.valor_pagado, Decimal('10.00'))
        self.assertEqual(m.abonos.count(), 1)
        self.assertEqual(m.vendedora, self.asesora)
        comprobante = Comprobante.objects.get(matricula=m)
        self.assertEqual((comprobante.factura_realizada, comprobante.fact_nombres), ('si', 'Ana Pérez'))
        # Ya está en la Lista de Facturas y no vuelve a salir para registrarla.
        self.assertEqual(self._en_listas(m), (True, False))
        avisos = [str(a) for a in get_messages(response.wsgi_request)]
        self.assertTrue(any('Factura N.º 001001000000123 registrada' in a for a in avisos), avisos)

    def test_con_si_y_estudiante_existente_usa_sus_datos_actualizados(self):
        Estudiante.objects.create(cedula='0912345678', nombres='Ana Vieja', correo='viejo@example.com')
        self._post(**{
            'fac-registrar': 'si', 'fac-cambiar_datos': '0', 'fac-numero_factura': '321',
        })
        m = self._matricula()
        self.assertEqual(Estudiante.objects.filter(cedula='0912345678').count(), 1)
        self.assertEqual((m.fact_nombres, m.fact_correo), ('Ana Pérez', 'ana@example.com'))
        self.assertEqual(m.estudiante.nombres, 'Ana Pérez')

    def test_cambiar_los_datos_factura_a_otra_persona(self):
        self._post(**{
            'fac-registrar': 'si', 'fac-cambiar_datos': '1',
            'fac-fact_nombres': 'Empresa XYZ', 'fac-fact_cedula': '0990 000 000 001',
            'fac-fact_correo': '', 'fac-numero_factura': '000124',
        })
        m = self._matricula()
        self.assertEqual(m.factura_realizada, 'si')
        self.assertEqual(m.fact_nombres, 'Empresa XYZ')
        self.assertEqual(m.fact_cedula, '0990000000001')
        self.assertEqual(m.fact_correo, '')
        self.assertEqual(m.numero_factura, '000124')
        # Los datos del estudiante no cambian por la factura.
        self.assertEqual(m.estudiante.nombres, 'Ana Pérez')

    def test_con_si_el_numero_es_obligatorio_y_solo_numeros(self):
        for numero in ('', 'ABC-123', '12a4'):
            with self.subTest(numero=numero):
                response = self._post(**{
                    'fac-registrar': 'si', 'fac-cambiar_datos': '0', 'fac-numero_factura': numero,
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(set(response.context['fact_form'].errors), {'numero_factura'})
                # Al volver, la factura sigue abierta con «Sí».
                self.assertNotIn('id="fm-campos" hidden', response.content.decode())
        self.assertFalse(Matricula.objects.exists())
        self.assertFalse(Abono.objects.exists())

    def test_con_otra_persona_nombres_y_cedula_son_obligatorios(self):
        response = self._post(**{
            'fac-registrar': 'si', 'fac-cambiar_datos': '1',
            'fac-fact_nombres': '', 'fac-fact_cedula': '09AB', 'fac-numero_factura': '555',
        })
        self.assertEqual(response.status_code, 200)
        form = response.context['fact_form']
        self.assertEqual(set(form.errors), {'fact_nombres', 'fact_cedula'})
        self.assertTrue(form.titular_editable)
        self.assertFalse(Matricula.objects.exists())

    def test_sin_la_pregunta_cuenta_como_no(self):
        # Un formulario abierto antes del cambio no envía «fac-registrar».
        self.assertEqual(self._post().status_code, 302)
        self.assertEqual(self._matricula().factura_realizada, 'no')

    def test_numero_repetido_se_guarda_con_aviso(self):
        otra = Matricula.objects.create(
            estudiante=Estudiante.objects.create(cedula='0922222222', nombres='Eva Ruiz'),
            curso=self.curso, modalidad='presencial', fecha_matricula=timezone.localdate(),
            valor_curso=Decimal('115.00'), factura_realizada='si', numero_factura='000777',
        )
        response = self._post(**{
            'fac-registrar': 'si', 'fac-cambiar_datos': '0', 'fac-numero_factura': '000777',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._matricula().numero_factura, '000777')
        avisos = [str(a) for a in get_messages(response.wsgi_request)]
        self.assertTrue(any(f'matrícula #{otra.pk}' in a for a in avisos), avisos)
