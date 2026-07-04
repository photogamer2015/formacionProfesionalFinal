"""
Comando: python manage.py init_proyecto

Deja el proyecto LISTO para usar en una base de datos nueva (por ejemplo el
MySQL de AWS): crea los grupos/roles del sistema y un superusuario
administrador para poder entrar.

Es IDEMPOTENTE: se puede ejecutar varias veces sin duplicar nada.
  - Si los grupos ya existen, solo actualiza sus permisos.
  - Si ya hay un superusuario, NO crea otro.

Credenciales del superusuario (en este orden de prioridad):
  1. Argumentos:  --username / --password / --email
  2. Variables de entorno:  DJANGO_SUPERUSER_USERNAME / _PASSWORD / _EMAIL
  3. Valores por defecto:  admin / admin1234   (⚠ CÁMBIALOS de inmediato)

Ejemplos:
  python manage.py init_proyecto
  python manage.py init_proyecto --username Yandri --password "MiClaveSegura#2025"
  DJANGO_SUPERUSER_USERNAME=admin DJANGO_SUPERUSER_PASSWORD=xxxx python manage.py init_proyecto
"""
import os

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand

DEFAULT_USERNAME = 'admin'
DEFAULT_PASSWORD = 'admin1234'


class Command(BaseCommand):
    help = 'Inicializa el proyecto: crea roles/grupos y un superusuario administrador.'

    def add_arguments(self, parser):
        parser.add_argument('--username', default=None, help='Usuario del superusuario a crear.')
        parser.add_argument('--password', default=None, help='Contraseña del superusuario a crear.')
        parser.add_argument('--email', default=None, help='Correo del superusuario (opcional).')

    def handle(self, *args, **options):
        # ── 1) Roles / grupos (idempotente) ──────────────────────────
        self.stdout.write('→ Creando/actualizando roles y permisos...')
        call_command('setup_roles')

        # ── 2) Superusuario ──────────────────────────────────────────
        User = get_user_model()

        username = options['username'] or os.environ.get('DJANGO_SUPERUSER_USERNAME') or DEFAULT_USERNAME
        email = options['email'] or os.environ.get('DJANGO_SUPERUSER_EMAIL') or ''
        password = options['password'] or os.environ.get('DJANGO_SUPERUSER_PASSWORD') or DEFAULT_PASSWORD
        password_es_default = password == DEFAULT_PASSWORD

        self.stdout.write('')
        if User.objects.filter(is_superuser=True).exists():
            self.stdout.write(self.style.WARNING(
                '→ Ya existe al menos un superusuario. No se crea otro.'
            ))
        elif User.objects.filter(username=username).exists():
            self.stdout.write(self.style.WARNING(
                f'→ Ya existe un usuario "{username}". No se crea de nuevo.'
            ))
        else:
            User.objects.create_superuser(username=username, email=email, password=password)
            self.stdout.write(self.style.SUCCESS(f'✓ Superusuario "{username}" creado.'))
            if password_es_default:
                self.stdout.write(self.style.WARNING(
                    f'⚠  Se usó la contraseña por defecto "{DEFAULT_PASSWORD}". '
                    'CÁMBIALA de inmediato desde /admin/ (Users → tu usuario → Change password) '
                    'o define DJANGO_SUPERUSER_PASSWORD antes de correr el comando.'
                ))

        # ── Resumen ──────────────────────────────────────────────────
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            '✓ Proyecto inicializado. Ya puedes ingresar por /login/ con el superusuario, '
            'y crear/asignar asesoras al grupo "Asesores" desde /admin/.'
        ))
