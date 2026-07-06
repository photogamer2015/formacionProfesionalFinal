import json
import os
from django.utils import timezone

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from .forms import (
    CategoriaForm, CursoForm, EstudianteForm,
    JornadaCursoForm, MatriculaForm,
)
from .models import (
    Abono, Categoria, Curso, Estudiante, JornadaCurso, Matricula,
    AssistantQueryLog, Sede, EstudianteArchivado, MatriculaArchivada,
    FORMA_PAGO_A_TIPO_ABONO,
)
from .permisos import (
    admin_requerido,
    jornadas_requeridas,
    matricula_requerida,
    permiso_jornada_requerido,
    permiso_requerido,
    puede_agregar_jornadas,
    puede_editar_jornadas,
    puede_eliminar_jornadas,
)


@login_required
@require_POST
def assistant_simple_chat(request):
    """Endpoint simple y basado en reglas para respuestas rápidas.

    Espera JSON: { "message": "..." }
    Responde JSON: { "reply": "..." }
    """
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        payload = {}
    msg = (payload.get('message') or '').strip()

    if not msg:
        return JsonResponse({'reply': '¿En qué puedo ayudarte hoy?'})

    if msg == '/clear':
        request.session['mercybot_history'] = []
        return JsonResponse({'reply': 'Memoria borrada'})

    try:
        # ── MercyBot en modo LOCAL (sin API de ChatGPT) ──────────────────
        # La integración con OpenAI fue desactivada intencionalmente. MercyBot
        # responde con su motor de reglas local, sin llamar a ningún servicio
        # externo ni consumir créditos. Toda la lógica de la API se conserva
        # más abajo (inalcanzable) por si en el futuro se desea reactivar;
        # para hacerlo, basta con volver a habilitar una clave de OpenAI y
        # quitar este bloque de retorno anticipado.
        reply = _assistant_rules_reply(msg)
        session_messages = request.session.get('mercybot_history', [])
        session_messages.append({"role": "user", "content": msg})
        session_messages.append({"role": "assistant", "content": reply})
        request.session['mercybot_history'] = session_messages[-15:]
        request.session.modified = True
        return JsonResponse({'reply': reply})

    except Exception:
        # Si por cualquier motivo fallan las reglas locales, respondemos algo neutro.
        return JsonResponse({'reply': (
            'Disculpa, no entendí bien. ¿Podrías intentar decírmelo de otra forma? '
            'También puedes revisar la sección de ayuda en /ayuda/.'
        )})

    # ─────────────────────────────────────────────────────────────────────
    # CÓDIGO LEGADO (OpenAI) — conservado pero inalcanzable tras el return
    # anterior. No se ejecuta mientras MercyBot esté en modo local.
    # ─────────────────────────────────────────────────────────────────────
    try:
        from openai import OpenAI
        from django.conf import settings
        from .ai_tools import MERCYBOT_TOOLS, execute_tool

        OPENAI_API_KEY = getattr(settings, 'OPENAI_API_KEY', '') or ''

        if not OPENAI_API_KEY:
            reply = _assistant_rules_reply(msg)
            session_messages = request.session.get('mercybot_history', [])
            session_messages.append({"role": "user", "content": msg})
            session_messages.append({"role": "assistant", "content": reply})
            request.session['mercybot_history'] = session_messages[-15:]
            request.session.modified = True
            return JsonResponse({'reply': reply})

        OPENAI_MODEL = getattr(settings, 'OPENAI_MODEL', '') or 'gpt-4o-mini'
        client = OpenAI(api_key=OPENAI_API_KEY)

        # Cargar historial de la sesión
        session_messages = request.session.get('mercybot_history', [])
        session_messages.append({"role": "user", "content": msg})

        # Mantener solo los últimos 15 mensajes para no saturar tokens
        if len(session_messages) > 15:
            session_messages = session_messages[-15:]

        usuario = request.user.get_full_name() or request.user.username
        system_prompt = (
            "Eres MercyBot, la asistente virtual de Formación Profesional EC, una academia "
            f"de formación técnica en Ecuador. Estás hablando con {usuario} (personal administrativo). "
            "Hablas español ecuatoriano, profesional, cálido y conciso. Los montos van con signo $.\n\n"
            "TUS CAPACIDADES (usa SIEMPRE las herramientas, NUNCA inventes datos):\n"
            "- Buscar estudiantes por nombre, apellido o cédula (la búsqueda tolera el orden de los nombres).\n"
            "- Registrar nuevos estudiantes.\n"
            "- Consultar cursos, deudores, pagos recientes, reporte financiero, adicionales y el resumen del día.\n"
            "- Abrir/navegar a secciones del sistema.\n\n"
            "REGLAS:\n"
            "1) Si te piden datos de un estudiante, llama a `buscar_estudiante` y resume de forma clara: "
            "nombre completo, cédula, cursos, modalidad/jornada, lo pagado y la deuda. Si no aparece, dilo y "
            "ofrece registrarlo; NO inventes que no existe sin haber buscado.\n"
            "2) Para REGISTRAR una matrícula por chat, DEBES pedir SIEMPRE todos estos datos antes de hacer nada: cédula, nombres completos, celular, ciudad/sede, el curso, modalidad, el tipo de matrícula y el valor pagado. Una vez que tengas todos estos datos, llama a la herramienta `registrar_matricula_completa`.\n"
            "3) Para NAVEGAR o si el usuario pide 'abrir', 'ir a', 'mostrar' (ej. 'abre registro de matricula', 'cursos disponibles'), llama a `abrir_pagina` con la sección solicitada. NO pidas datos si solo te piden abrir la página. Cuando la herramienta te devuelva un texto con el formato "
            "`[REDIRECT: /url/...]`, tu respuesta hacia el usuario DEBE INCLUIR EXACTAMENTE ESE TEXTO `[REDIRECT: /url/...]` CON SUS CORCHETES. ¡ES VITAL! No lo conviertas en un enlace markdown [aquí](url). Solo pega el texto tal cual para que el sistema lo intercepte.\n"
            "4) NO tienes permiso para modificar pagos, anular registros ni borrar nada. Si te lo piden, "
            "explica amablemente que esas acciones debe hacerlas una persona desde el sistema, e indícale "
            "en qué sección hacerlo.\n"
            "5) Si NO sabes algo o falta información para usar una herramienta, PREGÚNTALE al usuario en lugar "
            "de adivinar. Es preferible una pregunta corta a una respuesta inventada."
        )

        messages = [{"role": "system", "content": system_prompt}] + session_messages

        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            tools=MERCYBOT_TOOLS,
            tool_choice="auto",
        )
        
        response_message = response.choices[0].message
        
        # Check if GPT wanted to call a function
        if response_message.tool_calls:
            messages.append(response_message)
            for tool_call in response_message.tool_calls:
                function_name = tool_call.function.name
                function_args = tool_call.function.arguments
                function_response = execute_tool(function_name, function_args, user=request.user)
                
                messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": function_response,
                })
            
            # Second API call to get the final answer with the tool results
            second_response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages
            )
            reply = second_response.choices[0].message.content
        else:
            reply = response_message.content

        # Guardar respuesta en el historial de sesión
        session_messages.append({"role": "assistant", "content": reply})
        request.session['mercybot_history'] = session_messages
        request.session.modified = True

    except Exception as e:
        from django.conf import settings as _s
        if getattr(_s, 'DEBUG', False):
            reply = f"Tuve un problema técnico: {e}. Revisa que la clave de OpenAI sea válida."
        else:
            reply = ("Disculpa, no entendí bien o tuve una pequeña confusión en mis procesos. "
                     "¿Podrías intentar decírmelo de otra forma?")

    # Guardar log mínimo
    try:
        AssistantQueryLog.objects.create(
            user=request.user if request.user.is_authenticated else None,
            path=payload.get('path','') if isinstance(payload, dict) else '',
            message=msg,
            reply=reply,
            metadata={'source':'local'}
        )
    except Exception:
        pass

    return JsonResponse({'reply': reply})


