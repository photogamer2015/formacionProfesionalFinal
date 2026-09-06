from datetime import date, timedelta
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .forms import EstudianteForm
from .models import Matricula, JornadaCurso, CambioJornada, Comprobante
from .permisos import matricula_requerida


def editar_datos_estudiante(request, matricula):
    form = EstudianteForm(request.POST if request.method == 'POST' else None,
                          prefix='est', instance=matricula.estudiante)
    # Documentos antiguos se conservan aunque no cumplan la longitud actual.
    if request.method == 'POST' and request.POST.get('est-cedula', '').strip() == matricula.estudiante.cedula:
        form.fields['cedula'].disabled = True
    if request.method == 'POST' and form.is_valid():
        estudiante = form.save()
        Comprobante.objects.filter(matricula__estudiante=estudiante).update(
            nombre_persona=estudiante.nombres.strip(), celular=estudiante.celular,
        )
        messages.success(request, 'Datos del estudiante actualizados. La jornada y los pagos se conservaron.')
        return redirect('academia:matricula_lista', modalidad=matricula.modalidad)
    return render(request, 'matricula/editar_estudiante.html', {'form': form, 'matricula': matricula})


class CambioJornadaForm(forms.Form):
    jornada = forms.ModelChoiceField(queryset=JornadaCurso.objects.none(), label='Nueva jornada', widget=forms.Select(attrs={'class':'form-input'}))
    jornada_original = forms.CharField(required=False, widget=forms.HiddenInput)
    motivo = forms.CharField(max_length=500, label='Motivo del cambio', widget=forms.Textarea(attrs={'class':'form-input','rows':3}))

    def __init__(self, *args, matricula, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['jornada'].queryset = JornadaCurso.objects.filter(curso_id=matricula.curso_id, modalidad=matricula.modalidad, activo=True).exclude(pk=matricula.jornada_id)
        self.fields['jornada_original'].initial = str(matricula.jornada_id or '')


@matricula_requerida
@require_http_methods(['GET','POST'])
@transaction.atomic
def cambiar_jornada(request, pk):
    matricula = get_object_or_404(Matricula.objects.select_for_update(), pk=pk)
    form = CambioJornadaForm(request.POST if request.method == 'POST' else None, matricula=matricula)
    if request.method == 'POST' and form.is_valid():
        if form.cleaned_data['jornada_original'] != str(matricula.jornada_id or ''):
            form.add_error(None, 'La jornada cambió desde que abriste esta página. Vuelve a abrirla antes de continuar.')
        elif matricula.estado != 'activa':
            form.add_error(None, 'Solo se puede cambiar la jornada de una matrícula activa.')
        else:
            nueva = form.cleaned_data['jornada']
            anterior_id = matricula.jornada_id
            anterior = matricula.jornada.etiqueta if matricula.jornada_id else 'Sin jornada'
            # UPDATE limitado y condicional: ningún save() recalcula pagos o toca otros campos.
            actualizados = Matricula.objects.filter(pk=pk, jornada_id=anterior_id).update(jornada=nueva)
            if actualizados != 1:
                form.add_error(None, 'Otra persona modificó la jornada. Recarga la página.')
            else:
                # Mantener la ficha vinculada sincronizada sin tocar sus importes.
                Comprobante.objects.filter(matricula_id=pk).update(
                    jornada=nueva.descripcion_legible, inicio_curso=nueva.fecha_inicio,
                )
                CambioJornada.objects.create(matricula=matricula,
                    estudiante_nombre=matricula.estudiante.nombre_completo,
                    curso_nombre=matricula.curso.nombre, jornada_anterior=anterior,
                    jornada_nueva=nueva.etiqueta, motivo=form.cleaned_data['motivo'],
                    realizado_por=request.user, responsable_nombre=request.user.get_full_name() or request.user.username)
                messages.success(request, 'Jornada actualizada. Se conservaron los pagos y se registró el cambio en el historial.')
                return redirect('academia:cambios_jornada')
    return render(request, 'matricula/cambiar_jornada.html', {'form':form,'matricula':matricula})


@login_required
def historial(request):
    hoy = timezone.localdate()
    actual = hoy.replace(day=1)
    anterior = (actual-timedelta(days=1)).replace(day=1)
    try:
        mes = date.fromisoformat(request.GET.get('mes',actual.strftime('%Y-%m'))+'-01')
    except (ValueError, TypeError):
        mes = actual
    siguiente = (mes.replace(day=28)+timedelta(days=4)).replace(day=1)
    registros = CambioJornada.objects.filter(creado__date__gte=mes, creado__date__lt=siguiente)
    meses = list(CambioJornada.objects.dates('creado','month',order='DESC'))
    meses = sorted(set(meses+[actual,anterior,mes]), reverse=True)
    pagina = Paginator(registros,25).get_page(request.GET.get('page'))
    return render(request,'matricula/cambios_jornada.html', {'pagina':pagina,'mes':mes,'meses':meses,'actual':actual,'anterior':anterior,'total':registros.count()})
