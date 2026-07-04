# CHANGELOG v2.9 — Factura, Módulos, Cierre por mes y Banner progresivo

Resumen de los 5 cambios solicitados.

## 1. Factura con datos (matrícula)
- Cuando **¿Factura con datos? = Sí**, los datos de factura (Nombres, Cédula/RUC,
  Correo) se **autocompletan** con los datos del estudiante de la matrícula.
  Si editas un campo de factura a mano, se respeta y deja de sobreescribirse.
- Con factura = Sí, **Correo, Celular y Ciudad** del estudiante pasan a ser
  **obligatorios** (validado en el navegador y en el servidor).
- Archivos: `templates/matricula/form.html` (JS), `academia/forms.py`
  (`EstudianteForm.__init__`/`clean` con flag `factura_si`), `academia/views.py`
  (pasa `factura_si` a `EstudianteForm` en registrar y editar).

## 2. Quitar tarjetas de resumen en Pagos
- Se eliminaron las tres tarjetas **FACTURADO / COBRADO / POR COBRAR** de la
  vista de pagos.
- Archivo: `templates/pagos/lista.html`.

## 3. Cierre por mes (no mezclar meses)
- El cierre (por curso y global) ahora solo incluye las matrículas cuya
  **fecha de matrícula** cae en el **mes/año elegido** del cierre. Una matrícula
  de otro mes (p. ej. del mes siguiente) ya no entra en el cierre.
- La vista previa tiene un selector de **Mes / Año** y muestra
  "Cerrando matrículas de: <Mes> <Año>". El mes elegido en la previa se usa al
  ejecutar. Los adicionales se filtran por el mismo mes.
- Archivos: `academia/views_cierre.py` (`_periodo_desde_request`,
  `_matriculas_a_cerrar`, previews y ejecuciones), `templates/cursos/cierre_preview.html`,
  `templates/cursos/cierre_global_preview.html`.

## 4. Reserva + Módulo: desplegable "Módulo a pagar"
- Al elegir **Matrícula = "Reserva + Módulo 1"** aparece el selector
  **"Módulo a pagar"** con opciones acumulativas según los módulos del curso:
  *Módulo 1*, *Módulos 1 y 2*, *Módulos 1, 2 y 3*, …
- El **Valor pagado** se sugiere automáticamente = (nº de módulos) × (valor por módulo).
- Al guardar, cada módulo elegido se registra como un pago **Por módulo** y queda
  marcado como **Pagado** en el historial y el desglose.
  (Pago Mixto se aplica al primer módulo; si eliges varios módulos, el resto usa
  el método principal.)
- Archivos: `academia/forms.py` (campo `modulos_a_pagar`),
  `templates/matricula/form.html` (selector + JS), `academia/views.py`
  (`_registrar_pago_inicial` crea los abonos por módulo).

## 5. Banner progresivo por semanas
- En el panel de "Gestión de Matrículas", tras pagar el **Módulo 1** la alerta de
  ese módulo desaparece y, a la semana siguiente, aparece la del **Módulo 2**, y
  así sucesivamente. **1 módulo = 1 semana**, contando **desde el inicio de la
  jornada** (`fecha_inicio`). Si un curso tiene 4 módulos, hay 4 semanas; ciclo
  corto de 2 → 2 semanas.
- La alerta muestra "Pendiente de pago (Módulo N de T)" y el botón "Ya revisado"
  se aplica al módulo correcto.
- Archivos: `academia/views_pagos.py` (`_calcular_alertas_pago`),
  `templates/bienvenida.html`.

## Notas
- No requiere migraciones nuevas (los campos añadidos son solo de formulario).
- Criterios usados (avísame si prefieres otro): al pagar varios módulos quedan
  marcados como pagados completos; las semanas del banner se cuentan desde
  `fecha_inicio` de la jornada.
