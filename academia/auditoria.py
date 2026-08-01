"""Registro automático y seguro de actividad de usuarios."""

from django.db import DatabaseError


# Peticiones técnicas que no representan una acción consciente del usuario.
RUTAS_GET_EXCLUIDAS = {
    'session_keepalive',
    'api_curso_detalle',
    'api_curso_jornadas',
    'api_categoria_listar',
    'api_estudiante_por_cedula',
    'api_estudiantes_por_celular',
    'api_adicional_estudiante',
    'api_adicional_persona_externa',
}


ACCIONES_POST = {
    'login_code': ('acceso', 'Inició sesión en el sistema'),
    'logout': ('acceso', 'Cerró sesión en el sistema'),
    'matricula_registrar': ('creacion', 'Registró una matrícula'),
    'matricula_editar': ('edicion', 'Editó una matrícula'),
    'matricula_eliminar': ('eliminacion', 'Eliminó una matrícula'),
    'curso_crear': ('creacion', 'Creó un curso'),
    'curso_editar': ('edicion', 'Editó un curso'),
    'curso_eliminar': ('eliminacion', 'Eliminó un curso'),
    'curso_jornadas': ('creacion', 'Agregó una jornada a un curso'),
    'jornada_editar': ('edicion', 'Editó una jornada'),
    'jornada_eliminar': ('eliminacion', 'Eliminó una jornada'),
    'jornada_marcar_feriado': ('edicion', 'Marcó una jornada como día no laboral'),
    'curso_reinicio_jornada': ('administracion', 'Reinició el control diario de una jornada'),
    'hoja_recaudacion_guardar_cuotas': ('edicion', 'Guardó valores manuales de recaudación'),
    'alerta_marcar_revisada': ('edicion', 'Marcó una alerta de pago como revisada'),
    'recuperacion_marcar': ('creacion', 'Marcó una clase para recuperación'),
    'recuperacion_editar': ('edicion', 'Editó una clase en recuperación'),
    'recuperacion_cobrar': ('pago', 'Registró el pago de una recuperación'),
    'recuperacion_eliminar': ('eliminacion', 'Eliminó una recuperación'),
    'matricula_activar_retiro': ('edicion', 'Activó el retiro voluntario de una matrícula'),
    'matricula_revertir_retiro': ('edicion', 'Revirtió el retiro voluntario de una matrícula'),
    'abono_crear': ('pago', 'Registró un pago de estudiante'),
    'abono_editar': ('pago', 'Editó un pago de estudiante'),
    'abono_eliminar': ('eliminacion', 'Eliminó un pago de estudiante'),
    'comprobante_registrar': ('creacion', 'Registró un comprobante de venta'),
    'comprobante_editar': ('edicion', 'Editó un comprobante de venta'),
    'comprobante_eliminar': ('eliminacion', 'Eliminó un comprobante de venta'),
    'api_categoria_crear': ('creacion', 'Creó una categoría de curso'),
    'api_categoria_eliminar': ('eliminacion', 'Eliminó una categoría de curso'),
    'admin_egreso_crear': ('creacion', 'Registró un egreso'),
    'admin_egreso_editar': ('edicion', 'Editó un egreso'),
    'admin_egreso_eliminar': ('eliminacion', 'Eliminó un egreso'),
    'cierre_admin_ejecutar': ('administracion', 'Ejecutó un cierre administrativo'),
    'cierre_admin_eliminar': ('eliminacion', 'Eliminó un cierre administrativo'),
    'backup_s3': ('administracion', 'Ejecutó un respaldo en S3'),
    'sede_crear': ('creacion', 'Creó una sede'),
    'sede_editar': ('edicion', 'Editó una sede'),
    'sede_toggle': ('edicion', 'Cambió el estado de una sede'),
    'sede_eliminar': ('eliminacion', 'Eliminó una sede'),
    'api_sede_crear': ('creacion', 'Creó una sede desde un formulario'),
    'adicional_crear_interno': ('pago', 'Registró un servicio adicional para un estudiante'),
    'adicional_crear_externo': ('pago', 'Registró un servicio adicional externo'),
    'adicional_editar': ('edicion', 'Editó un servicio adicional'),
    'adicional_eliminar': ('eliminacion', 'Eliminó un servicio adicional'),
    'adicional_archivar': ('administracion', 'Archivó un servicio adicional'),
    'adicional_cierre': ('administracion', 'Ejecutó el cierre de adicionales'),
    'persona_externa_crear': ('creacion', 'Registró una persona externa'),
    'persona_externa_editar': ('edicion', 'Editó una persona externa'),
    'persona_externa_eliminar': ('eliminacion', 'Eliminó una persona externa'),
    'persona_externa_archivar': ('administracion', 'Archivó una persona externa'),
    'supletorio_marcar': ('pago', 'Registró un examen supletorio'),
    'cierre_ejecutar': ('administracion', 'Ejecutó el cierre de un curso'),
    'cierre_manual_estudiante_ejecutar': ('administracion', 'Cerró manualmente una matrícula'),
    'cierre_global_ejecutar': ('administracion', 'Ejecutó un cierre global de cursos'),
    'archivo_mes_eliminar': ('eliminacion', 'Eliminó un archivo mensual'),
    'cierre_eliminar': ('eliminacion', 'Eliminó un cierre de curso'),
    'aviso_crear': ('creacion', 'Publicó un aviso'),
    'aviso_editar': ('edicion', 'Editó un aviso'),
    'aviso_toggle': ('edicion', 'Cambió el estado de un aviso'),
    'aviso_eliminar': ('eliminacion', 'Eliminó un aviso'),
    'recordatorio_crear': ('creacion', 'Creó un recordatorio'),
    'recordatorio_editar': ('edicion', 'Editó un recordatorio'),
    'recordatorio_marcar_leido': ('edicion', 'Marcó un recordatorio como leído'),
    'recordatorio_eliminar': ('eliminacion', 'Eliminó un recordatorio'),
    'assistant_simple_chat': ('consulta', 'Consultó al asistente del sistema'),
    'assistant_llm_chat': ('consulta', 'Consultó al asistente inteligente'),
}


