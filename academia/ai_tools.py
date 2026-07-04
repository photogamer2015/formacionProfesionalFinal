import json
from decimal import Decimal
from django.db.models import Sum, Count, Q
from django.utils.timezone import now
from .models import Estudiante, Matricula, Curso, Abono

def buscar_estudiante(nombre):
    """Busca estudiantes por nombre, apellido o cédula y devuelve un informe detallado.

    Búsqueda flexible por tokens: cada palabra del término debe aparecer en
    nombres (sin importar el orden). Así 'Yandri Guevara' encuentra
    a 'Guevara Bustos Yandri David'. Si el término es solo dígitos, busca por cédula.
    """
    termino = (nombre or "").strip()
    if not termino:
        return json.dumps({"mensaje": "Indícame un nombre, apellido o número de cédula para buscar."})

    # Si parece una cédula (solo dígitos), priorizar búsqueda por cédula
    solo_digitos = termino.replace(" ", "").isdigit()

    if solo_digitos:
        estudiantes = Estudiante.objects.filter(cedula__icontains=termino.replace(" ", "")).distinct()
    else:
        # Cada palabra debe estar en nombres (orden indiferente)
        qs = Estudiante.objects.all()
        for palabra in termino.split():
            qs = qs.filter(
                Q(nombres__icontains=palabra) |

                Q(cedula__icontains=palabra)
            )
        estudiantes = qs.distinct()

        # Fallback: si los tokens no dan resultado, intento amplio (OR) por si
        # el usuario escribió un solo apodo o un fragmento.
        if not estudiantes.exists():
            estudiantes = Estudiante.objects.filter(
                Q(nombres__icontains=termino) |
                Q(cedula__icontains=termino)
            ).distinct()
    
    resultados = []
    for e in estudiantes[:5]:
        matriculas = e.matriculas.all()
        historial_cursos = []
        deuda_total = Decimal('0.00')
        pagado_total = Decimal('0.00')
        
        for m in matriculas:
            historial_cursos.append({
                "curso": m.curso.nombre,
                "modalidad": getattr(m, "modalidad", "") or "",
                "jornada": str(m.jornada) if getattr(m, "jornada", None) else "",
                "estado": m.estado,
                "saldo_pendiente_usd": float(m.saldo),
                "total_pagado_usd": float(m.valor_pagado)
            })
            deuda_total += m.saldo
            pagado_total += m.valor_pagado
            
        resultados.append({
            "id": e.id,
            "cedula": e.cedula,
            "nombre_completo": f"{e.nombres}",
            "celular": e.celular,
            "correo": e.correo,
            "ciudad": getattr(e, "ciudad", "") or "",
            "resumen_financiero": {
                "total_pagado_usd": float(pagado_total),
                "deuda_total_usd": float(deuda_total)
            },
            "cursos": historial_cursos
        })
    
    if not resultados:
        return json.dumps({
            "mensaje": f"No se encontró ningún estudiante que coincida con '{nombre}'.",
            "sugerencia": "Verifica la cédula o intenta con un solo apellido. "
                          "Si la persona no existe aún, puedo registrarla: pídeme "
                          "'registrar estudiante' y te pediré cédula, nombres completos."
        })
    return json.dumps({"estudiantes": resultados})

def resumen_del_dia():
    """Resumen rápido de la actividad de HOY: matrículas nuevas, abonos cobrados y adicionales."""
    from .models import Adicional
    hoy = now().date()
    matriculas_hoy = Matricula.objects.filter(fecha_matricula=hoy).count()
    abonos_hoy = Abono.objects.filter(fecha=hoy)
    cobrado_hoy = abonos_hoy.aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
    adicionales_hoy = Adicional.objects.filter(fecha=hoy)
    ingreso_adicionales = adicionales_hoy.aggregate(total=Sum('valor'))['total'] or Decimal('0.00')

    return json.dumps({
        "fecha": str(hoy),
        "matriculas_nuevas_hoy": matriculas_hoy,
        "abonos_cobrados_hoy": abonos_hoy.count(),
        "dinero_cobrado_hoy_usd": float(cobrado_hoy),
        "adicionales_vendidos_hoy": adicionales_hoy.count(),
        "ingreso_adicionales_hoy_usd": float(ingreso_adicionales),
    })


