# CHANGELOG v3.0 - Tablas mejoradas y actualizacion AWS

## 1. Tabla de Estado de Pagos mas limpia
- La tabla principal de `/pagos/` pasa de 15 a 11 columnas visibles.
- La primera columna consolida estudiante, C.I./RUC, curso y fecha de
  matricula para reducir el scroll horizontal.
- Se mantiene la informacion financiera: jornada, inicio, valor del curso,
  pagado, tipo, metodo, saldo, estado, asistencia y acciones.
- La tabla usa `data-table-page-size="15"` para mostrar 15 registros por pagina.

## 2. Paginacion de tablas configurable
- `static/responsive.js` ahora respeta `data-table-page-size` o `data-page-size`
  en cada tabla.
- Si una tabla no define tamano, conserva el valor global de 10 filas.

## 3. Configuracion de produccion mas simple
- `core/settings.py` lee `CSRF_TRUSTED_ORIGINS` desde `.env`.
- En `DEBUG=False`, si no se define `CSRF_TRUSTED_ORIGINS`, se genera a partir
  de `ALLOWED_HOSTS` con HTTPS.
- HSTS ahora se puede ajustar con variables de entorno.

## 4. Actualizacion rapida en AWS
- Nuevo script `scripts/update_aws.sh`.
- El script hace `git pull --ff-only`, instala dependencias, corre migraciones,
  ejecuta `collectstatic` y reinicia `formacion.service` si existe.
- Nuevo ejemplo `deploy/systemd/formacion.service.example` para correr Gunicorn
  como servicio.
- `DESPLIEGUE_AWS.md`, `.env.example` y `README.md` documentan el flujo real del
  repositorio `photogamer2015/formacionProfesionalFinal`.

## Notas
- No requiere migraciones de base de datos.
- No se sube ni se toca `.env`, `db.sqlite3`, `venv/` ni datos privados.
