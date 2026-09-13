# Pago, cierre y seguridad — 13 de septiembre de 2026

Cambios realizados en la copia local. No se ha desplegado en un servidor externo ni se han modificado matrículas de la base real. Hay respaldo de los archivos originales en `/Users/yandrig/Desktop/respaldo-codigo-20260913/`.

## Pago inicial

Al elegir «Editar el pago inicial» se abre una pantalla independiente, con monto, forma de pago, descuento y método (incluido mixto). No aparecen los formularios del estudiante, jornada, estado, asesor o facturación. El tipo de inscripción también se conserva. Los abonos posteriores permanecen intactos y se comprueba que inicial + posteriores no supere el valor neto.

El servidor conserva el asesor aunque alguien manipule la petición. El guardado se ejecuta en una transacción y bloquea la matrícula para serializar las ediciones en bases que admiten bloqueos de fila. Si falla la recreación del pago, se revierte la operación. Se conservan las opciones de módulos de las matrículas antiguas y los bancos existentes.

## Cierre de cursos

La guía visible y desplegable está en el cierre por curso y en el cierre total. Explica cierre individual, jornada, curso y general; fecha de matrícula frente a fecha de archivo; saldos pendientes; limpieza opcional del directorio; contraseña y consulta del historial.

Cerrar archiva, no certifica ni perdona una deuda. El cierre general filtra por mes de matrícula. El individual toma la matrícula exacta seleccionada, aunque sea de otro mes. Los pagos se archivan con la matrícula. No existe restauración automática: borrar un cierre no devuelve los registros activos.

Se rechazan períodos y jornadas malformados, para no convertir silenciosamente una selección inválida en un cierre más amplio. Se añadieron transacciones externas y bloqueos al obtener matrículas para el cierre. Los errores técnicos se registran en el servidor y no se muestran al usuario. Los pagos mixtos conservan su desglose en las observaciones del archivo, visible en el detalle y en el Excel. Esta conservación aplica a nuevos cierres: no reconstruye datos ya perdidos en archivos anteriores.

## Seguridad

- Se impide cambiar el destinatario del segundo factor de una cuenta que ya tiene correo mediante la pantalla de registro de correo. También se comprueba si el correo cambió mientras el reto estaba pendiente.
- Las APIs de consulta de estudiantes por cédula y celular requieren rol de matrícula.
- Los usuarios inactivos no se consideran administradores ni asesores.
- La edicion de datos, pago inicial y cambio de jornada de una matricula queda limitada al usuario que la registro. Los administradores pueden editar cualquier matricula. En registros antiguos sin `registrado_por`, se usa `vendedora` como respaldo. La eliminacion desde el listado queda bajo la misma regla para que una asesora ajena no pueda borrar la matricula.
- Las sesiones pasan de diez años a doce horas renovables, configurables mediante `SESSION_COOKIE_AGE`, con expiración al cerrar el navegador por defecto. Se aplican cookies HttpOnly/SameSite y una política de referencia del mismo origen. La restauración de sesiones del navegador puede conservar cookies de sesión.
- En producción se rechazan claves predeterminadas/cortas y hosts comodín.
- Django se actualizó de 6.0.7 a 6.0.8, sqlparse de 0.5.5 a 0.6.0 y pip de 26.1.2 a 26.2.1. Se actualizaron los requisitos de la aplicación. El entorno usado es Python 3.14; Django 6 requiere Python 3.12 o posterior.

Referencia oficial del parche de Django: https://www.djangoproject.com/weblog/2026/aug/04/security-releases/

La auditoría con pip-audit de las dependencias instaladas terminó sin vulnerabilidades conocidas. El informe está en `verificaciones/2026-09-13/dependencias.json`. Esto no equivale a certificar que toda la aplicación o su infraestructura carezcan de vulnerabilidades.

## Validación y despliegue

Pruebas de regresión: pago normal y mixto incoherente, sobrepago, petición manipulada, preservación de otros datos y abonos, reversión ante fallos, CSRF, usuario sin rol, cierre por estudiante y jornada, período, cierre global, reintento y protección del correo de verificación. Se revisaron las pantallas renderizadas en el navegador con datos ficticios. No se hizo un cierre sobre información real.

El `.env` local permanece en modo desarrollo. Al probar su configuración como producción, la nueva protección detectó una clave que no cumple el requisito de producción. No se cambió esa clave automáticamente para evitar invalidar sesiones existentes. Antes de desplegar, configura una clave aleatoria de al menos 50 caracteres, `DEBUG=False`, dominios explícitos en `ALLOWED_HOSTS` y HTTPS. El cambio de clave puede requerir que los usuarios inicien sesión otra vez. El chequeo de despliegue pasa con una clave temporal segura y hosts explícitos, usados únicamente en el proceso de validación.

En el entorno del servidor, instalar los requisitos con su Python compatible, actualizar pip y ejecutar `python manage.py check --deploy`, luego reiniciar el servicio. No se añadieron migraciones. Revisar en el servidor real HTTPS/proxy, acceso a la base, copias de respaldo y límites de intentos de acceso; esta revisión local no es una prueba de penetración ni valida la infraestructura remota.

Resultado final: 306 pruebas de la aplicación aprobadas. `manage.py check`, `pip check` y comprobación de migraciones sin incidencias. El log completo del cambio anterior se conserva en `verificaciones/2026-09-13/pruebas.txt`.