def _assistant_rules_reply(msg: str) -> str:
    """Reglas simples reutilizables para respuestas cuando no hay LLM disponible."""
    if not msg:
        return 'Escribe tu pregunta y te ayudo con el sistema. Por ejemplo: "¿Cómo registro una matrícula?"'
    low = msg.lower()
    if 'matric' in low or 'registr' in low:
        return ('Para registrar una matrícula: en el menú Matrícula selecciona la modalidad, '
                'completa los datos del estudiante y la jornada, y pulsa "Registrar matrícula". '
                'Si la cédula ya existe, los datos se autocompletan.')
    if 'factur' in low:
        return ('Si seleccionas "¿Factura realizada? = Sí", completa los campos de factura '
                'Nombres, Apellidos, Cédula/RUC y Correo; el formulario bloqueará el envío hasta que estén completos.')
    if 'recuper' in low:
        return ('Las clases en recuperación se marcan desde la sección Recuperaciones. '
                'Puedes marcar, cobrar (crear un abono tipo "recuperacion") o eliminar si no está pagada.')
    if 'abono' in low or 'pago' in low or 'cobrar' in low:
        return ('Para registrar pagos usa la vista de Abonos desde la matrícula del estudiante. '
                'Los abonos pueden asignarse a módulos o a recuperación según corresponda.')
    if 'curso' in low:
        return ('Los cursos se añaden desde Cursos → Nuevo Curso (solo administradores). '
                'Asegúrate de configurar jornadas y los valores para presencial/online.')
    if 'jornada' in low:
        return ('Selecciona la jornada que corresponda en el formulario de matrícula; la jornada define la modalidad final.')
    if 'vended' in low or 'vendedora' in low:
        return ('La vendedora se asigna automáticamente al usuario que registra la matrícula. Aparece en la sección Vendedora del formulario.')
    if 'imprimir' in low or 'ficha' in low:
        return ('Puedes exportar listados a PDF/Excel desde las vistas de lista. La ficha de matrícula actualmente se puede imprimir desde la página de la matrícula — si quieres, puedo añadir un botón que genere la ficha imprimible.')
    return ('No estoy seguro. Puedes consultar la sección de ayuda en /ayuda/ o escribir una pregunta más específica, por ejemplo "¿Cómo cobro una recuperación?"')


@login_required
@require_POST
def assistant_llm_chat(request):
    """Endpoint que usa un LLM externo (OpenAI) cuando hay clave, y registra logs.

    Request JSON: { message: str, path?: str }
    Response JSON: { reply: str }
    """
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        payload = {}
    msg = (payload.get('message') or '').strip()
    page = payload.get('path') or request.META.get('PATH_INFO','')

    reply = ''
    used_model = None
    # ── Modo LOCAL: la API de ChatGPT fue desactivada intencionalmente. ──
    # Siempre respondemos con la búsqueda local (README/templates) y, si no
    # hay coincidencias, con el motor de reglas. No se llama a OpenAI ni se
    # consumen créditos externos.
    reply = None
    try:
        reply = _assistant_local_search(msg)
    except Exception:
        reply = None
    if not reply:
        reply = _assistant_rules_reply(msg)

    # Guardar log
    try:
        AssistantQueryLog.objects.create(
            user=request.user if request.user.is_authenticated else None,
            path=page,
            message=msg,
            reply=reply,
            metadata={'model': used_model}
        )
    except Exception:
        pass

    return JsonResponse({'reply': reply})


def _assistant_local_search(query: str) -> str:
    """Busca palabras clave en README.md y archivos de templates para dar una respuesta contextual local.

    Retorna un texto breve con hasta 3 fragmentos encontrados, o cadena vacía si no hay matches.
    """
    import glob
    if not query or not query.strip():
        return ''
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    files = []
    # Priorizar README y templates
    candidates = [os.path.join(root, 'README.md')]
    candidates += glob.glob(os.path.join(root, 'templates', '**', '*.html'), recursive=True)
    candidates += glob.glob(os.path.join(root, '**', '*.md'), recursive=True)

    tokens = [t.lower() for t in query.split() if len(t) > 2]
    if not tokens:
        return ''

    hits = []
    for fp in candidates:
        try:
            with open(fp, 'r', encoding='utf-8', errors='ignore') as fh:
                text = fh.read()
        except Exception:
            continue
        low = text.lower()
        score = sum(low.count(tok) for tok in tokens)
        if score <= 0:
            continue
        # extract short snippets around first occurrences
        snippets = []
        for tok in tokens:
            idx = low.find(tok)
            if idx >= 0:
                start = max(0, idx - 80)
                end = min(len(text), idx + 160)
                snippet = text[start:end].replace('\n', ' ').strip()
                snippets.append(snippet)
        hits.append((score, fp, snippets[:2]))

    if not hits:
        return ''

    # ordenar por score y devolver hasta 3 fragmentos
    hits.sort(reverse=True, key=lambda x: x[0])
    parts = []
    taken = 0
    for score, fp, snippets in hits[:3]:
        rel = os.path.relpath(fp, root)
        parts.append(f'Encontrado en {rel}:')
        for s in snippets:
            parts.append(f'• {s}')
            taken += 1
            if taken >= 3:
                break
        if taken >= 3:
            break

    parts.append('\nSi quieres más detalle, escribe una pregunta más concreta o activa la API.')
    return '\n'.join(parts)


# ─────────────────────────────────────────────────────────
# Helpers de modalidad
# ─────────────────────────────────────────────────────────

MODALIDADES_VALIDAS = ('presencial', 'online')

# La matrícula online ha sido habilitada nuevamente a petición del usuario.
MATRICULA_ONLINE_HABILITADA = True


def _modalidad_o_404(modalidad):
    """Valida que la modalidad de la URL sea válida; si no, lanza 404."""
    if modalidad not in MODALIDADES_VALIDAS:
        from django.http import Http404
        raise Http404(f'Modalidad desconocida: {modalidad}')
    return modalidad


def _bloquear_si_online(request, modalidad):
    """
    Si la matrícula online está deshabilitada y se intenta acceder a esa modalidad,
    muestra mensaje y redirige al dashboard. Devuelve None si todo OK.
    """
    if modalidad == 'online' and not MATRICULA_ONLINE_HABILITADA:
        messages.info(
            request,
            'La matrícula online está temporalmente deshabilitada en el sistema. '
            'Disponible próximamente vía Google Forms.'
        )
        return redirect('academia:bienvenida')
    return None


def _label_modalidad(modalidad):
    return 'Presencial' if modalidad == 'presencial' else 'Online'


def _cursos_para_matricula():
    return Curso.objects.filter(
        activo=True,
    ).filter(
        Q(ofrece_presencial=True) | Q(ofrece_online=True)
    ).select_related('categoria').order_by('nombre')


# ─────────────────────────────────────────────────────────
# Páginas base
# ─────────────────────────────────────────────────────────

def home(request):
    if request.user.is_authenticated:
        return redirect('academia:bienvenida')
    return redirect('login')


def _avisos_vigentes_seguro():
    """Devuelve los avisos vigentes para el panel; nunca rompe el dashboard."""
    try:
        from .models import Aviso
        return list(Aviso.vigentes())
    except Exception:
        return []


@login_required
def bienvenida(request):
    stats = {
        'total_presencial': Matricula.objects.filter(modalidad='presencial').count(),
        'total_online': Matricula.objects.filter(modalidad='online').count(),
        'total_cursos_presencial': Curso.objects.filter(activo=True, ofrece_presencial=True).count(),
        'total_cursos_online': Curso.objects.filter(activo=True, ofrece_online=True).count(),
    }

    # ── Alertas de pago pendiente (solo para roles con gestión) ──
    from .permisos import puede_gestionar_matriculas as _puede_mat
    alertas_pago = []
    if _puede_mat(request.user):
        try:
            from .views_pagos import _calcular_alertas_pago
            alertas_pago = _calcular_alertas_pago(usuario_actual=request.user)
        except Exception:
            # Si algo falla en el cálculo, no rompemos el dashboard.
            alertas_pago = []

    return render(request, 'bienvenida.html', {
        'usuario': request.user,
        'stats': stats,
        'alertas_pago': alertas_pago,
        'avisos_vigentes': _avisos_vigentes_seguro(),
    })


@login_required
def ayuda(request):
    """Vista para la sección de ayuda y soporte del sistema."""
    return render(request, 'ayuda.html')


# ─────────────────────────────────────────────────────────
# Matrícula (presencial u online — parametrizado por URL)
# ─────────────────────────────────────────────────────────

@matricula_requerida
def matricula_menu(request, modalidad):
    modalidad = _modalidad_o_404(modalidad)
    bloqueo = _bloquear_si_online(request, modalidad)
    if bloqueo:
        return bloqueo
    total = Matricula.objects.filter(modalidad=modalidad).count()
    return render(request, 'matricula/menu.html', {
        'total': total,
        'modalidad': modalidad,
        'modalidad_label': _label_modalidad(modalidad),
    })