def buscar_adicionales(termino=""):
    """Lista adicionales (certificados, exámenes, camisas, prácticas, otros).
    Si se da un término, filtra por nombre/cédula del estudiante asociado."""
    from .models import Adicional
    qs = Adicional.objects.all().order_by('-fecha', '-id')
    termino = (termino or "").strip()
    if termino:
        qs = qs.filter(
            Q(estudiante__nombres__icontains=termino) |
            Q(estudiante__cedula__icontains=termino)
        )
    resultados = []
    for a in qs[:10]:
        if a.estudiante:
            persona = f"{a.estudiante.nombres}"
        elif a.persona_externa:
            persona = str(a.persona_externa)
        else:
            persona = "—"
        resultados.append({
            "fecha": str(a.fecha),
            "tipo": a.get_tipo_adicional_display(),
            "persona": persona,
            "valor_usd": float(a.valor),
        })
    if not resultados:
        return json.dumps({"mensaje": "No se encontraron adicionales con ese criterio."})
    return json.dumps({"adicionales": resultados})


def listar_cursos():
    """Devuelve la lista de cursos disponibles, sus precios y cuántos alumnos activos tienen."""
    cursos = Curso.objects.filter(activo=True)
    resultados = []
    for c in cursos:
        alumnos_activos = c.matriculas.filter(estado='activa').count()
        modalidades = []
        if c.ofrece_presencial: modalidades.append(f"Presencial (${c.valor_presencial})")
        if c.ofrece_online: modalidades.append(f"Online (${c.valor_online})")
        
        resultados.append({
            "nombre": c.nombre,
            "modalidades_y_precios": " / ".join(modalidades),
            "alumnos_activos": alumnos_activos
        })
    return json.dumps({"cursos_disponibles": resultados})

def reporte_financiero():
    """Genera un reporte completo de la situación financiera de la academia."""
    total_ingresos = Abono.objects.aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
    deuda_flotante = Matricula.objects.filter(estado='activa').aggregate(total=Sum('saldo'))['total'] or Decimal('0.00')
    
    pagos_hoy = Abono.objects.filter(fecha=now().date()).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
    
    return json.dumps({
        "ingresos_historicos_totales_usd": float(total_ingresos),
        "dinero_por_cobrar_usd": float(deuda_flotante),
        "ingresos_del_dia_usd": float(pagos_hoy)
    })

def pagos_recientes():
    """Devuelve los últimos 5 pagos registrados en el sistema."""
    ultimos_pagos = Abono.objects.order_by('-fecha', '-id')[:5]
    resultados = []
    for p in ultimos_pagos:
        resultados.append({
            "fecha": str(p.fecha),
            "estudiante": f"{p.matricula.estudiante.nombres}",
            "curso": p.matricula.curso.nombre,
            "monto_usd": float(p.monto),
            "metodo": p.metodo
        })
    return json.dumps({"ultimos_pagos": resultados})

def listar_deudores():
    """Devuelve la lista de estudiantes que tienen saldo pendiente mayor a 0."""
    # Buscar matrículas activas y calcular el saldo en memoria porque 'saldo' es una propiedad
    matriculas_activas = Matricula.objects.filter(estado='activa')
    resultados = []
    
    for m in matriculas_activas:
        if m.saldo > 0:
            resultados.append({
                "estudiante": f"{m.estudiante.nombres}",
                "cedula": m.estudiante.cedula,
                "curso": m.curso.nombre,
                "saldo_pendiente_usd": float(m.saldo),
                "celular": m.estudiante.celular
            })
            
    # Ordenar los resultados de mayor a menor deuda
    resultados.sort(key=lambda x: x["saldo_pendiente_usd"], reverse=True)
    
    if not resultados:
        return json.dumps({"mensaje": "Excelente noticia: No hay ningún estudiante con deudas pendientes en este momento."})
    return json.dumps({"deudores": resultados})

