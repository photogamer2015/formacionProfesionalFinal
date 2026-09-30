from datetime import date
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from academia.forms import (
    AbonoForm, AdicionalExternoForm, AdicionalInternoForm,
    AdicionalSupletorioRapidoForm, MatriculaForm,
)
from academia.models import (
    Abono, AbonoArchivado, Adicional, AdicionalArchivado, BANCOS_POR_METODO,
    Curso, Estudiante, JornadaCurso, Matricula, METODOS_PAGO, nombre_banco,
)
from academia.views import _resumen_pagos_factura
from academia.views_pagos import (
    _build_recaudacion_excel_response, _partes_pago_abono, _resumen_abonos,
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
            metodo='tarjeta',
            banco='deuna',
            monto_2=Decimal('10.00'),
            metodo_2='tarjeta',
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
        esperado = [('', '— Selecciona un banco —')] + list(Abono.BANCOS)
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
            opciones[-1], ('Banco Bolivariano', 'Banco Bolivariano'),
        )
        self.assertNotIn('OTRO', dict(opciones))

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
                forma_pago='Tarjeta / Link de pago',
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
            '"Guayaquil,Pichincha,Banco del Pacífico,Produbanco,'
            'Interbancario,Payphone,De una,N/A"',
        )
        lista_metodos = next(lista for lista in listas if 'Efectivo' in lista)
        self.assertEqual(
            lista_metodos,
            '"Efectivo,Depósito,Transferencia,Tarjeta / Link de pago,N/A"',
        )


class MetodosPagoTests(TestCase):
    """Depósito, transferencia y tarjeta / link de pago con sus bancos."""

    def test_metodos_de_pago_del_sistema(self):
        esperado = [
            ('efectivo', 'Efectivo'),
            ('deposito', 'Depósito'),
            ('transferencia', 'Transferencia bancaria'),
            ('tarjeta', 'Tarjeta / Link de pago'),
        ]
        self.assertEqual(METODOS_PAGO, esperado)
        self.assertEqual(Abono.METODOS, esperado)
        self.assertEqual(Adicional.METODOS_PAGO, esperado)
        formularios = [
            (MatriculaForm(), ('metodo_pago', 'metodo_pago_1', 'metodo_pago_2')),
            (AbonoForm(), ('metodo', 'metodo_pago_1', 'metodo_pago_2')),
            (AdicionalInternoForm(), ('metodo_pago', 'metodo_pago_1', 'metodo_pago_2')),
            (AdicionalExternoForm(), ('metodo_pago', 'metodo_pago_1', 'metodo_pago_2')),
            (AdicionalSupletorioRapidoForm(), ('metodo_pago', 'metodo_pago_1', 'metodo_pago_2')),
        ]
        for form, campos in formularios:
            for campo in campos:
                with self.subTest(form=type(form).__name__, campo=campo):
                    opciones = [c for c in form.fields[campo].choices if c[0]]
                    self.assertEqual(opciones, esperado)

    def test_bancos_de_cada_metodo(self):
        self.assertEqual(BANCOS_POR_METODO, {
            'deposito': ['guayaquil', 'pichincha', 'banco_pacifico', 'produbanco'],
            'transferencia': [
                'guayaquil', 'pichincha', 'banco_pacifico', 'produbanco',
                'interbancario',
            ],
            'tarjeta': ['payphone', 'deuna'],
        })

    def test_nombres_de_metodo_en_adicionales_archivados(self):
        archivado = AdicionalArchivado(
            metodo_pago_1='deposito', metodo_pago_2='tarjeta',
        )
        self.assertEqual(archivado.get_metodo_pago_1_display(), 'Depósito')
        self.assertEqual(
            archivado.get_metodo_pago_2_display(), 'Tarjeta / Link de pago'
        )
        self.assertEqual(
            Adicional(metodo_pago_2='deposito').get_metodo_pago_2_display(),
            'Depósito',
        )


