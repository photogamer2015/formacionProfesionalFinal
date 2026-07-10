from django.db import migrations


def backfill_estudiantes_cierre_manual(apps, schema_editor):
    CierreCurso = apps.get_model('academia', 'CierreCurso')
    MatriculaArchivada = apps.get_model('academia', 'MatriculaArchivada')
    EstudianteArchivado = apps.get_model('academia', 'EstudianteArchivado')

    for cierre in CierreCurso.objects.filter(alcance='manual'):
        creados = 0
        matriculas = MatriculaArchivada.objects.filter(cierre=cierre)

        for matricula in matriculas:
            estudiante_original_id = matricula.estudiante_id
            if estudiante_original_id:
                existe = EstudianteArchivado.objects.filter(
                    cierre=cierre,
                    estudiante_original_id=estudiante_original_id,
                ).exists()
            else:
                existe = EstudianteArchivado.objects.filter(
                    cierre=cierre,
                    cedula=matricula.cedula,
                    nombres=matricula.nombres,
                ).exists()
            if existe:
                continue

            edad = None
            edad_texto = str(matricula.edad or '').strip()
            if edad_texto.isdigit():
                edad = int(edad_texto)

            archivado = EstudianteArchivado.objects.create(
                cierre=cierre,
                estudiante_original_id=estudiante_original_id,
                cedula=matricula.cedula or '',
                nombres=matricula.nombres or '',
                edad=edad,
                correo=matricula.correo or '',
                celular=matricula.celular or '',
                nivel_formacion=matricula.nivel_formacion or '',
                titulo_profesional='',
                ciudad=matricula.ciudad_estudiante or '',
                vendedora_nombre=matricula.vendedora_nombre or '',
                registrado_por_nombre=matricula.registrado_por_nombre or '',
                creado_original=matricula.creado_original,
            )
            EstudianteArchivado.objects.filter(pk=archivado.pk).update(
                archivado_en=matricula.archivado_en
            )
            creados += 1

        if creados:
            total = EstudianteArchivado.objects.filter(cierre=cierre).count()
            CierreCurso.objects.filter(pk=cierre.pk).update(
                total_estudiantes_archivados=total
            )


class Migration(migrations.Migration):

    dependencies = [
        ('academia', '0048_alter_cierrecurso_alcance'),
    ]

    operations = [
        migrations.RunPython(backfill_estudiantes_cierre_manual, migrations.RunPython.noop),
    ]
