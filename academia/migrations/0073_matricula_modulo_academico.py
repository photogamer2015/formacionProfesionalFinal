from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('academia', '0072_avatar_slytherin')]
    operations = [
        migrations.AddField(
            model_name='matricula', name='desfase_modulo_academico',
            field=models.IntegerField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='matricula', name='ajuste_modulo_desde',
            field=models.DateField(null=True, blank=True),
        ),
    ]
