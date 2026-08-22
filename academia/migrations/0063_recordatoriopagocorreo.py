import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('academia', '0062_activar_pagos_dos_semanas_asistente_contable'),
    ]

    operations = [
        migrations.CreateModel(
            name='RecordatorioPagoCorreo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('numero_modulo', models.PositiveIntegerField(help_text='Número de la obligación o módulo recordado.')),
                ('fecha_alerta', models.DateField(help_text='Fecha en la que correspondía enviar el recordatorio.')),
                ('fecha_pago', models.DateField(help_text='Fecha informada al estudiante para realizar el pago.')),
                ('destinatario', models.EmailField(max_length=254)),
                ('monto', models.DecimalField(decimal_places=2, max_digits=10)),
                ('estado', models.CharField(choices=[('procesando', 'Procesando'), ('enviado', 'Enviado'), ('fallido', 'Fallido')], default='procesando', max_length=15)),
                ('intentos', models.PositiveIntegerField(default=1)),
                ('ultimo_error', models.TextField(blank=True)),
                ('enviado_en', models.DateTimeField(blank=True, null=True)),
                ('creado', models.DateTimeField(auto_now_add=True)),
                ('actualizado', models.DateTimeField(auto_now=True)),
                ('matricula', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='recordatorios_pago_correo', to='academia.matricula')),
            ],
            options={
                'verbose_name': 'Recordatorio de pago por correo',
                'verbose_name_plural': 'Recordatorios de pago por correo',
                'ordering': ['-fecha_alerta', '-creado'],
            },
        ),
        migrations.AddConstraint(
            model_name='recordatoriopagocorreo',
            constraint=models.UniqueConstraint(fields=('matricula', 'numero_modulo', 'fecha_alerta'), name='recordatorio_pago_correo_unico'),
        ),
    ]
