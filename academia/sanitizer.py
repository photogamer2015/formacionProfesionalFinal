"""
Sanitizador de HTML enriquecido, sin dependencias externas.

Se usa para limpiar el contenido de los Avisos antes de guardarlos, de modo
que el administrador pueda dar formato al texto (negrita, cursiva, subrayado,
listas, colores) pero NO pueda inyectar scripts, iframes, eventos onclick ni
otro HTML peligroso (protección contra XSS).

Funciona con una lista blanca (whitelist) muy estricta:
    - Solo se permiten ciertas etiquetas.
    - Solo se permiten ciertos atributos.
    - En `style` solo se permiten color, background-color, text-align,
      font-weight, font-style y text-decoration.
    - Cualquier etiqueta/atributo no permitido se descarta (el texto interno
      se conserva).
"""
from html.parser import HTMLParser
import re

# Etiquetas permitidas (formato de texto básico, sin nada interactivo)
_TAGS_PERMITIDAS = {
    'b', 'strong', 'i', 'em', 'u', 's', 'strike',
    'p', 'br', 'span', 'div',
    'ul', 'ol', 'li',
    'h3', 'h4',
    'blockquote',
}

# Etiquetas que se autocierran
_TAGS_VACIAS = {'br'}

# Atributos permitidos por etiqueta (solo style; los demás se eliminan)
_ATTRS_PERMITIDOS = {'style'}

# Propiedades CSS permitidas dentro de style=""
_CSS_PERMITIDO = {
    'color',
    'background-color',
    'text-align',
    'font-weight',
    'font-style',
    'text-decoration',
}

# Validación de valores CSS: solo colores (#hex, rgb(), nombres simples) y
# palabras clave conocidas. Evita url(), expression(), etc.
_RE_COLOR = re.compile(
    r'^(#[0-9a-fA-F]{3,8}'
    r'|rgb\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\)'
    r'|rgba\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*(0|1|0?\.\d+)\s*\)'
    r'|[a-zA-Z]{3,30})$'
)
_RE_KEYWORD = re.compile(r'^[a-zA-Z\- ]{1,40}$')


def _limpiar_style(valor):
    """Devuelve un style seguro a partir del original, o '' si nada es válido."""
    declaraciones_ok = []
    for parte in valor.split(';'):
        if ':' not in parte:
            continue
        prop, _, val = parte.partition(':')
        prop = prop.strip().lower()
        val = val.strip()
        if prop not in _CSS_PERMITIDO or not val:
            continue
        if prop in ('color', 'background-color'):
            if _RE_COLOR.match(val):
                declaraciones_ok.append(f'{prop}: {val}')
        else:
            if _RE_KEYWORD.match(val):
                declaraciones_ok.append(f'{prop}: {val}')
    return '; '.join(declaraciones_ok)


class _Sanitizador(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.salida = []
        self._pila = []  # etiquetas abiertas válidas, para cerrarlas bien

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag not in _TAGS_PERMITIDAS:
            return
        attrs_ok = []
        for nombre, valor in attrs:
            nombre = (nombre or '').lower()
            if nombre not in _ATTRS_PERMITIDOS or valor is None:
                continue
            if nombre == 'style':
                style_limpio = _limpiar_style(valor)
                if style_limpio:
                    attrs_ok.append(f'style="{style_limpio}"')
        attr_str = (' ' + ' '.join(attrs_ok)) if attrs_ok else ''
        if tag in _TAGS_VACIAS:
            self.salida.append(f'<{tag}{attr_str}>')
        else:
            self.salida.append(f'<{tag}{attr_str}>')
            self._pila.append(tag)

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if tag in _TAGS_PERMITIDAS and tag in _TAGS_VACIAS:
            self.salida.append(f'<{tag}>')

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag not in _TAGS_PERMITIDAS or tag in _TAGS_VACIAS:
            return
        # Cerrar de forma balanceada
        if tag in self._pila:
            while self._pila:
                abierta = self._pila.pop()
                self.salida.append(f'</{abierta}>')
                if abierta == tag:
                    break

    def handle_data(self, data):
        # Escapar texto plano para que no se pueda inyectar nada
        self.salida.append(
            data.replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
        )

    def resultado(self):
        # Cerrar cualquier etiqueta que haya quedado abierta
        while self._pila:
            self.salida.append(f'</{self._pila.pop()}>')
        return ''.join(self.salida)


def limpiar_html(texto):
    """Sanitiza el HTML de entrada y devuelve HTML seguro para mostrar."""
    if not texto:
        return ''
    parser = _Sanitizador()
    parser.feed(texto)
    parser.close()
    return parser.resultado().strip()
