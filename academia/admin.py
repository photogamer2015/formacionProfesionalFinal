from decimal import Decimal

from django import forms
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.contrib.auth.models import User
from django.db import transaction
from django.template.response import TemplateResponse
from django.utils.formats import number_format
from django.utils.html import format_html, format_html_join

from .models import (
    Adicional, Categoria, Comprobante, Curso, JornadaCurso,
    Estudiante, Matricula, PersonaExterna, RecuperacionPendiente,
    AssistantQueryLog, CierreCurso, MatriculaArchivada, AbonoArchivado,
    EstudianteArchivado, AdicionalArchivado, CierreAdministrativo, Sede,
    ActividadUsuario, AmistadUsuario, Aviso, MeGustaPerfil, PerfilUsuario,
    ConfirmacionMatriculaCorreo, Recordatorio, RecordatorioPagoCorreo,
    MONTO_RESERVA_MATRICULA,
)


def _dinero(valor):
    return f'${number_format(valor, 2)}'


@admin.register(ActividadUsuario)
class ActividadUsuarioAdmin(admin.ModelAdmin):
    list_display = ('creado', 'usuario_nombre', 'categoria', 'accion', 'estado_http')
    list_filter = ('categoria', 'creado')
    search_fields = ('usuario_nombre', 'usuario__username', 'accion', 'detalle', 'ruta')
    date_hierarchy = 'creado'
    readonly_fields = (
        'usuario', 'usuario_nombre', 'categoria', 'accion', 'detalle', 'ruta',
        'metodo_http', 'estado_http', 'direccion_ip', 'creado',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Sede)
class SedeAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'pais', 'orden', 'activa', 'num_jornadas')
    list_editable = ('orden', 'activa')
    list_filter = ('pais', 'activa')
    search_fields = ('nombre', 'pais')

    def num_jornadas(self, obj):
        return obj.jornadas.count()
    num_jornadas.short_description = '# jornadas'


@admin.register(Aviso)
class AvisoAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'tema', 'fecha_inicio', 'fecha_fin', 'activo', 'fijado', 'estado_legible')
    list_filter = ('tema', 'activo', 'fijado')
    search_fields = ('titulo', 'contenido')
    date_hierarchy = 'fecha_inicio'


@admin.register(Recordatorio)
class RecordatorioAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'creado_por', 'destinatario', 'prioridad', 'fecha', 'fecha_vencimiento', 'leido', 'estado_legible')
    list_filter = ('prioridad', 'leido')
    search_fields = ('titulo', 'contenido', 'creado_por__username', 'destinatario__username')
    date_hierarchy = 'fecha'


@admin.register(RecordatorioPagoCorreo)
class RecordatorioPagoCorreoAdmin(admin.ModelAdmin):
    list_display = (
        'fecha_alerta', 'matricula', 'numero_modulo', 'destinatario',
        'monto', 'estado', 'intentos', 'enviado_en',
    )
    list_filter = ('estado', 'fecha_alerta', 'fecha_pago')
    search_fields = (
        'destinatario', 'matricula__estudiante__nombres',
        'matricula__estudiante__cedula', 'matricula__curso__nombre',
    )
    readonly_fields = (
        'matricula', 'numero_modulo', 'fecha_alerta', 'fecha_pago',
        'destinatario', 'monto', 'estado', 'intentos', 'ultimo_error',
        'enviado_en', 'creado', 'actualizado',
    )
    date_hierarchy = 'fecha_alerta'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ConfirmacionMatriculaCorreo)
