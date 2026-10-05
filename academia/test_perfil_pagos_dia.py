from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Abono, Curso, Estudiante, Matricula


class PerfilPagosPorDiaTests(TestCase):
    """Sección «Pagos registrados por día» del perfil propio."""

    def setUp(self):
        asesores = Group.objects.create(name='Asesores')
        self.ana = User.objects.create_user('ana_pagos', first_name='Ana')
        self.beto = User.objects.create_user('beto_pagos', first_name='Beto')
        for usuario in (self.ana, self.beto):
            usuario.groups.add(asesores)
        self.admin = User.objects.create_superuser('admin_pagos_perfil')
        self.curso = Curso.objects.create(nombre='Curso pagos perfil')
        self.mat = Matricula.objects.create(
            estudiante=Estudiante.objects.create(cedula='0944444444', nombres='Luisa Pagos'),
            curso=self.curso, modalidad='presencial', tipo_matricula='reserva_abono',
            fecha_matricula=date(2026, 1, 5), valor_curso=Decimal('200.00'),
            registrado_por=self.ana, vendedora=self.ana,
        )

    def _pago(self, usuario, monto, creado=None, **datos):
        pago = Abono.objects.create(
            matricula=self.mat, fecha=datos.pop('fecha', timezone.localdate()),
            monto=Decimal(monto), registrado_por=usuario, **datos,
        )
        if creado is not None:
            Abono.objects.filter(pk=pago.pk).update(creado=creado)
            pago.refresh_from_db()
        return pago

    def _perfil(self, usuario, **params):
        return self.client.get(
            reverse('academia:comprobante_asesor_detalle', args=[usuario.pk]), params,
        )

    def test_cada_usuario_ve_solo_sus_pagos_de_hoy(self):
        mio = self._pago(
            self.ana, '25.00', tipo_pago='por_modulo', numero_modulo=2,
            metodo='transferencia', banco='pichincha',
        )
        ajeno = self._pago(self.beto, '40.00')
        ayer = self._pago(self.ana, '15.00', creado=timezone.now() - timedelta(days=1))

        self.client.force_login(self.ana)
        response = self._perfil(self.ana)

        self.assertEqual(response.status_code, 200)
        pr = response.context['pagos_registrados']
        self.assertTrue(pr['es_hoy'])
        self.assertEqual(pr['pagos'], [mio])
        self.assertEqual(pr['total'], Decimal('25.00'))
        self.assertContains(response, 'href="#pagos"')
        self.assertContains(response, 'Pagos registrados por día')
        self.assertContains(response, mio.numero_recibo)
        self.assertContains(response, 'Transferencia bancaria · Pichincha')
        self.assertContains(response, 'Mód. 2')
        self.assertNotContains(response, 'Total del día:')
        self.assertContains(response, reverse('academia:matricula_abonos', args=[self.mat.pk]))
        self.assertNotContains(response, ajeno.numero_recibo)
        self.assertNotContains(response, ayer.numero_recibo)
        for resto in ('{#', '{%', '{{', '#}', '%}', '}}'):
            self.assertNotContains(response, resto)

        # Beto ve solo el suyo.
        self.client.force_login(self.beto)
        pr_beto = self._perfil(self.beto).context['pagos_registrados']
        self.assertEqual(pr_beto['pagos'], [ajeno])

    def test_perfil_ajeno_no_muestra_pagos_ni_al_administrador(self):
        pago = self._pago(self.ana, '25.00')
        for visitante in (self.beto, self.admin):
            self.client.force_login(visitante)
            response = self._perfil(self.ana)
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.context['pagos_registrados'])
            self.assertNotContains(response, 'id="pagos"')
            self.assertNotContains(response, pago.numero_recibo)

    def test_solo_se_ve_y_solo_el_admin_edita_o_elimina_pagos(self):
        pago = self._pago(self.ana, '25.00', metodo='efectivo')
        url_pagos = reverse('academia:matricula_abonos', args=[self.mat.pk])
        url_editar = reverse('academia:abono_editar', args=[self.mat.pk, pago.pk])
        url_eliminar = reverse('academia:abono_eliminar', args=[self.mat.pk, pago.pk])

        self.client.force_login(self.ana)
        # La sección del perfil no tiene nada que guarde: solo elegir el día.
        perfil = self._perfil(self.ana).content.decode()
        seccion = perfil[perfil.index('id="pagos"'):perfil.index('id="actividad"')]
        self.assertNotIn('method="post"', seccion)
        self.assertIn('method="get"', seccion)
        # En la página de pagos la asesora no ve Editar ni Eliminar…
        pagina = self.client.get(url_pagos)
        self.assertEqual(pagina.status_code, 200)
        self.assertNotContains(pagina, url_editar)
        self.assertNotContains(pagina, url_eliminar)
        # …y aunque lo intente directamente, el servidor lo rechaza.
        self.assertEqual(self.client.get(url_editar).status_code, 302)
        self.assertEqual(self.client.post(url_editar, {'monto': '1.00'}).status_code, 302)
        self.assertEqual(self.client.post(url_eliminar).status_code, 302)
        pago.refresh_from_db()
        self.assertEqual(pago.monto, Decimal('25.00'))

        # Un usuario sin rol no entra a la página de pagos.
        sin_rol = User.objects.create_user('sin_rol_pagos')
        self.client.force_login(sin_rol)
        self.assertEqual(self.client.get(url_pagos).status_code, 302)

        # El administrador sí tiene Editar y Eliminar.
        self.client.force_login(self.admin)
        pagina_admin = self.client.get(url_pagos)
        self.assertContains(pagina_admin, url_editar)
        self.assertContains(pagina_admin, url_eliminar)

    def test_dia_es_el_de_registro_en_hora_local(self):
        # 23:30 en Guayaquil ya es el día siguiente en UTC.
        noche = timezone.make_aware(datetime(2026, 1, 15, 23, 30))
        pago = self._pago(self.ana, '30.00', creado=noche, fecha=date(2026, 1, 12))
        self.client.force_login(self.ana)

        response = self._perfil(self.ana, pagos_dia='2026-01-15')
        pr = response.context['pagos_registrados']
        self.assertEqual(pr['dia'], date(2026, 1, 15))
        self.assertEqual(pr['pagos'], [pago])
        self.assertEqual(pr['dia_anterior'], date(2026, 1, 14))
        self.assertEqual(pr['dia_siguiente'], date(2026, 1, 16))
        self.assertContains(response, '23:30')
        self.assertContains(response, '12/01/2026')  # fecha anotada en el pago
        self.assertContains(response, 'Jueves, 15 de enero de 2026')

        siguiente = self._perfil(self.ana, pagos_dia='2026-01-16').context['pagos_registrados']
        self.assertEqual(siguiente['pagos'], [])

    def test_pago_mixto_separa_los_metodos(self):
        pago = self._pago(
            self.ana, '30.00', metodo='efectivo',
            monto_2=Decimal('20.00'), metodo_2='transferencia', banco_2='pichincha',
        )
        self._pago(self.ana, '5.00', metodo='efectivo')
        self.client.force_login(self.ana)

        response = self._perfil(self.ana)
        pr = response.context['pagos_registrados']
        mixto = next(p for p in pr['pagos'] if p.pk == pago.pk)
        self.assertEqual(mixto.partes_metodo, [
            ('Efectivo', Decimal('10.00')),
            ('Transferencia bancaria · Pichincha', Decimal('20.00')),
        ])
        self.assertEqual(pr['total'], Decimal('35.00'))
        self.assertEqual(
            {m['etiqueta']: m['total'] for m in pr['metodos']},
            {'Efectivo': Decimal('15.00'), 'Transferencia bancaria · Pichincha': Decimal('20.00')},
        )

    def test_dia_invalido_o_futuro_muestra_hoy(self):
        self.client.force_login(self.ana)
        manana = (timezone.localdate() + timedelta(days=1)).isoformat()
        for valor in ('2026-02-30', 'abc', manana, '1990-01-01', ''):
            response = self._perfil(self.ana, pagos_dia=valor)
            self.assertEqual(response.status_code, 200, valor)
            pr = response.context['pagos_registrados']
            self.assertEqual(pr['dia'], timezone.localdate(), valor)
            self.assertIsNone(pr['dia_siguiente'])
            self.assertContains(response, 'Hoy aún no registras pagos')

    def test_ultimos_dias_con_pagos(self):
        hoy = timezone.localdate()
        for atras in range(9):
            momento = timezone.make_aware(
                datetime.combine(hoy - timedelta(days=atras * 2), datetime.min.time())
                + timedelta(hours=10)
            )
            for _ in range(2 if atras == 1 else 1):
                self._pago(self.ana, '10.00', creado=momento)
        self._pago(self.beto, '99.00')
        self.client.force_login(self.ana)

        dias = self._perfil(self.ana).context['pagos_registrados']['dias_recientes']
        self.assertEqual(len(dias), 7)
        self.assertEqual(dias[0]['dia'], hoy)
        self.assertEqual(dias[0]['total'], Decimal('10.00'))
        self.assertEqual(
            (dias[1]['dia'], dias[1]['cantidad'], dias[1]['total']),
            (hoy - timedelta(days=2), 2, Decimal('20.00')),
        )
        self.assertEqual(dias[-1]['dia'], hoy - timedelta(days=12))
