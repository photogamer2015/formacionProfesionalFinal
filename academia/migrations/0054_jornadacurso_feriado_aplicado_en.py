from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('academia', '0053_curso_pago_unico_online'),
    ]

    operations = [
        migrations.AddField(
            model_name='jornadacurso',
            name='feriado_aplicado_en',
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text=(
                    'Última vez que la jornada fue trasladada por día no laboral. '
                    'Controla el bloqueo de 24 horas para evitar movimientos duplicados.'
                ),
                null=True,
            ),
        ),
    ]