class ConfirmacionMatriculaCorreoAdmin(admin.ModelAdmin):
    list_display = (
        'creado', 'matricula', 'destinatario', 'estado', 'intentos',
        'enviado_en',
    )
    list_filter = ('estado', 'creado')
    search_fields = (
        'destinatario', 'matricula__estudiante__nombres',
        'matricula__estudiante__cedula', 'matricula__curso__nombre',
    )
    readonly_fields = (
        'matricula', 'destinatario', 'formulario_url', 'estado', 'intentos',
        'ultimo_error', 'enviado_en', 'creado', 'actualizado',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# ─────────────────────────────────────────────────────────
# Usuarios: color de cada uno en el Registro Estudiantil
# ─────────────────────────────────────────────────────────

class SelectorColorRegistro(forms.RadioSelect):
    """Opciones de color con su muestra, para elegir con un clic."""

    automatico_hex = ''

    def render(self, name, value, attrs=None, renderer=None):
        from .colores_registro import HEX

        base_id = (attrs or {}).get('id') or f'id_{name}'
        valor = '' if value is None else str(value)
        return format_html(
            '<div style="display:flex;flex-wrap:wrap;gap:10px;">{}</div>',
            format_html_join('', (
                '<label for="{}" style="display:inline-flex;align-items:center;'
                'gap:8px;padding:6px 12px;border:1px solid #c7ced8;'
                'border-radius:999px;cursor:pointer;">'
                '<input type="radio" name="{}" value="{}" id="{}"{}>'
                '<span style="display:inline-block;width:22px;height:22px;'
                'border-radius:5px;border:1px {} rgba(0,0,0,.45);'
                'background:{};"></span>{}</label>'
            ), (
                (
                    f'{base_id}_{indice}', name, codigo, f'{base_id}_{indice}',
                    ' checked' if codigo == valor else '',
                    'solid' if codigo else 'dashed',
                    HEX.get(codigo) or self.automatico_hex or '#d9d9d9',
                    etiqueta,
                )
                for indice, (codigo, etiqueta) in enumerate(self.choices)
            )),
        )


class UsuarioColorForm(UserChangeForm):
    color_registro = forms.ChoiceField(
        label='Color en el Registro Estudiantil', required=False,
        widget=SelectorColorRegistro,
        help_text=(
            'Color de las filas que registra este usuario en el Registro '
            'Estudiantil. También lo ve en su perfil.'
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .colores_registro import (
            HEX, NOMBRES, codigo_automatico_usuario,
        )
        from .models import COLORES_REGISTRO

        usuario = self.instance
        automatico = codigo_automatico_usuario(usuario) if usuario.pk else ''
        etiqueta = 'Automático (lo elige el sistema)'
        if automatico:
            etiqueta = f'Automático (ahora: {NOMBRES[automatico]})'
        campo = self.fields['color_registro']
        campo.choices = [('', etiqueta)] + [
            (codigo, nombre) for codigo, nombre, _hex in COLORES_REGISTRO
        ]
        campo.widget.automatico_hex = HEX.get(automatico, '')
        if usuario.pk:
            self.initial['color_registro'] = (
                PerfilUsuario.objects.filter(user_id=usuario.pk)
                .values_list('color_registro', flat=True).first()
            ) or ''


try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


@admin.register(User)
class UsuarioAdmin(UserAdmin):
    """Usuarios de Django con el color del Registro Estudiantil."""

    form = UsuarioColorForm
    fieldsets = (
        UserAdmin.fieldsets[:2]
        + (('Registro Estudiantil', {'fields': ('color_registro',)}),)
        + UserAdmin.fieldsets[2:]
    )
    list_display = UserAdmin.list_display + ('color_en_registro',)
    list_select_related = ('perfil_visual',)

    @admin.display(description='Color en el registro')
    def color_en_registro(self, obj):
        from .colores_registro import HEX, NOMBRES

        perfil = getattr(obj, 'perfil_visual', None)
        codigo = perfil.color_registro if perfil else ''
        if codigo not in HEX:
            return 'Automático'
        return format_html(
            '<span style="display:inline-block;width:14px;height:14px;'
            'margin-right:6px;vertical-align:middle;border-radius:3px;'
            'border:1px solid rgba(0,0,0,.45);background:{};"></span>{}',
            HEX[codigo], NOMBRES[codigo],
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if 'color_registro' in form.changed_data:
            PerfilUsuario.objects.update_or_create(
                user=obj,
                defaults={'color_registro': form.cleaned_data['color_registro']},
            )


@admin.register(PerfilUsuario)
class PerfilUsuarioAdmin(admin.ModelAdmin):
    list_display = ('user', 'avatar', 'portada', 'color_registro', 'actualizado')
    list_filter = ('avatar', 'portada', 'color_registro')
    search_fields = (
        'user__username', 'user__first_name', 'user__last_name',
        'descripcion_personal',
    )


@admin.register(AmistadUsuario)
class AmistadUsuarioAdmin(admin.ModelAdmin):
    list_display = (
        'usuario_a', 'usuario_b', 'solicitada_por', 'estado', 'actualizada',
    )
    list_filter = ('estado', 'actualizada')
    search_fields = (
        'usuario_a__username', 'usuario_a__first_name',
        'usuario_b__username', 'usuario_b__first_name',
    )
    readonly_fields = ('creada', 'actualizada')


@admin.register(MeGustaPerfil)
class MeGustaPerfilAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'perfil', 'creado')
    search_fields = (
        'usuario__username', 'usuario__first_name',
        'perfil__username', 'perfil__first_name',
    )
    readonly_fields = ('creado',)


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'orden', 'color', 'activo', 'cantidad_cursos')
    list_editable = ('orden', 'activo')
    search_fields = ('nombre',)

    def cantidad_cursos(self, obj):
        return obj.cursos.count()
    cantidad_cursos.short_description = '# cursos'


class JornadaCursoInline(admin.TabularInline):
    model = JornadaCurso
    extra = 1
    fields = ('modalidad', 'descripcion', 'descripcion_otros', 'fecha_inicio', 'hora_inicio', 'hora_fin', 'sede', 'activo')


@admin.register(Curso)
class CursoAdmin(admin.ModelAdmin):
    list_display = (
        'nombre', 'categoria',
        'ofrece_presencial', 'valor_presencial', 'valor_anterior_presencial',
        'ofrece_online', 'valor_online', 'valor_anterior_online',
        'duracion', 'activo',
    )
    list_filter = ('categoria', 'activo', 'ofrece_presencial', 'ofrece_online')
    search_fields = ('nombre',)
    autocomplete_fields = ('categoria',)
    inlines = [JornadaCursoInline]
    fieldsets = (
        (None, {
            'fields': ('categoria', 'nombre', 'descripcion', 'duracion', 'activo'),
        }),
        ('Modalidad presencial', {
            'fields': ('ofrece_presencial', 'valor_presencial', 'valor_anterior_presencial'),
        }),
        ('Modalidad online', {
            'fields': ('ofrece_online', 'valor_online', 'valor_anterior_online', 'pago_unico_online'),
        }),
        ('Calendario de pagos', {
            'fields': ('pagos_cada_dos_semanas',),
        }),
        ('Legado (no usar)', {
            'classes': ('collapse',),
            'fields': ('valor',),
            'description': 'Campo antiguo conservado por compatibilidad. Usa los valores por modalidad.',
        }),
    )


@admin.register(JornadaCurso)
class JornadaCursoAdmin(admin.ModelAdmin):
    list_display = (
        'curso', 'modalidad', 'descripcion', 'descripcion_otros', 'fecha_inicio',
        'hora_inicio', 'hora_fin', 'sede', 'ciudad', 'activo',
        'feriado_aplicado_en',
    )
    list_filter = ('modalidad', 'activo', 'sede', 'ciudad', 'curso')
    search_fields = ('curso__nombre', 'descripcion', 'descripcion_otros', 'ciudad')
    readonly_fields = ('feriado_aplicado_en',)


@admin.register(Estudiante)
class EstudianteAdmin(admin.ModelAdmin):
    list_display = (
        'cedula', 'nombres', 'edad',
        'correo', 'celular', 'ciudad', 'nivel_formacion',
    )
    search_fields = ('cedula', 'nombres', 'correo')
    list_filter = ('nivel_formacion', 'ciudad')


@admin.register(Matricula)
class MatriculaAdmin(admin.ModelAdmin):
    list_display = (
        'fecha_matricula', 'estudiante', 'curso', 'jornada',
        'modalidad', 'valor_curso', 'valor_pagado', 'estado_pago',
        'registrado_por',
    )
    list_filter = ('modalidad', 'curso', 'fecha_matricula', 'talla_camiseta', 'registrado_por')
    search_fields = (
        'estudiante__cedula',
        'estudiante__nombres', 'curso__nombre',
    )
    autocomplete_fields = ('estudiante', 'curso', 'jornada')
    readonly_fields = ('registrado_por', 'creado', 'actualizado')
    actions = ['aplicar_precio_actual']

    @admin.action(
        permissions=['change'],
        description='Aplicar el precio actual del curso',
    )
    def aplicar_precio_actual(self, request, queryset):
        """Baja las matrículas seleccionadas al precio que hoy tiene su curso,
        mostrando primero una página de confirmación."""
        matriculas = queryset.select_related(
            'curso', 'estudiante', 'jornada',
        ).order_by('curso__nombre', 'pk')
        cambios, sin_cambio = _plan_precio_actual(matriculas)

        if request.POST.get('confirmar') and cambios:
            with transaction.atomic():
                for cambio in cambios:
                    m = cambio['matricula']
                    # save() de Matricula también sincroniza su Comprobante.
                    m.save(update_fields=['valor_curso', 'actualizado'])
                    self.log_change(
                        request, m,
                        f'Valor del curso: {_dinero(cambio["valor_anterior"])} → '
                        f'{_dinero(m.valor_curso)} (precio actual del curso).',
                    )
            mensaje = (
                f'Se actualizaron {len(cambios)} matrícula(s) al precio actual '
                'del curso.'
            )
            if sin_cambio:
                # Algo cambió entre la confirmación y el guardado (p. ej. un pago).
                mensaje += (
                    f' {len(sin_cambio)} ya no cumplían las condiciones y '
                    'quedaron igual.'
                )
            self.message_user(request, mensaje, messages.SUCCESS)
            return None

        return TemplateResponse(
            request,
            'admin/academia/matricula/aplicar_precio_actual.html',
            {
                **self.admin_site.each_context(request),
                'title': 'Aplicar el precio actual del curso',
                'opts': self.model._meta,
                'cambios': cambios,
                'sin_cambio': sin_cambio,
                'action_checkbox_name': helpers.ACTION_CHECKBOX_NAME,
                'media': self.media,
            },
        )


def _plan_precio_actual(matriculas):
    """Separa las matrículas que bajan al precio actual de su curso de las
    que se dejan igual (con el motivo). Solo baja valores, nunca los sube."""
    cambios, sin_cambio = [], []
    for m in matriculas:
        # En «Inscripción (gratis)» el valor guardado ya descuenta los $10.
        ajuste = (
            MONTO_RESERVA_MATRICULA if m.es_inscripcion_gratis
            else Decimal('0.00')
        )
        nuevo = m.curso.valor_para(m.modalidad) - ajuste
        if m.estado == 'retiro_voluntario':
            motivo = 'Retiro voluntario'
        elif m.es_sin_costo:
            motivo = 'Tipo «Otros» (sin costo)'
        elif nuevo <= 0:
            motivo = (
                f'El curso no tiene precio en '
                f'{m.get_modalidad_display().lower()}'
            )
        elif m.valor_curso == nuevo:
            motivo = 'Ya tiene el precio actual'
        elif m.valor_curso < nuevo:
            motivo = f'Su valor es menor al precio actual ({_dinero(nuevo)}); no se sube'
        elif m.descuento:
            motivo = f'Tiene un descuento de {_dinero(m.descuento)}: revísala a mano'
        elif m.valor_pagado > nuevo:
            motivo = f'Ya pagó {_dinero(m.valor_pagado)}, más que el nuevo valor'
        else:
            motivo = ''

        if motivo:
            sin_cambio.append({'matricula': m, 'motivo': motivo})
            continue
        valor_anterior, saldo_anterior = m.valor_curso, m.saldo
        m.valor_curso = nuevo
        cambios.append({
            'matricula': m,
            'valor_anterior': valor_anterior,
            'saldo_anterior': saldo_anterior,
            'modulos': m.cuotas_modulos_objetivo(),
        })
    return cambios, sin_cambio


@admin.register(Comprobante)
class ComprobanteAdmin(admin.ModelAdmin):
    list_display = (
        'fecha_inscripcion', 'nombre_persona', 'curso',
        'modalidad', 'tipo_registro', 'pago_abono', 'diferencia',
        'vendedora_nombre', 'factura_realizada',
    )
    list_filter = ('modalidad', 'tipo_registro', 'factura_realizada', 'curso', 'vendedora')
    search_fields = (
        'nombre_persona', 'celular',
        'fact_nombres', 'fact_cedula', 'fact_correo',
        'curso__nombre',
    )
    autocomplete_fields = ('curso',)
    readonly_fields = ('vendedora_nombre', 'creado', 'actualizado')
    fieldsets = (
        ('Datos del curso', {
            'fields': ('curso', 'modalidad', 'jornada', 'inicio_curso',
                       'fecha_inscripcion'),
        }),
        ('Datos del cliente', {
            'fields': ('nombre_persona', 'celular'),
        }),
        ('Pago y Registro', {
            'fields': ('tipo_registro', 'pago_abono', 'diferencia'),
        }),
        ('Vendedora', {
            'fields': ('vendedora', 'vendedora_nombre'),
        }),
        ('Factura', {
            'fields': ('factura_realizada', 'fact_nombres',
                       'fact_cedula', 'fact_correo'),
        }),
        ('Auditoría', {
            'classes': ('collapse',),
            'fields': ('creado', 'actualizado'),
        }),
    )


@admin.register(PersonaExterna)
class PersonaExternaAdmin(admin.ModelAdmin):
    list_display = ('cedula', 'nombres', 'celular', 'correo', 'ciudad', 'creado')
    search_fields = ('cedula', 'nombres', 'correo', 'celular')
    list_filter = ('ciudad',)
    readonly_fields = ('creado', 'actualizado')


@admin.register(Adicional)
class AdicionalAdmin(admin.ModelAdmin):
    list_display = (
        'fecha', 'tipo_adicional', 'persona_nombre_admin',
        'curso', 'modalidad', 'valor', 'metodo_pago', 'registrado_por',
    )
    list_filter = ('tipo_adicional', 'modalidad', 'metodo_pago', 'fecha', 'registrado_por')
    search_fields = (
        'estudiante__cedula', 'estudiante__nombres',
        'persona_externa__cedula', 'persona_externa__nombres',
        'curso__nombre', 'observaciones',
    )
    autocomplete_fields = ('estudiante', 'persona_externa', 'curso', 'matricula_origen')
    readonly_fields = ('creado', 'actualizado', 'registrado_por')
    fieldsets = (
        ('Tipo', {
            'fields': ('tipo_adicional',),
        }),
        ('Persona', {
            'fields': ('estudiante', 'persona_externa'),
            'description': 'Llenar UNO de los dos: estudiante (interno) o persona_externa.',
        }),
        ('Curso (para certificados / examen supletorio)', {
            'fields': ('curso', 'modalidad'),
        }),
        ('Camisa', {
            'fields': ('talla_camiseta',),
        }),
        ('Examen Supletorio', {
            'fields': ('matricula_origen', 'numero_modulo'),
        }),
        ('Cobro', {
            'fields': ('fecha', 'valor', 'metodo_pago', 'observaciones'),
        }),
        ('Auditoría', {
            'classes': ('collapse',),
            'fields': ('registrado_por', 'creado', 'actualizado'),
        }),
    )

    def persona_nombre_admin(self, obj):
        return obj.persona_nombre
    persona_nombre_admin.short_description = 'Persona'


@admin.register(RecuperacionPendiente)
class RecuperacionPendienteAdmin(admin.ModelAdmin):
    list_display = (
        'matricula', 'numero_modulo', 'fecha_marcada', 'fecha_programada',
        'saldo_pendiente_al_marcar', 'pagada', 'fecha_recuperacion',
        'creado',
    )
    list_filter = (
        'pagada', 'numero_modulo', 'fecha_marcada', 'fecha_programada',
    )
    search_fields = (
        'matricula__estudiante__cedula',

        'matricula__estudiante__nombres',
        'matricula__curso__nombre',
    )
    autocomplete_fields = ('matricula',)
    readonly_fields = ('creado', 'actualizado')
    date_hierarchy = 'fecha_marcada'
    fieldsets = (
        ('Datos de la clase a recuperar', {
            'fields': ('matricula', 'numero_modulo', 'fecha_marcada',
                       'fecha_programada', 'saldo_pendiente_al_marcar'),
        }),
        ('Estado del cobro', {
            'fields': ('pagada', 'fecha_recuperacion', 'abono'),
        }),
        ('Notas', {
            'fields': ('observaciones',),
        }),
        ('Auditoría', {
            'classes': ('collapse',),
            'fields': ('creado', 'actualizado'),
        }),
    )


@admin.register(AssistantQueryLog)
class AssistantQueryLogAdmin(admin.ModelAdmin):
    list_display = ('created', 'user', 'path', 'message_short')
    search_fields = ('message', 'reply', 'path', 'user__username')
    readonly_fields = ('user', 'path', 'message', 'reply', 'metadata', 'created')

    def message_short(self, obj):
        return (obj.message[:80] + '...') if len(obj.message) > 80 else obj.message
    message_short.short_description = 'Mensaje'

# ─────────────────────────────────────────────────────────
# Cierre de Curso (historial archivado)
# ─────────────────────────────────────────────────────────

class AbonoArchivadoInline(admin.TabularInline):
    model = AbonoArchivado
    extra = 0
    can_delete = False
    fields = ('fecha', 'numero_recibo', 'monto', 'tipo_pago_label',
              'metodo_label', 'banco_label', 'numero_modulo', 'cuenta_para_saldo')
    readonly_fields = fields
    verbose_name_plural = 'Abonos archivados (snapshot)'


@admin.register(CierreCurso)
class CierreCursoAdmin(admin.ModelAdmin):
    list_display = (
        'fecha_cierre', 'curso_nombre', 'jornada_descripcion',
        'alcance', 'total_matriculas', 'total_facturado',
        'total_cobrado', 'cerrado_por',
    )
    list_filter = ('alcance', 'jornada_modalidad', 'fecha_cierre', 'cerrado_por')
    search_fields = ('curso_nombre', 'jornada_descripcion', 'ciclo_etiqueta', 'jornada_sede')
    readonly_fields = (
        'fecha_cierre', 'cerrado_por',
        'total_matriculas', 'total_facturado', 'total_cobrado', 'total_pendiente',
        'conteo_pagado', 'conteo_parcial', 'conteo_pendiente', 'conteo_retiro',
    )
    fieldsets = (
        ('Identidad', {
            'fields': ('curso', 'curso_nombre', 'curso_categoria',
                       'jornada', 'jornada_descripcion', 'jornada_modalidad',
                       'jornada_fecha_inicio', 'jornada_sede', 'alcance',
                       'ciclo_etiqueta', 'observaciones'),
        }),
        ('Totales (congelados)', {
            'fields': ('total_matriculas', 'total_facturado', 'total_cobrado', 'total_pendiente',
                       'conteo_pagado', 'conteo_parcial', 'conteo_pendiente', 'conteo_retiro'),
        }),
        ('Auditoría', {
            'fields': ('fecha_cierre', 'cerrado_por'),
        }),
    )


@admin.register(MatriculaArchivada)
class MatriculaArchivadaAdmin(admin.ModelAdmin):
    list_display = (
        'cedula', 'nombres', 'curso_nombre',
        'jornada_descripcion', 'modalidad', 'valor_neto',
        'valor_pagado', 'estado_pago', 'cierre',
    )
    list_filter = ('estado_pago', 'modalidad', 'cierre__curso_nombre')
    search_fields = ('cedula', 'nombres', 'correo', 'celular',
                     'curso_nombre', 'jornada_descripcion')
    readonly_fields = [f.name for f in MatriculaArchivada._meta.fields]
    inlines = [AbonoArchivadoInline]
    list_select_related = ('cierre',)


@admin.register(AbonoArchivado)
class AbonoArchivadoAdmin(admin.ModelAdmin):
    list_display = (
        'fecha', 'numero_recibo', 'monto', 'tipo_pago_label',
        'metodo_label', 'matricula_archivada', 'cierre',
    )
    list_filter = ('tipo_pago', 'metodo', 'fecha')
    search_fields = (
        'numero_recibo',
        'matricula_archivada__cedula',

        'matricula_archivada__curso_nombre',
    )
    readonly_fields = [f.name for f in AbonoArchivado._meta.fields]
    list_select_related = ('matricula_archivada', 'cierre')


@admin.register(EstudianteArchivado)
class EstudianteArchivadoAdmin(admin.ModelAdmin):
    list_display = (
        'cedula', 'nombres', 'correo', 'celular',
        'ciudad', 'archivado_en', 'cierre',
    )
    list_filter = ('archivado_en', 'ciudad')
    search_fields = ('cedula', 'nombres', 'correo', 'celular')
    readonly_fields = [f.name for f in EstudianteArchivado._meta.fields]
    list_select_related = ('cierre',)


@admin.register(AdicionalArchivado)
class AdicionalArchivadoAdmin(admin.ModelAdmin):
    list_display = (
        'fecha', 'tipo_adicional_label', 'persona_nombre', 'curso_nombre',
        'modalidad', 'valor', 'metodo_pago_label', 'archivado_en', 'cierre',
    )
    list_filter = ('tipo_adicional', 'modalidad', 'archivado_en')
    search_fields = ('persona_cedula', 'persona_nombre', 'persona_celular', 'curso_nombre', 'numero_recibo')
    readonly_fields = [f.name for f in AdicionalArchivado._meta.fields]
    list_select_related = ('cierre',)



@admin.register(CierreAdministrativo)
class CierreAdministrativoAdmin(admin.ModelAdmin):
    list_display = (
        'encabezado', 'anio', 'mes', 'ingreso_total', 'egreso_total',
        'balance_neto', 'fecha_cierre', 'cerrado_por',
    )
    list_filter = ('anio', 'mes', 'fecha_cierre')
    search_fields = ('etiqueta', 'observaciones')
    readonly_fields = ('fecha_cierre', 'cerrado_por')