CONSULTAS = {
    'home': 'Abrió la página principal',
    'bienvenida': 'Consultó el panel de inicio',
    'ayuda': 'Consultó la ayuda del sistema',
    'matricula_facturas': 'Consultó facturas de matrículas',
    'matricula_menu': 'Consultó el módulo de matrículas',
    'matricula_registrar': 'Abrió el formulario de matrícula',
    'matricula_lista': 'Consultó la lista de matrículas',
    'matricula_retirados': 'Consultó las matrículas retiradas',
    'matricula_editar': 'Abrió el detalle de una matrícula',
    'cursos_lista': 'Consultó la lista de cursos',
    'curso_crear': 'Abrió el formulario de nuevo curso',
    'curso_editar': 'Abrió la edición de un curso',
    'curso_jornadas': 'Consultó las jornadas de un curso',
    'pagos_lista': 'Consultó la gestión de pagos',
    'pagos_por_modulo': 'Consultó los pagos por módulo',
    'hoja_recaudacion': 'Generó una hoja de recaudación',
    'recuperaciones_lista': 'Consultó las clases en recuperación',
    'recuperacion_marcar': 'Abrió el formulario de recuperación',
    'recuperacion_editar': 'Abrió la edición de una recuperación',
    'recuperacion_cobrar': 'Abrió el cobro de una recuperación',
    'matricula_abonos': 'Consultó los pagos de una matrícula',
    'abono_crear': 'Abrió el formulario para registrar un pago',
    'abono_editar': 'Abrió la edición de un pago',
    'abono_recibo': 'Consultó un recibo de pago',
    'historial_lista': 'Consultó el historial de matriculados',
    'estudiantes_lista': 'Consultó la lista de estudiantes',
    'estudiantes_por_curso': 'Consultó estudiantes por curso',
    'estudiante_detalle': 'Consultó el detalle de un estudiante',
    'comprobante_menu': 'Consultó el módulo de comprobantes',
    'comprobante_registrar': 'Abrió el formulario de comprobante',
    'comprobante_lista': 'Consultó los comprobantes registrados',
    'comprobante_totales': 'Consultó los totales de ventas',
    'comprobante_asesor_detalle': 'Consultó el perfil de un usuario',
    'admin_dashboard': 'Consultó el Registro Administrativo',
    'control_registro': 'Consultó el control de matrículas y pagos',
    'actividad_usuarios': 'Consultó el registro diario de usuarios',
    'admin_egresos_lista': 'Consultó los egresos',
    'cierre_admin_preview': 'Consultó la vista previa del cierre administrativo',
    'cierre_admin_historial': 'Consultó el historial de cierres administrativos',
    'cierre_admin_detalle': 'Consultó un cierre administrativo',
    'sedes_lista': 'Consultó las sedes',
    'adicional_menu': 'Consultó el módulo de servicios adicionales',
    'adicional_lista': 'Consultó los servicios adicionales',
    'adicionales_archivados_lista': 'Consultó los adicionales archivados',
    'personas_externas_lista': 'Consultó las personas externas',
    'cierre_preview': 'Consultó la vista previa del cierre de curso',
    'cierre_global_preview': 'Consultó la vista previa del cierre global',
    'archivo_index': 'Consultó el archivo histórico',
    'cierre_historial': 'Consultó el historial de cierres de curso',
    'cierre_detalle': 'Consultó el detalle de un cierre de curso',
    'estudiantes_archivados_lista': 'Consultó estudiantes archivados',
    'avisos_lista': 'Consultó los avisos del panel',
    'recordatorio_lista': 'Consultó sus recordatorios',
}


