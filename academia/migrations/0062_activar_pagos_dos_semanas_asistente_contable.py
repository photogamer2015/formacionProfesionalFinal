from django.db import migrations


NOMBRE_CURSO = 'Asistente Contable'


def activar_calendario_dos_semanas(apps, schema_editor):
    Curso = apps.get_model('academia', 'Curso')
    Curso.objects.filter(nombre__iexact=NOMBRE_CURSO).update(
        pagos_cada_dos_semanas=True,
    )


def desactivar_calendario_dos_semanas(apps, schema_editor):
    Curso = apps.get_model('academia', 'Curso')
    Curso.objects.filter(nombre__iexact=NOMBRE_CURSO).update(
        pagos_cada_dos_semanas=False,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('academia', '0061_curso_pagos_cada_dos_semanas'),
    ]

    operations = [
        migrations.RunPython(
            activar_calendario_dos_semanas,
            desactivar_calendario_dos_semanas,
        ),
    ]
