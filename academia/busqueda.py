import unicodedata

from django.core.exceptions import ObjectDoesNotExist


def normalizar_texto_busqueda(valor):
    texto = str(valor or '').casefold()
    texto = unicodedata.normalize('NFD', texto)
    return ''.join(
        caracter
        for caracter in texto
        if unicodedata.category(caracter) != 'Mn'
    )


def _resolver_atributo(objeto, ruta):
    valor = objeto
    for parte in ruta.split('__'):
        if valor is None:
            return ''
        try:
            valor = getattr(valor, parte)
        except (AttributeError, ObjectDoesNotExist):
            return ''
        if callable(valor):
            valor = valor()
    return valor or ''


def filtrar_queryset_busqueda(qs, termino, campos):
    palabras = [
        palabra for palabra in normalizar_texto_busqueda(termino).split()
        if palabra
    ]
    if not palabras:
        return qs

    ids = []
    for obj in qs:
        texto = normalizar_texto_busqueda(
            ' '.join(str(_resolver_atributo(obj, campo)) for campo in campos)
        )
        if all(palabra in texto for palabra in palabras):
            ids.append(obj.pk)

    if not ids:
        return qs.none()
    return qs.filter(pk__in=ids)
