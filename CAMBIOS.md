# Cambios aplicados

Resumen de las 4 mejoras solicitadas. Todo probado con el cliente de test de Django.

## ⚠️ Antes de nada: aplicar la migración
Se agregó un campo nuevo (`forma_pago`). En tu servidor corré:

```bash
python manage.py migrate
```

> Nota: el ZIP **no incluye `db.sqlite3`** a propósito, para no sobrescribir tus
> datos ni tu contraseña de admin. Tu base de datos queda intacta; solo corré la
> migración sobre ella.

---

## 1) Registro Administrativo: selector de rango de fechas
- Además del selector Año/Mes, ahora hay un **rango personalizado** (estilo extracto
  bancario): `Desde → Hasta` + botón **Ver rango**, con atajos **Últ. 7 días** y **Últ. 30 días**.
- Todas las tarjetas, comparativas y totales se recalculan con el rango elegido.
- La comparación "vs periodo anterior" usa un periodo equivalente de la misma duración.
- Botón **↩ Mes** para volver a la vista mensual.
- Funciona vía `?desde=YYYY-MM-DD&hasta=YYYY-MM-DD`. Si las fechas son inválidas,
  cae automáticamente a la vista por mes.

Archivos: `academia/views_admin.py`, `templates/admin_panel/dashboard.html`.

## 2) Registro Administrativo: usuarios conectados / última conexión
- Nuevo panel **"Usuarios — última conexión"** con: nombre, rol (Administrador/Asesor),
  estado (🟢 En línea / ⚪ Desconectado) y fecha-hora de última conexión.
- Contador de **usuarios en línea** arriba a la derecha del panel.
- "En línea" = actividad en los últimos 5 minutos. "Última conexión" combina el
  último inicio de sesión con la última actividad registrada.
- Se agregó un middleware liviano (`UltimaActividadMiddleware`) que registra la
  actividad en la sesión (solo escribe una vez por minuto, sin sobrecargar la BD).

Archivos: `academia/middleware.py` (nuevo), `core/settings.py` (registro del middleware),
`academia/views_admin.py`, `templates/admin_panel/dashboard.html`.

## 3) Matrícula: campo obligatorio "Forma de pago" (Abono / Pago completo / Módulo)
- Nuevo `select` **obligatorio** en la zona del valor.
- El **Valor pagado** sigue la lógica según la opción:
  - **Pago completo** → cobra el valor neto (con descuento). Campo bloqueado.
  - **Módulo** → cobra el valor de **un** módulo = valor neto ÷ n.º de módulos del
    curso (depende del curso y la modalidad elegida). Campo bloqueado.
  - **Abono** → monto parcial libre (validado para que no supere el neto).
- Al registrar, el pago se **refleja automáticamente en la sección de Abonos**:
  se crea el abono inicial con el tipo correcto (`pago_completo`, `por_modulo` o `abono`).
- En **edición** el monto pagado se sigue gestionando desde la sección de Abonos
  (no se recaptura), pero la forma de pago sí es editable.

Archivos: `academia/models.py` (campo `forma_pago` + propiedades `valor_modulo`,
`monto_segun_forma_pago`), `academia/forms.py`, `academia/views.py`
(helper `_registrar_pago_inicial` + API del curso devuelve n.º de módulos),
`templates/matricula/form.html`.

## 4) Descuento etiquetado en todo el sistema
- Donde se mostraba solo el número, ahora dice **"Descuento: $X,XX"** (igual que en el
  listado de matrículas):
  - Formulario de matrícula (junto a "Valor a pagar").
  - Detalle de abonos de la matrícula.
  - Control de pagos por módulo.
- Nueva propiedad `Matricula.descuento_etiqueta` para reutilizar el texto estándar.

Archivos: `academia/models.py`, `templates/matricula/form.html`,
`templates/pagos/matricula_abonos.html`, `templates/pagos/por_modulo.html`.

---

### Revisar los cambios
Las modificaciones están sin commitear, así que podés ver exactamente qué cambió con:

```bash
git status
git diff
```