def registrar_matricula_completa(cedula, nombres, curso_nombre, modalidad, valor_pagado, tipo_matricula, correo="", celular="", ciudad="", asesor=None):
    """Crea o actualiza el estudiante y le genera una matrícula en el curso especificado."""
    try:
        # 1. Crear o buscar estudiante
        estudiante, created = Estudiante.objects.get_or_create(
            cedula=cedula,
            defaults={
                'nombres': nombres.title(),
                'correo': correo.lower(),
                'celular': celular,
                'ciudad': ciudad.title()
            }
        )
        if not created:
            # Actualizar datos si faltaban
            if celular and not estudiante.celular: estudiante.celular = celular
            if correo and not estudiante.correo: estudiante.correo = correo.lower()
            if ciudad and not estudiante.ciudad: estudiante.ciudad = ciudad.title()
            estudiante.save()

        # 2. Buscar Curso
        curso = Curso.objects.filter(nombre__icontains=curso_nombre).first()
        if not curso:
            return json.dumps({"error": f"No encontré ningún curso parecido a '{curso_nombre}'. Pídele al usuario que verifique el nombre exacto usando listar_cursos."})

        # 3. Determinar forma de pago basada en tipo_matricula
        forma_pago = 'abono'
        if tipo_matricula.lower() == 'reserva':
            forma_pago = 'abono'
        elif tipo_matricula.lower() == 'contado':
            forma_pago = 'pago_completo'

        # 4. Crear Matrícula
        from decimal import Decimal
        valor_pagado_dec = Decimal(str(valor_pagado)) if valor_pagado else Decimal('0.00')
        
        matricula = Matricula.objects.create(
            estudiante=estudiante,
            curso=curso,
            modalidad=modalidad.lower(),
            tipo_matricula=tipo_matricula.lower(),
            forma_pago=forma_pago,
            valor_pagado=valor_pagado_dec,
            vendedora=asesor,
            estado='activa'
        )

        # 5. Crear Abono Inicial si hay pago
        if valor_pagado_dec > 0:
            Abono.objects.create(
                matricula=matricula,
                fecha=matricula.fecha_matricula,
                monto=valor_pagado_dec,
                tipo_pago=tipo_matricula.lower() if tipo_matricula.lower() in ['reserva', 'abono'] else 'abono',
                cuenta_para_saldo=True,
                registrado_por=asesor,
                metodo='efectivo' # Por defecto del bot
            )

        return json.dumps({
            "exito": True,
            "mensaje": f"¡Matrícula registrada! El estudiante {estudiante.nombres} ha sido matriculado en {curso.nombre} ({modalidad}). ID de matrícula: {matricula.id}"
        })
    except Exception as e:
        return json.dumps({"error": f"Error al registrar la matrícula: {str(e)}"})

def abrir_pagina(seccion):
    """Devuelve el comando de redirección a la página solicitada por el usuario.

    El default seguro es la página de inicio real del sistema (/bienvenida/),
    NO /dashboard/ (esa ruta no existe y producía un error 404).
    """
    seccion = (seccion or "").lower()
    # Default seguro: página de inicio real (existe en core.urls).
    url = "/bienvenida/"
    etiqueta = seccion or "inicio"

    if "curso" in seccion and "presencial" in seccion:
        url = "/cursos/presencial/"
    elif "curso" in seccion and "online" in seccion:
        url = "/cursos/online/"
    elif "curso" in seccion:
        url = "/cursos/presencial/"  # Fallback a cursos
    elif "matricula" in seccion and ("registro" in seccion or "registrar" in seccion or "nueva" in seccion):
        if "online" in seccion:
            url = "/matricula/online/registrar/"
        else:
            url = "/matricula/presencial/registrar/"
    elif "matricula" in seccion and "online" in seccion:
        url = "/matricula/online/lista/"
    elif "matricula" in seccion:
        url = "/matricula/presencial/lista/"
    elif "estudiante" in seccion:
        url = "/estudiantes/"
    elif "pago" in seccion or "cobro" in seccion:
        url = "/pagos/"
    elif "recuperacion" in seccion or "recuperación" in seccion:
        url = "/recuperaciones/"
    elif "comprobante" in seccion or "factura" in seccion:
        url = "/comprobantes/"
    elif "registro administrativo" in seccion or "administrativo" in seccion or "admin" in seccion:
        url = "/admin-panel/"
    elif "adicional" in seccion or "certificado" in seccion or "supletorio" in seccion or "camiseta" in seccion or "camisa" in seccion:
        url = "/adicional/"
    elif "archivo" in seccion or "archivad" in seccion or "cierre" in seccion:
        url = "/historial/archivo/"
    elif "historial" in seccion:
        url = "/historial/"
    elif "ayuda" in seccion or "soporte" in seccion or "manual" in seccion:
        url = "/ayuda/"
    elif "inicio" in seccion or "dashboard" in seccion or "principal" in seccion or "home" in seccion or "bienvenid" in seccion:
        url = "/bienvenida/"

    # Este texto especial será interceptado por el Frontend
    return f"[REDIRECT: {url}] He ordenado al sistema abrir la sección de {etiqueta}."

