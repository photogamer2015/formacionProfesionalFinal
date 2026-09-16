"""Regresion de persistencia y cierre explicito para cualquier rol."""

from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.contrib.sessions.models import Session
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone


@override_settings(SECURE_SSL_REDIRECT=False)
class SesionesPersistentesTests(TestCase):
    def test_persistencia_por_rol_y_cierre_solo_del_dispositivo_actual(self):
        for rol in ("Administradores", "Asesores", "Usuario", "Superusuario"):
            with self.subTest(rol=rol):
                user = User.objects.create_user(
                    username=rol,
                    is_superuser=rol == "Superusuario",
                    is_staff=rol == "Superusuario",
                )
                if rol in ("Administradores", "Asesores"):
                    user.groups.add(Group.objects.get_or_create(name=rol)[0])

                dispositivo = Client()
                otro_dispositivo = Client()
                dispositivo.force_login(user)
                otro_dispositivo.force_login(user)
                session_key = dispositivo.session.session_key

                response = dispositivo.get(reverse("login"))
                cookie = response.cookies[settings.SESSION_COOKIE_NAME]
                self.assertFalse(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)
                self.assertEqual(int(cookie["max-age"]), 60 * 60 * 24 * 365 * 10)
                self.assertTrue(cookie["expires"])
                vencimiento = Session.objects.get(session_key=session_key).expire_date

                # Reabrir el navegador conservando unicamente su cookie persistente.
                reabierto = Client()
                reabierto.cookies[settings.SESSION_COOKIE_NAME] = cookie.value
                futuro = timezone.now() + timedelta(days=30)
                with patch("django.utils.timezone.now", return_value=futuro):
                    response = reabierto.get(reverse("login"))
                    self.assertTrue(response.wsgi_request.user.is_authenticated)
                    self.assertGreater(
                        Session.objects.get(session_key=session_key).expire_date,
                        vencimiento,
                    )

                response = reabierto.post(reverse("logout"))
                self.assertEqual(response.status_code, 302)
                self.assertFalse(Session.objects.filter(session_key=session_key).exists())
                self.assertNotIn("_auth_user_id", reabierto.session)

                # La cookie antigua no recupera una sesion cerrada.
                dispositivo.get(reverse("login"))
                self.assertNotIn("_auth_user_id", dispositivo.session)

                response = otro_dispositivo.get(reverse("login"))
                self.assertTrue(response.wsgi_request.user.is_authenticated)
