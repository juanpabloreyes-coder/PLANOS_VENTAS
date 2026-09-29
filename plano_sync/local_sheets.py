"""Lee las hojas de Revit que el add-in local SheetSync (ver revit_addin_sync/) escribe cada vez
que alguien sincroniza con exito -- sin llamar a ninguna API de Autodesk.

Cada modelo tiene un .json en la carpeta configurada como revit.carpeta_log_local, nombrado
"{PROYECTO}__{MODELO}.json" (el proyecto va primero para que dos modelos con el mismo nombre en
proyectos distintos -- p.ej. "12_ARQ_NAVE.rvt" existe tanto en GRANJAS JESSY como en GONVAUTO F2 --
nunca se pisen ni se confundan entre si) o "{MODELO}.json" cuando el nombre no es ambiguo, con la
forma:
    {"modelo": "...", "proyecto": "...", "model_guid": "...", "sincronizado_en": "...",
     "usuario": "...", "maquina": "...", "hojas": [{"numero": "...", "nombre": "..."}, ...]}

Si un modelo no tiene .json todavia (nadie con el add-in instalado lo ha sincronizado), esta
funcion devuelve None para ese modelo y collect.py cae de regreso al metodo actual (Model
Derivative / Design Automation) automaticamente -- el comportamiento del pipeline no cambia,
solo deja de costar en los modelos que ya tengan el add-in.

Para nombres de modelo repetidos en mas de un proyecto (ver collect.py/nombres_duplicados), el
add-in le pregunta a la persona una sola vez por modelo a que proyecto pertenece (ver
revit_addin_sync/SheetSync.cs) y guarda esa respuesta. Aun asi, aqui SIEMPRE se exige que el
"proyecto" dentro del .json coincida exactamente con el proyecto que ya sabemos por la API
(requerir_proyecto=True) -- si no coincide, o no esta, se descarta el archivo local sin mas y
collect.py cae de regreso al metodo de siempre. Asi un error humano en el desplegable del add-in
nunca puede mezclar hojas de un proyecto con las de otro: en el peor caso, ese modelo puntual
simplemente no se beneficia del add-in esa vez."""
# ACTUALIZACION 2026-09-29: el add-in ahora escribe "urn_<id>.json" con el URN del modelo y el
# proyecto de ACC. Se busca primero por URN (identidad exacta: un modelo de otro proyecto de ACC con
# el mismo nombre nunca se confunde). Los archivos por nombre de arriba quedan solo como transicion
# para modelos que aun no se han vuelto a sincronizar con el add-in nuevo.
import json
import logging
from pathlib import Path

log = logging.getLogger("plano_sync.local_sheets")

_INVALIDOS = '<>:"/\\|?*'


def _sanitizar(s):
    for c in _INVALIDOS:
        s = s.replace(c, "_")
    return s


def _candidatos(carpeta, proyecto, nombre_modelo):
    carpeta_p = Path(carpeta)
    modelo_safe = _sanitizar(nombre_modelo)
    rutas = []
    if proyecto:
        rutas.append(carpeta_p / f"{_sanitizar(proyecto)}__{modelo_safe}.json")
    # Respaldo: archivo sin prefijo de proyecto (nombre no ambiguo, o el add-in aun no confirmo
    # el proyecto). Con requerir_proyecto=True esta ruta nunca se acepta si no trae "proyecto"
    # coincidente -- ver _leer.
    rutas.append(carpeta_p / f"{modelo_safe}.json")
    return rutas


def _leer(p, proyecto_esperado, requerir_proyecto=False):
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("No se pudo leer %s: %s", p, e)
        return None
    proyecto_archivo = data.get("proyecto")
    if requerir_proyecto:
        # Nombre de modelo ambiguo entre proyectos: exigimos que el .json traiga un "proyecto"
        # explicito Y que coincida con el que ya sabemos por la API -- un archivo sin "proyecto"
        # (viejo, o el add-in nunca pregunto) NUNCA se acepta aqui, para no arriesgarnos.
        if not proyecto_archivo or proyecto_archivo != proyecto_esperado:
            return None
    elif proyecto_esperado and proyecto_archivo and proyecto_archivo != proyecto_esperado:
        return None  # es el registro de otro proyecto con el mismo nombre de modelo
    return data


def id_linaje(urn):
    """'urn:adsk.wipprod:dm.lineage:ABC' -> 'ABC' (None si no es un URN de linaje)."""
    s = str(urn or "")
    if "dm.lineage:" not in s:
        return None
    return s.split("dm.lineage:", 1)[1].split("?", 1)[0] or None


def _por_urn(carpeta, urn):
    """Archivo nuevo del add-in, nombrado por el URN del modelo: identidad exacta, sin ambiguedad
    de nombre ni de proyecto. -> dict o None."""
    lid = id_linaje(urn)
    if not carpeta or not lid:
        return None
    p = Path(carpeta) / f"urn_{_sanitizar(lid)}.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("No se pudo leer %s: %s", p, e)
        return None
    if id_linaje(data.get("model_urn")) != lid:
        return None
    return data


def _legado_valido(data):
    """Los archivos por NOMBRE son del add-in anterior (sin URN). Si uno trae model_urn, lo
    escribio el add-in nuevo para un modelo fuera de la nube -- no aplica aqui."""
    return data is not None and not data.get("model_urn")


def hojas_locales(carpeta, proyecto, nombre_modelo, requerir_proyecto=False, urn=None):
    """proyecto: nombre del proyecto tal como lo usa el pipeline (m["proyecto"]). nombre_modelo:
    nombre del .rvt SIN extension (igual a Path(...).stem). requerir_proyecto=True para nombres
    de modelo repetidos en mas de un proyecto (ver collect.py) -- exige coincidencia exacta de
    "proyecto" dentro del .json, no solo ausencia de contradiccion. Devuelve la lista de
    (numero, nombre) o None si no hay datos locales validos (y confiables) para ese modelo."""
    if not carpeta:
        return None
    # 1) Por URN (add-in actual): exacto. Si existe, manda aunque haya archivos viejos por nombre.
    data = _por_urn(carpeta, urn)
    if data is not None:
        hojas = data.get("hojas") or []
        return [(h.get("numero", ""), h.get("nombre", "")) for h in hojas if h.get("numero")] or None
    # 2) Transicion: archivos por nombre del add-in anterior (hasta que el modelo se vuelva a
    #    sincronizar con el add-in nuevo, que ya escribe por URN).
    for p in _candidatos(carpeta, proyecto, nombre_modelo):
        data = _leer(p, proyecto, requerir_proyecto)
        if not _legado_valido(data):
            continue
        hojas = data.get("hojas") or []
        pares = [(h.get("numero", ""), h.get("nombre", "")) for h in hojas if h.get("numero")]
        if pares:
            return pares
    return None


def info_extra(carpeta, proyecto, nombre_modelo, requerir_proyecto=False, urn=None):
    """Metadata de la ultima sincronizacion local (para diagnostico/log), o None."""
    if not carpeta:
        return None
    data = _por_urn(carpeta, urn)
    if data is not None:
        return {"sincronizado_en": data.get("sincronizado_en"), "usuario": data.get("usuario"),
                "maquina": data.get("maquina"), "proyecto": data.get("proyecto")}
    for p in _candidatos(carpeta, proyecto, nombre_modelo):
        data = _leer(p, proyecto, requerir_proyecto)
        if not _legado_valido(data):
            continue
        return {"sincronizado_en": data.get("sincronizado_en"), "usuario": data.get("usuario"),
                "maquina": data.get("maquina"), "proyecto": data.get("proyecto")}
    return None
