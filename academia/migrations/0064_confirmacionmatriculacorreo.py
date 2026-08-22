import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('academia', '0063_recordatoriopagocorreo'),
    ]

    operations = [
        migrations.CreateModel(
            name='ConfirmacionMatriculaCorreo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('destinatario', models.EmailField(max_length=254)),
                ('formulario_url', models.URLField(blank=True, max_length=500)),
                ('estado', models.CharField(choices=[('procesando', 'Procesando'), ('enviado', 'Enviado'), ('fallido', 'Fallido')], default='procesando', max_length=15)),
                ('intentos', models.PositiveIntegerField(default=1)),
                ('ultimo_error', models.TextField(blank=True)),
                ('enviado_en', models.DateTimeField(blank=True, null=True)),
                ('creado', models.DateTimeField(auto_now_add=True)),
                ('actualizado', models.DateTimeField(auto_now=True)),
                ('matricula', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='confirmacion_matricula_correo', to='academia.matricula')),
            ],
            options={
                'verbose_name': 'Confirmación de matrícula por correo',
                'verbose_name_plural': 'Confirmaciones de matrícula por correo',
                'ordering': ['-creado'],
            },
        ),
    ]