def _registrar_pago_inicial(matricula, usuario, mat_form=None,
                            monto_override=None, omitir_guarda_duplicado=False):
    """Crea el Abono inicial de una matrícula recién registrada según su
    forma de pago, para que el pago quede reflejado en la sección de Abonos.

    - Si valor_pagado es 0 o no hay forma de pago, no crea nada.
    - El tipo de abono se deriva de forma_pago (abono / pago_completo /
      por_modulo). Para 'modulo' se asocia al módulo 1.

    Parámetros opcionales (usados solo en EDICIÓN, no afectan el registro
    nuevo que llama sin ellos):
    - monto_override: monto del pago inicial tomado del formulario. Se usa
      cuando la matrícula ya tiene otros abonos (pagos posteriores) y su
      valor_pagado fue recalculado, para no leer un monto equivocado.
    - omitir_guarda_duplicado: en edición ya borramos el pago inicial antes
      de llamar aquí, así que la guarda anti-duplicado debe saltarse para
      poder recrearlo aunque existan pagos posteriores.
    Devuelve el Abono creado o None.
    """
    from decimal import Decimal
    if monto_override is not None:
        monto = monto_override or Decimal('0.00')
    else:
        monto = matricula.valor_pagado or Decimal('0.00')
    if not matricula.forma_pago or monto <= 0:
        return None
    # Evita duplicar si por algún motivo ya hay abonos.
    # En edición (omitir_guarda_duplicado=True) el pago inicial ya fue
    # eliminado antes de llamar; los abonos restantes son pagos posteriores
    # legítimos que deben conservarse, por eso no bloqueamos.
    if not omitir_guarda_duplicado and matricula.abonos.exists():
        return None
    
    tipo_cobro = 'un_solo_metodo'
    metodo = 'efectivo'
    banco = ''
    monto_1 = Decimal('0.00')
    metodo_1 = 'efectivo'
    banco_1 = ''
    monto_2 = Decimal('0.00')
    metodo_2 = 'efectivo'
    banco_2 = ''

    if mat_form and hasattr(mat_form, 'cleaned_data'):
        tipo_cobro = mat_form.cleaned_data.get('tipo_cobro') or 'un_solo_metodo'
        metodo = mat_form.cleaned_data.get('metodo_pago') or 'efectivo'
        banco = mat_form.cleaned_data.get('banco') or ''
        monto_1 = mat_form.cleaned_data.get('monto_pago_1') or Decimal('0.00')
        metodo_1 = mat_form.cleaned_data.get('metodo_pago_1') or 'efectivo'
        banco_1 = mat_form.cleaned_data.get('banco_1') or ''
        monto_2 = mat_form.cleaned_data.get('monto_pago_2') or Decimal('0.00')
        metodo_2 = mat_form.cleaned_data.get('metodo_pago_2') or 'efectivo'
        banco_2 = mat_form.cleaned_data.get('banco_2') or ''

    # ── Caso "Reserva + Módulo": se pagan k módulos acumulativos (1..k) ──
    # Cada módulo pagado se registra como un Abono 'por_modulo' con su
    # numero_modulo, para que quede marcado como PAGADO en el desglose y
    # desaparezca de las alertas de pago.
    modulos_k = 0
    if mat_form and hasattr(mat_form, 'cleaned_data'):
        modulos_k = mat_form.cleaned_data.get('modulos_a_pagar') or 0
    try:
        modulos_k = int(modulos_k)
    except (TypeError, ValueError):
        modulos_k = 0

    if matricula.tipo_matricula == 'reserva_modulo_1' and modulos_k >= 1:
        n_mod = matricula.curso.get_numero_modulos(matricula.modalidad) if matricula.curso_id else 1
        n_mod = n_mod or 1
        k = min(modulos_k, n_mod)
        valor_modulo = (
            (matricula.valor_neto / Decimal(n_mod)).quantize(Decimal('0.01'))
            if n_mod > 0 else Decimal('0.00')
        )
        monto_restante = monto
        ultimo = None
        for i in range(1, k + 1):
            if monto_restante <= 0:
                break
            if i < k:
                monto_abono = min(valor_modulo, monto_restante)
            else:
                monto_abono = monto_restante
            kwargs = dict(
                matricula=matricula,
                fecha=matricula.fecha_matricula,
                monto=monto_abono,
                tipo_pago='por_modulo',
                numero_modulo=i,
                cuenta_para_saldo=True,
                registrado_por=usuario,
            )
            # El pago mixto solo se aplica al primer módulo (para no duplicar
            # el desglone del método en cada módulo). El resto usa el método
            # principal. Para un solo módulo (k==1) el mixto funciona igual
            # que en el flujo normal.
            if i == 1 and tipo_cobro == 'mixto' and monto_1 > 0 and monto_2 > 0:
                kwargs.update(metodo=metodo_1, banco=banco_1,
                              monto_2=monto_2, metodo_2=metodo_2, banco_2=banco_2)
            else:
                kwargs.update(metodo=metodo, banco=banco)
            ultimo = Abono.objects.create(**kwargs)
            monto_restante -= monto_abono
        if ultimo is None:
            return None
        matricula.refresh_from_db()
        matricula.save()
        return ultimo

    tipo_abono = FORMA_PAGO_A_TIPO_ABONO.get(matricula.forma_pago, 'abono')
    numero_modulo = 1 if matricula.forma_pago == 'modulo' else None

    if tipo_cobro == 'mixto' and monto_1 > 0 and monto_2 > 0:
        abono = Abono.objects.create(
            matricula=matricula, fecha=matricula.fecha_matricula,
            monto=monto, tipo_pago=tipo_abono, numero_modulo=numero_modulo,
            cuenta_para_saldo=True, registrado_por=usuario,
            metodo=metodo_1, banco=banco_1,
            monto_2=monto_2, metodo_2=metodo_2, banco_2=banco_2
        )
    else:
        abono = Abono.objects.create(
            matricula=matricula,
            fecha=matricula.fecha_matricula,
            monto=monto,
            tipo_pago=tipo_abono,
            numero_modulo=numero_modulo,
            cuenta_para_saldo=True,
            registrado_por=usuario,
            metodo=metodo,
            banco=banco,
        )

    # Abono.save() ya recalcula valor_pagado. Re-guardamos la matrícula para
    # que el comprobante-espejo refleje el pago/saldo actualizado.
    matricula.refresh_from_db()
    matricula.save()
    return abono


@matricula_requerida
@transaction.atomic
def matricula_registrar(request, modalidad):
    modalidad = _modalidad_o_404(modalidad)
    bloqueo = _bloquear_si_online(request, modalidad)
    if bloqueo:
        return bloqueo

    asesores = User.objects.all().order_by('first_name', 'username')
    error_vendedora = None

    if request.method == 'POST':
        factura_si = request.POST.get('mat-factura_realizada', '') == 'si'
        est_form = EstudianteForm(request.POST, prefix='est', factura_si=factura_si)
        mat_form = MatriculaForm(request.POST, prefix='mat', modalidad=modalidad)

        vendedora_id = request.POST.get('vendedora_id', '').strip()
        asesor = None
        if vendedora_id:
            asesor = User.objects.filter(id=vendedora_id).first()
        
        if not asesor:
            error_vendedora = 'Debes seleccionar un asesor válido.'

        cedula = request.POST.get('est-cedula', '').strip()
        estudiante_existente = None
        if cedula:
            estudiante_existente = Estudiante.objects.filter(cedula=cedula).first()

        if not error_vendedora:
            if estudiante_existente:
                if mat_form.is_valid():
                    matricula = mat_form.save(commit=False)
                    matricula.estudiante = estudiante_existente
                    # La modalidad final la define la jornada elegida.
                    # save() sincroniza modalidad <- jornada.modalidad si hay jornada.
                    matricula.modalidad = matricula.jornada.modalidad if matricula.jornada else modalidad
                    matricula.vendedora = asesor
                    if not matricula.pk:
                        matricula.registrado_por = request.user
                    matricula.save()
                    _registrar_pago_inicial(matricula, request.user, mat_form)
                    messages.success(
                        request,
                        f'Matrícula registrada para '
                        f'{estudiante_existente.nombre_completo} '
                        f'({matricula.get_modalidad_display()}).'
                    )
                    # Redirigimos a la lista de la modalidad final
                    return redirect(
                        'academia:matricula_lista',
                        modalidad=matricula.modalidad,
                    )
            else:
                if est_form.is_valid() and mat_form.is_valid():
                    estudiante = est_form.save(commit=False)
                    if not estudiante.pk:
                        estudiante.registrado_por = request.user
                    estudiante.save()
                    matricula = mat_form.save(commit=False)
                    matricula.estudiante = estudiante
                    matricula.modalidad = matricula.jornada.modalidad if matricula.jornada else modalidad
                    matricula.vendedora = asesor
                    if not matricula.pk:
                        matricula.registrado_por = request.user
                    matricula.save()
                    _registrar_pago_inicial(matricula, request.user, mat_form)
                    messages.success(
                        request,
                        f'Matrícula registrada para '
                        f'{estudiante.nombre_completo} '
                        f'({matricula.get_modalidad_display()}).'
                    )
                    return redirect(
                        'academia:matricula_lista',
                        modalidad=matricula.modalidad,
                    )

    else:
        est_form = EstudianteForm(prefix='est')
        mat_form = MatriculaForm(prefix='mat', modalidad=modalidad)

    return render(request, 'matricula/form.html', {
        'est_form': est_form,
        'mat_form': mat_form,
        'cursos_disponibles': _cursos_para_matricula(),
        'modalidad': modalidad,
        'modalidad_label': _label_modalidad(modalidad),
        'modo': 'registrar',
        'titulo': f'Registrar Matrícula {_label_modalidad(modalidad)}',
        'asesores': asesores,
        'error_vendedora': error_vendedora,
        'vendedora_id_selected': request.POST.get('vendedora_id', '') if request.method == 'POST' else '',
    })


