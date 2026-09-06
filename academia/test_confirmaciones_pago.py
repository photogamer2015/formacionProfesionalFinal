from datetime import date
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.db import transaction
from .tests import PlanRecaudacionTests
from .models import Abono, ConfirmacionPagoCorreo
from .confirmaciones_pago import enviar_confirmacion, crear_mensaje, comprobante_pdf


class ConfirmacionPagoTests(TestCase):
    def setUp(self):
        helper = PlanRecaudacionTests(); helper.setUp()
        self.m = helper._matricula_con_adelanto(Decimal('110'), Decimal('10'), 4)
        self.m.estudiante.correo = 'estudiante@example.com'; self.m.estudiante.save()

    def pago(self, **kwargs):
        return Abono.objects.create(matricula=self.m, fecha=date(2026,9,6), monto=Decimal('25'), **kwargs)

    def test_programa_todos_los_tipos_solo_despues_de_guardar(self):
        with patch('academia.confirmaciones_pago.enviar_confirmacion') as envio:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                for tipo,_ in Abono.TIPOS_PAGO:self.pago(tipo_pago=tipo)
                envio.assert_not_called()
            self.assertEqual(len(callbacks),5)
            self.assertEqual(envio.call_count,5)

    def test_editar_no_reenvia_y_rollback_no_envia(self):
        a=self.pago()
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            a.observaciones='Corrección';a.save()
            try:
                with transaction.atomic():
                    b=self.pago();pk=b.pk
                    raise ValueError('cancelar')
            except ValueError:pass
        self.assertEqual(len(callbacks),0)
        self.assertFalse(ConfirmacionPagoCorreo.objects.filter(abono_id=pk).exists())

    def test_envio_pdf_y_no_duplicacion(self):
        a=self.pago(tipo_pago='recuperacion',numero_modulo=1,cuenta_para_saldo=False)
        with patch('academia.confirmaciones_pago.config_correo_mfa',return_value={'from_email':'academia@example.com'}), patch('academia.confirmaciones_pago._conexion_smtp') as conexion:
            smtp=conexion.return_value.__enter__.return_value;smtp.send_message.return_value={}
            enviar_confirmacion(a.confirmacion_correo.pk)
            enviar_confirmacion(a.confirmacion_correo.pk)
            self.assertEqual(smtp.send_message.call_count,1)
            msg=smtp.send_message.call_args.args[0]
            self.assertIn('Pago de recuperación',msg.get_body(preferencelist=('plain',)).get_content())
            attached=list(msg.iter_attachments())
            self.assertEqual(len(attached),1)
            self.assertEqual(attached[0].get_content_type(),'application/pdf')
            self.assertTrue(attached[0].get_payload(decode=True).startswith(b'%PDF'))
        a.confirmacion_correo.refresh_from_db();self.assertEqual(a.confirmacion_correo.estado,'enviado')

    def test_fallo_no_borra_pago(self):
        a=self.pago()
        with patch('academia.confirmaciones_pago.config_correo_mfa',side_effect=RuntimeError('SMTP')):
            enviar_confirmacion(a.confirmacion_correo.pk)
        a.refresh_from_db();self.assertEqual(a.monto,Decimal('25'))
        self.assertEqual(a.confirmacion_correo.estado,'fallido')

    def test_sin_correo_no_intenta_smtp(self):
        self.m.estudiante.correo='';self.m.estudiante.save();a=self.pago()
        with patch('academia.confirmaciones_pago.config_correo_mfa') as config:
            enviar_confirmacion(a.confirmacion_correo.pk);config.assert_not_called()
        a.confirmacion_correo.refresh_from_db()
        self.assertEqual(a.confirmacion_correo.estado,'sin_correo')
