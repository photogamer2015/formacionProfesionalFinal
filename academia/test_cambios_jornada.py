from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch
from django.contrib.auth.models import User
from django.db import transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from .tests import PlanRecaudacionTests
from .models import JornadaCurso, CambioJornada, Matricula, Abono, Curso, RecuperacionPendiente, Comprobante
from .views_pagos import _construir_hoja_recaudacion

class CambiosJornadaTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_superuser('cambios',password='prueba')
        self.client.force_login(self.user)
        helper=PlanRecaudacionTests();helper.setUp()
        self.m=helper._matricula_con_adelanto(Decimal('110'),Decimal('35'),4)
        self.m.vendedora=self.user;self.m.save()
        self.nueva=JornadaCurso.objects.create(curso=self.m.curso,modalidad='presencial',descripcion='sabados_intensivos',fecha_inicio=date(2026,9,6))
        self.url=reverse('academia:matricula_cambiar_jornada',args=[self.m.pk])
        self.datos={'jornada':self.nueva.pk,'jornada_original':self.m.jornada_id,'motivo':'Nuevo horario de trabajo'}

    def test_solo_cambia_jornada_y_calendario_conserva_pagos(self):
        antes=Matricula.objects.values().get(pk=self.m.pk)
        pagos=list(Abono.objects.values())
        RecuperacionPendiente.objects.create(matricula=self.m,numero_modulo=1,fecha_marcada=date(2026,7,8))
        recuperaciones=list(RecuperacionPendiente.objects.values())
        comp_antes=Comprobante.objects.values().get(matricula=self.m)
        otra=Matricula.objects.create(estudiante=self.m.estudiante,curso=self.m.curso,jornada=self.m.jornada,modalidad='presencial',valor_curso=110,fecha_matricula=date(2026,7,8))
        otra_antes=Matricula.objects.values().get(pk=otra.pk)
        response=self.client.post(self.url,self.datos)
        self.assertEqual(response.status_code,302)
        despues=Matricula.objects.values().get(pk=self.m.pk)
        self.assertEqual([k for k in antes if antes[k]!=despues[k]],['jornada_id'])
        self.assertEqual(pagos,list(Abono.objects.values()))
        self.assertEqual(recuperaciones,list(RecuperacionPendiente.objects.values()))
        self.assertEqual(otra_antes,Matricula.objects.values().get(pk=otra.pk))
        comp_despues=Comprobante.objects.values().get(matricula=self.m)
        self.assertEqual(set(k for k in comp_antes if comp_antes[k]!=comp_despues[k]),{'jornada','inicio_curso'})
        RecuperacionPendiente.objects.all().delete()
        self.m.refresh_from_db()
        hoja=_construir_hoja_recaudacion(self.m.curso,[self.m],date(2026,9,7))
        self.assertFalse(hoja['items'][0]['pago_pendiente_fecha'])
        hoja=_construir_hoja_recaudacion(self.m.curso,[self.m],date(2026,9,13))
        self.assertTrue(hoja['items'][0]['pago_pendiente_fecha'])
        self.assertEqual(CambioJornada.objects.count(),1)
        log=CambioJornada.objects.get();self.assertIn('06/09/2026',log.jornada_nueva)
        self.nueva.descripcion_otros='Otro';self.nueva.save()
        self.assertEqual(CambioJornada.objects.get().jornada_nueva,log.jornada_nueva)

    def test_rechaza_otro_curso_modalidad_inactiva_y_misma_jornada(self):
        otro=Curso.objects.create(nombre='Otro curso')
        for cambios in [{'curso':otro},{'modalidad':'online'},{'activo':False}]:
            for k,v in cambios.items():setattr(self.nueva,k,v)
            self.nueva.save()
            self.assertEqual(self.client.post(self.url,self.datos).status_code,200)
            self.assertEqual(CambioJornada.objects.count(),0)
            self.nueva.curso=self.m.curso;self.nueva.modalidad='presencial';self.nueva.activo=True
        self.datos['jornada']=self.m.jornada_id
        self.client.post(self.url,self.datos)
        self.assertEqual(CambioJornada.objects.count(),0)

    def test_doble_envio_y_formulario_desactualizado(self):
        self.client.post(self.url,self.datos)
        self.client.post(self.url,self.datos)
        self.assertEqual(CambioJornada.objects.count(),1)

    def test_fallo_historial_revierte_traslado(self):
        with patch('academia.views_jornadas_estudiante.CambioJornada.objects.create',side_effect=RuntimeError('fallo')):
            with self.assertRaises(RuntimeError):self.client.post(self.url,self.datos)
        anterior=self.m.jornada_id;self.m.refresh_from_db();self.assertEqual(self.m.jornada_id,anterior)

    def test_datos_ignora_jornada_pagos_y_otros_estudiantes(self):
        antes=Matricula.objects.values().get(pk=self.m.pk);pagos=list(Abono.objects.values())
        self.m.estudiante.correo='antes@example.com';self.m.estudiante.save()
        data={'est-cedula':self.m.estudiante.cedula,'est-nombres':'Nombre corregido','est-correo':'nuevo@example.com','mat-jornada':self.nueva.pk,'mat-valor_pagado':'999','mat-descuento':'100','mat-curso':'999'}
        response=self.client.post(reverse('academia:matricula_editar',args=['presencial',self.m.pk]),data)
        self.assertEqual(response.status_code,302)
        self.assertEqual(antes,Matricula.objects.values().get(pk=self.m.pk))
        self.assertEqual(pagos,list(Abono.objects.values()))
        self.m.estudiante.refresh_from_db();self.assertEqual(self.m.estudiante.nombres,'Nombre corregido')

    def test_historial_mes_actual_anterior_y_acceso_todos_autenticados(self):
        self.client.post(self.url,self.datos)
        log=CambioJornada.objects.get();hoy=timezone.localdate();primer=hoy.replace(day=1)
        from datetime import timedelta
        previo=primer-timedelta(days=1)
        CambioJornada.objects.filter(pk=log.pk).update(creado=timezone.make_aware(datetime(previo.year,previo.month,15,12)))
        lector=User.objects.create_user('lector',password='prueba');self.client.force_login(lector)
        url=reverse('academia:cambios_jornada')
        response=self.client.get(url);self.assertEqual(response.status_code,200);self.assertEqual(response.context['total'],0)
        response=self.client.get(url,{'mes':previo.strftime('%Y-%m')});self.assertEqual(response.context['total'],1)
        self.client.post(self.url,self.datos);self.assertEqual(CambioJornada.objects.count(),1)
        self.client.logout();self.assertEqual(self.client.get(url).status_code,302)