@matricula_requerida
@transaction.atomic
def matricula_editar(request, modalidad, pk):
    modalidad = _modalidad_o_404(modalidad)
    matricula = get_object_or_404(Matricula, pk=pk, modalidad=modalidad)

    asesores = User.objects.all().order_by('first_name', 'username')
    error_vendedora = None

    # ── Modo de edición ──────────────────────────────────────────────
    # Hay dos formas de editar una matrícula, elegidas por el usuario en la
    # ventana de advertencia al pulsar "Editar":
    #
    #   1) SOLO DATOS  (reiniciar_pago = False): corrige nombre, correo,
    #      curso, jornada, factura, etc. SIN tocar ningún pago. El
    #      "Valor pagado" y el saldo quedan exactamente como estaban.
    #
    #   2) REINICIAR PAGO (reiniciar_pago = True): edita los datos y además
    #      elimina el pago inicial de matrícula, dejando el "Valor pagado"
    #      en $0. Los pagos posteriores (hechos en "Gestionar Pagos") se
    #      conservan intactos.
    #
    # En GET el modo llega por querystring (?reiniciar_pago=1). En POST llega
    # por un campo oculto del formulario para no perderlo al enviar.
    if request.method == 'POST':
        reiniciar_pago = request.POST.get('reiniciar_pago', '') == '1'
    else:
        reiniciar_pago = request.GET.get('reiniciar_pago', '') == '1'

    if request.method == 'POST':
        factura_si = request.POST.get('mat-factura_realizada', '') == 'si'
        est_form = EstudianteForm(request.POST, prefix='est', instance=matricula.estudiante, factura_si=factura_si)
        # captura_pago=False: en edición NO se cobra un pago inicial nuevo.
        # El "Valor pagado" no es obligatorio ni se valida como cobro.
        mat_form = MatriculaForm(
            request.POST, prefix='mat', instance=matricula, modalidad=modalidad,
            captura_pago=False,
        )

        vendedora_id = request.POST.get('vendedora_id', '').strip()
        asesor = None
        if vendedora_id:
            asesor = User.objects.filter(id=vendedora_id).first()

        if not asesor:
            error_vendedora = 'Debes seleccionar un asesor válido.'

        if not error_vendedora and est_form.is_valid() and mat_form.is_valid():
            est_form.save()
            matricula_updated = mat_form.save(commit=False)
            matricula_updated.vendedora = asesor
            matricula_updated.save()

            if reiniciar_pago:
                # ── Reinicio del PAGO INICIAL de matrícula ──
                # Elimina ÚNICAMENTE el pago inicial (el/los abono(s) creados
                # al registrar la matrícula), dejando el "Valor pagado" en $0.
                # Los pagos posteriores hechos en "Gestionar Pagos" quedan
                # intactos. No se reconstruye ningún abono: si luego se quiere
                # registrar un pago, se hace desde "Gestionar Pagos".
                from .models import Abono

                # El pago inicial es el bloque de abonos más antiguos (por
                # orden de creación) cuya fecha == fecha_matrícula. En cuanto
                # aparece un abono de otra fecha, cortamos: lo posterior no se
                # toca.
                ids_pago_inicial = []
                for ab in matricula_updated.abonos.order_by('creado', 'id'):
                    if ab.fecha == matricula_updated.fecha_matricula:
                        ids_pago_inicial.append(ab.id)
                    else:
                        break

                if ids_pago_inicial:
                    Abono.objects.filter(id__in=ids_pago_inicial).delete()

                # Recalcula el saldo con lo que haya quedado (solo pagos
                # posteriores, si existían). Si no queda nada, el "Valor
                # pagado" queda en $0 y el saldo vuelve al valor neto.
                matricula_updated.recalcular_valor_pagado()

                messages.success(
                    request,
                    'Matrícula actualizada y pago inicial reiniciado a $0. '
                    'Los pagos posteriores (si los había) se conservan. Para '
                    'registrar un nuevo pago usa "Gestionar Pagos".'
                )
            else:
                # Solo datos: no se toca ningún pago. Reaseguramos que el
                # valor_pagado siga reflejando los abonos existentes (por si
                # el form trajo un valor distinto en su campo readonly).
                matricula_updated.recalcular_valor_pagado()
                messages.success(
                    request,
                    'Datos de la matrícula actualizados. Los pagos no se '
                    'modificaron.'
                )

            return redirect(
                'academia:matricula_lista',
                modalidad=matricula.modalidad,
            )
    else:
        est_form = EstudianteForm(prefix='est', instance=matricula.estudiante)
        # En edición el "Valor pagado" es informativo y no se vuelve a cobrar.
        mat_form = MatriculaForm(
            prefix='mat', instance=matricula, modalidad=modalidad,
            captura_pago=False,
        )

    comprobante_existente = getattr(matricula, 'comprobante', None)

    return render(request, 'matricula/form.html', {
        'est_form': est_form,
        'mat_form': mat_form,
        'matricula': matricula,
        'comprobante_existente': comprobante_existente,
        'cursos_disponibles': _cursos_para_matricula(),
        'modalidad': modalidad,
        'modalidad_label': _label_modalidad(modalidad),
        'modo': 'editar',
        'reiniciar_pago': reiniciar_pago,
        'titulo': f'Editar Matrícula #{matricula.pk}',
        'asesores': asesores,
        'error_vendedora': error_vendedora,
    })


@matricula_requerida
def matricula_lista(request, modalidad):
    modalidad = _modalidad_o_404(modalidad)
    q = request.GET.get('q', '').strip()
    curso_id = request.GET.get('curso', '').strip()
    descuento_str = request.GET.get('descuento', '').strip()

    registrado_por_id = request.GET.get('registrador', '').strip()

    qs = (Matricula.objects
          .filter(modalidad=modalidad)
          .select_related('estudiante', 'curso', 'jornada', 'registrado_por', 'comprobante'))

    if q:
        qs = qs.filter(
            Q(estudiante__cedula__icontains=q)
           
            | Q(estudiante__nombres__icontains=q)
            | Q(curso__nombre__icontains=q)
            | Q(fact_cedula__icontains=q)
        )
    if curso_id:
        qs = qs.filter(curso_id=curso_id)
        
    if descuento_str == 'si':
        qs = qs.filter(descuento__gt=0)
    elif descuento_str == 'no':
        qs = qs.filter(descuento=0)
        
    if registrado_por_id.isdigit():
        qs = qs.filter(registrado_por_id=int(registrado_por_id))

    if modalidad == 'online':
        cursos_filtro = Curso.objects.filter(activo=True, ofrece_online=True)
    else:
        cursos_filtro = Curso.objects.filter(activo=True, ofrece_presencial=True)

    from django.contrib.auth import get_user_model
    User = get_user_model()
    registradores = User.objects.filter(is_active=True).order_by('first_name', 'username')

    return render(request, 'matricula/lista.html', {
        'matriculas': qs,
        'cursos': cursos_filtro,
        'registradores': registradores,
        'q': q,
        'curso_seleccionado': curso_id,
        'descuento_seleccionado': descuento_str,
        'registrador_seleccionado': registrado_por_id,
        'modalidad': modalidad,
        'modalidad_label': _label_modalidad(modalidad),
    })



