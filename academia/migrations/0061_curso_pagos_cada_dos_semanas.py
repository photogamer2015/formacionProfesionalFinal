from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('academia', '0060_perfiles_sociales'),
    ]

    operations = [
        migrations.AddField(
            model_name='curso',
            name='pagos_cada_dos_semanas',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'Programa cada pago posterior al primero 14 días después '
                    'del anterior, tomando como base la fecha de inicio de la '
                    'jornada.'
                ),
            ),
        ),
    ]