# Definición de herramientas para OpenAI
MERCYBOT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "buscar_estudiante",
            "description": "Busca a un estudiante por cédula, nombre o apellido y devuelve todos sus datos, cursos en los que está matriculado, su deuda y lo que ha pagado.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre": {
                        "type": "string",
                        "description": "El nombre, apellido o número de cédula exacto o parcial."
                    }
                },
                "required": ["nombre"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "listar_cursos",
            "description": "Lista todos los cursos disponibles en la academia, mostrando su precio, modalidad y la cantidad de alumnos activos en cada uno.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "reporte_financiero",
            "description": "Devuelve un resumen financiero de la academia: total de ingresos históricos, dinero pendiente por cobrar (deuda de alumnos), e ingresos del día de hoy.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "pagos_recientes",
            "description": "Devuelve el detalle de los últimos pagos (abonos) que los estudiantes han realizado recientemente en el sistema.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "registrar_matricula_completa",
            "description": "Registra una matrícula completa para un estudiante, asignándole un curso, modalidad y el pago inicial. Siempre pregunta todos los datos obligatorios antes de llamarla.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cedula": {"type": "string"},
                    "nombres": {"type": "string"},
                    "curso_nombre": {"type": "string", "description": "Nombre del curso (ej: 'Automatización con Python'). Debe existir."},
                    "modalidad": {"type": "string", "enum": ["presencial", "online"]},
                    "tipo_matricula": {"type": "string", "enum": ["reserva", "abono", "contado"]},
                    "valor_pagado": {"type": "number", "description": "Monto en dólares que paga en este momento."},
                    "correo": {"type": "string"},
                    "celular": {"type": "string"},
                    "ciudad": {"type": "string"}
                },
                "required": ["cedula", "nombres", "curso_nombre", "modalidad", "tipo_matricula", "valor_pagado", "celular"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "listar_deudores",
            "description": "Lista a todos los estudiantes que tienen deudas (saldo pendiente mayor a cero) ordenados por la cantidad que deben.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "resumen_del_dia",
            "description": "Resumen de la actividad de HOY: cuántas matrículas nuevas se registraron, cuántos abonos se cobraron y cuánto dinero entró hoy, y cuántos adicionales se vendieron.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_adicionales",
            "description": "Lista o busca adicionales vendidos (certificados, examen supletorio, camisas, prácticas u otros). Opcionalmente filtra por el nombre o cédula del estudiante.",
            "parameters": {
                "type": "object",
                "properties": {
                    "termino": {
                        "type": "string",
                        "description": "Nombre, apellido o cédula para filtrar (opcional)."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "abrir_pagina",
            "description": "Redirige automáticamente el navegador del usuario a la página o sección que está pidiendo abrir (ej. 'cursos', 'pagos', 'matrículas', 'dashboard').",
            "parameters": {
                "type": "object",
                "properties": {
                    "seccion": {
                        "type": "string",
                        "description": "El nombre de la sección que el usuario quiere abrir."
                    }
                },
                "required": ["seccion"]
            }
        }
    }
]

def execute_tool(name, arguments, user=None):
    """Ejecuta la herramienta correspondiente basada en el nombre."""
    args = json.loads(arguments)
    if name == "buscar_estudiante":
        return buscar_estudiante(args.get("nombre", ""))
    elif name == "listar_cursos":
        return listar_cursos()
    elif name == "reporte_financiero":
        return reporte_financiero()
    elif name == "pagos_recientes":
        return pagos_recientes()
    elif name == "listar_deudores":
        return listar_deudores()
    elif name == "resumen_del_dia":
        return resumen_del_dia()
    elif name == "buscar_adicionales":
        return buscar_adicionales(args.get("termino", ""))
    elif name == "abrir_pagina":
        return abrir_pagina(args.get("seccion", "dashboard"))
    elif name == "registrar_matricula_completa":
        return registrar_matricula_completa(
            cedula=args.get("cedula"),
            nombres=args.get("nombres"),
            curso_nombre=args.get("curso_nombre"),
            modalidad=args.get("modalidad"),
            valor_pagado=args.get("valor_pagado"),
            tipo_matricula=args.get("tipo_matricula"),
            correo=args.get("correo", ""),
            celular=args.get("celular", ""),
            ciudad=args.get("ciudad", ""),
            asesor=user
        )
    return json.dumps({"error": f"Herramienta desconocida: {name}"})
