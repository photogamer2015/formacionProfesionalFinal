from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from .correos_pago import _crear_mensaje, enviar_recordatorios_pago
from .models import (
    Curso, Estudiante, JornadaCurso, Matricula, RecordatorioPagoCorreo,
)
from .views_pagos import _calcular_alertas_pago


SMTP_CONFIG = {
    'host': 'smtp.example.com',
    'port': 587,
    'use_ssl': False,
    'use_tls': True,
    'username': 'cuenta@example.com',
    'password': 'clave-prueba',
    'from_email': 'cuenta@example.com',
}


@override_settings(
    PAYMENT_REMINDER_EMAIL_ENABLED=True,
    PAYMENT_REMINDER_EMAIL_TIMEOUT=2,
)
class RecordatoriosPagoCorreoTests(TestCase):
    def setUp(self):
        self.estudiante = Estudiante.objects.create(
            cedula='0912345678',
            nombres='Ana Pérez',
            correo='ana@example.com',
        )
        self.curso = Curso.objects.create(
            nombre='Auxiliar Contable Online',
            ofrece_presencial=False,
            ofrece_online=True,
            valor_online=Decimal('60.00'),
            numero_modulos_online=2,
        )
        self.jornada = JornadaCurso.objects.create(
            curso=self.curso,
            modalidad='online',
            descripcion='otros',
            descripcion_otros='Online',
            fecha_inicio=date(2026, 8, 15),
        )
        self.matricula = Matricula.objects.create(
            estudiante=self.estudiante,
            curso=self.curso,
            jornada=self.jornada,
            modalidad='online',
            tipo_matricula='reserva_abono',
            forma_pago='abono',
            fecha_matricula=date(2026, 8, 10),
            valor_curso=Decimal('60.00'),
            valor_pagado=Decimal('10.00'),
        )

    def _alertas(self, hoy=date(2026, 8, 14)):
        return _calcular_alertas_pago(
            fecha_actual=hoy,
            excluir_revisadas=False,
        )

    def test_plazo_online_depende_del_envio_incluso_al_cambiar_de_anio(self):
        alerta = self._alertas()[0]
        mensaje = _crear_mensaje(
            alerta, self.estudiante.correo, SMTP_CONFIG, date(2026, 12, 31),
        )
        for formato in ('plain', 'html'):
            contenido = mensaje.get_body(preferencelist=(formato,)).get_content()
            self.assertIn('31/12/2026', contenido)
            self.assertIn('01/01/2027', contenido)
            self.assertIn('12:00 p. m. (mediodía)', contenido)
            self.assertNotIn('acercarse a nuestras instalaciones', contenido)

    def test_presencial_solicita_pago_en_instalaciones_sin_plazo_online(self):
        alerta = self._alertas()[0]
        alerta['matricula'].modalidad = 'presencial'
        alerta['modalidad_label'] = 'Presencial'
        mensaje = _crear_mensaje(
            alerta, self.estudiante.correo, SMTP_CONFIG, date(2026, 8, 14),
        )
        for formato in ('plain', 'html'):
            contenido = mensaje.get_body(preferencelist=(formato,)).get_content()
            self.assertIn('acercarse a nuestras instalaciones', contenido)
            self.assertIn('14/08/2026', contenido)
            self.assertNotIn('mediodía', contenido)
            self.assertNotIn('15/08/2026', contenido)

    @patch('academia.correos_pago.config_correo_mfa', return_value=SMTP_CONFIG)
    @patch('academia.correos_pago.smtplib.SMTP')
    def test_envia_un_dia_antes_con_datos_personalizados(
        self, smtp_mock, _config_mock,
    ):
        resumen = enviar_recordatorios_pago(
            self._alertas(), fecha_envio=date(2026, 8, 14),
        )

        self.assertEqual(resumen['enviados'], 1)
        servidor = smtp_mock.return_value
        servidor.starttls.assert_called_once_with()
        servidor.login.assert_called_once_with(
            'cuenta@example.com', 'clave-prueba',
        )
        servidor.send_message.assert_called_once()

        mensaje = servidor.send_message.call_args.args[0]
        texto = mensaje.get_body(preferencelist=('plain',)).get_content()
        html = mensaje.get_body(preferencelist=('html',)).get_content()
        self.assertEqual(mensaje['To'], 'ana@example.com')
        self.assertIn('Ana Pérez', texto)
        self.assertIn('Auxiliar Contable Online', texto)
        self.assertIn('Módulo 1 de 2', texto)
        self.assertIn('14/08/2026', texto)
        self.assertIn('25', texto)
        self.assertIn('Valor pendiente de este pago', html)

        registro = RecordatorioPagoCorreo.objects.get()
        self.assertEqual(
            registro.estado, RecordatorioPagoCorreo.ESTADO_ENVIADO,
        )
        self.assertEqual(registro.monto, Decimal('25.00'))
        self.assertEqual(registro.fecha_alerta, date(2026, 8, 14))
        self.assertEqual(registro.fecha_pago, date(2026, 8, 14))

    @patch('academia.correos_pago.config_correo_mfa', return_value=SMTP_CONFIG)
    @patch('academia.correos_pago.smtplib.SMTP')
    def test_no_duplica_el_mismo_recordatorio(
        self, smtp_mock, _config_mock,
    ):
        alertas = self._alertas()
        primero = enviar_recordatorios_pago(
            alertas, fecha_envio=date(2026, 8, 14),
        )
        segundo = enviar_recordatorios_pago(
            alertas, fecha_envio=date(2026, 8, 14),
        )

        self.assertEqual(primero['enviados'], 1)
        self.assertEqual(segundo['enviados'], 0)
        self.assertEqual(segundo['duplicados'], 1)
        self.assertEqual(
            smtp_mock.return_value.send_message.call_count, 1,
        )
        self.assertEqual(RecordatorioPagoCorreo.objects.count(), 1)

    @patch('academia.correos_pago.config_correo_mfa', return_value=SMTP_CONFIG)
    @patch('academia.correos_pago.smtplib.SMTP')
    def test_un_fallo_no_marca_enviado_y_se_puede_reintentar(
        self, smtp_mock, _config_mock,
    ):
        servidor = smtp_mock.return_value
        servidor.send_message.side_effect = [RuntimeError('SMTP caído'), None]
        alertas = self._alertas()

        primero = enviar_recordatorios_pago(
            alertas, fecha_envio=date(2026, 8, 14),
        )
        registro = RecordatorioPagoCorreo.objects.get()
        self.assertEqual(primero['fallidos'], 1)
        self.assertEqual(
            registro.estado, RecordatorioPagoCorreo.ESTADO_FALLIDO,
        )

        segundo = enviar_recordatorios_pago(
            alertas, fecha_envio=date(2026, 8, 14),
        )
        registro.refresh_from_db()
        self.assertEqual(segundo['enviados'], 1)
        self.assertEqual(registro.intentos, 2)
        self.assertEqual(
            registro.estado, RecordatorioPagoCorreo.ESTADO_ENVIADO,
        )

    @patch('academia.correos_pago.smtplib.SMTP')
    def test_omite_correo_invalido_sin_intentar_smtp(self, smtp_mock):
        self.estudiante.correo = 'correo-invalido'
        self.estudiante.save(update_fields=['correo'])

        resumen = enviar_recordatorios_pago(
            self._alertas(), fecha_envio=date(2026, 8, 14),
        )

        self.assertEqual(resumen['sin_correo'], 1)
        self.assertEqual(resumen['candidatos'], 0)
        smtp_mock.assert_not_called()
        self.assertFalse(RecordatorioPagoCorreo.objects.exists())

    @patch('academia.correos_pago.smtplib.SMTP')
    def test_no_envia_fuera_de_la_fecha_exacta(self, smtp_mock):
        resumen = enviar_recordatorios_pago(
            self._alertas(), fecha_envio=date(2026, 8, 13),
        )

        self.assertEqual(resumen['candidatos'], 0)
        smtp_mock.assert_not_called()
        self.assertFalse(RecordatorioPagoCorreo.objects.exists())

    @patch('academia.correos_pago.config_correo_mfa', return_value=SMTP_CONFIG)
    @patch('academia.correos_pago.smtplib.SMTP')
    def test_matricula_creada_hoy_con_fecha_vencida_envia_inmediatamente(
        self, smtp_mock, _config_mock,
    ):
        hoy = timezone.localdate()

        resumen = enviar_recordatorios_pago(
            self._alertas(hoy=hoy), fecha_envio=hoy,
        )

        self.assertEqual(resumen['candidatos'], 1)
        self.assertEqual(resumen['atrasados_nuevos'], 1)
        self.assertEqual(resumen['enviados'], 1)
        mensaje = smtp_mock.return_value.send_message.call_args.args[0]
        texto = mensaje.get_body(preferencelist=('plain',)).get_content()
        self.assertIn('registrada después de la fecha prevista', texto)
        self.assertIn('pago pendiente', texto)

    @patch('academia.correos_pago.smtplib.SMTP')
    def test_matricula_antigua_atrasada_no_dispara_envio_masivo(
        self, smtp_mock,
    ):
        Matricula.objects.filter(pk=self.matricula.pk).update(
            creado=timezone.now() - timedelta(days=2),
        )
        hoy = timezone.localdate()

        resumen = enviar_recordatorios_pago(
            self._alertas(hoy=hoy), fecha_envio=hoy,
        )

        self.assertEqual(resumen['candidatos'], 0)
        self.assertEqual(resumen['atrasados_nuevos'], 0)
        smtp_mock.assert_not_called()
        self.assertFalse(RecordatorioPagoCorreo.objects.exists())

    @patch('academia.correos_pago.smtplib.SMTP')
    def test_curso_pagado_no_genera_recordatorio(self, smtp_mock):
        self.matricula.valor_pagado = Decimal('60.00')
        self.matricula.save(update_fields=['valor_pagado'])

        alertas = self._alertas()
        resumen = enviar_recordatorios_pago(
            alertas, fecha_envio=date(2026, 8, 14),
        )

        self.assertFalse(any(
            alerta['matricula'].pk == self.matricula.pk
            for alerta in alertas
        ))
        self.assertEqual(resumen['candidatos'], 0)
        smtp_mock.assert_not_called()