@matricula_requerida
@require_POST
def matricula_eliminar(request, modalidad, pk):
    modalidad = _modalidad_o_404(modalidad)
    matricula = get_object_or_404(Matricula, pk=pk, modalidad=modalidad)
    matricula.delete()
    messages.success(request, 'Matrícula eliminada.')
    return redirect('academia:matricula_lista', modalidad=modalidad)


# ─────────────────────────────────────────────────────────
# Cursos y categorías
# ─────────────────────────────────────────────────────────

@login_required
def cursos_lista(request, modalidad):
    """
    Lista cursos filtrados por modalidad. Solo muestra los que
    ofrecen la modalidad seleccionada.

    Vista tipo CRM: cada curso trae precargadas sus jornadas de la modalidad
    activa (con día, fecha, hora opcional y sede), y se calculan métricas por
    categoría y totales generales.
    """
    modalidad = _modalidad_o_404(modalidad)

    from django.db.models import Prefetch

    # Solo jornadas activas de la modalidad que estamos viendo, ordenadas.
    jornadas_qs = (
        JornadaCurso.objects
        .filter(modalidad=modalidad, activo=True)
        .select_related('sede')
        .order_by('fecha_inicio', 'hora_inicio')
    )

    # Filtro principal: cursos que ofrecen esta modalidad
    if modalidad == 'online':
        cursos_qs = Curso.objects.filter(ofrece_online=True)
    else:
        cursos_qs = Curso.objects.filter(ofrece_presencial=True)

    cursos_qs = cursos_qs.select_related('categoria').prefetch_related(
        Prefetch('jornadas', queryset=jornadas_qs, to_attr='jornadas_modalidad')
    )

    # Categorías: agrupa solo los cursos que ofrecen la modalidad
    categorias_lista = []
    total_jornadas_global = 0
    total_con_jornada = 0
    for cat in Categoria.objects.filter(activo=True).order_by('orden', 'nombre'):
        cursos_cat = list(cursos_qs.filter(categoria=cat).order_by('nombre'))
        # Métricas de la categoría
        jorn_cat = sum(len(c.jornadas_modalidad) for c in cursos_cat)
        con_jorn = sum(1 for c in cursos_cat if c.jornadas_modalidad)
        total_jornadas_global += jorn_cat
        total_con_jornada += con_jorn
        categorias_lista.append({
            'obj': cat,
            'cursos': cursos_cat,
            'total': len(cursos_cat),
            'total_jornadas': jorn_cat,
            'con_jornada': con_jorn,
        })

    sin_categoria = list(cursos_qs.filter(categoria__isnull=True).order_by('nombre'))
    total_cursos = cursos_qs.count()

    # Conteo en cada modalidad para mostrar en los tabs
    counts = {
        'presencial': Curso.objects.filter(ofrece_presencial=True).count(),
        'online': Curso.objects.filter(ofrece_online=True).count(),
    }

    cursos_activos = cursos_qs.filter(activo=True).order_by('nombre')

    # Sedes activas (para el creador rápido de sede y para mostrar contexto).
    sedes_activas = Sede.objects.filter(activa=True).order_by('pais', 'orden', 'nombre')

    return render(request, 'cursos/lista.html', {
        'categorias': categorias_lista,
        'sin_categoria': sin_categoria,
        'total_cursos': total_cursos,
        'total_jornadas_global': total_jornadas_global,
        'total_con_jornada': total_con_jornada,
        'modalidad': modalidad,
        'modalidad_label': _label_modalidad(modalidad),
        'counts': counts,
        'cursos_activos': cursos_activos,
        'sedes_activas': sedes_activas,
    })


@permiso_requerido('academia.add_curso', 'No tienes permiso para crear cursos.')
def curso_crear(request):
    modalidad_pref = request.GET.get('modalidad', 'presencial')
    if modalidad_pref not in MODALIDADES_VALIDAS:
        modalidad_pref = 'presencial'

    if request.method == 'POST':
        form = CursoForm(request.POST)
        if form.is_valid():
            curso = form.save()
            messages.success(request, f'Curso "{curso.nombre}" creado.')
            modalidad_redirect = (
                'online' if curso.ofrece_online and not curso.ofrece_presencial
                else 'presencial'
            )
            return redirect('academia:cursos_lista', modalidad=modalidad_redirect)
    else:
        cat_id = request.GET.get('categoria')
        initial = {
            'ofrece_presencial': modalidad_pref == 'presencial',
            'ofrece_online': modalidad_pref == 'online',
        }
        if cat_id and cat_id.isdigit():
            initial['categoria'] = cat_id
        form = CursoForm(initial=initial)

    return render(request, 'cursos/form.html', {
        'form': form,
        'modo': 'crear',
        'titulo': 'Nuevo Curso',
        'modalidad_pref': modalidad_pref,
    })


@permiso_requerido('academia.change_curso', 'No tienes permiso para editar cursos.')
def curso_editar(request, pk):
    curso = get_object_or_404(Curso, pk=pk)
    if request.method == 'POST':
        form = CursoForm(request.POST, instance=curso)
        if form.is_valid():
            form.save()
            messages.success(request, f'Curso "{curso.nombre}" actualizado.')
            modalidad_redirect = 'online' if curso.ofrece_online and not curso.ofrece_presencial else 'presencial'
            return redirect('academia:cursos_lista', modalidad=modalidad_redirect)
    else:
        form = CursoForm(instance=curso)
    return render(request, 'cursos/form.html', {
        'form': form,
        'curso': curso,
        'modo': 'editar',
        'titulo': f'Editar: {curso.nombre}',
        'modalidad_pref': 'online' if (curso.ofrece_online and not curso.ofrece_presencial) else 'presencial',
    })


@permiso_requerido('academia.delete_curso', 'No tienes permiso para eliminar cursos.')
@require_POST
def curso_eliminar(request, pk):
    curso = get_object_or_404(Curso, pk=pk)
    modalidad_redirect = 'online' if (curso.ofrece_online and not curso.ofrece_presencial) else 'presencial'
    if curso.matriculas.exists():
        curso.activo = False
        curso.save()
        messages.warning(
            request,
            f'El curso "{curso.nombre}" tiene matrículas. Se marcó como inactivo.'
        )
    else:
        nombre = curso.nombre
        curso.delete()
        messages.success(request, f'Curso "{nombre}" eliminado.')
    return redirect('academia:cursos_lista', modalidad=modalidad_redirect)


@jornadas_requeridas
def curso_jornadas(request, pk):
    """Lista jornadas del curso y permite agregar nuevas en la misma pantalla."""
    curso = get_object_or_404(Curso, pk=pk)
    modalidad_activa = request.GET.get('modalidad', 'presencial')
    puede_agregar = puede_agregar_jornadas(request.user)
    
    if request.method == 'POST':
        if not puede_agregar:
            messages.error(request, 'No tienes permiso para agregar jornadas.')
            from django.urls import reverse
            return redirect(f"{reverse('academia:curso_jornadas', args=[curso.pk])}?modalidad={modalidad_activa}")

        form = JornadaCursoForm(request.POST)
        if form.is_valid():
            jornada = form.save(commit=False)
            jornada.curso = curso
            jornada.save()
            messages.success(request, f'Jornada {jornada.get_modalidad_display().lower()} agregada.')
            from django.urls import reverse
            return redirect(f"{reverse('academia:curso_jornadas', args=[curso.pk])}?modalidad={modalidad_activa}")
    else:
        form = JornadaCursoForm(initial={'modalidad': modalidad_activa, 'activo': True})

    jornadas_pres = curso.jornadas.filter(modalidad='presencial').order_by('fecha_inicio')
    jornadas_onl = curso.jornadas.filter(modalidad='online').order_by('fecha_inicio')

    sedes = Sede.objects.filter(activa=True).order_by('pais', 'orden', 'nombre')

    return render(request, 'cursos/jornadas.html', {
        'curso': curso,
        'jornadas_presencial': jornadas_pres,
        'jornadas_online': jornadas_onl,
        'form': form,
        'modalidad_activa': modalidad_activa,
        'sedes': sedes,
        'puede_agregar_jornada': puede_agregar,
        'puede_editar_jornada': puede_editar_jornadas(request.user),
        'puede_eliminar_jornada': puede_eliminar_jornadas(request.user),
    })


