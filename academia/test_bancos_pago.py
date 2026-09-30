from datetime import date
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

from django.test import TestCase
from openpyxl import load_workbook

from academia.forms import (
    AbonoForm, AdicionalExternoForm, AdicionalInternoForm,
    AdicionalSupletorioRapidoForm, MatriculaForm,
)
from academia.models import (
    Abono, AbonoArchivado, Adicional, AdicionalArchivado, nombre_banco,
)
from academia.views_pagos import (
    _build_recaudacion_excel_response, _partes_pago_abono,
)


class NombresBancoTests(TestCase):
    """"De una" se ofrece en los formularios; debe mostrarse con su nombre."""

    def test_nombre_banco_reconoce_de_una_y_conserva_los_escritos_a_mano(self):
        self.assertEqual(nombre_banco('deuna'), 'De una')
        self.assertEqual(nombre_banco('banco_pacifico'), 'Banco del Pacífico')
        self.assertEqual(
            nombre_banco('Banco Bolivariano'),
            'Otro banco - Banco Bolivariano',
        )
        self.assertEqual(nombre_banco(''), '')
        self.assertEqual(nombre_banco(None), '')

    def test_todos_los_registros_de_pago_muestran_de_una(self):
        abono = Abono(banco='deuna', banco_2='deuna')
        adicional = Adicional(banco='deuna', banco_2='deuna')
        adicional_archivado = AdicionalArchivado(
            banco='deuna', banco_1='deuna', banco_2='deuna',
        )

        self.assertEqual(abono.get_banco_display(), 'De una')
        self.assertEqual(abono.get_banco_2_display(), 'De una')
        self.assertEqual(adicional.get_banco_display(), 'De una')
        self.assertEqual(adicional.get_banco_2_display(), 'De una')
        self.assertEqual(
            AbonoArchivado(banco='deuna').get_banco_display(), 'De una'
        )
        self.assertEqual(adicional_archivado.get_banco_display(), 'De una')
        self.assertEqual(adicional_archivado.get_banco_1_display(), 'De una')
        self.assertEqual(adicional_archivado.get_banco_2_display(), 'De una')

    def test_pago_mixto_muestra_de_una_en_ambas_partes(self):
        abono = Abono(
            monto=Decimal('30.00'),
            metodo='transferencia',
            banco='deuna',
            monto_2=Decimal('10.00'),
            metodo_2='transferencia',
            banco_2='deuna',
        )

        partes = _partes_pago_abono(abono)

        self.assertEqual(
            [parte['banco_display'] for parte in partes],
            ['De una', 'De una'],
        )

    def test_todos_los_formularios_de_pago_ofrecen_la_misma_lista(self):
        formularios = [
            MatriculaForm(),
            AbonoForm(),
            AdicionalInternoForm(),
            AdicionalExternoForm(),
            AdicionalSupletorioRapidoForm(),
        ]
        esperado = (
            [('', '— Selecciona un banco —')]
            + list(Abono.BANCOS)
            + [('OTRO', 'Otro banco...')]
        )
        self.assertIn(('deuna', 'De una'), Abono.BANCOS)
        for form in formularios:
            campos = [
                campo for campo in ('banco', 'banco_1', 'banco_2')
                if campo in form.fields
            ]
            self.assertEqual(len(campos), 3, type(form).__name__)
            for campo in campos:
                with self.subTest(form=type(form).__name__, campo=campo):
                    self.assertEqual(
                        list(form.fields[campo].widget.choices), esperado
                    )

    def test_formulario_conserva_el_banco_escrito_a_mano_al_editar(self):
        form = AbonoForm(initial={'banco': 'Banco Bolivariano'})

        opciones = list(form.fields['banco'].widget.choices)

        self.assertEqual(
            opciones[-2:],
            [
                ('Banco Bolivariano', 'Banco Bolivariano'),
                ('OTRO', 'Otro banco...'),
            ],
        )

    def test_excel_de_recaudacion_permite_elegir_de_una(self):
        hoja = {
            'curso': SimpleNamespace(nombre='Asistente Contable'),
            'fecha': date(2026, 9, 30),
            'dia_semana': 'MIÉRCOLES',
            'ciudad': 'Guayaquil',
            'jornada_label': 'Presencial – Mar, Mié, Jue.',
            'responsable': 'Responsable de prueba',
            'total_efectivo': Decimal('0'),
            'total_transferencia_impresion': Decimal('20'),
            'total_payphone': Decimal('0'),
            'total_recaudado': Decimal('20'),
            'items': [dict(
                estudiante=SimpleNamespace(nombre_completo='Estudiante Prueba'),
                modulo=1,
                cuota_sugerida=Decimal('25'),
                recaudado=Decimal('20'),
                forma_pago='Transferencia',
                banco='De una',
            )],
        }

        response = _build_recaudacion_excel_response(
            'prueba.xlsx', 'Recaudación', [hoja]
        )

        ws = load_workbook(BytesIO(response.content)).active
        listas = [
            validacion.formula1
            for validacion in ws.data_validations.dataValidation
        ]
        lista_bancos = next(lista for lista in listas if 'Payphone' in lista)
        self.assertEqual(
            lista_bancos,
            '"Pichincha,Guayaquil,Produbanco,Banco del Pacífico,'
            'Payphone,De una,Interbancario,N/A"',
        )
