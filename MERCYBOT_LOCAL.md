# MercyBot local

MercyBot consulta la base de datos del sistema y mantiene una conversación por sesión. No utiliza un modelo de IA, claves de API ni servicios externos para generar respuestas. Reconoce intenciones y campos definidos en `academia/mercybot.py`; no aprende automáticamente nuevas operaciones a partir de los mensajes.

## Uso

- `Quiero agregar un nuevo estudiante` o `registrar matrícula`: es el mismo flujo. Recoge la matrícula completa —todos los campos de `EstudianteForm` y de `MatriculaForm` más la asesora— y guarda estudiante, matrícula, pago inicial y comprobante en una sola transacción al final. Los opcionales se pueden saltar con `omitir` o `omitir opcionales`.
- Al indicar el curso muestra sus jornadas activas con fecha de inicio, modalidad y sede; al elegir una informa el precio de esa modalidad (`usar valor` toma el precio del curso). Cambiar de curso o de jornada descarta solo los datos que dependían de la anterior.
- Pide también estado, tipo de matrícula, fecha de matrícula (`hoy` o DD/MM/AAAA), valor, descuento, forma de pago, valor pagado, pago simple o mixto con su método y banco, talla de camiseta cuando el curso es Técnico, observaciones, origen de la venta, asesora (`yo` se asigna al usuario), factura con sus datos y enlace del comprobante.
- No escribe nada hasta que el formulario completo valida: un dato faltante o inválido deja la conversación pendiente sin crear estudiante, matrícula ni pago. Si el estudiante ya existe por cédula, reutiliza su ficha y avisa; si ya tiene una matrícula activa en esa misma jornada, no crea otra.
- Se pueden enviar varios datos juntos: `cédula: 0912345678; nombres: Ana Pérez; celular: 0991234567; ciudad: Quito`. También reconoce `mi cédula es ...`.
- Si el celular pertenece a otra persona, exige corregirlo o confirmar expresamente `número compartido: sí`.
- `Ver pagos de Andrés Guevara` o `ver pagos de 0912345678`: consulta matrículas, importes, saldo y los últimos 20 abonos por matrícula, con enlaces al historial completo. Las consultas incluyen los registros vivos; el archivo histórico se revisa en su sección.
- Si coinciden varios estudiantes, pide la cédula exacta. La búsqueda de nombres tolera tildes y cambios de orden.
- `Y sus recuperaciones`: reutiliza el estudiante de la consulta anterior.
- `Registrar recuperación`: pide estudiante, matrícula si hay varias, módulo pendiente, fecha de falta, fecha programada, clase/equipo cuando corresponde y observaciones. Reutiliza `RecuperacionPendienteForm`, conserva el saldo al marcar y evita duplicados de matrícula/módulo/clase/fecha.
- `Abrir pagos`, `abrir cursos online`, `abrir matrícula`, `abrir recuperaciones`: navega a las rutas existentes.
- `Cómo funcionan los pagos por módulo`, `factura` o `hoja de recaudación`: ofrece guías locales basadas en la ayuda y formularios del sistema.
- `Hola`, `qué tal`, `buenas` o `hola soy Ana`: Mercy saluda según la hora, usa el nombre que la persona indica (o el de su usuario) y se presenta con lo que puede hacer. Saludar a mitad de un registro no altera los datos pendientes.
- `Atrás`, `volver`, `regresar`, `paso anterior`, `me equivoqué` o `deshacer`: descarta el último dato capturado y vuelve a preguntarlo. Volver sobre el curso reabre también la jornada, el valor y la talla, que dependen de él; volver reactiva las preguntas opcionales que se habían saltado. Funciona igual en matrículas y en recuperaciones. El widget muestra además un botón «← Atrás» junto al de cancelar mientras hay un registro pendiente.
- `Ayuda`: muestra las capacidades.
- Detener un registro: además de `cancelar`, reconoce `cancelar matrícula`, `anular el registro`, `detener`, `reiniciar`, `ya no quiero registrar`, `mejor no`, `olvídalo` o `ya no`. Las formas breves no se aplican cuando el dato pedido es texto libre (observaciones, título profesional), donde podrían ser el valor real. El widget muestra además los botones «← Atrás» y «Cancelar registro» mientras hay uno pendiente. Cancelar descarta los datos pendientes; los registros ya guardados permanecen.
- Preguntas u órdenes durante un registro (`ver pagos de…`, `abrir cursos`, `cuántos cursos hay`) no se guardan como respuesta: el bot avisa qué dato falta y ofrece cancelar.

Registrar por chat guarda la matrícula completa con su pago inicial, usando `_guardar_matricula_formularios`, el mismo guardado de la pantalla de registro. Las ediciones, eliminaciones y cobros posteriores se realizan en los formularios existentes. El bot no afirma haber realizado una operación que no ejecutó. Los temas no reconocidos reciben: «Eso no se encuentra en el sistema, lo siento, no te puedo ayudar».

## Integración y mantenimiento

La respuesta del chat incluye `pending`, que indica si quedó un registro a medias; el widget lo usa para mostrar el aviso y el botón de cancelar, y la voz lee solo las dos primeras líneas útiles (las listas de cursos, jornadas y opciones se leen en pantalla). La voz elige una voz española cálida —prefiere las «natural/neural» y descarta las masculinas—, espera a que el navegador termine de cargarlas antes de hablar y pronuncia los importes como «20 dólares con 50». Las consultas de pagos y recuperaciones traen los abonos y las recuperaciones con `prefetch_related`, de modo que el número de consultas no crece con la cantidad de matrículas.

Ambas rutas de chat utilizan el mismo motor local y conservan autenticación, CSRF y permisos. Solo administradores y asesores pueden consultar información de estudiantes y registrar matrículas/recuperaciones. Cada paso vuelve a comprobar permisos. Los guardados usan transacciones y los mensajes repetidos con el mismo identificador inmediato reutilizan su respuesta.

El texto del chat se escapa antes de mostrarlo; la navegación llega en un campo separado y solo acepta rutas internas. El historial visual está separado por usuario y pestaña. No se requiere migración ni cambiar los modelos o reglas de cálculo.

Para ampliar vocabulario, modificar `intent`, `ALIASES`, `SECTIONS` o `KNOWLEDGE`. Toda nueva escritura debe usar los formularios, permisos y validaciones del módulo correspondiente y agregar pruebas de errores, ambigüedad y duplicados. No ejecutar instrucciones contenidas en mensajes o registros ni conectar el despachador legado de herramientas.

Pruebas:

```sh
DB_NAME='' venv/bin/python manage.py test academia.test_mercybot academia.test_mercybot_matricula academia.tests.JornadaOrdenYFiltroTests academia.tests.PagosFiltroRecuperacionTests academia.tests.CamposNumericosMatriculaTests --noinput
venv/bin/python manage.py check
```

Las pruebas crean una base independiente y no escriben en los registros de operación.