SECCIONES = {
    'matricula': 'matrículas',
    'curso': 'cursos',
    'jornada': 'jornadas',
    'pago': 'pagos',
    'abono': 'pagos',
    'recuperacion': 'recuperaciones',
    'estudiante': 'estudiantes',
    'comprobante': 'comprobantes',
    'admin': 'administración',
    'egreso': 'egresos',
    'sede': 'sedes',
    'adicional': 'servicios adicionales',
    'persona_externa': 'personas externas',
    'cierre': 'cierres',
    'archivo': 'archivo histórico',
    'aviso': 'avisos',
    'recordatorio': 'recordatorios',
    'assistant': 'asistente',
}


ETIQUETAS_PARAMETROS = {
    'pk': 'Registro',
    'matricula_pk': 'Matrícula',
    'abono_pk': 'Pago',
    'recup_pk': 'Recuperación',
    'curso_pk': 'Curso',
    'jornada_pk': 'Jornada',
    'cierre_pk': 'Cierre',
    'vendedora_id': 'Usuario',
    'modalidad': 'Modalidad',
    'categoria': 'Categoría',
    'anio': 'Año',
    'mes': 'Mes',
}


def _nombre_usuario(user):
    nombre = user.get_full_name().strip()
    return nombre or user.get_username()


def _direccion_ip(request):
    reenviada = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if reenviada:
        return reenviada.split(',')[0].strip() or None
    return request.META.get('REMOTE_ADDR') or None


def _detalle_ruta(request, estado_http):
    resolver = request.resolver_match
    partes = []
    if resolver:
        for clave, valor in resolver.kwargs.items():
            etiqueta = ETIQUETAS_PARAMETROS.get(clave, clave.replace('_', ' ').title())
            valor_legible = str(valor).replace('_', ' ').title() if clave == 'modalidad' else valor
            partes.append(f'{etiqueta}: {valor_legible}')
    if estado_http >= 400:
        partes.append(f'Respuesta del sistema: HTTP {estado_http}')
    return ' · '.join(str(parte) for parte in partes)


def _accion_generica(nombre_ruta, metodo):
    nombre = nombre_ruta or 'página del sistema'
    seccion = 'el sistema'
    for prefijo, etiqueta in SECCIONES.items():
        if nombre.startswith(prefijo) or f'_{prefijo}_' in f'_{nombre}_':
            seccion = etiqueta
            break

    if metodo == 'POST':
        if 'eliminar' in nombre:
            return 'eliminacion', f'Eliminó un registro en {seccion}'
        if 'editar' in nombre or 'toggle' in nombre or 'revertir' in nombre:
            return 'edicion', f'Editó un registro en {seccion}'
        if 'crear' in nombre or 'registrar' in nombre or 'marcar' in nombre:
            return 'creacion', f'Registró una acción en {seccion}'
        return 'administracion', f'Realizó una acción en {seccion}'
    return 'consulta', f'Consultó {seccion}'


def datos_actividad(request, response, user):
    """Construye los datos auditables de una petición o devuelve ``None``."""
    if not user or not user.is_authenticated:
        return None
    if request.path.startswith(('/static/', '/media/')):
        return None

    resolver = request.resolver_match
    nombre_ruta = resolver.url_name if resolver else ''
    metodo = request.method.upper()
    if metodo == 'GET' and nombre_ruta in RUTAS_GET_EXCLUIDAS:
        return None
    if metodo not in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE'}:
        return None

    if metodo == 'GET' and ('export' in nombre_ruta or nombre_ruta.endswith('_pdf')):
        categoria, accion = 'exportacion', 'Exportó información del sistema'
    elif metodo == 'POST' and nombre_ruta in ACCIONES_POST:
        categoria, accion = ACCIONES_POST[nombre_ruta]
    elif metodo == 'GET' and nombre_ruta in CONSULTAS:
        categoria, accion = 'consulta', CONSULTAS[nombre_ruta]
    else:
        categoria, accion = _accion_generica(nombre_ruta, metodo)

    return {
        'usuario': user,
        'usuario_nombre': _nombre_usuario(user),
        'categoria': categoria,
        'accion': accion,
        'detalle': _detalle_ruta(request, response.status_code),
        'ruta': request.path[:255],
        'metodo_http': metodo,
        'estado_http': response.status_code,
        'direccion_ip': _direccion_ip(request),
    }


def registrar_actividad(request, response, user):
    """Guarda una actividad sin poner en riesgo la petición principal.

    Durante un despliegue AWS puede existir una ventana breve entre actualizar
    el código y ejecutar la migración. Cualquier error de base de datos se
    ignora deliberadamente para que la aplicación siga operativa.
    """
    datos = datos_actividad(request, response, user)
    if not datos:
        return
    try:
        from .models import ActividadUsuario
        ActividadUsuario.objects.create(**datos)
    except DatabaseError:
        return