@admin_requerido
@require_POST
def curso_reinicio_jornada(request):
    """
    Reinicia un curso entero borrando TODAS sus jornadas,
    matrículas y abonos asociados. (Hard delete).
    """
    curso_id = request.POST.get('curso_id')
    modalidad = request.POST.get('modalidad', 'presencial')
    admin_password = request.POST.get('admin_password', '')
    
    if not curso_id:
        messages.error(request, 'Debe seleccionar un curso.')
        return redirect('academia:cursos_lista', modalidad=modalidad)

    if not request.user.check_password(admin_password):
        messages.error(request, 'Contraseña incorrecta. Acción cancelada.')
        return redirect('academia:cursos_lista', modalidad=modalidad)

    curso = get_object_or_404(Curso, pk=curso_id)

    try:
        with transaction.atomic():
            jornadas = JornadaCurso.objects.filter(curso=curso, modalidad=modalidad)
            matriculas = Matricula.objects.filter(jornada__in=jornadas)
            
            jornadas_count = jornadas.count()
            matriculas_count = matriculas.count()
            abonos_count = Abono.objects.filter(matricula__in=matriculas).count()
            
            Abono.objects.filter(matricula__in=matriculas).delete()
            matriculas.delete()
            jornadas.delete()
            
            messages.success(
                request,
                f'Reinicio exitoso: se eliminaron {jornadas_count} jornadas, '
                f'{matriculas_count} matrículas y {abonos_count} abonos '
                f'del curso «{curso.nombre}» en modalidad {modalidad}.'
            )
    except Exception as e:
        messages.error(request, f'Error al reiniciar el curso: {str(e)}')
        
    return redirect('academia:cursos_lista', modalidad=modalidad)


@permiso_jornada_requerido('academia.delete_jornadacurso')
@require_POST
def jornada_eliminar(request, pk, jornada_pk):
    curso = get_object_or_404(Curso, pk=pk)
    jornada = get_object_or_404(JornadaCurso, pk=jornada_pk, curso=curso)
    modalidad_jornada = jornada.modalidad
    if jornada.matriculas.exists():
        jornada.activo = False
        jornada.save()
        messages.warning(request, 'La jornada tiene matrículas; se marcó como inactiva.')
    else:
        jornada.delete()
        messages.success(request, 'Jornada eliminada.')
    from django.urls import reverse
    return redirect(f"{reverse('academia:curso_jornadas', args=[curso.pk])}?modalidad={modalidad_jornada}")


@permiso_jornada_requerido('academia.change_jornadacurso')
def jornada_editar(request, pk, jornada_pk):
    """Edita una jornada existente. Acepta POST (form) o GET (devuelve datos JSON para el modal)."""
    curso = get_object_or_404(Curso, pk=pk)
    jornada = get_object_or_404(JornadaCurso, pk=jornada_pk, curso=curso)

    if request.method == 'GET' and request.headers.get('x-requested-with') == 'XMLHttpRequest':
        # Devolver datos de la jornada como JSON para pre-rellenar el modal
        return JsonResponse({
            'ok': True,
            'jornada': {
                'id': jornada.pk,
                'modalidad': jornada.modalidad,
                'descripcion': jornada.descripcion,
                'descripcion_otros': jornada.descripcion_otros or '',
                'fecha_inicio': jornada.fecha_inicio.strftime('%Y-%m-%d') if jornada.fecha_inicio else '',
                'hora_inicio': jornada.hora_inicio.strftime('%H:%M') if jornada.hora_inicio else '',
                'hora_fin': jornada.hora_fin.strftime('%H:%M') if jornada.hora_fin else '',
                'sede': jornada.sede_id or '',
                'ciudad': jornada.ciudad or '',
                'activo': jornada.activo,
            }
        })

    if request.method == 'POST':
        form = JornadaCursoForm(request.POST, instance=jornada)
        if form.is_valid():
            form.save()
            messages.success(request, 'Jornada actualizada correctamente.')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')

    from django.urls import reverse
    modalidad_activa = request.POST.get('modalidad_activa', jornada.modalidad)
    return redirect(f"{reverse('academia:curso_jornadas', args=[curso.pk])}?modalidad={modalidad_activa}")


# ─────────────────────────────────────────────────────────
# Endpoints AJAX
# ─────────────────────────────────────────────────────────

@login_required
def api_curso_detalle(request, pk):
    """Devuelve datos del curso. Usa ?modalidad= para devolver el valor correcto."""
    curso = get_object_or_404(Curso, pk=pk)
    modalidad = request.GET.get('modalidad', 'presencial')
    if modalidad not in MODALIDADES_VALIDAS:
        modalidad = 'presencial'

    return JsonResponse({
        'ok': True,
        'curso': {
            'id': curso.id,
            'nombre': curso.nombre,
            'valor': str(curso.valor_para(modalidad)),
            'valor_presencial': str(curso.valor_presencial),
            'valor_online': str(curso.valor_online),
            'numero_modulos': curso.numero_modulos or 1,
            'numero_modulos_online': curso.numero_modulos_online or 1,
            'ofrece_presencial': curso.ofrece_presencial,
            'ofrece_online': curso.ofrece_online,
            'categoria_id': curso.categoria_id,
            'categoria_nombre': curso.categoria.nombre if curso.categoria else '',
            'requiere_talla': bool(
                curso.categoria
                and curso.categoria.nombre.strip().lower() in ('técnico', 'tecnico')
            ),
        }
    })


@login_required
def api_curso_jornadas(request, pk):
    """
    Devuelve jornadas del curso.

    - Si NO se pasa ?modalidad= o se pasa ?modalidad=all → devuelve TODAS las
      jornadas activas del curso (presenciales + online). Cada jornada incluye
      su propia modalidad para que el frontend pueda etiquetarlas.
    - Si se pasa ?modalidad=presencial / ?modalidad=online → filtra por esa.
    """
    curso = get_object_or_404(Curso, pk=pk)
    modalidad = request.GET.get('modalidad', '').strip().lower()

    jornadas = curso.jornadas.filter(activo=True)
    if modalidad in MODALIDADES_VALIDAS:
        jornadas = jornadas.filter(modalidad=modalidad)
    # Si modalidad == '' o 'all' → no filtramos: salen ambas

    data = []
    for j in jornadas:
        data.append({
            'id': j.id,
            'modalidad': j.modalidad,
            'modalidad_label': j.get_modalidad_display(),
            'descripcion_codigo': j.descripcion,
            'descripcion': j.descripcion_legible,
            'fecha': j.fecha_inicio.strftime('%d/%m/%Y') if j.fecha_inicio else '',
            'hora_inicio': j.hora_inicio.strftime('%H:%M') if j.hora_inicio else '',
            'hora_fin': j.hora_fin.strftime('%H:%M') if j.hora_fin else '',
            'ciudad': j.ciudad or '',
            'etiqueta': j.etiqueta,
        })
    return JsonResponse({'ok': True, 'jornadas': data})


