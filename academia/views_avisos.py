"""
Gestión de Avisos / Anuncios del panel principal.

Solo el administrador puede crear, editar o eliminar avisos. Los avisos
vigentes (dentro de su rango de fechas y activos) se muestran en la pantalla
de Bienvenida para TODOS los usuarios.

Al pasar la fecha final, el aviso se considera expirado y deja de mostrarse
automáticamente (no hace falta borrarlo): basta con que la fecha actual supere
fecha_fin. El admin puede crear otro cuando quiera.
"""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import AvisoForm
from .models import Aviso
from .permisos import admin_requerido


@admin_requerido
def avisos_lista(request):
    """Lista todos los avisos (vigentes, programados, expirados, ocultos)."""
    avisos = Aviso.objects.all().select_related('creado_por')

    vigentes = [a for a in avisos if a.vigente]
    programados = [a for a in avisos if a.por_iniciar and a.activo]
    expirados = [a for a in avisos if a.expirado]
    ocultos = [a for a in avisos if not a.activo and not a.expirado and not a.por_iniciar]

    return render(request, 'avisos/lista.html', {
        'avisos': avisos,
        'vigentes': vigentes,
        'programados': programados,
        'expirados': expirados,
        'ocultos': ocultos,
        'total': avisos.count(),
        'total_vigentes': len(vigentes),
    })


@admin_requerido
def aviso_crear(request):
    """Crea un nuevo aviso."""
    if request.method == 'POST':
        form = AvisoForm(request.POST)
        if form.is_valid():
            aviso = form.save(commit=False)
            aviso.creado_por = request.user
            aviso.save()
            messages.success(request, f'Aviso «{aviso.titulo}» publicado.')
            return redirect('academia:avisos_lista')
    else:
        from django.utils import timezone
        ahora = timezone.localtime()
        # Por defecto: vigente desde ahora hasta dentro de 7 días.
        fin = ahora + timezone.timedelta(days=7)
        form = AvisoForm(initial={
            'tema': 'info',
            'activo': True,
            'fecha_inicio': ahora.strftime('%Y-%m-%dT%H:%M'),
            'fecha_fin': fin.strftime('%Y-%m-%dT%H:%M'),
        })

    return render(request, 'avisos/form.html', {
        'form': form,
        'modo': 'crear',
        'titulo': 'Nuevo aviso',
    })


@admin_requerido
def aviso_editar(request, pk):
    """Edita un aviso existente."""
    aviso = get_object_or_404(Aviso, pk=pk)
    if request.method == 'POST':
        form = AvisoForm(request.POST, instance=aviso)
        if form.is_valid():
            form.save()
            messages.success(request, f'Aviso «{aviso.titulo}» actualizado.')
            return redirect('academia:avisos_lista')
    else:
        form = AvisoForm(instance=aviso)

    return render(request, 'avisos/form.html', {
        'form': form,
        'aviso': aviso,
        'modo': 'editar',
        'titulo': f'Editar aviso: {aviso.titulo}',
    })


@admin_requerido
@require_POST
def aviso_toggle(request, pk):
    """Activa o desactiva (oculta) un aviso sin borrarlo."""
    aviso = get_object_or_404(Aviso, pk=pk)
    aviso.activo = not aviso.activo
    aviso.save(update_fields=['activo'])
    estado = 'mostrado' if aviso.activo else 'ocultado'
    messages.success(request, f'Aviso «{aviso.titulo}» {estado}.')
    return redirect('academia:avisos_lista')


@admin_requerido
@require_POST
def aviso_eliminar(request, pk):
    """Elimina un aviso de forma permanente."""
    aviso = get_object_or_404(Aviso, pk=pk)
    titulo = aviso.titulo
    aviso.delete()
    messages.success(request, f'Aviso «{titulo}» eliminado.')
    return redirect('academia:avisos_lista')
