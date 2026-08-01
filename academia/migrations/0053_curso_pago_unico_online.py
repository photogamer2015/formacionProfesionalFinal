from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('academia', '0052_perfilusuario'),
    ]

    operations = [
        migrations.AddField(
            model_name='curso',
            name='pago_unico_online',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'En ciclos cortos online, cobra todo el saldo posterior '
                    'a la reserva en una sola cuota, sin cambiar los módulos '
                    'académicos.'
                ),
            ),
        ),
    ]