@login_required
def api_estudiante_por_cedula(request, cedula):
    """
    Busca un estudiante por cédula y devuelve sus datos para autocompletar
    el formulario de matrícula.

    Se monta como GET /api/estudiante/<cedula>/
    Si no existe, devuelve {ok: false, encontrado: false}.
    """
    cedula = (cedula or '').strip()
    if not cedula:
        return JsonResponse({'ok': False, 'error': 'Cédula vacía.'}, status=400)

    estudiante = Estudiante.objects.filter(cedula=cedula).first()
    if not estudiante:
        # No está en el directorio vivo. Buscar en el archivo histórico:
        # si el estudiante fue archivado en un cierre con "limpiar directorio",
        # recuperamos sus datos personales para autocompletar igual y no
        # obligar a teclear todo de nuevo. Al guardar la matrícula, el sistema
        # lo vuelve a crear como estudiante vivo automáticamente.
        archivado = (
            EstudianteArchivado.objects
            .filter(cedula=cedula)
            .order_by('-archivado_en')
            .first()
        )
        if not archivado:
            archivado = (
                MatriculaArchivada.objects
                .filter(cedula=cedula)
                .order_by('-archivado_en')
                .first()
            )

        if archivado:
            # El nivel_formacion en el archivo está guardado como texto legible
            # (ej. "Técnico"); el <select> del formulario espera el código
            # interno (ej. "tecnico"). Hacemos el mapeo inverso.
            nivel_codigo = ''
            nivel_legible = (archivado.nivel_formacion or '').strip()
            if nivel_legible:
                for codigo, label in Estudiante.NIVELES_FORMACION:
                    if label == nivel_legible or codigo == nivel_legible:
                        nivel_codigo = codigo
                        break

            ciudad_est = getattr(archivado, 'ciudad', getattr(archivado, 'ciudad_estudiante', ''))
            titulo_prof = getattr(archivado, 'titulo_profesional', '')

            return JsonResponse({
                'ok': True,
                'encontrado': True,
                'desde_archivo': True,
                'estudiante': {
                    'id': '',  # no tiene id vivo todavía; se creará al matricular
                    'cedula': archivado.cedula,
                    'nombres': archivado.nombres,
                    'edad': archivado.edad if archivado.edad is not None else '',
                    'correo': archivado.correo or '',
                    'celular': archivado.celular or '',
                    'nivel_formacion': nivel_codigo,
                    'titulo_profesional': titulo_prof,
                    'ciudad': ciudad_est,
                },
                'matriculas': [],  # las matrículas viejas están archivadas, no vivas
            })
        return JsonResponse({'ok': True, 'encontrado': False})

    # Incluir matrículas existentes para detectar duplicados en el frontend
    matriculas_existentes = list(
        estudiante.matriculas.select_related('curso', 'jornada').values(
            'curso__id', 'curso__nombre', 'jornada__descripcion',
        )
    )

    return JsonResponse({
        'ok': True,
        'encontrado': True,
        'desde_archivo': False,
        'estudiante': {
            'id': estudiante.id,
            'cedula': estudiante.cedula,
            'nombres': estudiante.nombres,
            'edad': estudiante.edad if estudiante.edad is not None else '',
            'correo': estudiante.correo or '',
            'celular': estudiante.celular or '',
            'nivel_formacion': estudiante.nivel_formacion or '',
            'titulo_profesional': estudiante.titulo_profesional or '',
            'ciudad': estudiante.ciudad or '',
        },
        'matriculas': [
            {
                'curso_id': m['curso__id'],
                'curso_nombre': m['curso__nombre'],
                'jornada': m['jornada__descripcion'] or '',
            }
            for m in matriculas_existentes
        ],
    })


def _normalizar_celular(celular):
    """Deja solo dígitos para comparar números sin importar espacios/guiones."""
    return ''.join(x for x in (celular or '') if x.isdigit())


@login_required
def api_estudiantes_por_celular(request, celular):
    """
    Busca todos los estudiantes que comparten un mismo número de celular.

    Útil cuando un padre/madre registra a varios hijos con el mismo número,
    o cuando una familia comparte el celular. NO bloquea la matrícula: es
    solo un aviso informativo que también permite copiar los datos de un
    estudiante existente.

    Se monta como GET /api/estudiantes-por-celular/<celular>/
    Acepta el parámetro opcional ?excluir_cedula=<cedula> para excluir al
    estudiante que se está editando.
    """
    celular_digitos = _normalizar_celular(celular)
    if not celular_digitos or len(celular_digitos) < 7:
        return JsonResponse({'ok': True, 'encontrados': False, 'estudiantes': []})

    excluir_cedula = (request.GET.get('excluir_cedula') or '').strip()

    qs = Estudiante.objects.exclude(celular='')
    if excluir_cedula:
        qs = qs.exclude(cedula=excluir_cedula)

    coincidencias = []
    for est in qs.only('id', 'cedula', 'nombres', 'correo',
                       'celular', 'ciudad', 'nivel_formacion',
                       'titulo_profesional', 'edad'):
        est_digitos = _normalizar_celular(est.celular)
        if not est_digitos:
            continue
        if est_digitos[-9:] == celular_digitos[-9:]:
            coincidencias.append({
                'id': est.id,
                'cedula': est.cedula,
                'nombres': est.nombres,
                'nombre_completo': est.nombre_completo,
                'edad': est.edad if est.edad is not None else '',
                'correo': est.correo or '',
                'celular': est.celular or '',
                'ciudad': est.ciudad or '',
                'nivel_formacion': est.nivel_formacion or '',
                'titulo_profesional': est.titulo_profesional or '',
            })

    return JsonResponse({
        'ok': True,
        'encontrados': len(coincidencias) > 0,
        'cantidad': len(coincidencias),
        'estudiantes': coincidencias,
    })


@permiso_requerido('academia.add_categoria', 'No tienes permiso para crear categorías.')
@require_http_methods(['POST'])
def api_categoria_crear(request):
    """Crea una categoría desde el modal del form de curso."""
    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        data = request.POST

    nombre = (data.get('nombre') or '').strip()
    color = (data.get('color') or '#1a237e').strip()
    descripcion = (data.get('descripcion') or '').strip()

    if not nombre:
        return JsonResponse(
            {'ok': False, 'error': 'El nombre de la categoría es obligatorio.'},
            status=400
        )

    if Categoria.objects.filter(nombre__iexact=nombre).exists():
        return JsonResponse(
            {'ok': False, 'error': f'Ya existe una categoría llamada "{nombre}".'},
            status=409
        )

    colores_validos = [c[0] for c in Categoria.COLORES]
    if color not in colores_validos:
        color = '#1a237e'

    siguiente_orden = (Categoria.objects.order_by('-orden').first().orden + 1) \
        if Categoria.objects.exists() else 1

    categoria = Categoria.objects.create(
        nombre=nombre,
        descripcion=descripcion,
        color=color,
        orden=siguiente_orden,
    )

    return JsonResponse({
        'ok': True,
        'categoria': {
            'id': categoria.id,
            'nombre': categoria.nombre,
            'color': categoria.color,
        },
    })


@require_http_methods(['GET'])
def api_categoria_listar(request):
    """
    Devuelve la lista de categorías activas (id, nombre, color, descripción)
    para refrescar el selector del formulario de cursos sin recargar página.
    """
    categorias = (Categoria.objects
                  .filter(activo=True)
                  .order_by('orden', 'nombre')
                  .values('id', 'nombre', 'color', 'descripcion'))
    return JsonResponse({
        'ok': True,
        'categorias': list(categorias),
    })


@permiso_requerido('academia.delete_categoria', 'No tienes permiso para eliminar categorías.')
@require_http_methods(['POST'])
def api_categoria_eliminar(request, pk):
    """
    Elimina una categoría. Si tiene cursos asociados, devuelve 409 (Conflict)
    en lugar de borrar — gracias a `on_delete=PROTECT` en el modelo Curso.
    Respeta el permiso `delete_categoria` configurado en Django Admin.
    """
    from django.db.models import ProtectedError

    try:
        categoria = Categoria.objects.get(pk=pk)
    except Categoria.DoesNotExist:
        return JsonResponse(
            {'ok': False, 'error': 'La categoría ya no existe.'},
            status=404
        )

    nombre = categoria.nombre
    cursos_asociados = categoria.cursos.count()

    if cursos_asociados > 0:
        return JsonResponse({
            'ok': False,
            'error': (
                f'No se puede eliminar "{nombre}" porque tiene '
                f'{cursos_asociados} curso(s) asociado(s). Reasigna o elimina '
                f'esos cursos primero.'
            ),
            'cursos_asociados': cursos_asociados,
        }, status=409)

    try:
        categoria.delete()
    except ProtectedError:
        # Doble seguro por si Django detecta otra protección
        return JsonResponse({
            'ok': False,
            'error': f'No se puede eliminar "{nombre}" porque tiene registros relacionados.',
        }, status=409)

    return JsonResponse({
        'ok': True,
        'mensaje': f'Categoría "{nombre}" eliminada correctamente.',
    })


# ─────────────────────────────────────────────────────────
# Exportación: Lista de matrículas a Excel y PDF
# ─────────────────────────────────────────────────────────

def _matriculas_filtradas_para_export(request, modalidad):
    """Aplica los mismos filtros que matricula_lista y devuelve el queryset."""
    q = request.GET.get('q', '').strip()
    curso_id = request.GET.get('curso', '').strip()
    descuento_str = request.GET.get('descuento', '').strip()
    registrador_id = request.GET.get('registrador', '').strip()

    qs = (Matricula.objects
          .filter(modalidad=modalidad)
          .select_related('estudiante', 'curso', 'jornada', 'registrado_por'))

    if q:
        qs = qs.filter(
            Q(estudiante__cedula__icontains=q)
           
            | Q(estudiante__nombres__icontains=q)
            | Q(curso__nombre__icontains=q)
            | Q(fact_cedula__icontains=q)
        )
    if curso_id:
        qs = qs.filter(curso_id=curso_id)
        
    if descuento_str == 'si':
        qs = qs.filter(descuento__gt=0)
    elif descuento_str == 'no':
        qs = qs.filter(descuento=0)

    if registrador_id.isdigit():
        qs = qs.filter(registrado_por_id=int(registrador_id))

    return qs.order_by('-fecha_matricula', '-creado')


