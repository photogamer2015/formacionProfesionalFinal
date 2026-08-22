from datetime import date, time
from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings

from .correos_matricula import (
    enviar_confirmacion_matricula, formulario_inscripcion_para_curso,
)
from .models import (
    ConfirmacionMatriculaCorreo, Curso, Estudiante, JornadaCurso, Matricula,
)
from .views import _programar_confirmacion_matricula


SMTP_CONFIG = {
    'host': 'smtp.example.com',
    'port': 587,
    'use_ssl': False,
    'use_tls': True,
    'username': 'cuenta@example.com',
    'password': 'clave-prueba',
    'from_email': 'cuenta@example.com',
}


class FormulariosInscripcionCursoTests(SimpleTestCase):
    def test_cada_nombre_real_del_sistema_recibe_su_enlace_correcto(self):
        casos = {
            'Asistente Contable': 'https://forms.gle/QsYEbKLveSy8TDjH8',
            'Automatización con Python': 'https://forms.gle/qvUb589ueCvb8Ng69',
            'Corte y Confección': 'https://forms.gle/Z1HshJtL1p9yej4R8',
            'Ebanistería Integral': 'https://forms.gle/ZFXH2zy9KTa7zdePA',
            'Electricidad Residencial': 'https://forms.gle/QvsStr8ERDM62mNm9',
            'Excel': 'https://forms.gle/HsfHYm5NF14a92ZMA',
            'Gestión de Talento Humano': 'https://forms.gle/9m2at3GA65RrUyQN6',
            'Impresión 3D': 'https://forms.gle/oev5HpfrZuez6utq5',
            'Línea Blanca': 'https://forms.gle/pw8V2Jj7twumbMhx6',
            'Marketing Digital': 'https://forms.gle/2weGDubEMpJUo5qy5',
            'Mecánica de Motos': 'https://forms.gle/azR9AtMRw5rQciL77',
            'Refrigeración y Aires Acondicionados': 'https://forms.gle/ohbk6fEmRaQdNw34A',
            'Servicio Técnico': 'https://forms.gle/RvghnEhRuNHZfwfX7',
            'Talento Humano': 'https://forms.gle/9m2at3GA65RrUyQN6',
            'Tributación contable': 'https://forms.gle/vKZRUPWh6eSSHAn26',
        }

        for nombre, url in casos.items():
            with self.subTest(nombre=nombre):
                self.assertEqual(
                    formulario_inscripcion_para_curso(nombre)['url'], url,
                )

    def test_mapeo_ignora_tildes_mayusculas_y_texto_posterior(self):
        formulario = formulario_inscripcion_para_curso(
            '  PYTHON PROFESIONAL Y AUTOMATIZACIÓN - ONLINE '
        )
        self.assertEqual(
            formulario['url'], 'https://forms.gle/qvUb589ueCvb8Ng69',
        )

    def test_curso_sin_formulario_no_recibe_un_enlace_incorrecto(self):
        self.assertIsNone(
            formulario_inscripcion_para_curso('Curso nuevo sin formulario')
        )


