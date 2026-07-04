"""
Django settings for core project.
"""
from pathlib import Path
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, True),
    SECRET_KEY=(str, 'django-insecure-dev-key-cambiar-en-produccion-xxxxxxxx'),
    DB_NAME=(str, ''),
    DB_USER=(str, ''),
    DB_PASSWORD=(str, ''),
    DB_HOST=(str, '127.0.0.1'),
    DB_PORT=(str, '3306'),
    OPENAI_API_KEY=(str, ''),
    OPENAI_MODEL=(str, 'gpt-4o-mini'),
)
env_file = BASE_DIR / '.env'
if env_file.exists():
    environ.Env.read_env(env_file)

SECRET_KEY = env('SECRET_KEY')
DEBUG = env('DEBUG')

# ── MercyBot / OpenAI ──
# La clave se lee del .env (nunca se versiona). Si está vacía, MercyBot
# responde con sus reglas básicas sin llamar a la API.
OPENAI_API_KEY = env('OPENAI_API_KEY')
OPENAI_MODEL = env('OPENAI_MODEL')

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['*'])

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'academia',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'academia.middleware.UltimaActividadMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'academia.context_processors.roles',
                'academia.context_processors.feature_flags',
                'academia.context_processors.recordatorios',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'

if env('DB_NAME'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': env('DB_NAME'),
            'USER': env('DB_USER'),
            'PASSWORD': env('DB_PASSWORD'),
            'HOST': env('DB_HOST'),
            'PORT': env('DB_PORT'),
            'OPTIONS': {
                'charset': 'utf8mb4',
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'es-ec'
TIME_ZONE = 'America/Guayaquil'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/bienvenida/'


# ======== CONFIGURACIÓN DE SESIÓN (AUTO-LOGOUT) ========
# Cerrar sesión después de 20 minutos (1200 segundos) de inactividad
SESSION_COOKIE_AGE = 1200
# Refrescar la cookie en cada solicitud para que cuente 20 minutos desde el último clic
SESSION_SAVE_EVERY_REQUEST = True
# Cerrar sesión si el usuario cierra el navegador
SESSION_EXPIRE_AT_BROWSER_CLOSE = True


# ======== SEGURIDAD EN PRODUCCIÓN (AWS / HTTPS) ========
# Estos ajustes solo se aplican cuando DEBUG=False (producción). En
# desarrollo local (DEBUG=True) quedan desactivados para no forzar HTTPS.
if not DEBUG:
    # Detrás de un balanceador de AWS (ALB/ELB) que termina el SSL,
    # esta cabecera evita bucles de redirección al forzar HTTPS.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=True)

    # Cookies de sesión y CSRF solo por HTTPS.
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # HTTP Strict Transport Security (1 año). Activar solo si TODO el
    # sitio se sirve por HTTPS.
    SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

    # Evita que el navegador adivine el tipo de contenido.
    SECURE_CONTENT_TYPE_NOSNIFF = True

    # Sirve estáticos comprimidos vía WhiteNoise. Se usa la variante SIN
    # "manifest" a propósito: si algún archivo estático referenciado no
    # existe (p. ej. un video no incluido), la página NO se cae con 500;
    # solo ese recurso devuelve 404 y el resto funciona normal.
    STORAGES = {
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage',
        },
    }