@matricula_requerida
def matricula_export_excel(request, modalidad):
    """Exporta la lista de matrículas filtradas a un archivo Excel (.xlsx)."""
    from .views_pagos import _build_excel_response
    from datetime import date as _date

    modalidad = _modalidad_o_404(modalidad)
    qs = _matriculas_filtradas_para_export(request, modalidad)

    headers = [
        'Cédula', 'Apellidos', 'Nombres', 'Edad', 'Correo', 'Celular',
        'Nivel formación', 'Título profesional', 'Ciudad',
        'Curso', 'Modalidad', 'Tipo matrícula',
        'Jornada', 'Sede / Plataforma', 'Fecha jornada', 'Horario',
        'Talla', 'Fecha matrícula',
        'Valor curso', 'Descuento', 'Valor neto', 'Valor pagado', 'Saldo', 'Estado pago',
        'Tipo registro', 'Vendedora',
        'Factura', 'Fact. nombres', 'Fact. cédula', 'Fact. correo',
        'Link comprobante',
    ]
    rows = []
    total_curso = total_descuento = total_neto = total_pagado = total_saldo = 0
    for m in qs:
        e = m.estudiante
        j = m.jornada
        vendedora = ''
        if m.registrado_por:
            vendedora = (
                f'{m.registrado_por.first_name} {m.registrado_por.last_name}'.strip()
                or m.registrado_por.username
            )
        rows.append([
            e.cedula, e.nombres,
            e.edad if e.edad is not None else '',
            e.correo or '', e.celular or '',
            e.get_nivel_formacion_display() if e.nivel_formacion else '',
            e.titulo_profesional or '', e.ciudad or '',
            m.curso.nombre,
            m.get_modalidad_display(),
            m.get_tipo_matricula_display(),
            j.descripcion_legible if j else '',
            (j.ciudad if j and j.ciudad else ''),
            j.fecha_inicio.strftime('%d/%m/%Y') if (j and j.fecha_inicio) else '',
            f'{j.hora_inicio.strftime("%H:%M")} - {j.hora_fin.strftime("%H:%M")}' if (j and j.hora_inicio and j.hora_fin) else '',
            m.get_talla_camiseta_display() if m.talla_camiseta else '',
            m.fecha_matricula.strftime('%d/%m/%Y') if m.fecha_matricula else '',
            float(m.valor_curso or 0),
            float(m.descuento or 0),
            float(m.valor_neto or 0),
            float(m.valor_pagado or 0),
            float(m.saldo or 0),
            m.estado_pago,
            m.get_tipo_registro_display() if m.tipo_registro else '',
            vendedora,
            m.get_factura_realizada_display(),
            m.fact_nombres or '',
            m.fact_cedula or '', m.fact_correo or '',
            m.link_comprobante or '',
        ])
        total_curso += float(m.valor_curso or 0)
        total_descuento += float(m.descuento or 0)
        total_neto += float(m.valor_neto or 0)
        total_pagado += float(m.valor_pagado or 0)
        total_saldo += float(m.saldo or 0)

    # Indices 0-based de las columnas numéricas para los totales:
    # 18=Valor curso, 19=Descuento, 20=Valor neto, 21=Valor pagado, 22=Saldo
    totals = {
        18: round(total_curso, 2),
        19: round(total_descuento, 2),
        20: round(total_neto, 2),
        21: round(total_pagado, 2),
        22: round(total_saldo, 2),
    }
    filename = f"matriculas_{modalidad}_{_date.today().strftime('%Y%m%d')}.xlsx"
    sheet_name = f"Matrículas {_label_modalidad(modalidad)}"
    return _build_excel_response(filename, sheet_name, headers, rows, totals=totals)


@matricula_requerida
def matricula_export_pdf(request, modalidad):
    """Exporta la lista de matrículas filtradas a un PDF."""
    from datetime import date as _date
    from io import BytesIO

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
        )
    except ImportError:
        from django.http import HttpResponse
        return HttpResponse(
            'Para exportar a PDF instala reportlab:  pip install reportlab',
            status=500, content_type='text/plain; charset=utf-8',
        )

    modalidad = _modalidad_o_404(modalidad)
    qs = _matriculas_filtradas_para_export(request, modalidad)

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=1*cm, rightMargin=1*cm, topMargin=1.2*cm, bottomMargin=1*cm,
        title=f'Matrículas {_label_modalidad(modalidad)}',
    )
    styles = getSampleStyleSheet()
    titulo_st = ParagraphStyle('titulo', parent=styles['Title'],
                               textColor=colors.HexColor('#1A237E'),
                               fontSize=16, alignment=1, spaceAfter=8)
    sub_st = ParagraphStyle('sub', parent=styles['Normal'],
                            textColor=colors.HexColor('#666666'),
                            fontSize=9, alignment=1, spaceAfter=12)

    elements = [
        Paragraph(f'Lista de Matrículas — {_label_modalidad(modalidad)}', titulo_st),
        Paragraph(
            f'Formación Técnica y Profesional EC · Generado el '
            f'{_date.today().strftime("%d/%m/%Y")} · {qs.count()} matrícula(s)',
            sub_st,
        ),
    ]

    headers = [
        'Cédula', 'Estudiante', 'Curso', 'Jornada',
        'F. matric.', 'Tipo matric.', 'Tipo reg.',
        'Valor', 'Desc.', 'Pagado', 'Saldo', 'Estado',
        'Vendedora', 'Factura',
    ]
    data = [headers]
    total_curso = total_descuento = total_pagado = total_saldo = 0
    for m in qs:
        e = m.estudiante
        j = m.jornada
        vendedora = ''
        if m.registrado_por:
            vendedora = (
                f'{m.registrado_por.first_name} {m.registrado_por.last_name}'.strip()
                or m.registrado_por.username
            )
        # Si hay descuento, mostramos el valor con descuento aplicado y el monto del descuento
        desc = float(m.descuento or 0)
        valor_mostrar = float(m.valor_neto or 0) if desc > 0 else float(m.valor_curso or 0)
        data.append([
            e.cedula,
            e.nombres.strip(),
            m.curso.nombre,
            j.descripcion_legible if j else '—',
            m.fecha_matricula.strftime('%d/%m/%Y') if m.fecha_matricula else '',
            m.get_tipo_matricula_display(),
            m.get_tipo_registro_display() if m.tipo_registro else '—',
            f'${valor_mostrar:.2f}',
            f'${desc:.2f}' if desc > 0 else '—',
            f'${float(m.valor_pagado or 0):.2f}',
            f'${float(m.saldo or 0):.2f}',
            m.estado_pago,
            vendedora or '—',
            m.get_factura_realizada_display(),
        ])
        total_curso += valor_mostrar
        total_descuento += desc
        total_pagado += float(m.valor_pagado or 0)
        total_saldo += float(m.saldo or 0)

    # Fila de totales
    data.append([
        '', '', '', '', '', '', 'TOTAL',
        f'${total_curso:.2f}',
        f'${total_descuento:.2f}' if total_descuento > 0 else '—',
        f'${total_pagado:.2f}',
        f'${total_saldo:.2f}',
        '', '', '',
    ])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        # Encabezado
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1A237E')),
        ('TEXTCOLOR',  (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, 0), (-1, 0), 8),
        ('ALIGN',      (0, 0), (-1, 0), 'CENTER'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        # Cuerpo
        ('FONTSIZE',   (0, 1), (-1, -2), 7),
        ('VALIGN',     (0, 1), (-1, -1), 'MIDDLE'),
        ('GRID',       (0, 0), (-1, -1), 0.3, colors.HexColor('#CCCCCC')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#F5F5F5')]),
        # Total
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#FFF8E1')),
        ('FONTNAME',   (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR',  (0, -1), (-1, -1), colors.HexColor('#1A237E')),
        ('FONTSIZE',   (0, -1), (-1, -1), 8),
    ]))
    elements.append(table)
    doc.build(elements)

    pdf_bytes = buf.getvalue()
    buf.close()
    from django.http import HttpResponse
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    filename = f'matriculas_{modalidad}_{_date.today().strftime("%Y%m%d")}.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
