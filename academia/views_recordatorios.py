"""
Gestión de Recordatorios / Borradores (notas internas del equipo).

Cualquier usuario con rol (asesor o administrador) puede crear notas tipo
recordatorio, asignarlas a otro usuario para notificarle, y consultar tanto
las que recibió como las que envió.

Permisos:
- Crear: cualquier asesor o admin.
- Editar / Eliminar: quien lo creó, el destinatario, o un administrador.
- La campana del encabezado muestra los recordatorios no leídos dirigidos
  al usuario actual (ver context_processors.recordatorios).
"""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import RecordatorioForm
from .models import Recordatorio
from .permisos import matricula_requerida, es_admin


def _puede_gestionar(user, recordatorio):
    """¿Este usuario puede editar/eliminar este recordatorio?"""
    return (
        es_admin(user)
        or recordatorio.creado_por_id == user.id
        or recordatorio.destinatario_id == user.id
    )


@matricula_requerida
def recordatorio_lista(request):
    """
    Lista los recordatorios relacionados con el usuario actual:
    los que recibió (notificaciones) y los que él mismo creó.
    El administrador ve además todos los del sistema.
    """
    from django.utils import timezone
    # Borrado automático de recordatorios que ya vencieron (por seguridad y limpieza)
    Recordatorio.objects.filter(fecha_vencimiento__lt=timezone.localdate()).delete()

    recibidos = (
        Recordatorio.objects
        .filter(destinatario=request.user)
        .select_related('creado_por', 'destinatario')
    )
    enviados = (
        Recordatorio.objects
        .filter(creado_por=request.user)
        .exclude(destinatario=request.user)
        .select_related('creado_por', 'destinatario')
    )

    todos = None
    if es_admin(request.user):
        todos = (
            Recordatorio.objects
            .exclude(creado_por=request.user)
            .exclude(destinatario=request.user)
            .select_related('creado_por', 'destinatario')
        )

    no_leidos = sum(1 for r in recibidos if not r.leido and not r.vencido)

    return render(request, 'recordatorios/lista.html', {
        'recibidos': recibidos,
        'enviados': enviados,
        'todos': todos,
        'no_leidos': no_leidos,
    })


@matricula_requerida
def recordatorio_crear(request):
    """Crea un nuevo recordatorio."""
    if request.method == 'POST':
        form = RecordatorioForm(request.POST)
        if form.is_valid():
            rec = form.save(commit=False)
            rec.creado_por = request.user
            # Si el usuario se lo asigna a sí mismo, queda como leído de una vez
            # (no tiene sentido auto-notificarse con campana).
            if rec.destinatario_id == request.user.id:
                rec.leido = True
            rec.save()
            messages.success(request, f'Recordatorio «{rec.titulo}» guardado.')
            return redirect('academia:recordatorio_lista')
    else:
        from django.utils import timezone
        hoy = timezone.localdate()
        fin = hoy + timezone.timedelta(days=3)
        form = RecordatorioForm(initial={
            'prioridad': 'media',
            'destinatario': request.user.id,
            'fecha': hoy.strftime('%Y-%m-%d'),
            'fecha_vencimiento': fin.strftime('%Y-%m-%d'),
        })

    return render(request, 'recordatorios/form.html', {
        'form': form,
        'modo': 'crear',
        'titulo': 'Nuevo recordatorio',
    })


@matricula_requerida
def recordatorio_editar(request, pk):
    """Edita un recordatorio existente (creador, destinatario o admin)."""
    rec = get_object_or_404(Recordatorio, pk=pk)

    if not (es_admin(request.user) or rec.creado_por_id == request.user.id):
        messages.error(
            request,
            'Solo el creador o un administrador pueden editar este recordatorio.'
        )
        return redirect('academia:recordatorio_lista')

    if request.method == 'POST':
        form = RecordatorioForm(request.POST, instance=rec)
        if form.is_valid():
            form.save()
            messages.success(request, f'Recordatorio «{rec.titulo}» actualizado.')
            return redirect('academia:recordatorio_lista')
    else:
        form = RecordatorioForm(instance=rec)

    return render(request, 'recordatorios/form.html', {
        'form': form,
        'recordatorio': rec,
        'modo': 'editar',
        'titulo': f'Editar recordatorio: {rec.titulo}',
    })


@matricula_requerida
@require_POST
def recordatorio_marcar_leido(request, pk):
    """El destinatario (o admin) marca el recordatorio como leído/enterado."""
    rec = get_object_or_404(Recordatorio, pk=pk)

    if not (es_admin(request.user) or rec.destinatario_id == request.user.id):
        messages.error(request, 'Solo el destinatario puede marcarlo como leído.')
        return redirect('academia:recordatorio_lista')

    rec.leido = True
    rec.save(update_fields=['leido', 'actualizado'])
    messages.success(request, f'Recordatorio «{rec.titulo}» marcado como leído.')
    # Permite volver de donde venía (campana o lista)
    destino = request.POST.get('next') or 'academia:recordatorio_lista'
    if destino.startswith('academia:'):
        return redirect(destino)
    return redirect('academia:recordatorio_lista')


@matricula_requerida
@require_POST
def recordatorio_eliminar(request, pk):
    """Elimina un recordatorio (creador, destinatario o admin)."""
    rec = get_object_or_404(Recordatorio, pk=pk)

    if not _puede_gestionar(request.user, rec):
        messages.error(
            request,
            'Solo puedes eliminar recordatorios que tú creaste o que te fueron asignados.'
        )
        return redirect('academia:recordatorio_lista')

    titulo = rec.titulo
    rec.delete()
    messages.success(request, f'Recordatorio «{titulo}» eliminado.')
    return redirect('academia:recordatorio_lista')
