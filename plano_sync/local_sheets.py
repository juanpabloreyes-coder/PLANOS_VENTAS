"""Lee las hojas de Revit que el add-in local SheetSync (ver revit_addin_sync/) escribe cada vez
que alguien sincroniza con exito -- sin llamar a ninguna API de Autodesk.

Cada modelo tiene un .json (uno por nombre de archivo .rvt) en la carpeta configurada como
revit.carpeta_log_local, con la forma:
    {"modelo": "...", "sincronizado_en": "...", "usuario": "...", "maquina": "...",
     "hojas": [{"numero": "...", "nombre": "..."}, ...]}

Si un modelo no tiene .json todavia (nadie con el add-in instalado lo ha sincronizado), esta
funcion devuelve None para ese modelo y collect.py cae de regreso al metodo actual (Model
Derivative / Design Automation) automaticamente -- el comportamiento del pipeline no cambia,
solo deja de costar en los modelos que ya tengan el add-in."""
import json
import logging
from pathlib import Path

log = logging.getLogger("plano_sync.local_sheets")


def hojas_locales(carpeta, nombre_modelo):
    """nombre_modelo: nombre del .rvt SIN extension (igual a Path(...).stem). Devuelve la lista de
    (numero, nombre) o None si no hay datos locales para ese modelo todavia."""
    if not carpeta:
        return None
    p = Path(carpeta) / f"{nombre_modelo}.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("No se pudo leer %s: %s", p, e)
        return None
    hojas = data.get("hojas") or []
    pares = [(h.get("numero", ""), h.get("nombre", "")) for h in hojas if h.get("numero")]
    return pares if pares else None


def info_extra(carpeta, nombre_modelo):
    """Metadata de la ultima sincronizacion local (para diagnostico/log), o None."""
    if not carpeta:
        return None
    p = Path(carpeta) / f"{nombre_modelo}.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    return {"sincronizado_en": data.get("sincronizado_en"), "usuario": data.get("usuario"),
            "maquina": data.get("maquina")}
