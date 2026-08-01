from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('academia', '0051_recuperacionpendiente_fecha_programada'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PerfilUsuario',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                (
                    'avatar',
                    models.CharField(
                        choices=[
                            ('princesa', 'Princesa'),
                            ('corona', 'Corona'),
                            ('pollito', 'Pollito'),
                            ('leon', 'León'),
                            ('mujer_rubia', 'Mujer rubia'),
                            ('mujer_afro_castana', 'Mujer afro castaña'),
                            ('latina', 'Latina'),
                            ('morena', 'Morena'),
                            ('mulata', 'Mulata'),
                            ('pacman', 'Pac-Man'),
                            ('gorra_mario', 'Gorra de Mario'),
                            ('princesa_peach', 'Princesa Peach'),
                        ],
                        default='corona',
                        max_length=32,
                    ),
                ),
                ('actualizado', models.DateTimeField(auto_now=True)),
                (
                    'user',
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='perfil_visual',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'verbose_name': 'Perfil de usuario',
                'verbose_name_plural': 'Perfiles de usuario',
            },
        ),
    ]
