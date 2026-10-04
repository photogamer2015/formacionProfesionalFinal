from datetime import date, time
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Abono, Curso, Estudiante, JornadaCurso, Matricula, Sede


class ReciboWhatsAppJornadaTests(TestCase):
    """«Copiar para WhatsApp» del recibo muestra la jornada de la matrícula."""

    def setUp(self):
        self.admin = User.objects.create_superuser('admin_recibo_whatsapp')
        self.client.force_login(self.admin)
        curso = Curso.objects.create(
            nombre='Curso recibo WhatsApp', ofrece_presencial=True,
            valor_presencial=Decimal('90.00'),
        )
        self.jornada = JornadaCurso.objects.create(
            curso=curso, modalidad='presencial', descripcion='lun_mie_vie',
            fecha_inicio=date(2026, 8, 24),
            sede=Sede.objects.create(nombre='Guayaquil', orden=1),
        )
        self.matricula = Matricula.objects.create(
            estudiante=Estudiante.objects.create(cedula='0912345670', nombres='Yandri David'),
            curso=curso, jornada=self.jornada, modalidad='presencial',
            tipo_matricula='reserva_abono', forma_pago='abono',
            fecha_matricula=date(2026, 8, 20), valor_curso=Decimal('90.00'),
            tipo_registro='central_ia', registrado_por=self.admin,
        )
        self.abono = Abono.objects.create(
            matricula=self.matricula, fecha=date(2026, 9, 30),
            monto=Decimal('10.00'), tipo_pago='abono', metodo='efectivo',
            registrado_por=self.admin,
        )

    def texto_whatsapp(self):
        response = self.client.get(reverse('academia:abono_recibo', args=[self.abono.pk]))
        self.assertEqual(response.status_code, 200)
        # Las notas internas de la plantilla nunca deben verse en la página.
        self.assertNotContains(response, '{#')
        html = response.content.decode()
        inicio = html.index('const texto = `')
        return html[inicio:html.index('`;', inicio)]

    def test_muestra_los_dias_de_la_jornada(self):
        texto = self.texto_whatsapp()
        self.assertIn('*JORNADA:* LUN, MIÉ, VIE.\n', texto)
        self.assertNotIn('*JORNADA:* N/A', texto)
        self.assertIn('*INICIO DE CURSO:* 24 DE AGOSTO\n', texto)

    def test_agrega_el_horario_si_la_jornada_lo_tiene(self):
        JornadaCurso.objects.filter(pk=self.jornada.pk).update(
            hora_inicio=time(18, 0), hora_fin=time(21, 0),
        )
        self.assertIn('*JORNADA:* LUN, MIÉ, VIE. (18:00 A 21:00)\n', self.texto_whatsapp())

    def test_dias_en_texto_libre_no_rompen_el_texto_copiado(self):
        JornadaCurso.objects.filter(pk=self.jornada.pk).update(
            descripcion='otros', descripcion_otros='Lunes `y` viernes',
        )
        self.assertIn('*JORNADA:* LUNES \\u0060Y\\u0060 VIERNES\n', self.texto_whatsapp())

    def test_sin_jornada_muestra_na(self):
        Matricula.objects.filter(pk=self.matricula.pk).update(jornada=None)
        self.assertIn('*JORNADA:* N/A\n', self.texto_whatsapp())

    def test_factura_realizada_sale_de_la_matricula(self):
        # Antes leía abono.factura_realizada, que no existe: siempre decía NO.
        self.assertIn('*FACTURA REALIZADA:* NO\n', self.texto_whatsapp())
        Matricula.objects.filter(pk=self.matricula.pk).update(factura_realizada='si')
        self.assertIn('*FACTURA REALIZADA:* SÍ\n', self.texto_whatsapp())
        Matricula.objects.filter(pk=self.matricula.pk).update(numero_factura='001001000000123')
        self.assertIn('*FACTURA REALIZADA:* SÍ (N.º 001001000000123)\n', self.texto_whatsapp())
