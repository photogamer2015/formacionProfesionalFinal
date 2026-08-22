from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from academia.correos_pago import enviar_recordatorios_pago
from academia.views_pagos import _calcular_alertas_pago


class Command(BaseCommand):
    help = (
        'Envía a los estudiantes los recordatorios de pago que corresponden '
        'a la fecha indicada, sin duplicar correos ya enviados.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--fecha',
            help='Fecha de ejecución en formato AAAA-MM-DD (por defecto hoy).',
        )
        parser.add_argument(
            '--simular', action='store_true',
            help='Cuenta los candidatos sin reservar ni enviar correos.',
        )
        parser.add_argument(
            '--forzar', action='store_true',
            help='Permite el envío aunque esté deshabilitado en la configuración.',
        )

    def handle(self, *args, **options):
        fecha_texto = (options.get('fecha') or '').strip()
        fecha = parse_date(fecha_texto) if fecha_texto else timezone.localdate()
        if fecha_texto and fecha is None:
            raise CommandError('La fecha debe tener el formato AAAA-MM-DD.')

        alertas = _calcular_alertas_pago(
            fecha_actual=fecha,
            excluir_revisadas=False,
        )
        resumen = enviar_recordatorios_pago(
            alertas,
            fecha_envio=fecha,
            forzar=options['forzar'],
            simular=options['simular'],
        )

        if resumen['deshabilitado']:
            self.stdout.write(self.style.WARNING(
                'El envío está deshabilitado. Configura '
                'PAYMENT_REMINDER_EMAIL_ENABLED=True o usa --forzar.'
            ))

        etiqueta = 'Simulación' if options['simular'] else 'Resultado'
        self.stdout.write(
            f'{etiqueta} {fecha:%d/%m/%Y}: '
            f'{resumen["candidatos"]} candidato(s), '
            f'{resumen["enviados"]} enviado(s), '
            f'{resumen["duplicados"]} duplicado(s), '
            f'{resumen["atrasados_nuevos"]} alta(s) nueva(s) atrasada(s), '
            f'{resumen["sin_correo"]} sin correo válido, '
            f'{resumen["fallidos"]} fallido(s).'
        )
