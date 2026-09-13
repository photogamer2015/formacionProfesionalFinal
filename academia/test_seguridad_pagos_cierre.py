from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.test import TestCase, Client
from django.urls import reverse
from .models import Curso, Estudiante, JornadaCurso, Matricula, Abono, CierreCurso
from . import tests as pruebas_existentes


class EdicionMatriculaPropietarioTests(TestCase):
    def setUp(self):
        self.grupo_asesores = Group.objects.create(name='Asesores')
        self.duena = User.objects.create_user('asesora_duena', password='clave-prueba')
        self.otra = User.objects.create_user('asesora_ajena', password='clave-prueba')
        self.admin = User.objects.create_superuser('admin_propietario', password='clave-prueba')
        self.duena.groups.add(self.grupo_asesores)
        self.otra.groups.add(self.grupo_asesores)

        self.curso = Curso.objects.create(
            nombre='Curso propietario',
            ofrece_presencial=True,
            valor_presencial=100,
        )
        self.jornada = JornadaCurso.objects.create(
            curso=self.curso,
            modalidad='presencial',
            descripcion='lun_mie_vie',
            fecha_inicio=date(2026, 8, 1),
        )
        self.nueva_jornada = JornadaCurso.objects.create(
            curso=self.curso,
            modalidad='presencial',
            descripcion='sabados_intensivos',
            fecha_inicio=date(2026, 9, 1),
        )
        self.est = Estudiante.objects.create(
            cedula='0911111111',
            nombres='Propietaria prueba',
            correo='antes@example.com',
        )
        self.mat = Matricula.objects.create(
            estudiante=self.est,
            curso=self.curso,
            jornada=self.jornada,
            modalidad='presencial',
            tipo_matricula='reserva_abono',
            forma_pago='abono',
            fecha_matricula=date(2026, 8, 1),
            valor_curso=Decimal('100.00'),
            valor_pagado=Decimal('10.00'),
            tipo_registro='central_ia',
            factura_realizada='no',
            registrado_por=self.duena,
            vendedora=self.duena,
        )
        self.inicial = Abono.objects.create(
            matricula=self.mat,
            fecha=date(2026, 8, 1),
            monto=Decimal('10.00'),
            tipo_pago='abono',
            metodo='efectivo',
        )
        self.url_editar = reverse('academia:matricula_editar', args=['presencial', self.mat.pk])
        self.url_jornada = reverse('academia:matricula_cambiar_jornada', args=[self.mat.pk])
        self.url_eliminar = reverse('academia:matricula_eliminar', args=['presencial', self.mat.pk])

    def test_asesora_ajena_no_edita_datos_pago_jornada_ni_elimina(self):
        self.client.force_login(self.otra)
        self.assertEqual(self.client.get(self.url_editar).status_code, 302)
        self.assertEqual(self.client.get(self.url_editar, {'editar_pago': '1'}).status_code, 302)
        self.assertEqual(self.client.get(self.url_jornada).status_code, 302)

        response = self.client.post(self.url_editar, {
            'est-cedula': self.est.cedula,
            'est-nombres': 'Nombre ajeno',
            'est-correo': 'ajeno@example.com',
        })
        self.assertEqual(response.status_code, 302)

        response = self.client.post(self.url_editar, {
            'editar_pago': '1',
            'mat-valor_pagado': '50',
            'mat-forma_pago': 'abono',
            'mat-descuento': '0',
            'mat-tipo_cobro': 'un_solo_metodo',
            'mat-metodo_pago': 'efectivo',
        })
        self.assertEqual(response.status_code, 302)

        response = self.client.post(self.url_jornada, {
            'jornada': self.nueva_jornada.pk,
            'jornada_original': self.jornada.pk,
            'motivo': 'Intento ajeno',
        })
        self.assertEqual(response.status_code, 302)

        response = self.client.post(self.url_eliminar)
        self.assertEqual(response.status_code, 302)

        self.mat.refresh_from_db()
        self.est.refresh_from_db()
        self.assertEqual(self.est.nombres, 'Propietaria prueba')
        self.assertEqual(self.est.correo, 'antes@example.com')
        self.assertEqual(self.mat.valor_pagado, Decimal('10.00'))
        self.assertEqual(self.mat.jornada_id, self.jornada.pk)
        self.assertTrue(Matricula.objects.filter(pk=self.mat.pk).exists())

    def test_duena_y_admin_si_pueden_abrir_edicion(self):
        self.client.force_login(self.duena)
        self.assertEqual(self.client.get(self.url_editar).status_code, 200)
        self.assertEqual(self.client.get(self.url_editar, {'editar_pago': '1'}).status_code, 200)
        self.assertEqual(self.client.get(self.url_jornada).status_code, 200)

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url_editar).status_code, 200)
        self.assertEqual(self.client.get(self.url_editar, {'editar_pago': '1'}).status_code, 200)
        self.assertEqual(self.client.get(self.url_jornada).status_code, 200)

    def test_matricula_antigua_usa_vendedora_como_respaldo(self):
        Matricula.objects.filter(pk=self.mat.pk).update(registrado_por=None)
        self.client.force_login(self.duena)
        self.assertEqual(self.client.get(self.url_editar).status_code, 200)

        self.client.force_login(self.otra)
        self.assertEqual(self.client.get(self.url_editar).status_code, 302)


class PagoAisladoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('seguridad_pago', password='clave-prueba')
        self.client.force_login(self.user)
        self.curso = Curso.objects.create(nombre='Curso seguridad', ofrece_online=True, valor_online=100)
        self.jornada = JornadaCurso.objects.create(curso=self.curso, modalidad='online', descripcion='lun_mie_vie', fecha_inicio=date(2026, 8, 1))
        self.est = Estudiante.objects.create(cedula='0999999999', nombres='Prueba pago')
        self.mat = Matricula.objects.create(estudiante=self.est, curso=self.curso, jornada=self.jornada, modalidad='online', tipo_matricula='reserva_abono', forma_pago='abono', fecha_matricula=date(2026,8,1), valor_curso=100, tipo_registro='central_ia', factura_realizada='no', vendedora=self.user)
        self.inicial = Abono.objects.create(matricula=self.mat, fecha=date(2026,8,1), monto=10, tipo_pago='abono', metodo='efectivo')
        self.posterior = Abono.objects.create(matricula=self.mat, fecha=date(2026,8,10), monto=20, tipo_pago='abono', metodo='efectivo')
        # El detector agrupa pagos iniciales creados en el mismo instante.
        from django.utils import timezone
        from datetime import timedelta
        Abono.objects.filter(pk=self.inicial.pk).update(creado=self.mat.creado)
        Abono.objects.filter(pk=self.posterior.pk).update(creado=self.mat.creado + timedelta(days=9))
        self.url = reverse('academia:matricula_editar', args=['online', self.mat.pk])
        self.data = {'editar_pago':'1', 'mat-valor_pagado':'15', 'mat-forma_pago':'abono', 'mat-descuento':'0', 'mat-tipo_cobro':'un_solo_metodo', 'mat-metodo_pago':'efectivo'}

    def test_pantalla_solo_pago(self):
        response = self.client.get(self.url, {'editar_pago':'1'})
        self.assertEqual(response.status_code,200)
        for name in ['est-nombres','mat-jornada','mat-estado','vendedora_id','mat-tipo_matricula']:
            self.assertNotContains(response, 'name="'+name+'"')
        self.assertContains(response, 'Valor pagado (USD)')

    def test_post_manipulado_conserva_datos_y_posteriores(self):
        otro = User.objects.create_user('otro_asesor')
        self.mat.refresh_from_db()
        before = Matricula.objects.values().get(pk=self.mat.pk)
        pago = Abono.objects.values().get(pk=self.posterior.pk)
        self.data.update({'vendedora_id':str(otro.pk), 'est-nombres':'Alterado', 'mat-jornada':'999999', 'mat-valor_curso':'9999', 'mat-tipo_matricula':'programa_completo'})
        response = self.client.post(self.url,self.data)
        self.assertEqual(response.status_code,302, getattr(response,'context',None) and response.context['mat_form'].errors)
        self.mat.refresh_from_db();self.est.refresh_from_db()
        self.assertEqual(self.mat.valor_pagado,Decimal('35'))
        self.assertEqual(self.est.nombres,'Prueba pago')
        after = Matricula.objects.values().get(pk=self.mat.pk)
        self.assertEqual([k for k in before if before[k] != after[k]], ['valor_pagado', 'actualizado'])
        self.assertEqual(pago, Abono.objects.values().get(pk=self.posterior.pk))

    def test_rechaza_sobrepago_y_mixto_incoherente(self):
        for values in [{'mat-valor_pagado':'90'}, {'mat-tipo_cobro':'mixto','mat-monto_pago_1':'8','mat-monto_pago_2':'8','mat-metodo_pago_1':'efectivo','mat-metodo_pago_2':'efectivo'}]:
            before = list(Abono.objects.values())
            response=self.client.post(self.url,{**self.data,**values})
            self.assertEqual(response.status_code,200)
            self.assertTrue(response.context['mat_form'].errors)
            self.assertEqual(before,list(Abono.objects.values()))

    def test_fallo_al_recrear_pago_revierte_operacion(self):
        before=list(Abono.objects.values())
        with patch('academia.views._registrar_pago_inicial',side_effect=RuntimeError('fallo simulado')):
            with self.assertRaises(RuntimeError): self.client.post(self.url,self.data)
        self.assertEqual(before,list(Abono.objects.values()))

    def test_csrf_y_acceso_sin_rol(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.user)
        self.assertEqual(client.post(self.url,self.data).status_code,403)
        otro=User.objects.create_user('sin_rol');self.client.force_login(otro)
        self.assertEqual(self.client.get(self.url).status_code,302)
        self.assertEqual(self.client.get(reverse('academia:api_estudiante_por_cedula',args=[self.est.cedula])).status_code,302)