class ValidacionBancoPorMetodoTests(TestCase):
    """El servidor rechaza bancos que no corresponden al método."""

    def _abono(self, **cambios):
        datos = {
            'fecha': '2026-09-30',
            'monto': '25.00',
            'tipo_pago': 'abono',
            'cuenta_para_saldo': 'True',
            'tipo_cobro': 'un_solo_metodo',
            'metodo': 'efectivo',
            'banco': '',
        }
        datos.update(cambios)
        return datos

    def test_cada_metodo_acepta_solo_sus_bancos(self):
        casos = [
            ('deposito', 'guayaquil', True),
            ('deposito', 'pichincha', True),
            ('deposito', 'banco_pacifico', True),
            ('deposito', 'produbanco', True),
            ('deposito', 'interbancario', False),
            ('deposito', 'deuna', False),
            ('deposito', 'payphone', False),
            ('transferencia', 'interbancario', True),
            ('transferencia', 'produbanco', True),
            ('transferencia', 'deuna', False),
            ('transferencia', 'payphone', False),
            ('transferencia', 'Banco Bolivariano', False),
            ('tarjeta', 'payphone', True),
            ('tarjeta', 'deuna', True),
            ('tarjeta', 'pichincha', False),
        ]
        for metodo, banco, valido in casos:
            with self.subTest(metodo=metodo, banco=banco):
                form = AbonoForm(self._abono(metodo=metodo, banco=banco))
                self.assertEqual(form.is_valid(), valido, form.errors)
                if valido:
                    self.assertEqual(form.cleaned_data['banco'], banco)
                else:
                    self.assertIn('no corresponde', form.errors['banco'][0])

    def test_metodos_con_banco_lo_exigen_y_efectivo_lo_borra(self):
        for metodo in ('deposito', 'transferencia', 'tarjeta'):
            with self.subTest(metodo=metodo):
                form = AbonoForm(self._abono(metodo=metodo))
                self.assertFalse(form.is_valid())
                self.assertIn('banco', form.errors)

        form = AbonoForm(self._abono(metodo='efectivo', banco='pichincha'))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['banco'], '')

    def test_pago_mixto_valida_el_banco_de_cada_parte(self):
        datos = self._abono(
            tipo_cobro='mixto',
            monto_pago_1='15.00', metodo_pago_1='deposito', banco_1='pichincha',
            monto_pago_2='10.00', metodo_pago_2='tarjeta', banco_2='guayaquil',
        )
        form = AbonoForm(datos)
        self.assertFalse(form.is_valid())
        self.assertNotIn('banco_1', form.errors)
        self.assertIn('banco_2', form.errors)

        datos['banco_2'] = 'deuna'
        self.assertTrue(AbonoForm(datos).is_valid())

    def test_pago_antiguo_conserva_su_banco_mientras_no_cambie_el_metodo(self):
        estudiante = Estudiante.objects.create(
            cedula='0912345670', nombres='Pago Antiguo',
        )
        curso = Curso.objects.create(
            nombre='Curso Bancos', ofrece_presencial=True,
            valor_presencial=Decimal('100.00'),
        )
        jornada = JornadaCurso.objects.create(
            curso=curso, modalidad='presencial',
            descripcion='sabados_intensivos', fecha_inicio=date(2026, 10, 3),
        )
        matricula = Matricula.objects.create(
            estudiante=estudiante, curso=curso, jornada=jornada,
            modalidad='presencial', tipo_matricula='reserva_abono',
            forma_pago='abono', fecha_matricula=date(2026, 9, 1),
            valor_curso=Decimal('100.00'), valor_pagado=Decimal('0.00'),
            tipo_registro='central_ia',
        )
        abono = Abono.objects.create(
            matricula=matricula, fecha=date(2026, 9, 1),
            monto=Decimal('20.00'), tipo_pago='abono',
            metodo='transferencia', banco='deuna',
        )

        form = AbonoForm(
            self._abono(monto='20.00', metodo='transferencia', banco='deuna'),
            instance=abono, matricula=matricula,
        )
        self.assertTrue(form.is_valid(), form.errors)

        form = AbonoForm(
            self._abono(monto='20.00', metodo='deposito', banco='deuna'),
            instance=abono, matricula=matricula,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('banco', form.errors)

    def test_adicionales_y_matricula_usan_las_mismas_reglas(self):
        adicional = AdicionalExternoForm(data={
            'tipo_cobro': 'un_solo_metodo',
            'metodo_pago': 'deposito', 'banco': 'interbancario',
        })
        adicional.is_valid()
        self.assertIn('banco', adicional.errors)

        supletorio = AdicionalSupletorioRapidoForm(data={
            'tipo_cobro': 'mixto',
            'metodo_pago_1': 'transferencia', 'banco_1': 'deuna',
            'metodo_pago_2': 'deposito', 'banco_2': 'produbanco',
        })
        supletorio.is_valid()
        self.assertIn('banco_1', supletorio.errors)
        self.assertNotIn('banco_2', supletorio.errors)

        matricula = MatriculaForm(data={
            'mat-tipo_cobro': 'un_solo_metodo',
            'mat-metodo_pago': 'tarjeta', 'mat-banco': 'pichincha',
        }, prefix='mat')
        matricula.is_valid()
        self.assertIn('banco', matricula.errors)

    def test_pago_mixto_no_exige_el_banco_del_metodo_unico_oculto(self):
        # Se eligió Depósito sin banco y luego se pasó a Pago Mixto: el
        # método único queda oculto con su valor y no debe pedir banco.
        form = MatriculaForm(data={
            'mat-tipo_cobro': 'mixto',
            'mat-metodo_pago': 'deposito', 'mat-banco': '',
            'mat-monto_pago_1': '6', 'mat-metodo_pago_1': 'deposito',
            'mat-banco_1': 'guayaquil',
            'mat-monto_pago_2': '4', 'mat-metodo_pago_2': 'tarjeta',
            'mat-banco_2': 'payphone',
        }, prefix='mat')
        form.is_valid()
        for campo in ('banco', 'banco_1', 'banco_2'):
            self.assertNotIn(campo, form.errors)


class ReportesConDepositoTests(TestCase):
    """El depósito aparece con su banco en los resúmenes de pago."""

    def test_resumenes_muestran_deposito_con_su_banco(self):
        abono = Abono(
            monto=Decimal('30.00'), tipo_pago='abono',
            metodo='deposito', banco='produbanco',
            monto_2=Decimal('10.00'), metodo_2='tarjeta', banco_2='deuna',
        )

        etiquetas = [m['label'] for m in _resumen_abonos([abono])['metodos']]
        self.assertEqual(
            etiquetas,
            ['Depósito · Produbanco', 'Tarjeta / Link de pago · De una'],
        )
        etiquetas = [m['label'] for m in _resumen_pagos_factura([abono])['metodos']]
        self.assertEqual(
            etiquetas,
            ['Depósito · Produbanco', 'Tarjeta / Link de pago · De una'],
        )

    def test_paginas_de_pago_reciben_los_bancos_de_cada_metodo(self):
        admin = User.objects.create_superuser(
            username='admin_bancos_pago', password='clave12345',
        )
        self.client.force_login(admin)

        response = self.client.get(reverse('academia:bienvenida'))

        self.assertContains(response, 'id="bancos-por-metodo"')
        self.assertContains(response, 'window.BancosPago')
        self.assertNotContains(response, 'Otro banco...')
