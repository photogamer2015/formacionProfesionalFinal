# Despliegue en AWS — Formación Técnica Profesional

Guía paso a paso para dejar el sistema funcionando en un servidor (por
ejemplo EC2 Ubuntu + base de datos MySQL en RDS). Sigue el orden.

---

## 1. Dependencias del sistema (ANTES de instalar paquetes de Python)

`mysqlclient` necesita librerías del sistema o `pip install` falla:

```bash
sudo apt update
sudo apt install -y python3-dev python3-venv default-libmysqlclient-dev build-essential pkg-config
```

## 2. Código y entorno virtual

```bash
git clone https://github.com/<tu-usuario>/<tu-repo>.git
cd <tu-repo>
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 3. Archivo `.env` (NUNCA se sube al repo)

Copia el ejemplo y edítalo:

```bash
cp .env.example .env
nano .env
```

Valores mínimos para producción:

```ini
DEBUG=False
SECRET_KEY=<pega-aqui-una-clave-aleatoria>     # genérala con el comando de abajo
ALLOWED_HOSTS=tu-dominio.com,www.tu-dominio.com  # o la IP/DNS del servidor

# MySQL de AWS (RDS). Si dejas DB_NAME vacío, usa SQLite (solo para pruebas).
DB_NAME=formacion
DB_USER=<usuario_rds>
DB_PASSWORD=<password_rds>
DB_HOST=<endpoint>.rds.amazonaws.com
DB_PORT=3306
```

Generar el `SECRET_KEY`:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

## 4. Base de datos: migrar e INICIALIZAR (roles + superusuario)

```bash
python manage.py migrate
python manage.py init_proyecto
```

`init_proyecto` deja todo listo: crea los grupos **Administradores** y
**Asesores** con sus permisos y un superusuario para entrar.

- Por defecto crea el usuario `admin` con contraseña `admin1234`
  (**cámbiala de inmediato**).
- Para definir tus propias credenciales desde el inicio:

  ```bash
  python manage.py init_proyecto --username Yandri --password "TuClaveSegura#2025"
  ```

  o con variables de entorno:

  ```bash
  DJANGO_SUPERUSER_USERNAME=admin DJANGO_SUPERUSER_PASSWORD=xxxx python manage.py init_proyecto
  ```

El comando es idempotente: se puede correr varias veces sin duplicar nada.

## 5. Archivos estáticos

```bash
python manage.py collectstatic --noinput
```

## 6. Servir la aplicación (Gunicorn)

```bash
gunicorn core.wsgi:application --bind 0.0.0.0:8000 --workers 3
```

En producción va detrás de Nginx o del balanceador (ALB). Si el balanceador
termina el SSL, la app ya está preparada (usa `X-Forwarded-Proto` para no
entrar en bucle de redirección HTTPS).

---

## Después de entrar

1. Ingresa por `/login/` con el superusuario.
2. Entra a `/admin/` para crear las asesoras y asignarlas al grupo
   **Asesores** (Users → editar usuario → Groups). Ellas entran por
   `/login/`, no necesitan `/admin/`.

---

## Errores comunes y solución

| Síntoma | Causa | Solución |
|---|---|---|
| `pip install` falla en `mysqlclient` | Faltan libs del sistema | Ejecuta el paso 1 |
| `DisallowedHost` / 400 al abrir | Falta el dominio en `ALLOWED_HOSTS` | Ponlo en el `.env` |
| No puedo entrar / no hay usuarios | No corriste `init_proyecto` | `python manage.py init_proyecto` |
| Solo existe "Administradores", falta "Asesores" | Migración creó roles a medias | `python manage.py init_proyecto` (los completa) |
| Estáticos (CSS/logo) no cargan | Falta `collectstatic` | Ejecuta el paso 5 |
| Error de conexión a la BD | Datos `DB_*` o security group de RDS | Revisa `.env` y que el puerto 3306 esté abierto al servidor |

> Nota: el video de la página de Ayuda (`El Plan Maestro.mp4`) no viene
> incluido. No rompe nada (solo ese reproductor sale vacío). Si lo quieres,
> coloca el archivo en `static/`; si no, quita esa sección de
> `templates/ayuda.html`.