class CierreSeguroTests(pruebas_existentes.CierreCursoManualTests):
    def test_archivo_conserva_desglose_mixto(self):
        from .models import AbonoArchivado
        Abono.objects.create(matricula=self.matricula_1,fecha=date(2026,8,10),monto=30,metodo='efectivo',monto_2=20,metodo_2='transferencia',banco_2='pichincha',observaciones='Referencia original')
        self.client.post(reverse('academia:cierre_manual_estudiante_ejecutar',args=[self.curso.pk,self.matricula_1.pk]),{'archivo_mes':'8','archivo_anio':'2026','admin_password':'clave-admin-123'})
        pago=AbonoArchivado.objects.get()
        self.assertEqual(pago.monto,Decimal('30'))
        self.assertEqual(pago.metodo_label,'Pago mixto')
        for texto in ['Referencia original','$10.00','$20.00','Pichincha']:
            self.assertIn(texto,pago.observaciones)

    def test_jornada_invalida_no_amplia_alcance(self):
        response=self.client.post(reverse('academia:cierre_ejecutar',args=[self.curso.pk]), {'jornada_id':'invalida','archivo_mes':'8','archivo_anio':'2026','admin_password':'clave-admin-123'})
        self.assertEqual(response.status_code,400)
        self.assertEqual(Matricula.objects.count(),2)
        self.assertFalse(CierreCurso.objects.exists())

    def test_periodo_invalido_no_cierra_mes_por_defecto(self):
        for anio,mes in [('0','8'),('2026','13'),('texto','8')]:
            response=self.client.post(reverse('academia:cierre_global_ejecutar',args=['todas']), {'archivo_mes':mes,'archivo_anio':anio,'admin_password':'clave-admin-123'})
            self.assertEqual(response.status_code,400)
            self.assertEqual(Matricula.objects.count(),2)

    def test_fallo_snapshot_revierte_cierre(self):
        with patch('academia.views_cierre._snapshot_matricula',side_effect=RuntimeError('fallo simulado')):
            response=self.client.post(reverse('academia:cierre_ejecutar',args=[self.curso.pk]), {'archivo_mes':'8','archivo_anio':'2026','admin_password':'clave-admin-123'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(Matricula.objects.count(),2)
        self.assertFalse(CierreCurso.objects.exists())

    def test_global_respeta_mes_y_reintento_no_duplica(self):
        self.matricula_2.fecha_matricula=date(2026,7,10);self.matricula_2.save()
        url=reverse('academia:cierre_global_ejecutar',args=['todas'])
        data={'archivo_mes':'8','archivo_anio':'2026','admin_password':'clave-admin-123'}
        self.client.post(url,data);self.client.post(url,data)
        self.assertEqual(CierreCurso.objects.count(),1)
        self.assertTrue(Matricula.objects.filter(pk=self.matricula_2.pk).exists())


class SegundoFactorSeguroTests(TestCase):
    def test_no_permite_redirigir_codigo_a_otro_correo(self):
        from .authentication import LOGIN_MFA_USER_ID_SESSION_KEY
        user=User.objects.create_user('con_correo',email='original@example.com',password='clave-prueba')
        session=self.client.session
        session[LOGIN_MFA_USER_ID_SESSION_KEY]=user.pk
        session.save()
        with patch('academia.authentication.enviar_codigo_login') as enviar:
            response=self.client.post(reverse('login_email'),{'email':'otro@example.com','email_confirm':'otro@example.com'})
        self.assertRedirects(response,reverse('login'),fetch_redirect_response=False)
        enviar.assert_not_called()
        user.refresh_from_db();self.assertEqual(user.email,'original@example.com')