@override_settings(ENROLLMENT_CONFIRMATION_EMAIL_ENABLED=True)
class ConfirmacionMatriculaCorreoTests(TestCase):
    def setUp(self):
        self.estudiante = Estudiante.objects.create(
            cedula='0912345678',
            nombres='María Fernanda López',
            edad=27,
            correo='maria@example.com',
            celular='0991234567',
            nivel_formacion='tercer_nivel',
            titulo_profesional='Ingeniera Comercial',
            ciudad='Guayaquil',
        )
        self.curso = Curso.objects.get(nombre='Automatización con Python')
        self.curso.ofrece_presencial = False
        self.curso.ofrece_online = True
        self.curso.valor_online = Decimal('60.00')
        self.curso.numero_modulos_online = 2
        self.curso.save(update_fields=[
            'ofrece_presencial', 'ofrece_online', 'valor_online',
            'numero_modulos_online',
        ])
        self.jornada = JornadaCurso.objects.create(
            curso=self.curso,
            modalidad='online',
            descripcion='otros',
            descripcion_otros='Martes y jueves en vivo',
            fecha_inicio=date(2026, 8, 25),
            hora_inicio=time(19, 0),
            hora_fin=time(21, 0),
            ciudad='Zoom',
        )
        self.matricula = Matricula.objects.create(
            estudiante=self.estudiante,
            curso=self.curso,
            jornada=self.jornada,
            modalidad='online',
            tipo_matricula='reserva_abono',
            forma_pago='abono',
            fecha_matricula=date(2026, 8, 21),
            talla_camiseta='M',
            valor_curso=Decimal('60.00'),
            descuento=Decimal('5.00'),
            valor_pagado=Decimal('10.00'),
        )

    @patch('academia.correos_matricula.config_correo_mfa', return_value=SMTP_CONFIG)
    @patch('academia.correos_pago.smtplib.SMTP')
    def test_envia_template_completo_con_formulario_correcto(
        self, smtp_mock, _config_mock,
    ):
        resultado = enviar_confirmacion_matricula(self.matricula.pk)

        self.assertEqual(resultado['estado'], 'enviado')
        servidor = smtp_mock.return_value
        servidor.send_message.assert_called_once()
        mensaje = servidor.send_message.call_args.args[0]
        texto = mensaje.get_body(preferencelist=('plain',)).get_content()
        html = mensaje.get_body(preferencelist=('html',)).get_content()

        self.assertEqual(mensaje['To'], 'maria@example.com')
        self.assertIn('Confirmación de matrícula', mensaje['Subject'])
        for contenido in (
            'María Fernanda López', '0912345678', '0991234567',
            'Ingeniera Comercial', '21/08/2026',
            'Automatización con Python', 'Martes y jueves en vivo',
            '25/08/2026', '19:00 a 21:00', 'Zoom',
            'https://forms.gle/qvUb589ueCvb8Ng69',
        ):
            self.assertIn(contenido, texto)
        self.assertIn('Completar formulario de inscripción', html)
        self.assertIn(
            'href="https://forms.gle/qvUb589ueCvb8Ng69"', html,
        )
        self.assertGreater(
            texto.index('https://forms.gle/qvUb589ueCvb8Ng69'),
            texto.index('RESUMEN FINANCIERO'),
        )

        registro = ConfirmacionMatriculaCorreo.objects.get(
            matricula=self.matricula,
        )
        self.assertEqual(
            registro.estado, ConfirmacionMatriculaCorreo.ESTADO_ENVIADO,
        )
        self.assertEqual(
            registro.formulario_url,
            'https://forms.gle/qvUb589ueCvb8Ng69',
        )

    @patch('academia.correos_matricula.config_correo_mfa', return_value=SMTP_CONFIG)
    @patch('academia.correos_pago.smtplib.SMTP')
    def test_no_duplica_confirmacion_de_la_misma_matricula(
        self, smtp_mock, _config_mock,
    ):
        primero = enviar_confirmacion_matricula(self.matricula.pk)
        segundo = enviar_confirmacion_matricula(self.matricula.pk)

        self.assertEqual(primero['estado'], 'enviado')
        self.assertEqual(segundo['estado'], 'duplicado')
        self.assertEqual(smtp_mock.return_value.send_message.call_count, 1)
        self.assertEqual(ConfirmacionMatriculaCorreo.objects.count(), 1)

    @patch('academia.correos_matricula.enviar_confirmacion_matricula')
    def test_programacion_espera_hasta_confirmar_transaccion(self, enviar_mock):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            _programar_confirmacion_matricula(self.matricula)

        self.assertEqual(len(callbacks), 1)
        enviar_mock.assert_called_once_with(self.matricula.pk)

    @patch('academia.correos_pago.smtplib.SMTP')
    def test_sin_correo_valido_no_intenta_envio(self, smtp_mock):
        self.estudiante.correo = 'correo-invalido'
        self.estudiante.save(update_fields=['correo'])

        resultado = enviar_confirmacion_matricula(self.matricula.pk)

        self.assertEqual(resultado['estado'], 'sin_correo')
        smtp_mock.assert_not_called()
        self.assertFalse(ConfirmacionMatriculaCorreo.objects.exists())
