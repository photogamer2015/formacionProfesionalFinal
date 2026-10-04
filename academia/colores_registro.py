"""Color de cada usuario en el Registro Estudiantil.

El administrador lo elige en el admin de Django (Usuarios › Modificar
usuario › Registro Estudiantil) y se guarda en PerfilUsuario.color_registro.
Quien todavía no tiene color elegido recibe uno automático: el de la hoja de
Excel para las asesoras conocidas y, para las demás, uno fijo según su nombre.
"""
import re
import zlib

from .busqueda import normalizar_texto_busqueda
from .models import COLORES_REGISTRO, PerfilUsuario


HEX = {codigo: valor for codigo, _nombre, valor in COLORES_REGISTRO}
NOMBRES = {codigo: nombre for codigo, nombre, _valor in COLORES_REGISTRO}
COLOR_SIN_REGISTRO = '#d9d9d9'

# Colores automáticos: los de la hoja de Excel del equipo.
ASESORAS_EXCEL = {
    'shirley': 'azul',
    'kimberly': 'naranja',
    'buffer': 'rojo',
    'melanie': 'verde',
}
ALIAS_ASESORAS = {
    'shirly': 'shirley',
    'kim': 'kimberly',
    'kimberli': 'kimberly',
    'bufer': 'buffer',
    'melany': 'melanie',
    'melani': 'melanie',
}
# Para las demás, uno de estos según su nombre.
AUTOMATICOS = ('rosado', 'morado', 'lila')


def _nombre(usuario):
    return usuario.get_full_name().strip() or usuario.username


def codigo_automatico(texto_busqueda, nombre_visible):
    """Color automático por nombre ('' si no hay nombre)."""
    palabras = re.split(r'[^a-z0-9]+', normalizar_texto_busqueda(texto_busqueda))
    for palabra in palabras:
        clave = ALIAS_ASESORAS.get(palabra, palabra)
        if clave in ASESORAS_EXCEL:
            return ASESORAS_EXCEL[clave]
    base = normalizar_texto_busqueda(nombre_visible).strip()
    if not base:
        return ''
    # Por el nombre (no por el id) para que la asesora tenga el mismo color
    # en sus matrículas vivas y en las archivadas.
    return AUTOMATICOS[zlib.crc32(base.encode()) % len(AUTOMATICOS)]


def codigo_automatico_usuario(usuario):
    return codigo_automatico(
        ' '.join((usuario.first_name, usuario.username, usuario.last_name)),
        _nombre(usuario),
    )


def color_de_usuario(usuario):
    """Color de un usuario para mostrarlo (por ejemplo, en su perfil)."""
    if not usuario:
        return None
    codigo = (
        PerfilUsuario.objects.filter(user_id=usuario.pk)
        .values_list('color_registro', flat=True).first()
    ) or ''
    automatico = codigo not in HEX
    if automatico:
        codigo = codigo_automatico_usuario(usuario)
    return {
        'codigo': codigo,
        'nombre': NOMBRES[codigo],
        'hex': HEX[codigo],
        'automatico': automatico,
    }


class Paleta:
    """Colores de una hoja: se cargan una sola vez por consulta."""

    def __init__(self):
        self.por_usuario = {}
        self.por_nombre = {}
        perfiles = (
            PerfilUsuario.objects.filter(color_registro__in=list(HEX))
            .select_related('user')
        )
        for perfil in perfiles:
            self.por_usuario[perfil.user_id] = perfil.color_registro
            nombre = normalizar_texto_busqueda(_nombre(perfil.user)).strip()
            self.por_nombre[nombre] = perfil.color_registro

    def de_usuario(self, usuario):
        """Color de las filas que registró ``usuario``."""
        if not usuario:
            return COLOR_SIN_REGISTRO
        codigo = (
            self.por_usuario.get(usuario.pk)
            or codigo_automatico_usuario(usuario)
        )
        return HEX.get(codigo, COLOR_SIN_REGISTRO)

    def de_nombre(self, nombre):
        """Color de una matrícula archivada, que solo guarda el nombre."""
        clave = normalizar_texto_busqueda(nombre).strip()
        if not clave:
            return COLOR_SIN_REGISTRO
        codigo = self.por_nombre.get(clave) or codigo_automatico(nombre, nombre)
        return HEX.get(codigo, COLOR_SIN_REGISTRO)
