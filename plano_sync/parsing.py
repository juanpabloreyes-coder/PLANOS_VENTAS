"""Limpieza de nombres de archivo -> (numero, nombre) y disciplina por ruta.

Port fiel de las funciones M de Power BI (fxSepararPlano, fxDisciplina,
fxNormalizarNumero, fxNormalizarNombre).
"""
import re
import unicodedata

_NUM = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
_TRIM = " -_"

DISCIPLINAS_DEFAULT = [
    ("Federados", ["01100_", "FEDERAD"]),
    ("Arquitectura", ["01101_", "ARQUITECT"]),
    ("Estructura", ["01102_", "ESTRUCT"]),
    ("Mecanica", ["01103_", "MECANIC"]),
    ("Plomeria", ["01104_", "PLOMER", "HIDRAUL", "SANIT"]),
    ("Electrica", ["01105_", "ELECTRIC"]),
    ("Especiales", ["01106_", "ESPECIAL"]),
    ("Contratista", ["01107_", "CONTRAT"]),
    ("Cliente", ["01108_", "CLIENTE"]),
    ("Otro", ["OTRO"]),
]


def _is_num(s):
    return bool(_NUM.match(s.strip()))


def _sin_acentos_basico(s):
    s = unicodedata.normalize("NFD", (s or "").strip().upper())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").replace("Ñ", "N")


def _ndn(s):
    """Quita acentos conservando la Ñ como N (igual que la tabla de reemplazos original)."""
    s = (s or "").strip().upper()
    for a, b in (("Á", "A"), ("É", "E"), ("Í", "I"), ("Ó", "O"), ("Ú", "U"), ("Ü", "U"), ("Ñ", "N")):
        s = s.replace(a, b)
    return s


def normalizar_numero(v):
    return re.sub(r"[ \-_./]", "", _ndn(v))


def normalizar_nombre(v):
    partes = re.split(r"[ \-_./,;:()\[\]{}]", _ndn(v))
    return " ".join(p.strip() for p in partes if p.strip())


def separar_plano(archivo):
    """'A-101 - Planta baja.pdf' -> ('A-101', 'Planta baja')."""
    archivo = (archivo or "").strip()
    sin_ext = re.sub(r"\.[A-Za-z0-9]{3}$", "", archivo).strip()

    p_esp = sin_ext.find(" - ")
    p_bajo = sin_ext.find("_")
    validas = [p for p in (p_esp, p_bajo) if p >= 0]
    if validas:
        pos = min(validas)
        sep_len = 1 if pos == p_bajo else 3
        num = sin_ext[:pos].strip(_TRIM)
        nom = sin_ext[pos + sep_len:].replace("_", " ").strip(_TRIM)
        return (num or None), (nom or None)

    partes = [p.strip() for p in sin_ext.split("-")]
    primer_num = _is_num(partes[0]) if partes else False
    n_base = min(3 if primer_num else 2, len(partes))
    base = partes[:n_base]
    ultima = base[-1] if base else ""
    i_esp = ultima.find(" ")
    ult_codigo = ultima[:i_esp] if i_esp >= 0 else ultima
    nombre_en_base = ultima[i_esp + 1:].strip() if i_esp >= 0 else ""
    if base:
        base = base[:-1] + [ult_codigo]
    numero_base = "-".join(p for p in base if p)

    restantes = partes[n_base:]
    primera = restantes[0] if restantes else ""
    i_suf = primera.find(" ")
    cand = primera[:i_suf] if i_suf >= 0 else primera
    es_letra = len(cand) == 1 and cand.upper() in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    es_dec = "." in cand and _is_num(cand)
    usa_suf = bool(restantes) and (es_letra or es_dec)
    numero = numero_base + "-" + cand if usa_suf else numero_base
    if usa_suf:
        despues = primera[i_suf + 1:].strip() if i_suf >= 0 else ""
        partes_nom = [despues] + restantes[1:]
    else:
        partes_nom = restantes
    nombre_rest = "-".join(p for p in partes_nom if p).strip(_TRIM)
    nombre = " ".join(p for p in (nombre_en_base, nombre_rest) if p).strip(_TRIM)
    numero = numero.strip(_TRIM)
    return (numero or None), (nombre or None)


def disciplina_por_ruta(ruta, reglas=None):
    t = _ndn(ruta)
    for nombre, tokens in (reglas or DISCIPLINAS_DEFAULT):
        if any(tok.upper() in t for tok in tokens):
            return nombre
    return "Sin clasificar"


DISCIPLINA_PALABRAS_WIP = [
    ("Arquitectura", "ARQUITECTURA"),
    ("Estructura", "ESTRUCTURA"),
    ("Mecanica", "MECANICA"),
    ("Plomeria", "PLOMERIA"),
    ("Electrica", "ELECTRICA"),
    ("Especiales", "ESPECIALES"),
]


def disciplina_por_carpeta_wip(ruta, subcarpeta="011_WIP"):
    """Disciplina = la primera carpeta despues de la subcarpeta de datos (p.ej. '011_WIP') en la
    ruta del MODELO Revit, si su nombre normalizado (mayusculas, sin acentos) contiene alguna de
    las palabras reconocidas (Arquitectura, Estructura, Mecanica, Plomeria, Electrica, Especiales).
    None si no aplica (no se encontro la subcarpeta en la ruta, no hay carpeta siguiente, o su
    nombre no trae ninguna de esas palabras) -- el llamador debe descartar esos planos del reporte
    por completo, igual que con integrante sin asignar."""
    partes = [p for p in (ruta or "").split("/") if p]
    objetivo = _ndn(subcarpeta).strip()
    idx = next((i for i, p in enumerate(partes) if _ndn(p).strip() == objetivo), None)
    if idx is None or idx + 1 >= len(partes):
        return None
    carpeta = _ndn(partes[idx + 1])
    for nombre, palabra in DISCIPLINA_PALABRAS_WIP:
        if palabra in carpeta:
            return nombre
    return None


def extension_permitida(nombre_archivo, proyecto, disciplina, reglas):
    """reglas = {"default": ["pdf"], "DMG MORI": {"default": ["dwg"]},
                 "SENSATA B5": {"default": ["pdf"], "Mecanica": ["dwg"]}}"""
    ext = nombre_archivo.rsplit(".", 1)[-1].lower() if "." in nombre_archivo else ""
    r = reglas.get(proyecto, reglas)
    if isinstance(r, dict):
        exts = r.get(disciplina, r.get("default", reglas.get("default", ["pdf"])))
    else:
        exts = r
    return ext in [e.lower() for e in exts]
